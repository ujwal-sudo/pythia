#!/usr/bin/env python3
"""Resilient PyPI acquisition and package analysis – Session 3."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import tarfile
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests
from tqdm import tqdm

from config import (
    PYPI_DIR,
    PYPI_PACKAGES_DIR,
    PYPI_METADATA_DIR,
    PYPI_MANIFESTS_DIR,
    PYPI_LICENSES_DIR,
    PYPI_REPORTS_DIR,
    PYPI_TOP_PACKAGES_URL,
    PYPI_TOP_PACKAGES_PATH,
    PYPI_CANDIDATES_MANIFEST_PATH,
    PYPI_ACQUISITION_MANIFEST_PATH,
    PYPI_PILOT_REPORT_PATH,
    PYPI_SELECTION_REPORT_PATH,
    PYPI_CANDIDATE_POOL_SIZE,
    PYPI_DOCSTRING_THRESHOLD_HIGH,
    PYPI_DOCSTRING_THRESHOLD_MEDIUM,
    MIN_TOKEN_LENGTH,
    MAX_TOKEN_LENGTH,
    MIN_COMMENT_RATIO,
    PEP8_MAX_VIOLATIONS,
)
from scripts.logger import get_logger
from scripts.validators.ast_validator import validate_python

logger = get_logger(__name__)

# ------------------------------------------------------------------ tiny helpers
def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            d.update(chunk)
    return d.hexdigest()


def normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


# ------------------------------------------------------------------ top‑list discovery
def discover_top_packages(limit: int = PYPI_CANDIDATE_POOL_SIZE, timeout: int = 30) -> List[Dict[str, object]]:
    resp = requests.get(PYPI_TOP_PACKAGES_URL, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    rows = data.get("rows", [])
    rows.sort(key=lambda r: (-r.get("download_count", 0), r["project"].lower()))
    cands = []
    for i, r in enumerate(rows[:limit]):
        cands.append(
            {
                "package": r["project"],
                "normalized": normalize_package_name(r["project"]),
                "rank": i + 1,
                "download_count": r.get("download_count", 0),
                "source_url": PYPI_TOP_PACKAGES_URL,
                "last_update": data.get("last_update", ""),
                "top_list_sha256": sha256_file(PYPI_TOP_PACKAGES_PATH) if PYPI_TOP_PACKAGES_PATH.exists() else None,
            }
        )
    return cands


# ------------------------------------------------------------------ PyPI metadata helpers
def _classify_license(lf: str | None, le: str | None, cls: Sequence[str]) -> Dict[str, str]:
    txt = " ".join([lf or "", le or "", *cls]).lower()
    perm = {"mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc", "psf-2.0", "unlicense", "wtfpl"}
    share = {"gpl-2.0", "gpl-3.0", "lgpl-2.1", "lgpl-3.0", "agpl-3.0", "mpl-2.0", "eupl-1.2", "cc-by-sa"}
    rest = {"proprietary", "commercial", "other/proprietary"}
    if any(t in txt for t in perm):
        return {"status": "CLEAR", "reason": "permissive"}
    if any(t in txt for t in share):
        return {"status": "REVIEW_REQUIRED", "reason": "share-alike"}
    if not txt.strip():
        return {"status": "UNKNOWN", "reason": "no licence metadata"}
    return {"status": "UNKNOWN", "reason": "unclear"}


def fetch_package_metadata(package: str, timeout: int = 30) -> Optional[Dict[str, object]]:
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        d = r.json()
    except Exception as exc:
        logger.warning("PyPI metadata fetch failed for %s: %s", package, exc)
        return None
    info = d.get("info", {})
    rels = d.get("releases", {})

    # pick latest non-yanked sdist
    sel = None
    rule = "no_sdist_available"
    for ver, files in rels.items():
        if any(f.get("yanked", False) for f in files):
            continue
        sd = [f for f in files if f.get("packagetype") == "sdist"]
        if sd:
            sd.sort(key=lambda f: f.get("upload_time_iso_8601", ""), reverse=True)
            sel = sd[0]
            rule = "latest_stable_non_yanked_sdist_by_upload_time"
            break

    # fallback to latest non-yanked wheel
    if sel is None:
        for ver, files in rels.items():
            if any(f.get("yanked", False) for f in files):
                continue
            wh = [f for f in files if f.get("packagetype") == "bdist_wheel"]
            if wh:
                sel = wh[0]
                rule = "latest_non_yanked_wheel_fallback"
                break

    if sel is None:
        logger.warning("No distribution for %s", package)
        return None

    archive_url = sel.get("url", "")
    archive_sha = sel.get("digests", {}).get("sha256")
    archive_sz = sel.get("size", 0)
    archive_fname = sel.get("filename", "")
    rel_date = sel.get("upload_time_iso_8601") or sel.get("upload_time")

    info = d.get("info", {})
    lic = _classify_license(info.get("license"), info.get("license_expression"), info.get("classifiers", []))
    purls = info.get("project_urls") or {}
    repo_url = next(
        (purls[k] for k in ("Repository", "Source", "GitHub", "homepage", "home page") if purls.get(k)),
        None,
    )
    if not repo_url:
        for v in purls.values():
            if v and ("github" in v.lower() or "gitlab" in v.lower()):
                repo_url = v
                break
    doc_url = purls.get("Documentation") or info.get("docs_url")

    requires_python = info.get("requires_python")
    requires_dist = info.get("requires_dist", ())

    return {
        "package": package,
        "version": sel.get("version") or info.get("version"),
        "pypi_url": f"https://pypi.org/pypi/{info.get('version')}",
        "project_url": info.get("home_page"),
        "repository_url": repo_url,
        "documentation_url": doc_url,
        "summary": info.get("summary", ""),
        "description": info.get("description", ""),
        "release_date": sel.get("upload_time_iso_8601") or sel.get("upload_time"),
        "download_count": d.get("rows", [{}])[0].get("download_count") if d.get("rows") else None,
        "archive_url": archive_url,
        "archive_filename": archive_fname,
        "archive_sha256": archive_sha,
        "archive_size": archive_sz,
        "requires_python": requires_python,
        "requires_dist": requires_dist,
        "license_status": lic["status"],
        "license_reason": lic["reason"],
        "license_field": info.get("license"),
        "license_expression": info.get("license_expression"),
        "license_classifiers": tuple(info.get("classifiers", [])),
        "selection_rule": rule,
        "acquisition_timestamp": utc_now_iso(),
    }


# ------------------------------------------------------------------ safe extraction
def safe_extract_archive(archive_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive_path, "r:*") as tf:
            tf.extractall(dest_dir, filter="data")
        return
    except Exception:
        pass
    import zipfile
    with zipfile.ZipFile(archive_path, "r") as zf:
        for member in zf.infolist():
            target = (dest_dir / member.filename).resolve()
            if not str(target).startswith(str(dest_dir.resolve())):
                continue
            if member.is_dir():
                (dest_dir / member.filename).mkdir(parents=True, exist_ok=True)
            else:
                zf.extract(member, dest_dir)


# ------------------------------------------------------------------ Python-file analysis
def _is_gen_or_vendor(p: Path, src: str | None) -> bool:
    parts = {p.lower() for p in p.parts}
    if parts & {"vendor", "third_party", "third-party", "_vendor", "bundled", "vendored"}:
        return True
    if p.name in {"_pb2.py", "_pb2_grpc.py", "_version.py"}:
        return True
    if src:
        lo = src.lower()
        if any(kw in lo for kw in ("autogenerated", "generated by", "do not edit", "machine-generated", "warning: generated")):
            return True
    return False


def _cat_path(p: Path) -> str:
    parts = {p.lower() for p in p.parts}
    if parts & {"vendor", "third_party", "third-party", "_vendor", "bundled", "vendored"}:
        return "vendor"
    if parts & {"tests", "test", "testing", "unittests"}:
        return "test"
    if parts & {"examples", "example", "demos", "demo"}:
        return "example"
    if parts & {"docs", "doc", "documentation"}:
        return "docs"
    if parts & {"generated", ".generated", "build", "dist", "__pycache__"}:
        return "generated"
    return "source"


def analyze_package(archive_path: Path, pkg_name: str) -> Dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="pypi_pilot_") as tmp:
        tmp_path = Path(tmp)
        safe_extract_archive(archive_path, tmp_path)

        py_files = sorted(tmp_path.rglob("*.py")) + sorted(tmp_path.rglob("*.pyw"))
        py_files += sorted(tmp_path.rglob("*.pyi"))

        ast_valid = 0
        ast_invalid = 0
        total_loc = 0
        total_doc = 0
        total_comm = 0
        total_gen = 0
        total_vendor = 0
        dupes: set = set()

        for fp in py_files:
            try:
                src = fp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if "\x00" in src[:4096]:
                continue
            if _is_gen_or_vendor(fp, src):
                total_gen += 1
                continue
            cat = _cat_path(fp)
            if cat == "vendor":
                total_vendor += 1
                continue

            val = validate_python(src)
            if not val.is_valid:
                ast_invalid += 1
                continue
            ast_valid += 1

            total_loc += len(src.splitlines())
            total_doc += val.docstring_count
            total_comm += val.comment_count

            norm_hash = hashlib.sha256(fp.read_bytes()).hexdigest()
            if norm_hash in dupes:
                total_gen += 1
                continue
            dupes.add(norm_hash)

        pkg_sz = archive_path.stat().st_size if archive_path.exists() else 0
        largest = max(
            [(len(fp.read_text(encoding="utf-8", errors="replace").splitlines()), str(fp.relative_to(tmp_path))) for fp in py_files if fp.exists()],
            default=(0, ""),
        )

        return {
            "python_files": len(py_files),
            "non_python_files": 0,
            "python_loc": total_loc,
            "ast_valid": ast_valid,
            "ast_invalid": ast_invalid,
            "docstring_count": total_doc,
            "comment_count": total_comm,
            "generated_or_vendor_count": total_gen + total_vendor,
            "duplicate_count": len(dupes),
            "largest_python_file": largest[1],
            "largest_python_loc": largest[0],
            "package_size_bytes": pkg_sz,
            "docstring_ratio": total_doc / max(1, len(py_files)),
            "comment_ratio": total_comm / max(1, total_loc),
        }


# ------------------------------------------------------------------ manifest helpers
def _atomic_write_json(path: Path, data: Dict[str, object]) -> None:
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _atomic_write_jsonl(path: Path, records: List[Dict[str, object]]) -> None:
    tmp = path.with_suffix(".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, sort_keys=True) + "\n")
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def write_candidates_manifest(candidates: List[Dict[str, object]], path: Path = PYPI_CANDIDATES_MANIFEST_PATH) -> None:
    _atomic_write_jsonl(path, candidates)


def write_acquisition_manifest(packages: List[Dict[str, object]], path: Path = PYPI_ACQUISITION_MANIFEST_PATH) -> None:
    _atomic_write_json(path, {"source": "pypi", "generated_at": utc_now_iso(),
                               "record_count": len(packages), "packages": packages})


# ------------------------------------------------------------------ checkpoint / resumability
def _load_checkpoint(path: Path) -> Dict[str, Dict[str, object]]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_checkpoint(path: Path, state: Dict[str, Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, state)


def checkpoint_path(pkg_norm: str) -> Path:
    return PYPI_METADATA_DIR / f"{pkg_norm}_checkpoint.json"


def is_acquired(pkg_norm: str) -> bool:
    st = _load_checkpoint(checkpoint_path(pkg_norm)).get(pkg_norm, {})
    return st.get("state") == "ACQUIRED"


def mark_acquired(pkg_norm: str, **kw) -> None:
    cp = checkpoint_path(pkg_norm)
    _save_checkpoint(cp, {pkg_norm: {"state": "ACQUIRED", "acquired_at": utc_now_iso(), **kw}})


def mark_failed(pkg_norm: str, reason: str, **kw) -> None:
    cp = checkpoint_path(pkg_norm)
    _save_checkpoint(cp, {pkg_norm: {"state": "FAILED", "failure_reason": reason, "failed_at": utc_now_iso(), **kw}})


def _load_all_acquired_license_statuses() -> List[str]:
    """Return a list of license_status for all packages with state ACQUIRED in checkpoints."""
    statuses = []
    for cp in PYPI_METADATA_DIR.glob("*_checkpoint.json"):
        try:
            data = json.loads(cp.read_text(encoding="utf-8"))
            for pkg, info in data.items():
                if info.get("state") == "ACQUIRED":
                    status = info.get("licence_status", "UNKNOWN")
                    statuses.append(status)
        except Exception:
            pass
    return statuses


def _regenerate_manifests_from_checkpoints() -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    """Read all checkpoints and rebuild acquisition manifest and pilot report."""
    acquired: List[Dict[str, object]] = []
    failures: List[Dict[str, object]] = []
    skipped: List[Dict[str, object]] = []

    for cp in sorted(PYPI_METADATA_DIR.glob("*_checkpoint.json")):
        try:
            data = json.loads(cp.read_text(encoding="utf-8"))
            for pkg, info in data.items():
                state = info.get("state")
                if state == "ACQUIRED":
                    acquired.append({
                        "package": pkg,
                        "normalized": normalize_package_name(pkg),
                        "version": info.get("version"),
                        "archive_path": f"/mnt/pythia-cloud/Pythia/raw/pypi/packages/{normalize_package_name(pkg)}/{info.get('version')}/{pkg}-{info.get('version')}.tar.gz",
                        "analysis": {
                            "ast_valid": info.get("ast_valid", 0),
                            "ast_invalid": info.get("ast_invalid", 0),
                            "comment_count": info.get("comment_count", 0),
                            "docstring_count": info.get("docstring_count", 0),
                            "docstring_ratio": info.get("docstring_ratio", 0.0),
                            "comment_ratio": info.get("comment_ratio", 0.0),
                            "duplicate_count": info.get("duplicate_count", 0),
                            "generated_or_vendor_count": info.get("generated_or_vendor_count", 0),
                            "python_files": info.get("python_files", 0),
                            "python_loc": info.get("python_loc", 0),
                            "package_size_bytes": info.get("archive_size", 0),
                            "license_status": info.get("licence_status", "UNKNOWN"),
                        },
                        "selection_rule": info.get("selection_rule", "latest_stable_non_yanked_sdist_by_upload_time"),
                        "acquisition_timestamp": info.get("acquired_at"),
                    })
                elif state == "FAILED":
                    failures.append({
                        "package": pkg,
                        "normalized": normalize_package_name(pkg),
                        "reason": info.get("failure_reason", "unknown"),
                        "failed_at": info.get("failed_at"),
                    })
                elif state == "SKIPPED":
                    skipped.append({"package": pkg, "reason": info.get("reason", "already_acquired")})
        except Exception:
            pass

    # Build report
    from collections import Counter
    report = {
        "experiment_id": "PYT-DATA-PYPI-002",
        "pilot_size": len(acquired) + len(failures) + len(skipped),
        "packages_discovered": PYPI_CANDIDATE_POOL_SIZE,
        "packages_acquired": len(acquired),
        "packages_failed": len(failures),
        "packages_skipped": len(skipped),
        "python_files_total": sum(a["analysis"]["python_files"] for a in acquired),
        "ast_valid": sum(a["analysis"]["ast_valid"] for a in acquired),
        "ast_invalid": sum(a["analysis"]["ast_invalid"] for a in acquired),
        "docstring_ratio": sum(a["analysis"]["docstring_ratio"] for a in acquired) / max(1, len(acquired)),
        "comment_ratio": sum(a["analysis"]["comment_ratio"] for a in acquired) / max(1, len(acquired)),
        "license_status_dist": dict(Counter(a.get("license_status", "UNKNOWN") for a in acquired)),
        "generated_vendor_total": sum(a["analysis"]["generated_or_vendor_count"] for a in acquired),
        "duplicate_count": sum(a["analysis"]["duplicate_count"] for a in acquired),
        "storage_used_bytes": sum(a["analysis"]["package_size_bytes"] for a in acquired),
    }

    return acquired, failures, skipped, {"acquired": acquired, "failures": failures, "skipped": skipped, "report": {"experiment_id": "PYT-DATA-PYPI-002", **report}}


def _atomic_write_json(path: Path, data: Dict[str, object]) -> None:
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _atomic_write_jsonl(path: Path, records: List[Dict[str, object]]) -> None:
    tmp = path.with_suffix(".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, sort_keys=True) + "\n")
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def write_candidates_manifest(candidates: List[Dict[str, object]], path: Path = PYPI_CANDIDATES_MANIFEST_PATH) -> None:
    _atomic_write_jsonl(path, candidates)


def write_acquisition_manifest(packages: List[Dict[str, object]], path: Path = PYPI_ACQUISITION_MANIFEST_PATH) -> None:
    _atomic_write_json(path, {"source": "pypi", "generated_at": utc_now_iso(),
                               "record_count": len(packages), "packages": packages})


def _download_file(url: str, dest: Path, timeout: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = Path(str(dest) + ".part")
    try:
        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            with part.open("wb") as f, tqdm(total=total, unit="B", unit_scale=True, desc=dest.name) as bar:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        bar.update(len(chunk))
        part.replace(dest)
    except Exception:
        part.unlink(missing_ok=True)
        raise


# ------------------------------------------------------------------ pilot orchestration
def run_pilot(limit: int = 5, timeout: int = 60) -> Dict[str, object]:
    candidates = discover_top_packages(limit=PYPI_CANDIDATE_POOL_SIZE)
    pilot_cands = candidates[:limit]

    # Ensure manifests directory exists
    PYPI_MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
    write_candidates_manifest(candidates)

    # Load already acquired from checkpoints
    acquired: List[Dict[str, object]] = []
    failures: List[Dict[str, object]] = []
    skipped: List[Dict[str, object]] = []

    for c in tqdm(pilot_cands, desc="pypi-pilot"):
        norm = c["normalized"]
        if is_acquired(norm):
            skipped.append({**c, "reason": "already_acquired"})
            continue

        # Process package with full error isolation
        try:
            meta = fetch_package_metadata(c["package"])
            if meta is None:
                mark_failed(norm, "metadata_fetch_failed")
                failures.append({**c, "reason": "metadata_fetch_failed"})
                continue

            dest_dir = PYPI_PACKAGES_DIR / norm
            dest_dir.mkdir(parents=True, exist_ok=True)
            archive_name = meta.get("archive_filename", "")
            version = meta.get("version")
            archive_path = (dest_dir / version / archive_name) if version else dest_dir / archive_name
            archive_path.parent.mkdir(parents=True, exist_ok=True)

            downloaded = archive_path.exists() and archive_path.stat().st_size > 0
            verified = False
            if downloaded:
                if meta.get("archive_sha256"):
                    verified = sha256_file(archive_path) == meta["archive_sha256"]
                else:
                    verified = True
            if not downloaded or not verified:
                _download_file(meta["archive_url"], archive_path, timeout)
                if meta.get("archive_sha256"):
                    verified = sha256_file(archive_path) == meta["archive_sha256"]
                else:
                    verified = True

            if not verified:
                mark_failed(norm, "checksum_mismatch")
                failures.append({**c, "reason": "checksum_mismatch"})
                continue

            analysis = analyze_package(archive_path, c["package"])

            mark_acquired(norm,
                          version=meta["version"],
                          archive_sha256=meta["archive_sha256"],
                          archive_size=meta["archive_size"],
                          licence_status=meta["license_status"],
                          licence_reason=meta["license_reason"],
                          docstring_ratio=analysis["docstring_ratio"],
                          comment_ratio=analysis["comment_ratio"],
                          ast_valid=analysis["ast_valid"],
                          ast_invalid=analysis["ast_invalid"],
                          python_files=analysis["python_files"],
                          python_loc=analysis["python_loc"],
                          )
            analysis["license_status"] = meta["license_status"]
            acquired.append({
                "package": c["package"],
                "normalized": norm,
                "version": meta["version"],
                "archive_path": str(archive_path),
                "analysis": analysis,
                "selection_rule": meta["selection_rule"],
                "acquisition_timestamp": meta["acquisition_timestamp"],
            })

        except Exception as exc:
            logger.exception("Unexpected error processing %s", c["package"])
            mark_failed(norm, f"unexpected_error:{exc}")
            failures.append({**c, "reason": f"unexpected_error:{exc}"})
            continue

        # After each package, regenerate manifests from checkpoints to keep them durable
        _regenerate_and_write_manifests()

    # Final regeneration
    _regenerate_and_write_manifests()

    report = {
        "experiment_id": "PYT-DATA-PYPI-002",
        "pilot_size": limit,
        "packages_discovered": len(candidates),
        "packages_attempted": len(pilot_cands),
        "packages_acquired": len(acquired),
        "packages_failed": len(failures),
        "packages_skipped": len(skipped),
        "python_files_total": sum(a["analysis"]["python_files"] for a in acquired),
        "ast_valid": sum(a["analysis"]["ast_valid"] for a in acquired),
        "ast_invalid": sum(a["analysis"]["ast_invalid"] for a in acquired),
        "docstring_ratio": sum(a["analysis"]["docstring_ratio"] for a in acquired) / max(1, len(acquired)),
        "comment_ratio": sum(a["analysis"]["comment_ratio"] for a in acquired) / max(1, len(acquired)),
        "license_status_dist": dict(Counter(a.get("license_status", "UNKNOWN") for a in acquired)),
        "generated_vendor_total": sum(a["analysis"]["generated_or_vendor_count"] for a in acquired),
        "duplicate_count": sum(a["analysis"]["duplicate_count"] for a in acquired),
        "storage_used_bytes": sum(a["analysis"]["package_size_bytes"] for a in acquired),
    }

    PYPI_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(PYPI_PILOT_REPORT_PATH, {"experiment_id": "PYT-DATA-PYPI-002", **report})

    return {"acquired": acquired, "failures": failures, "skipped": skipped, "report": {"experiment_id": "PYT-DATA-PYPI-002", **report}}


def _regenerate_and_write_manifests() -> None:
    """Regenerate acquisition manifest and pilot report from checkpoints."""
    acquired, failures, skipped, report_bundle = _regenerate_manifests_from_checkpoints()
    write_acquisition_manifest(acquired)
    PYPI_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(PYPI_PILOT_REPORT_PATH, {"experiment_id": "PYT-DATA-PYPI-002", **_regenerate_manifests_from_checkpoints()[3]["report"]})


def _download_file(url: str, dest: Path, timeout: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = Path(str(dest) + ".part")
    try:
        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            with part.open("wb") as f, tqdm(total=total, unit="B", unit_scale=True, desc=dest.name) as bar:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        bar.update(len(chunk))
        part.replace(dest)
    except Exception:
        part.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PyPI pilot (Session 3)")
    parser.add_argument("--limit", type=int, default=5, help="how many packages to try")
    parser.add_argument("--timeout", type=int, default=120, help="download timeout seconds")
    args = parser.parse_args()
    run_pilot(limit=args.limit, timeout=args.timeout)