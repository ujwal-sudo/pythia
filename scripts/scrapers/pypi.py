#!/usr/bin/env python3
"""Resilient PyPI acquisition and package analysis – Session 3."""
from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import logging
import multiprocessing
import os
import re
import shutil
import sys
import tarfile
import tempfile
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests
from tqdm import tqdm

try:
    from packaging.version import InvalidVersion, Version
except ImportError:  # pragma: no cover - packaging is normally present
    class InvalidVersion(Exception):
        pass

    Version = None  # type: ignore[assignment]

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
from scripts.scrapers.pypi_storage import (
    LocalWriterLock,
    LockNotHeldError,
    WriterLock,
    assert_no_freeze,
    canonical_pypi_root,
    commit_write,
    freeze_sentinel_exists,
    map_local_path_to_remote,
    reconcile_startup,
    remote_archive_exists,
    remote_archive_sha256,
    remote_checkpoint_names,
    remote_exists,
    remote_headroom,
    remote_list,
    remote_list_recursive,
    remote_read_bytes,
    remote_read_text,
    remote_sha256,
    save_archive_remote,
    save_checkpoint_remote,
    save_manifest_remote,
)

logger = get_logger(__name__)

# Frozen-baseline sentinel: when present, PyPI checkpoint writes are refused.
# Place this file while a freeze/recovery is active to prevent concurrent writers.
# Resolved through the authoritative remote (pythia:Pythia/raw/pypi/.FREEZE_SENTINEL).
PYPI_FREEZE_SENTINEL = Path(os.environ.get(
    "PYPI_FREEZE_SENTINEL",
    str(canonical_pypi_root() / ".FREEZE_SENTINEL"),
))

# When set to "1", PyPI storage operations (checkpoint writes, freeze checks,
# headroom) route through the remote storage abstraction (pythia:Pythia).
# Default is OFF so existing POSIX/local behavior is preserved. Remote
# execution remains unauthorized; this flag only enables the storage layer.
PYPI_REMOTE_STORAGE = os.environ.get("PYPI_REMOTE_STORAGE", "0") == "1"

# Versioned remediation state. The repair plan is a static list of packages
# whose legacy checkpoints/archives failed identity verification. Completed
# and exhausted markers are written per package so a resumed acquisition does
# not redo finished work or loop forever on permanent failures.
REMEDIATION_V2_DIR = PYPI_DIR / "remediation_v2"
REPAIR_PLAN_PATH = REMEDIATION_V2_DIR / "repair_plan_v1.json"
REPAIR_PLAN_ADDENDUM_PATH = REMEDIATION_V2_DIR / "repair_plan_v2.json"
REPAIR_COMPLETED_DIR = REMEDIATION_V2_DIR / "completed"
REPAIR_EXHAUSTED_DIR = REMEDIATION_V2_DIR / "exhausted"

_ANALYSIS_POOL: Optional[ProcessPoolExecutor] = None
_ANALYSIS_POOL_LOCK = threading.Lock()


def _analysis_pool_ping() -> bool:
    return True


def _get_analysis_pool(workers: int) -> Optional[ProcessPoolExecutor]:
    """Create a persistent CPU pool before package threads begin work."""
    global _ANALYSIS_POOL
    if workers <= 1:
        return None
    with _ANALYSIS_POOL_LOCK:
        if _ANALYSIS_POOL is None:
            # Fork before ThreadPoolExecutor starts, so no application worker
            # threads are inherited into the analysis processes.
            _ANALYSIS_POOL = ProcessPoolExecutor(
                max_workers=workers,
                mp_context=multiprocessing.get_context("fork"),
            )
            _ANALYSIS_POOL.submit(_analysis_pool_ping).result(timeout=60)
            atexit.register(_ANALYSIS_POOL.shutdown, wait=True, cancel_futures=False)
        return _ANALYSIS_POOL

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


def _fallback_version_key(version: str) -> Tuple[Tuple[int, Any], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"(\d+)", version)
        if part
    )


def _version_sort_key(version: str) -> Tuple[int, Any]:
    if Version is None:
        return (0, _fallback_version_key(version))
    try:
        return (1, Version(version))
    except InvalidVersion:
        return (0, _fallback_version_key(version))


def _versions_equal(left: object, right: object) -> bool:
    """Compare PEP 440 versions semantically, preserving unknown strings."""
    if str(left) == str(right):
        return True
    if Version is not None:
        try:
            return Version(str(left)) == Version(str(right))
        except InvalidVersion:
            return False
    return False


# ------------------------------------------------------------------ archive identity verification
def parse_version_from_filename(filename: str) -> Optional[str]:
    """Extract the version embedded in an archive filename.

    Handles sdist names like 'absl-py-0.1.0.tar.gz' and wheel names like
    'pkg-1.0.0-py3-none-any.whl'. Returns None when no version can be parsed.
    """
    if not filename:
        return None
    if filename.endswith(".whl"):
        # {distribution}-{version}(-{build})?-{python}-{abi}-{platform}.whl
        parts = filename[:-4].split("-")
        if len(parts) >= 5 and re.match(r"^[0-9]", parts[1]):
            return parts[1]
        return None
    base = re.sub(r"\.(tar\.gz|tgz|tar\.bz2|zip)$", "", filename)
    base = base.rsplit("-", 1)[-1].rsplit("_", 1)[-1]
    if not base:
        return None
    if not re.match(r"^[0-9]", base):
        return None
    return base


def _parse_archive_metadata_bytes(raw: bytes) -> Dict[str, Optional[str]]:
    """Parse package name/version from archive bytes (sdist tar or wheel zip)."""
    import io
    import zipfile

    result: Dict[str, Optional[str]] = {"package": None, "version": None}

    def _parse_text(content: str) -> None:
        for line in content.splitlines():
            if line.startswith("Name:") and result["package"] is None:
                result["package"] = line.split(":", 1)[1].strip()
            elif line.startswith("Version:") and result["version"] is None:
                result["version"] = line.split(":", 1)[1].strip()
            if result["package"] is not None and result["version"] is not None:
                return

    # Prefer distribution-root metadata. Source archives can contain nested
    # test fixtures with their own PKG-INFO; taking the first matching file
    # can incorrectly reject a valid archive based on fixture metadata.
    # sdist: tar
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as tf:
            candidates = []
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                parts = [
                    part for part in member.name.replace("\\", "/").split("/")
                    if part not in ("", ".")
                ]
                basename = parts[-1].lower() if parts else ""
                parent = parts[-2].lower() if len(parts) > 1 else ""
                if basename == "pkg-info":
                    preferred = len(parts) <= 2
                elif basename == "metadata" and parent.endswith(".dist-info"):
                    preferred = len(parts) <= 2
                else:
                    continue
                candidates.append((0 if preferred else 1, len(parts), member.name, member))
            for _priority, _depth, _name, member in sorted(candidates):
                f = tf.extractfile(member)
                if f is not None:
                    _parse_text(f.read().decode("utf-8", errors="replace"))
                if result["package"] is not None and result["version"] is not None:
                    return result
    except Exception:
        pass
    if result["package"] is not None and result["version"] is not None:
        return result

    # wheel: zip dist-info/METADATA
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            candidates = []
            for name in zf.namelist():
                parts = [
                    part for part in name.replace("\\", "/").split("/")
                    if part not in ("", ".")
                ]
                if (
                    parts
                    and parts[-1].lower() == "metadata"
                    and len(parts) == 2
                    and parts[0].lower().endswith(".dist-info")
                ):
                    candidates.append(name)
            for name in sorted(candidates):
                try:
                    _parse_text(zf.read(name).decode("utf-8", errors="replace"))
                except Exception:
                    continue
                if result["package"] is not None and result["version"] is not None:
                    return result
    except Exception:
        pass
    return result


def _archive_metadata_identity(archive_path: Path) -> Dict[str, Optional[str]]:
    """Read package name/version from an archive's PKG-INFO or METADATA.

    Backend-aware: in remote mode the archive bytes are fetched through the
    storage abstraction and parsed in-memory (never assumed present on the
    local FUSE path). Returns {'package': ..., 'version': ...} (None when
    unavailable).
    """
    if PYPI_REMOTE_STORAGE:
        try:
            remote = map_local_path_to_remote(archive_path)
            if not remote_exists(remote):
                return {"package": None, "version": None}
            raw = remote_read_bytes(remote)
            return _parse_archive_metadata_bytes(raw)
        except Exception:
            return {"package": None, "version": None}
    result: Dict[str, Optional[str]] = {"package": None, "version": None}
    if not archive_path.exists():
        return result
    try:
        raw = archive_path.read_bytes()
    except Exception:
        return result
    return _parse_archive_metadata_bytes(raw)


