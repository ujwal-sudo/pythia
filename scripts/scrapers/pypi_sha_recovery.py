#!/usr/bin/env python3
"""PyPI SHA-anchored exact-version recovery (Session 2, policy v1).

Recovery uses the historical archive_sha256 as the PRIMARY identity anchor:
  historical package + historical archive_sha256 -> exact PyPI distribution.

Historical data is IMMUTABLE. Recovery writes ONLY under
/mnt/pythia-cloud/Pythia/recovery/pypi/.

Usage:
  python scripts/scrapers/pypi_sha_recovery.py --packages pkg1 pkg2 ... 
  python scripts/scrapers/pypi_sha_recovery.py --from-manifest --batch-size 50
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.scrapers.pypi import (
    sha256_file,
    verify_archive_identity,
    _download_file,
    analyze_package,
    normalize_package_name,
)
from scripts.research.pypi_metadata import content_hash, normalize_code_for_hash

from scripts.scrapers.pypi_storage import (
    assert_no_freeze,
    commit_write,
    recovery_state_remote,
)

RECOVERY_ROOT = Path("/mnt/pythia-cloud/Pythia/recovery")
RECOVERY_DIR = RECOVERY_ROOT / "pypi"
RECOVERY_ARCHIVES = RECOVERY_DIR / "archives"
RECOVERY_STATE_PATH = RECOVERY_DIR / "recovery_state_v1.json"
RECOVERY_MANIFEST_PATH = RECOVERY_DIR / "recovery_manifest_v1.jsonl"

FROZEN_MANIFEST = Path("/mnt/pythia-cloud/Pythia/raw/pypi/manifests/pypi_acquisition_v1.json")
META_DIR = Path("/mnt/pythia-cloud/Pythia/raw/pypi/metadata")

# Route recovery writes through the remote storage abstraction when enabled.
PYPI_REMOTE_STORAGE = os.environ.get("PYPI_REMOTE_STORAGE", "0") == "1"

EXPERIMENT = "PYT-DATA-PYPI-RECOVERY-001"
PREPROC = "pypi_recovery_v1"
VALIDATOR = "scripts.validators.ast_validator"
DATASET_VER = "PYTHIA-DATA-v0.1"


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def load_state() -> dict:
    if PYPI_REMOTE_STORAGE:
        from scripts.scrapers.pypi_storage import remote_exists, remote_read_text
        if remote_exists(recovery_state_remote()):
            return json.loads(remote_read_text(recovery_state_remote()))
        return {"records": {}}
    if RECOVERY_STATE_PATH.exists():
        return json.loads(RECOVERY_STATE_PATH.read_text(encoding="utf-8"))
    return {"records": {}}


def save_state(state: dict) -> None:
    if PYPI_REMOTE_STORAGE:
        # Freeze checked first inside the storage layer; two-phase commit.
        assert_no_freeze()
        data = (json.dumps(state, indent=2) + "\n").encode("utf-8")
        commit_write(data, recovery_state_remote(), prevent_overwrite=False,
                     namespace="recovery", verify=True)
        return
    RECOVERY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = RECOVERY_STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tmp.replace(RECOVERY_STATE_PATH)


def append_manifest(rec: dict) -> None:
    if PYPI_REMOTE_STORAGE:
        raise RuntimeError(
            "append_manifest over remote is not safe (append is not atomic); "
            "use manifest rewrite via commit_write instead")
    RECOVERY_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RECOVERY_MANIFEST_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


# ------------------------------------------------------------- SHA-anchored resolution
def find_distribution_by_sha(package: str, target_sha: str) -> dict:
    """Query PyPI release history; return distributions whose digest matches
    target_sha. Returns list of matched {version, filename, url, sha256, size, type}."""
    import requests
    r = requests.get(f"https://pypi.org/pypi/{package}/json", timeout=30)
    r.raise_for_status()
    d = r.json()
    matches = []
    for ver, files in d.get("releases", {}).items():
        for f in files:
            if f.get("digests", {}).get("sha256") == target_sha:
                matches.append({
                    "version": ver,
                    "filename": f.get("filename"),
                    "url": f.get("url"),
                    "sha256": f.get("digests", {}).get("sha256"),
                    "size": f.get("size"),
                    "type": f.get("packagetype"),
                })
    return matches


def wheel_identity(path: Path) -> dict:
    """Extract deterministic identity from a wheel (filename + dist-info)."""
    ident = {"package": None, "version": None, "filename_package": None, "filename_version": None}
    # Filename: {dist}-{version}(-{build})?-{py}-{abi}-{platform}.whl
    base = path.name
    m = re.match(r"^(.+?)-(\d[^-]*?)(?:-[^-.]+)?-([^-]+)-([^-]+)-[^/]+\.whl$", base)
    if m:
        ident["filename_package"] = m.group(1).replace("_", "-").lower()
        ident["filename_version"] = m.group(2)
    try:
        with zipfile.ZipFile(path) as zf:
            for n in zf.namelist():
                if n.endswith(".dist-info/METADATA") or n.endswith("/METADATA"):
                    md = zf.read(n).decode("utf-8", errors="replace")
                    for line in md.splitlines():
                        if line.startswith("Name:") and ident["package"] is None:
                            ident["package"] = line.split(":", 1)[1].strip()
                        elif line.startswith("Version:") and ident["version"] is None:
                            ident["version"] = line.split(":", 1)[1].strip()
                    break
    except Exception:
        pass
    return ident


def _archive_metadata_identity(path: Path) -> dict:
    """Read package/version from sdist PKG-INFO or wheel METADATA."""
    ident = {"package": None, "version": None}
    if path.name.endswith(".whl"):
        w = wheel_identity(path)
        ident.update(w)
        return ident
    if path.name.endswith(".zip"):
        try:
            with zipfile.ZipFile(path) as zf:
                for n in zf.namelist():
                    if n.endswith("PKG-INFO") or n.endswith("METADATA"):
                        content = zf.read(n).decode("utf-8", errors="replace")
                        for line in content.splitlines():
                            if line.startswith("Name:") and ident["package"] is None:
                                ident["package"] = line.split(":", 1)[1].strip()
                            elif line.startswith("Version:") and ident["version"] is None:
                                ident["version"] = line.split(":", 1)[1].strip()
                        break
        except Exception:
            pass
        return ident
    try:
        with tarfile.open(path, "r:*") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                nm = member.name.lower()
                if nm.endswith("pkg-info") or nm.endswith("/metadata"):
                    raw = tf.extractfile(member)
                    if raw is None:
                        continue
                    content = raw.read().decode("utf-8", errors="replace")
                    for line in content.splitlines():
                        if line.startswith("Name:") and ident["package"] is None:
                            ident["package"] = line.split(":", 1)[1].strip()
                        elif line.startswith("Version:") and ident["version"] is None:
                            ident["version"] = line.split(":", 1)[1].strip()
                    break
    except Exception:
        pass
    return ident


def _extract_python_code(path: Path) -> list:
    """Extract all Python file texts from an archive deterministically (sorted)."""
    files = []
    if path.name.endswith(".whl"):
        with zipfile.ZipFile(path) as zf:
            names = sorted(n for n in zf.namelist() if n.endswith(".py"))
            for n in names:
                files.append((n, zf.read(n).decode("utf-8", errors="replace")))
        return files
    if path.name.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            names = sorted(n for n in zf.namelist() if n.endswith(".py"))
            for n in names:
                files.append((n, zf.read(n).decode("utf-8", errors="replace")))
        return files
    with tarfile.open(path, "r:*") as tf:
        members = sorted([m for m in tf.getmembers() if m.isfile() and m.name.endswith(".py")],
                         key=lambda m: m.name)
        for m in members:
            raw = tf.extractfile(m)
            if raw is None:
                continue
            files.append((m.name, raw.read().decode("utf-8", errors="replace")))
    return files


def recover_one(hist: dict) -> dict:
    pkg = hist["package"]
    hist_ver = hist["version"]
    hist_sha = hist.get("archive_sha256")
    if not hist_sha:
        # The acquisition manifest does not carry archive_sha256; load it from
        # the frozen checkpoint (the authoritative source).
        ckpt = load_checkpoint(pkg)
        hist_sha = ckpt.get("archive_sha256")

    rec = {
        "recovery_id": f"pypi:{normalize_package_name(pkg)}:{hist_ver}",
        "historical_package": pkg,
        "historical_version": hist_ver,
        "historical_archive_sha256": hist_sha,
        "requested_package": pkg,
        "state": "OTHER_BLOCKED",
        "recovery_timestamp": utc_now(),
    }

    if not hist_sha:
        rec["state"] = "IDENTITY_UNPROVEN"
        rec["reason"] = "no_historical_archive_sha"
        return rec

    # SHA-anchored resolution (Mission 2): historical SHA is the primary anchor.
    try:
        matches = find_distribution_by_sha(pkg, hist_sha)
    except Exception as exc:
        rec["state"] = "NETWORK_ERROR"
        rec["reason"] = f"{type(exc).__name__}:{str(exc)[:100]}"
        return rec

    if not matches:
        rec["state"] = "ARCHIVE_UNAVAILABLE"
        rec["reason"] = "no_pypi_distribution_matches_historical_sha"
        return rec

    if len(matches) > 1:
        rec["state"] = "IDENTITY_UNPROVEN"
        rec["reason"] = f"ambiguous:{len(matches)}_distributions_share_sha"
        rec["candidate_distributions"] = matches
        return rec

    m = matches[0]
    intended_ver = m["version"]
    intended_fname = m["filename"]
    intended_url = m["url"]
    intended_sha = m["sha256"]
    rec.update({
        "requested_version": intended_ver,
        "resolved_package": pkg,
        "resolved_version": intended_ver,
        "resolved_filename": intended_fname,
        "resolved_url": intended_url,
        "resolved_sha256": intended_sha,
        "distribution_type": m["type"],
        "intended_version_source": "historical_archive_sha256_anchor",
    })

    # Download to isolated recovery area.
    dest_dir = RECOVERY_ARCHIVES / normalize_package_name(pkg) / intended_ver
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / intended_fname
    try:
        if not (dest.exists() and dest.stat().st_size > 0):
            _download_file(intended_url, dest, 120)
    except Exception as exc:
        rec["state"] = "NETWORK_ERROR"
        rec["reason"] = f"download:{type(exc).__name__}:{str(exc)[:100]}"
        return rec

    # SHA verification.
    observed_sha = sha256_file(dest)
    rec["archive_sha256_observed"] = observed_sha
    if observed_sha != intended_sha:
        rec["state"] = "HASH_MISMATCH"
        rec["reason"] = "downloaded_archive_sha_differs_from_pypi_digest"
        return rec

    # Identity verification (filename + internal metadata).
    fname_ver = None
    if intended_fname.endswith(".whl"):
        w = wheel_identity(dest)
        fname_ver = w.get("filename_version")
        inner_pkg = w.get("package")
        inner_ver = w.get("version")
    else:
        inner = _archive_metadata_identity(dest)
        inner_pkg = inner.get("package")
        inner_ver = inner.get("version")
        # filename version parse
        mm = re.search(r"[-_]([0-9][0-9A-Za-z.+-]*(?:\.dev[0-9]*)?)$", intended_fname.replace(".tar.gz", "").replace(".zip", ""))
        fname_ver = mm.group(1) if mm else None

    rec["observed_filename_version"] = fname_ver
    rec["observed_metadata_package"] = inner_pkg
    rec["observed_metadata_version"] = inner_ver

    # Identity gate: filename and metadata must be consistent with intended version.
    if fname_ver is not None and fname_ver != intended_ver:
        rec["state"] = "IDENTITY_MISMATCH"
        rec["reason"] = f"filename_version_mismatch:{fname_ver}!={intended_ver}"
        return rec
    if inner_ver is not None and inner_ver != intended_ver:
        rec["state"] = "IDENTITY_MISMATCH"
        rec["reason"] = f"metadata_version_mismatch:{inner_ver}!={intended_ver}"
        return rec
    if inner_pkg is not None and normalize_package_name(inner_pkg) != normalize_package_name(pkg):
        rec["state"] = "IDENTITY_MISMATCH"
        rec["reason"] = f"metadata_package_mismatch:{inner_pkg}!={pkg}"
        return rec

    # Content extraction + hashes.
    try:
        py_files = _extract_python_code(dest)
    except Exception as exc:
        rec["state"] = "EXTRACTION_FAILED"
        rec["reason"] = f"{type(exc).__name__}:{str(exc)[:100]}"
        return rec

    if not py_files:
        rec["state"] = "NO_PYTHON_CODE"
        return rec

    joined = "\n".join(normalize_code_for_hash(t) for _, t in py_files)
    rec["content_hash"] = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    rec["normalized_hash"] = content_hash(joined)
    rec["python_files"] = len(py_files)
    rec["python_loc"] = sum(len(t.splitlines()) for _, t in py_files)

    # AST stats via analyze_package (works on archives).
    try:
        analysis = analyze_package(dest, pkg)
        rec["ast_valid"] = analysis.get("ast_valid", 0)
        rec["ast_invalid"] = analysis.get("ast_invalid", 0)
    except Exception:
        rec["ast_valid"] = None
        rec["ast_invalid"] = None

    rec["provenance_chain"] = (
        f"historical_checkpoint/{EXPERIMENT} -> sha256_anchor:{hist_sha[:16]}"
        f" -> pypi_distribution:{intended_fname} -> download -> sha_verify"
        f" -> identity_verify -> extraction -> normalization -> recovery_record"
    )
    rec["preprocessing_version"] = PREPROC
    rec["validator_version"] = VALIDATOR
    rec["dataset_version"] = DATASET_VER
    rec["quality_metadata"] = {
        "python_files": rec.get("python_files"),
        "python_loc": rec.get("python_loc"),
        "ast_valid": rec.get("ast_valid"),
        "ast_invalid": rec.get("ast_invalid"),
    }
    rec["state"] = "RECOVERED_VERIFIED"
    rec["reason"] = "sha_anchored_identity_and_integrity_verified"
    return rec


def load_frozen_manifest() -> list:
    data = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
    return data["packages"]


def load_checkpoint(pkg: str) -> dict:
    """Load the frozen checkpoint for a package; returns its inner dict or {}."""
    cp = META_DIR / f"{normalize_package_name(pkg)}_checkpoint.json"
    if not cp.exists():
        return {}
    try:
        data = json.loads(cp.read_text(encoding="utf-8"))
        for key, info in data.items():
            if normalize_package_name(key) == normalize_package_name(pkg):
                return info
    except Exception:
        return {}
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packages", nargs="*", default=None)
    ap.add_argument("--from-manifest", action="store_true")
    ap.add_argument("--batch-size", type=int, default=50)
    args = ap.parse_args()

    state = load_state()

    if args.packages:
        pkgs = [p for p in load_frozen_manifest() if p["package"] in args.packages]
    elif args.from_manifest:
        pkgs = load_frozen_manifest()
    else:
        pkgs = load_frozen_manifest()

    # Pending = not yet in state.
    pending = []
    for p in pkgs:
        rid = f"pypi:{normalize_package_name(p['package'])}:{p['version']}"
        if rid not in state["records"]:
            pending.append(p)

    # If packages explicitly given, respect full list (for targeted analysis).
    batch = pending[: args.batch_size]
    print(f"Recovery batch: {len(batch)} records")

    # Single-writer lock (advisory/best-effort) before any recovery mutation.
    from scripts.scrapers.pypi_storage import WriterLock
    _lock = WriterLock(lease_seconds=600)
    if not _lock.acquire(timeout=15):
        print("FATAL: could not acquire PyPI single-writer lock")
        return
    try:
        for hist in batch:
            rec = recover_one(hist)
            rid = rec["recovery_id"]
            state["records"][rid] = rec
            save_state(state)
            append_manifest(rec)
            print(f"  {hist['package']} hist_v={hist['version']} -> {rec['state']} (intended={rec.get('resolved_version','-')})")
    finally:
        _lock.release()

    from collections import Counter
    counts = Counter(r["state"] for r in state["records"].values())
    print(f"\nTotal records in state: {len(state['records'])}")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    print(f"State: {RECOVERY_STATE_PATH}")


if __name__ == "__main__":
    main()