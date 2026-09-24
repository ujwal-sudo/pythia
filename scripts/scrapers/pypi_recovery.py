#!/usr/bin/env python3
"""PyPI controlled recovery of the frozen ACQUIRED set (Session 2).

Recovers/re-validates historical ACQUIRED records using the verified safe
pipeline. Writes ONLY to an isolated recovery directory. Never modifies the
frozen /mnt/pythia-cloud/Pythia/raw/pypi dataset.

States (Mission 3):
  RECOVERED_VERIFIED, IDENTITY_MISMATCH, ARCHIVE_UNAVAILABLE, HASH_MISMATCH,
  NO_PYTHON_CODE, EXTRACTION_FAILED, NETWORK_ERROR, OTHER_BLOCKED

Usage:
  python scripts/scrapers/pypi_recovery.py --batch-size 25
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.scrapers.pypi import (
    fetch_package_metadata,
    verify_archive_identity,
    _download_file,
    analyze_package,
    normalize_package_name,
)
from scripts.research.pypi_metadata import content_hash, make_record_id

RECOVERY_ROOT = Path("/mnt/pythia-cloud/Pythia/recovery")
RECOVERY_DIR = RECOVERY_ROOT / "pypi"
RECOVERY_ARCHIVES = RECOVERY_DIR / "archives"
RECOVERY_STATE_PATH = RECOVERY_DIR / "recovery_state_v1.json"
RECOVERY_MANIFEST_PATH = RECOVERY_DIR / "recovery_manifest_v1.jsonl"

FROZEN_MANIFEST = Path("/mnt/pythia-cloud/Pythia/raw/pypi/manifests/pypi_acquisition_v1.json")


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def load_state() -> dict:
    if RECOVERY_STATE_PATH.exists():
        return json.loads(RECOVERY_STATE_PATH.read_text(encoding="utf-8"))
    return {"records": {}}


def save_state(state: dict) -> None:
    RECOVERY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = RECOVERY_STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tmp.replace(RECOVERY_STATE_PATH)


def append_manifest(rec: dict) -> None:
    RECOVERY_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RECOVERY_MANIFEST_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def recover_one(hist: dict) -> dict:
    hist_pkg = hist["package"]
    hist_ver = hist["version"]
    hist_sha = hist.get("archive_sha256")
    rec_id = make_record_id(hist_pkg, hist_ver)

    rec = {
        "recovery_id": rec_id,
        "historical_package": hist_pkg,
        "historical_version": hist_ver,
        "historical_archive_sha256": hist_sha,
        "requested_package": hist_pkg,
        "requested_version": hist_ver,
        "state": "OTHER_BLOCKED",
        "recovery_timestamp": utc_now(),
    }

    try:
        meta = fetch_package_metadata(hist_pkg, timeout=30, requested_version=hist_ver)
    except Exception as exc:
        rec["state"] = "NETWORK_ERROR"
        rec["reason"] = f"{type(exc).__name__}:{str(exc)[:100]}"
        return rec

    if meta is None:
        rec["state"] = "ARCHIVE_UNAVAILABLE"
        rec["reason"] = "metadata_fetch_failed"
        return rec

    res_pkg = meta["package"]
    res_ver = meta["resolved_version"]
    res_fname = meta["resolved_filename"]
    rec.update({
        "resolved_package": res_pkg,
        "resolved_version": res_ver,
        "resolved_filename": res_fname,
        "resolved_url": meta["archive_url"],
        "resolved_sha256": meta["archive_sha256"],
        "used_info_version_fallback": meta["used_info_version_fallback"],
    })

    # Mission 5: identity safety — requested must equal resolved.
    if res_pkg != hist_pkg or res_ver != hist_ver:
        rec["state"] = "IDENTITY_MISMATCH"
        rec["reason"] = "requested_vs_resolved_identity_mismatch"
        rec["identity_classification"] = "historical_version_label_inconsistent_with_live_resolution"
        return rec

    # Download to isolated recovery area.
    dest = RECOVERY_ARCHIVES / normalize_package_name(hist_pkg) / hist_ver / res_fname
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not (dest.exists() and dest.stat().st_size > 0):
            _download_file(meta["archive_url"], dest, 120)
    except Exception as exc:
        rec["state"] = "NETWORK_ERROR"
        rec["reason"] = f"download:{type(exc).__name__}:{str(exc)[:100]}"
        return rec

    # Identity gate with true requested version.
    gate = verify_archive_identity(
        requested_package=hist_pkg,
        requested_version=hist_ver,
        meta=meta,
        archive_path=dest,
    )
    rec["gate_status"] = gate["status"]
    rec["gate_reason"] = gate["reason"]
    rec["observed_filename_version"] = gate.get("observed_filename_version")
    rec["observed_metadata_version"] = gate.get("observed_metadata_version")
    rec["observed_archive_sha256"] = gate.get("archive_sha256_observed")

    if not gate["ok"]:
        if gate["reason"] == "sha_mismatch":
            rec["state"] = "HASH_MISMATCH"
        else:
            rec["state"] = "IDENTITY_MISMATCH"
        rec["reason"] = gate["reason"]
        rec["identity_classification"] = "live_resolution_identity_contradiction"
        return rec

    # Mission 7: content extraction + content_hash / normalized_hash.
    try:
        analysis = analyze_package(dest, hist_pkg)
    except Exception as exc:
        rec["state"] = "EXTRACTION_FAILED"
        rec["reason"] = f"{type(exc).__name__}:{str(exc)[:100]}"
        return rec

    if analysis.get("python_files", 0) == 0:
        rec["state"] = "NO_PYTHON_CODE"
        rec["analysis"] = analysis
        return rec

    # Compute code identity from the archive's Python files.
    # Concatenate normalized file contents deterministically (sorted paths) to
    # produce a stable content identity for the package.
    code_identity = _archive_code_identity(dest, hist_pkg)
    rec["content_hash"] = code_identity["content_hash"]
    rec["normalized_hash"] = code_identity["normalized_hash"]
    rec["python_files"] = analysis.get("python_files", 0)
    rec["python_loc"] = analysis.get("python_loc", 0)
    rec["ast_valid"] = analysis.get("ast_valid", 0)
    rec["ast_invalid"] = analysis.get("ast_invalid", 0)

    rec["state"] = "RECOVERED_VERIFIED"
    rec["reason"] = "identity_and_integrity_verified"
    return rec


def _archive_code_identity(archive_path: Path, pkg: str) -> dict:
    """Deterministically derive a content identity from the archive's Python
    files. Uses the project's canonical normalization per file, then a
    deterministic concatenation over sorted relative paths."""
    import tarfile
    import tempfile

    parts = []
    with tarfile.open(archive_path, "r:*") as tf:
        members = sorted(
            [m for m in tf.getmembers() if m.isfile() and m.name.endswith(".py")],
            key=lambda m: m.name,
        )
        for m in members:
            raw = tf.extractfile(m)
            if raw is None:
                continue
            text = raw.read().decode("utf-8", errors="replace")
            normalized = _normalize_pkg_code(text)
            parts.append(normalized)
    joined = "\n".join(parts)
    return {
        "content_hash": hashlib.sha256(joined.encode("utf-8")).hexdigest(),
        "normalized_hash": content_hash(joined),
    }


def _normalize_pkg_code(text: str) -> str:
    from scripts.research.pypi_metadata import normalize_code_for_hash
    return normalize_code_for_hash(text)


def load_frozen_manifest() -> list:
    data = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
    return data["packages"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=25)
    ap.add_argument("--packages", nargs="*", default=None,
                    help="explicit package list (must match manifest packages)")
    args = ap.parse_args()

    pkgs = load_frozen_manifest()
    by_pkg = {p["package"]: p for p in pkgs}

    state = load_state()
    # Build pending list: not yet processed.
    pending = []
    for p in pkgs:
        rec_id = make_record_id(p["package"], p["version"])
        if rec_id not in state["records"]:
            pending.append(p)

    # Optional explicit package filter (for the pilot sample).
    if args.packages:
        pending = [p for p in pending if p["package"] in args.packages]

    batch = pending[: args.batch_size]
    print(f"Recovery batch: {len(batch)} records (pending total: {len(pending)})")

    for hist in batch:
        rec_id = make_record_id(hist["package"], hist["version"])
        rec = recover_one(hist)
        state["records"][rec_id] = rec
        save_state(state)
        append_manifest(rec)
        print(f"  {hist['package']} v{hist['version']}: {rec['state']}")

    # Summary
    from collections import Counter
    counts = Counter(r["state"] for r in state["records"].values())
    print(f"\nRecovery state summary (total records in state): {len(state['records'])}")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    print(f"State saved: {RECOVERY_STATE_PATH}")


if __name__ == "__main__":
    main()