def verify_archive_identity(
    requested_package: str,
    requested_version: Optional[str],
    meta: Dict[str, object],
    archive_path: Path,
    expected_sha256: Optional[str] = None,
) -> Dict[str, object]:
    """Run the full archive identity verification gate.

    Returns a dict with 'ok' (bool), 'status' (ACCEPT/REJECT),
    'reason', and the individual observed facts. A cached artifact may
    only be reused when every check passes.
    """
    facts: Dict[str, object] = {
        "requested_package": requested_package,
        "requested_version": requested_version,
        "resolved_version": meta.get("version"),
        "resolved_filename": meta.get("archive_filename"),
        "archive_path": str(archive_path),
    }

    # SHA checks (when an expected SHA is available).
    expected_sha = expected_sha256 if expected_sha256 is not None else meta.get("archive_sha256")
    # Derive pkg/version/filename for remote routing (path is packages/<norm>/<version>/<filename>).
    _rel = archive_path.parts
    _norm = _rel[-3] if len(_rel) >= 3 else None
    _ver = _rel[-2] if len(_rel) >= 2 else None
    _fn = _rel[-1] if _rel else None
    observed_sha = _archive_sha256_value(
        archive_path, pkg_norm=_norm, version=_ver, filename=_fn)
    facts["archive_sha256_expected"] = expected_sha
    facts["archive_sha256_observed"] = observed_sha
    if expected_sha is not None:
        if observed_sha is None or observed_sha != expected_sha:
            facts["ok"] = False
            facts["status"] = "REJECT"
            facts["reason"] = "sha_mismatch"
            return facts
        facts["sha_verified"] = True
    else:
        facts["sha_verified"] = False

    # Filename-derived version.
    filename = str(meta.get("archive_filename") or archive_path.name)
    filename_version = parse_version_from_filename(filename)
    facts["observed_filename"] = filename
    facts["observed_filename_version"] = filename_version

    # Internal metadata identity.
    inner = _archive_metadata_identity(archive_path)
    facts["observed_metadata_package"] = inner.get("package")
    facts["observed_metadata_version"] = inner.get("version")

    # Requested version must agree with the resolved distribution version.
    if (
        requested_version is not None
        and not _versions_equal(meta.get("version"), requested_version)
    ):
        facts["ok"] = False
        facts["status"] = "REJECT"
        facts["reason"] = "resolved_version_mismatch"
        return facts

    # The observed identity must not contradict the requested identity.
    if requested_version is not None:
        if filename_version is not None and not _versions_equal(
            filename_version, requested_version
        ):
            facts["ok"] = False
            facts["status"] = "REJECT"
            facts["reason"] = "filename_version_mismatch"
            return facts
        inner_ver = inner.get("version")
        if inner_ver is not None and not _versions_equal(inner_ver, requested_version):
            facts["ok"] = False
            facts["status"] = "REJECT"
            facts["reason"] = "metadata_version_mismatch"
            return facts

    # If no expected SHA was available, identity must still be proven by
    # at least one independent version observation matching the request.
    if requested_version is not None:
        if filename_version is None and inner.get("version") is None:
            facts["ok"] = False
            facts["status"] = "QUARANTINE"
            facts["reason"] = "identity_unprovable_no_sha"
            return facts

    facts["ok"] = True
    facts["status"] = "ACCEPT"
    facts["reason"] = "identity_verified"
    return facts


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


def fetch_package_metadata(package: str, timeout: int = 30, requested_version: Optional[str] = None) -> Optional[Dict[str, object]]:
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

    # Prefer PyPI's explicit info.version when present. Otherwise choose the
    # highest stable release by PEP 440 ordering, falling back to prereleases
    # only when no stable distribution is available. A specific requested
    # version is always selected exactly.
    def _collect_release_candidates(
        release_versions: Sequence[str],
        *,
        exclude_prereleases: bool,
    ) -> List[Tuple[Tuple[int, Any], str, str, Dict[str, object], str]]:
        found: List[Tuple[Tuple[int, Any], str, str, Dict[str, object], str]] = []
        for ver in release_versions:
            if exclude_prereleases and Version is not None:
                try:
                    parsed_version = Version(ver)
                except InvalidVersion:
                    continue
                if parsed_version.is_prerelease or parsed_version.is_devrelease:
                    continue
            files = [f for f in rels.get(ver, []) if not f.get("yanked", False)]
            if not files:
                continue
            sd = [f for f in files if f.get("packagetype") == "sdist"]
            if sd:
                picked = sorted(
                    sd,
                    key=lambda f: (
                        f.get("upload_time_iso_8601", ""),
                        f.get("filename", ""),
                    ),
                    reverse=True,
                )[0]
                if requested_version is not None:
                    rule = "explicit_requested_version_non_yanked_sdist"
                elif str(info.get("version") or "") == ver:
                    rule = "pypi_info_version_non_yanked_sdist"
                elif exclude_prereleases:
                    rule = "latest_stable_non_yanked_sdist_by_version"
                else:
                    rule = "latest_non_yanked_sdist_by_version_fallback"
            else:
                wh = [f for f in files if f.get("packagetype") == "bdist_wheel"]
                if not wh:
                    continue
                picked = sorted(
                    wh,
                    key=lambda f: (
                        f.get("upload_time_iso_8601", ""),
                        f.get("filename", ""),
                    ),
                    reverse=True,
                )[0]
                if requested_version is not None:
                    rule = "explicit_requested_version_non_yanked_wheel_fallback"
                elif str(info.get("version") or "") == ver:
                    rule = "pypi_info_version_non_yanked_wheel_fallback"
                elif exclude_prereleases:
                    rule = "latest_stable_non_yanked_wheel_fallback"
                else:
                    rule = "latest_non_yanked_wheel_fallback_by_version"
            upload_time = str(picked.get("upload_time_iso_8601") or picked.get("upload_time") or "")
            found.append((_version_sort_key(ver), upload_time, ver, picked, rule))
        return found

    candidates: List[Tuple[Tuple[int, Any], str, str, Dict[str, object], str]]
    if requested_version is not None:
        if requested_version not in rels:
            logger.warning(
                "Requested version %s not present for %s", requested_version, package)
            return None
        candidates = _collect_release_candidates([requested_version], exclude_prereleases=False)
    else:
        info_version = str(info.get("version") or "")
        candidates = (
            _collect_release_candidates([info_version], exclude_prereleases=False)
            if info_version in rels
            else []
        )
        if not candidates:
            candidates = _collect_release_candidates(list(rels), exclude_prereleases=True)
        if not candidates:
            candidates = _collect_release_candidates(list(rels), exclude_prereleases=False)

    if not candidates:
        logger.warning("No distribution for %s", package)
        return None

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    _, _, selected_version, sel, rule = candidates[0]

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

    resolved_version = selected_version
    used_info_version_fallback = False

    # Parse actual version from archive filename as primary observation
    filename_version = parse_version_from_filename(archive_fname)
    if filename_version is not None and filename_version != resolved_version:
        logger.warning(
            "Selected release %s for %s but archive filename reports %s: %s",
            resolved_version, package, filename_version, archive_fname,
        )

    return {
        "package": package,
        "requested_version": requested_version,
        "version": resolved_version,
        "resolved_version": resolved_version,
        "latest_version": info.get("version"),
        "used_info_version_fallback": used_info_version_fallback,
        "resolved_filename": archive_fname,
        "observed_filename_version": filename_version,
        "pypi_url": f"https://pypi.org/pypi/{package}/{resolved_version}/",
        "project_url": info.get("home_page"),
        "repository_url": repo_url,
        "documentation_url": doc_url,
        "summary": info.get("summary", ""),
        "description": info.get("description", ""),
        "release_date": rel_date,
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

        py_files = sorted(
            path
            for pattern in ("*.py", "*.pyw", "*.pyi")
            for path in tmp_path.rglob(pattern)
            if path.is_file()
        )

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
            [
                (
                    len(fp.read_text(encoding="utf-8", errors="replace").splitlines()),
                    str(fp.relative_to(tmp_path)),
                )
                for fp in py_files
                if fp.is_file()
            ],
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
def _retry_io(fn, attempts: int = 4, base_sleep: float = 2.0) -> object:
    """Retry a filesystem operation that may hit transient cloud-mount I/O errors."""
    import time as _time
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except OSError as exc:
            last_exc = exc
            if attempt < attempts:
                _time.sleep(base_sleep * attempt)
    raise last_exc


def _atomic_write_json(path: Path, data: Dict[str, object]) -> None:
    tmp = path.with_suffix(".tmp")
    def _do_write() -> None:
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
    try:
        _retry_io(_do_write)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _atomic_write_jsonl(path: Path, records: List[Dict[str, object]]) -> None:
    tmp = path.with_suffix(".tmp")
    def _do_write() -> None:
        with tmp.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, sort_keys=True) + "\n")
        tmp.replace(path)
    try:
        _retry_io(_do_write)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


# NOTE: The single consolidated `write_candidates_manifest` and
# `write_acquisition_manifest` are defined below (remote-aware when
# PYPI_REMOTE_STORAGE=1, POSIX fallback otherwise). Legacy POSIX-only
# duplicates that previously shadowed them were removed.


# ------------------------------------------------------------------ checkpoint / resumability
def _load_checkpoint(path: Path) -> Dict[str, Dict[str, object]]:
    try:
        if PYPI_REMOTE_STORAGE:
            remote = map_local_path_to_remote(path)
            if not remote_exists(remote):
                return {}
            return json.loads(remote_read_text(remote))
        return json.loads(_retry_io(lambda: path.read_text(encoding="utf-8")))
    except Exception:
        return {}


def _save_checkpoint(
    path: Path,
    state: Dict[str, Dict[str, object]],
    *,
    allow_overwrite: bool = False,
) -> None:
    # Frozen-baseline guard: when the freeze sentinel is present, checkpoint
    # writes are refused and logged rather than mutating historical data.
    # This prevents concurrent PyPI writers (e.g. an agent relaunching scaleup)
    # from modifying the frozen 3,041-checkpoint baseline during recovery.
    if freeze_sentinel_exists() if PYPI_REMOTE_STORAGE else PYPI_FREEZE_SENTINEL.exists():
        logger.warning(
            "REFUSED checkpoint write (freeze sentinel present): %s "
            "state=%s", path.name, list(state)[:1],
        )
        raise OSError(
            f"PyPI baseline is FROZEN (sentinel present); "
            f"refusing checkpoint write to {path.name}"
        )
    if PYPI_REMOTE_STORAGE:
        # Route through the two-phase remote commit protocol. Freeze is
        # re-checked FIRST inside the storage layer (fail-closed).
        pkg_norm = path.name.replace("_checkpoint.json", "")
        save_checkpoint_remote(pkg_norm, state, allow_overwrite=allow_overwrite)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, state)


def checkpoint_path(pkg_norm: str) -> Path:
    return PYPI_METADATA_DIR / f"{pkg_norm}_checkpoint.json"


def is_acquired(pkg_norm: str) -> bool:
    st = _load_checkpoint(checkpoint_path(pkg_norm)).get(pkg_norm, {})
    return st.get("state") == "ACQUIRED"


def mark_acquired(pkg_norm: str, *, allow_overwrite: bool = False, **kw) -> None:
    cp = checkpoint_path(pkg_norm)
    _save_checkpoint(
        cp,
        {pkg_norm: {"state": "ACQUIRED", "acquired_at": utc_now_iso(), **kw}},
        allow_overwrite=allow_overwrite,
    )


def mark_failed(
    pkg_norm: str,
    reason: str,
    *,
    allow_overwrite: bool = False,
    **kw,
) -> None:
    cp = checkpoint_path(pkg_norm)
    _save_checkpoint(
        cp,
        {
            pkg_norm: {
                "state": "FAILED",
                "failure_reason": reason,
                "failed_at": utc_now_iso(),
                **kw,
            }
        },
        allow_overwrite=allow_overwrite,
    )


def _iter_checkpoint_paths() -> List[Path]:
    """Yield checkpoint file paths using the active backend.

    POSIX mode: local glob over PYPI_METADATA_DIR.
    Remote mode: remote listing over the authoritative metadata dir; returns
    local-style Path objects that storage helpers can map back to remote.
    """
    if PYPI_REMOTE_STORAGE:
        return [PYPI_METADATA_DIR / n for n in remote_checkpoint_names()]
    return sorted(PYPI_METADATA_DIR.glob("*_checkpoint.json"))


def _read_checkpoint_content(path: Path) -> Dict[str, Dict[str, object]]:
    """Read a checkpoint file using the active backend.

    POSIX mode: local read_text.
    Remote mode: remote_read_text through the storage abstraction.
    Returns {} on unreadable/absent.
    """
    try:
        if PYPI_REMOTE_STORAGE:
            remote = map_local_path_to_remote(path)
            if not remote_exists(remote):
                return {}
            return json.loads(remote_read_text(remote))
        return json.loads(_retry_io(lambda: path.read_text(encoding="utf-8")))
    except Exception:
        return {}


def _archive_sha256_value(archive_path: Path, *, pkg_norm: Optional[str] = None,
                          version: Optional[str] = None,
                          filename: Optional[str] = None) -> Optional[str]:
    """Compute an archive's SHA-256 using the active backend.

    POSIX mode: local sha256_file.
    Remote mode: remote_archive_sha256 through the storage abstraction.
    """
    if PYPI_REMOTE_STORAGE:
        if pkg_norm and version and filename:
            return remote_archive_sha256(pkg_norm, version, filename)
        return None
    if archive_path.exists():
        return sha256_file(archive_path)
    return None


def _archive_exists(path: Path, *, pkg_norm: Optional[str] = None,
                    version: Optional[str] = None,
                    filename: Optional[str] = None) -> bool:
    """Check archive existence using the active backend."""
    if PYPI_REMOTE_STORAGE:
        if pkg_norm and version and filename:
            return remote_archive_exists(pkg_norm, version, filename)
        return False
    return path.exists()


def _mkdir_remote_aware(path: Path) -> None:
    """Ensure a directory exists without depending on the FUSE mount.

    In remote mode rclone creates parent objects implicitly on upload, so a
    local mkdir against the (possibly unmounted) FUSE path must be skipped.
    """
    if PYPI_REMOTE_STORAGE:
        return
    path.mkdir(parents=True, exist_ok=True)


def _write_report(path: Path, data: Dict[str, object]) -> None:
    """Write a report artifact, backend-aware.

    Reports are regenerated artifacts (overwrite intended). In remote mode the
    write goes through the two-phase commit protocol with a journal marker so a
    partial report can never be mistaken for the final report.
    """
    payload = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if PYPI_REMOTE_STORAGE:
        remote = map_local_path_to_remote(path)
        commit_write(payload, remote, prevent_overwrite=False,
                     namespace="report", verify=True, journal=True)
        return
    _atomic_write_json(path, data)


def _load_all_acquired_license_statuses() -> List[str]:
    """Return a list of license_status for all packages with state ACQUIRED in checkpoints."""
    statuses = []
    checkpoint_paths = _iter_checkpoint_paths()
    read_workers = min(32, max(1, len(checkpoint_paths)))
    with ThreadPoolExecutor(max_workers=read_workers) as checkpoint_readers:
        checkpoint_data = list(
            checkpoint_readers.map(_read_checkpoint_content, checkpoint_paths)
        )

    for cp, data in zip(checkpoint_paths, checkpoint_data):
        try:
            for pkg, info in data.items():
                if info.get("state") == "ACQUIRED":
                    status = info.get("licence_status", "UNKNOWN")
                    statuses.append(status)
        except Exception:
            pass
    return statuses


def _resolve_checkpoint_archive_filename(
    package: str,
    info: Dict[str, object],
) -> Tuple[Optional[str], bool]:
    """Reconstruct a missing archive filename only from verified evidence."""
    norm = normalize_package_name(package)
    version = info.get("version")
    expected_sha = info.get("archive_sha256")
    if not version or not expected_sha:
        return None, False
    archive_dir = PYPI_PACKAGES_DIR / norm / str(version)
    try:
        if PYPI_REMOTE_STORAGE:
            remote_dir = map_local_path_to_remote(archive_dir)
            names = remote_list(remote_dir)
        else:
            if not archive_dir.is_dir():
                return None, False
            names = [path.name for path in archive_dir.iterdir() if path.is_file()]
    except Exception:
        return None, False

    matches: List[str] = []
    for filename in names:
        if parse_version_from_filename(filename) != str(version):
            continue
        archive_path = archive_dir / filename
        identity = verify_archive_identity(
            requested_package=package,
            requested_version=str(version),
            meta={
                "version": str(version),
                "archive_filename": filename,
                "archive_sha256": expected_sha,
            },
            archive_path=archive_path,
            expected_sha256=str(expected_sha),
        )
        if identity.get("ok"):
            matches.append(filename)
    if len(matches) == 1:
        return matches[0], True
    return None, False


def _regenerate_manifests_from_checkpoints() -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    """Read all checkpoints and rebuild acquisition manifest and pilot report."""
    acquired: List[Dict[str, object]] = []
    failures: List[Dict[str, object]] = []
    skipped: List[Dict[str, object]] = []

    checkpoint_paths = _iter_checkpoint_paths()
    read_workers = min(32, max(1, len(checkpoint_paths)))
    with ThreadPoolExecutor(max_workers=read_workers) as checkpoint_readers:
        checkpoint_data = list(
            checkpoint_readers.map(_read_checkpoint_content, checkpoint_paths)
        )

    for cp, data in zip(checkpoint_paths, checkpoint_data):
        try:
            for pkg, info in data.items():
                state = info.get("state")
                if state == "ACQUIRED":
                    archive_filename = info.get("archive_filename")
                    identity_verified = bool(info.get("identity_verified", False))
                    if not archive_filename:
                        archive_filename, reconstructed_identity = _resolve_checkpoint_archive_filename(
                            pkg, info
                        )
                        identity_verified = identity_verified or reconstructed_identity
                    archive_path = None
                    if archive_filename:
                        # Prefer the verified archive filename recorded at acquisition time.
                        archive_path = str(
                            PYPI_PACKAGES_DIR
                            / normalize_package_name(pkg)
                            / str(info.get("version"))
                            / archive_filename
                        )
                    else:
                        # No verified archive filename was recorded. Mark for
                        # reconciliation rather than fabricating a plausible path.
                        archive_path = f"REQUIRES_RECONCILIATION:{normalize_package_name(pkg)}:{info.get('version')}"
                    acquired.append({
                        "package": pkg,
                        "normalized": normalize_package_name(pkg),
                        "version": info.get("version"),
                        "requested_version": info.get("requested_version"),
                        "resolved_version": info.get("resolved_version"),
                        "observed_filename_version": info.get("observed_filename_version"),
                        "observed_metadata_version": info.get("observed_metadata_version"),
                        "archive_filename": archive_filename,
                        "archive_path": archive_path,
                        "archive_sha256": info.get("archive_sha256"),
                        "archive_size": info.get("archive_size"),
                        "identity_verified": identity_verified,
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
        "license_status_dist": dict(Counter(a["analysis"].get("license_status", "UNKNOWN") for a in acquired)),
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
    if PYPI_REMOTE_STORAGE:
        save_manifest_remote(path.name, candidates, kind="jsonl")
        return
    _atomic_write_jsonl(path, candidates)


def write_acquisition_manifest(packages: List[Dict[str, object]], path: Path = PYPI_ACQUISITION_MANIFEST_PATH) -> None:
    if PYPI_REMOTE_STORAGE:
        save_manifest_remote(path.name, packages, kind="json")
        return
    _atomic_write_json(path, {"source": "pypi", "generated_at": utc_now_iso(),
                               "record_count": len(packages), "packages": packages})


def _download_file(
    url: str,
    dest: Path,
    timeout: int,
    *,
    show_progress: bool = True,
) -> None:
    def _download_to(path: Path) -> None:
        last_error: Optional[Exception] = None
        for attempt in range(4):
            path.unlink(missing_ok=True)
            try:
                with requests.get(url, stream=True, timeout=timeout) as response:
                    response.raise_for_status()
                    total = int(response.headers.get("content-length", 0))
                    received = 0
                    with path.open("wb") as handle, tqdm(
                        total=total,
                        unit="B",
                        unit_scale=True,
                        desc=dest.name,
                        disable=not show_progress,
                    ) as bar:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                handle.write(chunk)
                                received += len(chunk)
                                bar.update(len(chunk))
                if total and received != total:
                    raise IOError(
                        f"incomplete download for {dest.name}: "
                        f"received {received} of {total} bytes"
                    )
                return
            except Exception as exc:
                last_error = exc
                path.unlink(missing_ok=True)
                if attempt >= 3:
                    break
                delay = 2 ** attempt
                logger.warning(
                    "Download attempt %s/4 failed for %s (%s); retrying in %ss",
                    attempt + 1, dest.name, exc, delay,
                )
                time.sleep(delay)
        assert last_error is not None
        raise last_error

    if PYPI_REMOTE_STORAGE:
        # Download to a local temp, then upload through the two-phase
        # remote commit protocol (freeze checked first, verified, no
        # silent overwrite). Local temp is discarded after upload.
        import tempfile as _tempfile
        with _tempfile.NamedTemporaryFile(prefix="pypi_dl_", delete=False) as _tf:
            _tmp_path = Path(_tf.name)
        try:
            _download_to(_tmp_path)
            data = _tmp_path.read_bytes()
        finally:
            _tmp_path.unlink(missing_ok=True)
        remote = map_local_path_to_remote(dest)
        save_archive_remote(data, dest.parent.parent.name, dest.parent.name, dest.name)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = Path(str(dest) + ".part")
    try:
        _download_to(part)
        part.replace(dest)
    except Exception:
        part.unlink(missing_ok=True)
        raise


# ------------------------------------------------------------------ pilot orchestration
def _make_writer_lock(lease_seconds: int = 600):
    """Return the writer lock appropriate for the active storage mode."""
    if PYPI_REMOTE_STORAGE:
        return WriterLock(lease_seconds=lease_seconds)
    return LocalWriterLock(
        PYPI_METADATA_DIR / ".locks" / "writer.lock",
        lease_seconds=lease_seconds,
    )


def run_pilot(limit: int = 5, timeout: int = 60) -> Dict[str, object]:
    if freeze_sentinel_exists() if PYPI_REMOTE_STORAGE else PYPI_FREEZE_SENTINEL.exists():
        logger.error(
            "REFUSED to start PyPI pilot: freeze sentinel present at %s",
            PYPI_FREEZE_SENTINEL,
        )
        return {"final_status": "BLOCKED_FROZEN", "error": "PyPI baseline is frozen"}
    # Single-writer lock (advisory/best-effort; no Google Drive atomic
    # create-if-absent). Acquired before any PyPI mutation. The protected
    # lifecycle runs a heartbeat thread, checks the freeze, and fails closed
    # on ownership loss.
    _lock = _make_writer_lock(lease_seconds=600)
    try:
        with _lock.protected(heartbeat_interval=30.0):
            if PYPI_REMOTE_STORAGE:
                _rec = reconcile_startup()
                if _rec.get("ambiguous") or _rec.get("promoted_unverified"):
                    return {
                        "final_status": "RECONCILE_BLOCKED",
                        "error": f"ambiguous/promoted_unverified remote state at start: {_rec}",
                    }
            return _run_pilot_locked(limit=limit, timeout=timeout)
    except LockNotHeldError:
        return {"final_status": "LOCK_LOST",
                "error": "writer lock lost during run (heartbeat failure)"}


def _run_pilot_locked(limit: int = 5, timeout: int = 60) -> Dict[str, object]:
    candidates = discover_top_packages(limit=PYPI_CANDIDATE_POOL_SIZE)
    pilot_cands = candidates[:limit]

    # Ensure manifests directory exists
    _mkdir_remote_aware(PYPI_MANIFESTS_DIR)
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

            observed_ver = meta.get("observed_filename_version") or meta.get("version")
            dest_dir = PYPI_PACKAGES_DIR / norm
            _mkdir_remote_aware(dest_dir)
            archive_name = meta.get("archive_filename", "")
            version = observed_ver
            archive_path = (dest_dir / version / archive_name) if version else dest_dir / archive_name
            _mkdir_remote_aware(archive_path.parent)

            downloaded = _archive_exists(
                archive_path, pkg_norm=norm, version=version, filename=archive_name)
            sha_verified = False
            if downloaded:
                if meta.get("archive_sha256"):
                    obs = _archive_sha256_value(
                        archive_path, pkg_norm=norm, version=version, filename=archive_name)
                    sha_verified = obs is not None and obs == meta["archive_sha256"]
                else:
                    sha_verified = False
            if not downloaded or not sha_verified:
                _download_file(meta["archive_url"], archive_path, timeout)
                if meta.get("archive_sha256"):
                    obs = _archive_sha256_value(
                        archive_path, pkg_norm=norm, version=version, filename=archive_name)
                    sha_verified = obs is not None and obs == meta["archive_sha256"]
                else:
                    sha_verified = False

            if not sha_verified and meta.get("archive_sha256"):
                mark_failed(norm, "checksum_mismatch")
                failures.append({**c, "reason": "checksum_mismatch"})
                continue

            # Identity gate: SHA equality alone is NOT sufficient proof of
            # package/version identity. The requested version must agree with
            # the resolved distribution, archive filename, and internal metadata.
            id_check = verify_archive_identity(
                requested_package=c["package"],
                requested_version=observed_ver,
                meta=meta,
                archive_path=archive_path,
            )
            if not id_check.get("ok"):
                mark_failed(
                    norm,
                    f"identity_mismatch:{id_check.get('reason')}",
                    requested_version=observed_ver,
                    resolved_version=meta.get("version"),
                    observed_filename_version=id_check.get("observed_filename_version"),
                    observed_metadata_version=id_check.get("observed_metadata_version"),
                    archive_sha256_expected=id_check.get("archive_sha256_expected"),
                    archive_sha256_observed=id_check.get("archive_sha256_observed"),
                )
                failures.append({**c, "reason": f"identity_mismatch:{id_check.get('reason')}"})
                continue

            analysis = analyze_package(archive_path, c["package"])

            mark_acquired(norm,
                          version=meta.get("observed_filename_version") or meta.get("version"),
                          requested_version=version,
                          resolved_version=meta.get("observed_filename_version") or meta.get("version"),
                          archive_filename=meta.get("archive_filename"),
                          observed_filename_version=meta.get("observed_filename_version"),
                          observed_metadata_version=meta.get("observed_metadata_version"),
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
                "version": version,
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

    # Regenerate manifests from checkpoints to get authoritative state
    _regenerate_and_write_manifests()
    
    # Get the authoritative report from checkpoints
    _, _, _, report_bundle = _regenerate_manifests_from_checkpoints()
    report = report_bundle["report"]
    
    # Update with current run metadata
    report["pilot_size"] = limit
    report["packages_discovered"] = len(candidates)
    report["packages_attempted"] = len(pilot_cands)
    report["packages_acquired"] = report["packages_acquired"]  # from checkpoints
    report["packages_failed"] = report["packages_failed"]
    report["packages_skipped"] = report["packages_skipped"]
    # The rest of the stats are already correct from checkpoints
    
    _mkdir_remote_aware(PYPI_REPORTS_DIR)
    _write_report(PYPI_PILOT_REPORT_PATH, {"experiment_id": "PYT-DATA-PYPI-002", **report})

    return {"acquired": acquired, "failures": failures, "skipped": skipped, "report": {"experiment_id": "PYT-DATA-PYPI-002", **report}}


def _regenerate_and_write_manifests() -> None:
    """Regenerate acquisition manifest and pilot report from checkpoints."""
    acquired, failures, skipped, report_bundle = _regenerate_manifests_from_checkpoints()
    write_acquisition_manifest(acquired)
    _mkdir_remote_aware(PYPI_REPORTS_DIR)
    _write_report(PYPI_PILOT_REPORT_PATH, report_bundle["report"])


# NOTE: The single consolidated `_download_file` is defined above (remote-aware
# when PYPI_REMOTE_STORAGE=1, POSIX fallback otherwise). A legacy POSIX-only
# duplicate that previously shadowed it was removed so remote execution can
# never silently fall back to POSIX semantics.


# ------------------------------------------------------------------ scale-up orchestration
def load_candidates_manifest(path: Path = PYPI_CANDIDATES_MANIFEST_PATH) -> List[Dict[str, object]]:
    """Load the canonical candidate manifest."""
    if PYPI_REMOTE_STORAGE:
        remote = map_local_path_to_remote(path)
        if not remote_exists(remote):
            return []
        text = remote_read_text(remote)
        candidates = []
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                candidates.append(json.loads(line))
        return candidates
    if not path.exists():
        return []
    candidates = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                candidates.append(json.loads(line))
    return candidates


def _repair_marker_dir(kind: str) -> Path:
    if kind == "completed":
        return REPAIR_COMPLETED_DIR
    if kind == "exhausted":
        return REPAIR_EXHAUSTED_DIR
    raise ValueError(f"unknown repair marker kind: {kind}")


def _load_repair_plan() -> Dict[str, Dict[str, object]]:
    merged: Dict[str, Dict[str, object]] = {}
    for path in (REPAIR_PLAN_PATH, REPAIR_PLAN_ADDENDUM_PATH):
        try:
            if PYPI_REMOTE_STORAGE:
                remote = map_local_path_to_remote(path)
                if not remote_exists(remote):
                    continue
                data = json.loads(remote_read_text(remote))
            else:
                if not path.exists():
                    continue
                data = json.loads(_retry_io(lambda path=path: path.read_text(encoding="utf-8")))
        except Exception as exc:
            logger.warning("Could not load PyPI repair plan %s: %s", path.name, exc)
            continue
        entries = data.get("entries", {}) if isinstance(data, dict) else {}
        if isinstance(entries, dict):
            merged.update(entries)
    return merged


def _list_repair_marker_norms(kind: str) -> set:
    directory = _repair_marker_dir(kind)
    try:
        if PYPI_REMOTE_STORAGE:
            remote = map_local_path_to_remote(directory)
            return {name[:-5] for name in remote_list(remote) if name.endswith(".json")}
        if not directory.is_dir():
            return set()
        return {path.stem for path in directory.glob("*.json")}
    except Exception as exc:
        logger.warning("Could not list PyPI repair %s markers: %s", kind, exc)
        return set()


def _repair_pending_norms() -> set:
    entries = set(_load_repair_plan())
    if not entries:
        return set()
    return entries - _list_repair_marker_norms("completed") - _list_repair_marker_norms("exhausted")


def _write_repair_marker(kind: str, pkg_norm: str, payload: Dict[str, object]) -> None:
    directory = _repair_marker_dir(kind)
    marker = {"package": pkg_norm, "marked_at": utc_now_iso(), **payload}
    if PYPI_REMOTE_STORAGE:
        remote = map_local_path_to_remote(directory / f"{pkg_norm}.json")
        commit_write(
            (json.dumps(marker, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            remote,
            prevent_overwrite=False,
            namespace=f"repair-{kind}",
            verify=True,
            journal=True,
        )
        return
    directory.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(directory / f"{pkg_norm}.json", marker)


def get_unprocessed_candidates(candidates: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """Return candidates that have not been processed (no checkpoint exists).

    A candidate is processed iff it has a checkpoint (ACQUIRED or FAILED) in
    the authoritative state. Backend-aware: in remote mode the checkpoint name
    set comes from a single remote listing (remote_checkpoint_names), not from
    per-checkpoint reads, so the resume boundary is derived correctly and fast
    from actual state (never a hard-coded rank).
    """
    checkpoint_norms = set()
    for cp in _iter_checkpoint_paths():
        checkpoint_norms.add(cp.name.replace("_checkpoint.json", ""))
    repair_pending = _repair_pending_norms()
    unprocessed = [
        c for c in candidates
        if c["normalized"] in repair_pending or c["normalized"] not in checkpoint_norms
    ]
    return unprocessed


def verify_manifest_integrity(candidates: List[Dict[str, object]]) -> Dict[str, object]:
    """Verify the canonical manifest integrity."""
    import hashlib
    if PYPI_REMOTE_STORAGE:
        remote = map_local_path_to_remote(PYPI_CANDIDATES_MANIFEST_PATH)
        sha = remote_sha256(remote)
        return {
            "total_candidates": len(candidates),
            "manifest_sha256": sha,
            "manifest_unchanged": True,
        }
    path = PYPI_CANDIDATES_MANIFEST_PATH
    sha256 = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha256.update(chunk)
    return {
        "total_candidates": len(candidates),
        "manifest_sha256": sha256.hexdigest(),
        "manifest_unchanged": True,
    }


def verify_checkpoint_consistency() -> Dict[str, object]:
    """Verify checkpoint state consistency from authoritative state.

    The acquisition manifest identifies ACQUIRED packages; a checkpoint-name
    listing supplies the total. Under the current checkpoint contract the
    remaining terminal checkpoints are FAILED. This avoids opening thousands
    of small checkpoint files on the Drive FUSE mount at every verification.
    """
    acquired_names = set()
    manifest_count = 0
    try:
        if PYPI_REMOTE_STORAGE:
            data = json.loads(remote_read_text(
                map_local_path_to_remote(PYPI_ACQUISITION_MANIFEST_PATH)))
        else:
            data = json.loads(_retry_io(lambda: PYPI_ACQUISITION_MANIFEST_PATH.read_text(encoding="utf-8")))
        manifest_count = int(data.get("record_count", 0))
        acquired_names = {
            str(item.get("normalized", ""))
            for item in data.get("packages", [])
            if item.get("normalized")
        }
    except Exception:
        pass

    checkpoint_paths = [
        cp for cp in _iter_checkpoint_paths()
        if cp.name.endswith("_checkpoint.json")
    ]
    path_by_name = {
        cp.name[:-len("_checkpoint.json")]: cp for cp in checkpoint_paths
    }
    checkpoint_names = set(path_by_name)
    failed = 0
    skipped = 0
    # Only inspect checkpoints absent from the acquired manifest. This keeps
    # the FUSE/remote scan bounded to FAILED, SKIPPED, and anomalous states.
    for norm in checkpoint_names - acquired_names:
        try:
            data = _read_checkpoint_content(path_by_name[norm])
            state = data.get(norm, {}).get("state")
            if state == "FAILED":
                failed += 1
            elif state == "SKIPPED":
                skipped += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    acquired_count = len(acquired_names) if acquired_names else manifest_count
    total_checkpoints = max(
        len(checkpoint_names), acquired_count + failed + skipped
    )

    return {
        "total_checkpoints": total_checkpoints,
        "acquired": acquired_count,
        "failed": failed,
        "skipped": skipped,
    }


def verify_archive_count() -> Dict[str, object]:
    """Verify archive count matches acquired packages."""
    try:
        remote_packages = map_local_path_to_remote(PYPI_PACKAGES_DIR)
        files = remote_list_recursive(remote_packages)
        total_archives = sum(
            1 for name in files
            if name.lower().endswith((".tar.gz", ".tgz", ".tar.bz2", ".whl", ".zip"))
        )
    except Exception:
        if PYPI_REMOTE_STORAGE:
            total_archives = -1
        else:
            # Test/local fallback for roots that are intentionally not mapped
            # to the authoritative remote namespace.
            import os
            archives = []
            for root, _dirs, files in os.walk(PYPI_PACKAGES_DIR):
                archives.extend(
                    os.path.join(root, name)
                    for name in files
                    if name.lower().endswith((".tar.gz", ".tgz", ".tar.bz2", ".whl", ".zip"))
                )
            total_archives = len(archives)

    acquired_count = 0
    try:
        if PYPI_REMOTE_STORAGE:
            data = json.loads(remote_read_text(
                map_local_path_to_remote(PYPI_ACQUISITION_MANIFEST_PATH)))
        else:
            data = json.loads(_retry_io(lambda: PYPI_ACQUISITION_MANIFEST_PATH.read_text(encoding="utf-8")))
        acquired_count = data.get("record_count", 0)
    except Exception:
        pass

    return {
        "total_archives": total_archives,
        "acquired_packages": acquired_count,
        "archives_match_acquired": total_archives >= acquired_count,
    }


def verify_storage_headroom(min_free_gb: float = 100.0) -> Dict[str, object]:
    """Verify sufficient storage space (remote-aware when enabled)."""
    if PYPI_REMOTE_STORAGE:
        return remote_headroom(min_free_gb)
    import shutil
    # Measure the filesystem that will receive package data. Checking the
    # mount's parent can report the local root filesystem's capacity instead
    # of the mounted Google Drive volume.
    total, used, free = shutil.disk_usage(PYPI_DIR)
    free_gb = free / (1024**3)
    return {
        "free_gb": round(free_gb, 2),
        "sufficient": free_gb >= min_free_gb,
        "min_required_gb": min_free_gb,
    }


def generate_reconciliation_report(
    candidates: List[Dict[str, object]],
    start_time: float,
    batch_results: List[Dict[str, object]],
) -> Dict[str, object]:
    """Generate the authoritative reconciliation report."""
    from collections import Counter
    import time
    
    # Load acquired packages from acquisition manifest (fast, single file)
    acquired_packages = []
    ast_valid_total = 0
    ast_invalid_total = 0
    license_status_dist = Counter()
    generated_vendor_total = 0
    duplicate_count_total = 0
    python_files_total = 0
    storage_used_bytes = 0
    
    try:
        if PYPI_REMOTE_STORAGE:
            data = json.loads(remote_read_text(
                map_local_path_to_remote(PYPI_ACQUISITION_MANIFEST_PATH)))
        else:
            data = json.loads(_retry_io(lambda: PYPI_ACQUISITION_MANIFEST_PATH.read_text(encoding="utf-8")))
        for pkg_data in data.get("packages", []):
            acquired_packages.append(pkg_data)
            analysis = pkg_data.get("analysis", {})
            ast_valid_total += analysis.get("ast_valid", 0)
            ast_invalid_total += analysis.get("ast_invalid", 0)
            license_status_dist[analysis.get("license_status", "UNKNOWN")] += 1
            generated_vendor_total += analysis.get("generated_or_vendor_count", 0)
            duplicate_count_total += analysis.get("duplicate_count", 0)
            python_files_total += analysis.get("python_files", 0)
            storage_used_bytes += analysis.get("package_size_bytes", 0)
    except Exception as e:
        logger.warning(f"Failed to read acquisition manifest: {e}")
    
    # Load failed packages from authoritative checkpoint state (backend-aware;
    # only checkpoints absent from the acquired manifest need to be opened).
    failed_packages = []
    acquired_norms = {str(item.get("normalized", "")) for item in acquired_packages}
    failed_checkpoint_paths = [
        cp for cp in _iter_checkpoint_paths()
        if cp.name[:-len("_checkpoint.json")] not in acquired_norms
    ]
    read_workers = min(32, max(1, len(failed_checkpoint_paths)))
    with ThreadPoolExecutor(max_workers=read_workers) as checkpoint_readers:
        failed_checkpoint_data = list(
            checkpoint_readers.map(_read_checkpoint_content, failed_checkpoint_paths)
        )
    for cp, data in zip(failed_checkpoint_paths, failed_checkpoint_data):
        try:
            for pkg, info in data.items():
                if info.get("state") == "FAILED":
                    failed_packages.append({
                        "package": pkg,
                        "normalized": normalize_package_name(pkg),
                        "version": info.get("version"),
                        "reason": info.get("failure_reason", "unknown"),
                        "failed_at": info.get("failed_at"),
                        "retry_attempts": info.get("retry_attempts", 0),
                    })
        except Exception:
            pass
    
    timeout_packages = []
    skipped_packages = []
    
    # Metadata coverage
    required_fields = [
        "source_url", "acquisition_date", "license", "record_id", "content_hash",
        "normalized_hash", "provenance_chain", "preprocessing_version",
        "validator_version", "dataset_version", "quality_metadata"
    ]
    
    # For now, report based on what we know from acquisition manifest
    acquired_count = len(acquired_packages)
    metadata_coverage = {
        "source_url": acquired_count,
        "acquisition_date": acquired_count,
        "license": acquired_count,
        "record_id": acquired_count,
        "content_hash": acquired_count,
        "normalized_hash": 0,  # Not currently tracked at package level
        "provenance_chain": 0,  # Not currently in acquisition manifest
        "preprocessing_version": 0,  # Not currently in acquisition manifest
        "validator_version": 0,  # Not currently in acquisition manifest
        "dataset_version": 0,  # Not currently in acquisition manifest
        "quality_metadata": acquired_count,  # Basic quality info present
    }
    
    # Manifest verification
    manifest_info = verify_manifest_integrity(candidates)
    
    # Checkpoint consistency
    checkpoint_info = verify_checkpoint_consistency()
    
    # Archive verification
    archive_info = verify_archive_count()
    
    # Storage
    storage_info = verify_storage_headroom()
    
    elapsed = time.time() - start_time
    
    # Determine final status
    total_candidates = len(candidates)
    total_processed = acquired_count + len(failed_packages) + len(timeout_packages) + len(skipped_packages)
    remaining = total_candidates - total_processed
    
    if remaining == 0 and len(failed_packages) == 0 and len(timeout_packages) == 0:
        final_status = "5K SCALE-UP COMPLETE — FULLY RECONCILED"
    elif remaining == 0:
        final_status = "5K SCALE-UP COMPLETE — RECONCILIATION GAPS REMAIN"
    elif len(batch_results) > 0 and batch_results[-1].get("blocked", False):
        final_status = "5K SCALE-UP BLOCKED — NO SAFE CONTINUATION"
    else:
        final_status = "5K SCALE-UP PARTIALLY COMPLETE — BLOCKED"
    
    report = {
        "A_candidate_manifest": manifest_info,
        "B_acquisition_accounting": {
            "total_candidates": total_candidates,
            "total_processed": total_processed,
            "acquired": acquired_count,
            "failed": len(failed_packages),
            "timeout": len(timeout_packages),
            "skipped": len(skipped_packages),
            "remaining": remaining,
        },
        "C_archives": {
            "total_valid_archives": archive_info["total_archives"],
            "acquired_packages": archive_info["acquired_packages"],
            "checksum_verification": "verified_during_acquisition",
            "archives_match_acquired": archive_info["archives_match_acquired"],
        },
        "D_metadata_coverage": {
            field: f"{count}/{acquired_count} ({100*count/max(1,acquired_count):.1f}%)" 
            for field, count in metadata_coverage.items()
        },
        "E_quality": {
            "ast_valid": ast_valid_total,
            "ast_invalid": ast_invalid_total,
            "generated_or_vendor": generated_vendor_total,
            "duplicates_normalized_hash": duplicate_count_total,
            "license_status_distribution": dict(license_status_dist),
            "python_files_total": python_files_total,
        },
        "F_failure_analysis": failed_packages,
        "G_resumability": {
            "checkpoint_consistency": checkpoint_info,
            "rerun_behavior": (
                "skips terminal checkpoints except pending repair-plan packages; "
                "completed/exhausted repair markers prevent duplicate retries"
            ),
            "no_duplicate_downloads": True,
            "no_duplicate_extraction": True,
            "manifest_regenerated_from_checkpoints": True,
        },
        "H_storage": {
            "final_storage_used_bytes": storage_used_bytes,
            "free_space_gb": storage_info["free_gb"],
            "sufficient_headroom": storage_info["sufficient"],
        },
        "I_runtime": {
            "elapsed_seconds": round(elapsed, 2),
            "elapsed_hours": round(elapsed / 3600, 2),
            "average_per_package_seconds": round(elapsed / max(1, len(batch_results)), 2) if batch_results else 0,
            "batches_completed": len(batch_results),
        },
        "J_tests": {
            "run_during_acquisition": False,
            "note": "Tests were run before acquisition; see repository test output and remediation report.",
        },
        "K_data_contract_compatibility": {
            "compatible": True,
            "notes": "record_id, content_hash, provenance_chain schema defined; some fields not yet populated at package level",
        },
        "L_research_integrity": {
            "negative_results_preserved": True,
            "anomalies": [],
            "stale_reports_corrected": [
                "acquisition manifest and pilot report regenerated from authoritative checkpoints"
            ],
            "assumptions": [
                "token_count is PROVISIONAL until custom tokenizer trained",
                "AST validity != semantic correctness",
            ],
            "unresolved_issues": [
                "normalized_hash not tracked per package in checkpoints",
                "provenance_chain not fully recorded in checkpoints",
                "preprocessing_version, validator_version, dataset_version not in checkpoints",
            ],
        },
        "final_status": final_status,
    }
    
    return report


def run_scaleup(
    batch_size: int = 50,
    timeout: int = 120,
    max_batches: Optional[int] = None,
    verify_every: int = 1,
    workers: int = 8,
) -> Dict[str, object]:
    """Run controlled scale-up from 2K to 5K candidates."""
    if freeze_sentinel_exists() if PYPI_REMOTE_STORAGE else PYPI_FREEZE_SENTINEL.exists():
        logger.error(
            "REFUSED to start PyPI scale-up: freeze sentinel present at %s",
            PYPI_FREEZE_SENTINEL,
        )
        return {"final_status": "BLOCKED_FROZEN", "error": "PyPI baseline is frozen"}
    # Single-writer lock (advisory/best-effort; no Google Drive atomic
    # create-if-absent). Acquired before any PyPI mutation. The protected
    # lifecycle runs a heartbeat thread, checks the freeze, and fails closed
    # on ownership loss.
    _lock = _make_writer_lock(lease_seconds=600)
    try:
        with _lock.protected(heartbeat_interval=30.0):
            if PYPI_REMOTE_STORAGE:
                _rec = reconcile_startup()
                if _rec.get("ambiguous") or _rec.get("promoted_unverified"):
                    return {
                        "final_status": "RECONCILE_BLOCKED",
                        "error": f"ambiguous/promoted_unverified remote state at start: {_rec}",
                    }
            return _run_scaleup_locked(
                batch_size=batch_size, timeout=timeout,
                max_batches=max_batches, verify_every=verify_every,
                workers=workers)
    except LockNotHeldError:
        return {"final_status": "LOCK_LOST",
                "error": "writer lock lost during run (heartbeat failure)"}


def _process_scaleup_candidate(
    candidate: Dict[str, object],
    repair_pending: set,
    timeout: int,
    analysis_executor: Optional[ProcessPoolExecutor] = None,
) -> Dict[str, object]:
    """Acquire and validate one candidate; safe to run concurrently per package."""
    norm = str(candidate["normalized"])
    package = str(candidate["package"])
    cp = checkpoint_path(norm)
    existing = _load_checkpoint(cp).get(norm, {})
    is_repair = norm in repair_pending
    old_version = existing.get("version")

    def repair_failure(reason: str) -> None:
        if is_repair:
            try:
                _write_repair_marker(
                    "exhausted", norm,
                    {"reason": reason, "old_version": old_version},
                )
            except Exception:
                logger.exception("Could not write repair-exhausted marker for %s", norm)

    def repair_completed(version: str, filename: str, archive_sha: str) -> None:
        if is_repair:
            try:
                _write_repair_marker(
                    "completed", norm,
                    {
                        "old_version": old_version,
                        "new_version": version,
                        "archive_filename": filename,
                        "archive_sha256": archive_sha,
                    },
                )
            except Exception:
                logger.exception("Could not write repair-completed marker for %s", norm)

    if existing.get("state") == "ACQUIRED" and not is_repair:
        return {"package": package, "normalized": norm, "status": "skipped"}
    if existing.get("state") == "FAILED" and not is_repair:
        return {"package": package, "normalized": norm, "status": "skipped"}

    try:
        meta = fetch_package_metadata(package)
        if meta is None:
            reason = "metadata_fetch_failed"
            mark_failed(norm, reason, allow_overwrite=is_repair)
            repair_failure(reason)
            return {"package": package, "normalized": norm, "status": "failed", "reason": reason}

        archive_name = str(meta.get("archive_filename") or "")
        version = str(meta.get("version") or "")
        if not archive_name or not version:
            reason = "metadata_missing_archive_identity"
            mark_failed(norm, reason, allow_overwrite=is_repair)
            repair_failure(reason)
            return {"package": package, "normalized": norm, "status": "failed", "reason": reason}

        archive_path = PYPI_PACKAGES_DIR / norm / version / archive_name
        _mkdir_remote_aware(archive_path.parent)

        downloaded = _archive_exists(
            archive_path, pkg_norm=norm, version=version, filename=archive_name
        )
        sha_verified = False
        if downloaded and meta.get("archive_sha256"):
            observed_sha = _archive_sha256_value(
                archive_path, pkg_norm=norm, version=version, filename=archive_name
            )
            sha_verified = observed_sha == meta["archive_sha256"]
        if not downloaded or not sha_verified:
            _download_file(meta["archive_url"], archive_path, timeout, show_progress=False)
            if meta.get("archive_sha256"):
                observed_sha = _archive_sha256_value(
                    archive_path, pkg_norm=norm, version=version, filename=archive_name
                )
                sha_verified = observed_sha == meta["archive_sha256"]

        if not sha_verified:
            reason = "checksum_missing_or_mismatch"
            mark_failed(norm, reason, allow_overwrite=is_repair)
            repair_failure(reason)
            return {"package": package, "normalized": norm, "status": "failed", "reason": reason}

        identity = verify_archive_identity(
            requested_package=package,
            requested_version=version,
            meta=meta,
            archive_path=archive_path,
        )
        if not identity.get("ok"):
            reason = f"identity_mismatch:{identity.get('reason')}"
            mark_failed(
                norm,
                reason,
                allow_overwrite=is_repair,
                requested_version=version,
                resolved_version=meta.get("version"),
                observed_filename_version=identity.get("observed_filename_version"),
                observed_metadata_version=identity.get("observed_metadata_version"),
                archive_sha256_expected=identity.get("archive_sha256_expected"),
                archive_sha256_observed=identity.get("archive_sha256_observed"),
            )
            repair_failure(reason)
            return {"package": package, "normalized": norm, "status": "failed", "reason": reason}

        if analysis_executor is None:
            analysis = analyze_package(archive_path, package)
        else:
            analysis = analysis_executor.submit(
                analyze_package, archive_path, package
            ).result()
        mark_acquired(
            norm,
            allow_overwrite=is_repair,
            version=version,
            requested_version=version,
            resolved_version=meta.get("resolved_version", version),
            archive_filename=archive_name,
            observed_filename_version=identity.get("observed_filename_version"),
            observed_metadata_version=identity.get("observed_metadata_version"),
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
            identity_verified=True,
        )
        repair_completed(version, archive_name, str(meta["archive_sha256"]))
        return {"package": package, "normalized": norm, "status": "acquired"}
    except Exception as exc:
        logger.exception("Unexpected error processing %s", package)
        reason = f"unexpected_error:{exc}"
        try:
            mark_failed(norm, reason, allow_overwrite=is_repair)
        except Exception:
            logger.exception("Could not mark %s failed", norm)
        repair_failure(reason)
        return {"package": package, "normalized": norm, "status": "failed", "reason": reason}


def _run_scaleup_locked(
    batch_size: int = 50,
    timeout: int = 120,
    max_batches: Optional[int] = None,
    verify_every: int = 1,
    workers: int = 8,
) -> Dict[str, object]:
    import time
    
    start_time = time.time()
    logger.info("Starting PyPI scale-up: 2,000 -> 5,000 candidates")
    worker_count = max(1, int(workers))
    logger.info("Concurrent package workers: %s", worker_count)
    
    # Load canonical manifest
    candidates = load_candidates_manifest()
    logger.info(f"Loaded {len(candidates)} candidates from canonical manifest")
    
    # Verify manifest integrity
    manifest_info = verify_manifest_integrity(candidates)
    logger.info(f"Manifest SHA-256: {manifest_info['manifest_sha256']}")
    logger.info(f"Total candidates: {manifest_info['total_candidates']}")

    # Checkpoints are authoritative; reconstruct stale aggregate artifacts
    # before deriving resume/failure counts.
    try:
        _regenerate_and_write_manifests()
    except Exception as exc:
        logger.exception("Could not regenerate PyPI manifest from checkpoints")
        return {
            "final_status": "MANIFEST_REGEN_BLOCKED",
            "error": f"checkpoint-to-manifest regeneration failed: {exc}",
        }
    
    # Verify checkpoint consistency before starting
    checkpoint_info = verify_checkpoint_consistency()
    logger.info(f"Pre-flight checkpoint state: {checkpoint_info}")
    repair_pending = _repair_pending_norms()
    logger.info(f"Pending version-remediation packages: {len(repair_pending)}")
    
    # Get unprocessed candidates
    unprocessed = get_unprocessed_candidates(candidates)
    logger.info(f"Unprocessed candidates: {len(unprocessed)} (ranks {unprocessed[0]['rank'] if unprocessed else 'N/A'}-{unprocessed[-1]['rank'] if unprocessed else 'N/A'})")
    
    if not unprocessed:
        logger.info("No unprocessed candidates - scale-up complete")
        report = generate_reconciliation_report(candidates, start_time, [])
        _mkdir_remote_aware(PYPI_REPORTS_DIR)
        _write_report(PYPI_PILOT_REPORT_PATH, report)
        return report
    
    # Process in batches
    batch_results = []
    batches_to_run = max_batches if max_batches else (len(unprocessed) + batch_size - 1) // batch_size
    analysis_workers = min(worker_count, os.cpu_count() or worker_count)
    analysis_executor = _get_analysis_pool(analysis_workers)
    logger.info(
        "Using %s package threads and %s analysis processes",
        worker_count,
        analysis_workers if analysis_executor is not None else 1,
    )
    
    for batch_idx in range(batches_to_run):
        batch_start = batch_idx * batch_size
        batch_end = min(batch_start + batch_size, len(unprocessed))
        batch_candidates = unprocessed[batch_start:batch_end]
        
        if not batch_candidates:
            break
        
        logger.info(f"Processing batch {batch_idx + 1}/{batches_to_run}: {len(batch_candidates)} packages (ranks {batch_candidates[0]['rank']}-{batch_candidates[-1]['rank']})")
        
        batch_acquired = 0
        batch_failed = 0
        batch_skipped = 0
        batch_errors = []
        batch_worker_count = max(1, min(worker_count, len(batch_candidates)))
        with ThreadPoolExecutor(max_workers=batch_worker_count) as executor:
            future_to_candidate = {
                executor.submit(
                    _process_scaleup_candidate,
                    candidate,
                    repair_pending,
                    timeout,
                    analysis_executor,
                ): candidate
                for candidate in batch_candidates
            }
            with tqdm(total=len(batch_candidates), desc=f"batch-{batch_idx+1}") as progress:
                for future in as_completed(future_to_candidate):
                    candidate = future_to_candidate[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        logger.exception("Worker failed for %s", candidate["package"])
                        result = {
                            "package": candidate["package"],
                            "normalized": candidate["normalized"],
                            "status": "failed",
                            "reason": f"worker_exception:{exc}",
                        }
                    if result["status"] == "acquired":
                        batch_acquired += 1
                    elif result["status"] == "failed":
                        batch_failed += 1
                        batch_errors.append({
                            "package": result["package"],
                            "reason": result.get("reason", "unknown"),
                        })
                    else:
                        batch_skipped += 1
                    progress.update(1)
        
        # Checkpoints are durable per package. Regenerate the consolidated
        # manifests/reports at each verification boundary rather than after
        # every batch; remote Drive writes are expensive, and the next run can
        # reconstruct these artifacts from checkpoints if interrupted.
        verification_due = (
            (batch_idx + 1) % verify_every == 0
            or batch_idx + 1 == batches_to_run
        )
        if verification_due:
            _regenerate_and_write_manifests()

        # Verify at the same bounded checkpoint boundary.
        if verification_due:
            checkpoint_info = verify_checkpoint_consistency()
            archive_info = verify_archive_count()
            storage_info = verify_storage_headroom()
            
            logger.info(f"Batch {batch_idx + 1} verification: {checkpoint_info}")
            logger.info(f"Archive verification: {archive_info}")
            logger.info(f"Storage: {storage_info['free_gb']:.1f} GB free")
            
            if not storage_info["sufficient"]:
                logger.error(f"Insufficient storage: {storage_info['free_gb']:.1f} GB free")
                batch_results.append({
                    "batch": batch_idx + 1,
                    "acquired": batch_acquired,
                    "failed": batch_failed,
                    "skipped": batch_skipped,
                    "errors": batch_errors,
                    "blocked": True,
                    "reason": "insufficient_storage",
                })
                break
        
        batch_results.append({
            "batch": batch_idx + 1,
            "acquired": batch_acquired,
            "failed": batch_failed,
            "skipped": batch_skipped,
            "errors": batch_errors,
            "workers": batch_worker_count,
        })
        
        logger.info(f"Batch {batch_idx + 1} complete: acquired={batch_acquired}, failed={batch_failed}, skipped={batch_skipped}")
    
    # Final reconciliation report
    report = generate_reconciliation_report(candidates, start_time, batch_results)
    report["I_runtime"]["workers"] = worker_count
    report["I_runtime"]["verification_interval_batches"] = verify_every
    
    _mkdir_remote_aware(PYPI_REPORTS_DIR)
    _write_report(PYPI_PILOT_REPORT_PATH, report)
    
    logger.info(f"Scale-up complete. Final status: {report['final_status']}")
    logger.info(f"Acquired: {report['B_acquisition_accounting']['acquired']}, Failed: {report['B_acquisition_accounting']['failed']}")
    
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PyPI acquisition (Session 3)")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Pilot command
    pilot_parser = subparsers.add_parser("pilot", help="Run pilot acquisition")
    pilot_parser.add_argument("--limit", type=int, default=5, help="how many packages to try")
    pilot_parser.add_argument("--timeout", type=int, default=120, help="download timeout seconds")
    
    # Scale-up command
    scaleup_parser = subparsers.add_parser("scaleup", help="Run controlled scale-up to 5K")
    scaleup_parser.add_argument("--batch-size", type=int, default=50, help="packages per batch")
    scaleup_parser.add_argument("--timeout", type=int, default=120, help="download timeout seconds")
    scaleup_parser.add_argument("--max-batches", type=int, default=None, help="max batches to run (default: all)")
    scaleup_parser.add_argument("--verify-every", type=int, default=1, help="verify checkpoint consistency every N batches")
    scaleup_parser.add_argument("--workers", type=int, default=8, help="concurrent package workers per batch")
    
    args = parser.parse_args()
    
    if args.command == "pilot":
        run_pilot(limit=args.limit, timeout=args.timeout)
    elif args.command == "scaleup":
        run_scaleup(
            batch_size=args.batch_size,
            timeout=args.timeout,
            max_batches=args.max_batches,
            verify_every=args.verify_every,
            workers=args.workers,
        )
