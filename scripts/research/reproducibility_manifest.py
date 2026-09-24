"""Reproducibility manifest — Pythia-160M.

Captures the full environment and configuration under which a dataset build
or experiment was executed.  Designed so that a future reader can reconstruct
WHY a record or dataset was accepted or rejected.

The manifest is JSON and is written alongside experiment outputs (e.g.
under `research/results/` or per‑dataset directories).  It is deliberately
stand‑alone — no external state is required to interpret it.
"""

from __future__ import annotations

import json
import os
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure config is on the path so we can read DATA_ROOT etc.
_sys_path = sys.path + [str(Path(__file__).resolve().parent.parent.parent)]
for _p in _sys_path:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import DATA_ROOT  # noqa: F401,F811


def _python_version() -> str:
    """Return the Python interpreter version string."""
    return sys.version


def _pip_packages() -> Dict[str, str]:
    """Return a best-effort dict of installed pip package names ⇒ versions.

    If ``pip`` is unavailable or an package cannot be queried, the value
    is ``"unknown"``.
    """
    pkgs: Dict[str, str] = {}
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=freeze"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            # pip list --format=freeze gives "package==version"
            try:
                name, version = line.split("==", 1)
                pkgs[name.lower()] = version
            except ValueError:
                pkgs[name.lower()] = "unknown"
    except Exception:  # pylint: disable=broad-except
        pass
    return pkgs


def _os_info() -> Dict[str, str]:
    """Return basic OS / environment information."""
    return {
        "os": os.name,
        "platform": sys.platform,
    }


def _git_commit(repo_path: Optional[Path] = None) -> Optional[str]:
    """Return the short SHA-1 of the current git commit, if available.

    Args:
        repo_path: Path to a git repository.  Defaults to the project root.
    """
    path = repo_path or Path(__file__).resolve().parent.parent.parent
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _git_diff_summary(repo_path: Optional[Path] = None) -> Optional[str]:
    """Return a brief diff summary of uncommitted changes, if any.

    Args:
        repo_path: Path to a git repository.  Defaults to the project root.
    """
    path = repo_path or Path(__file__).resolve().parent.parent.parent
    try:
        result = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _data_root() -> str:
    """Return the effective DATA_ROOT as currently configured."""
    return str(DATA_ROOT)


def _config_thresholds() -> Dict[str, any]:
    """Return the key quality‑gate thresholds from ``config.py``."""
    from config import (
        MIN_TOKEN_LENGTH,
        MAX_TOKEN_LENGTH,
        MIN_COMMENT_RATIO,
        PEP8_MAX_VIOLATIONS,
        DEDUP_SIMILARITY_THRESHOLD,
    )
    return {
        "min_token_length": MIN_TOKEN_LENGTH,
        "max_token_length": MAX_TOKEN_LENGTH,
        "min_comment_ratio": MIN_COMMENT_RATIO,
        "pep8_max_violations": PEP8_MAX_VIOLATIONS,
        "dedup_similarity_threshold": DEDUP_SIMILARITY_THRESHOLD,
    }


def generate_manifest(
    experiment_id: str,
    run_id: str,
    source_infos: Dict[str, Dict[str, any]],
    record_count: int,
    accepted_count: int,
    rejected_count: int,
    validator_version: str = "scripts.validators.ast_validator",
    tokenizer_version: Optional[str] = None,
    extra: Optional[Dict[str, any]] = None,
) -> Dict[str, any]:
    """Generate a reproducibility manifest dict.

    This is the primary entry point.  The caller supplies the experimental
    context and per‑source snapshot information; the function fills in the
    environment, configuration, and timestamps.

    Args:
        experiment_id: The experiment identifier (e.g. ``"PYT-DATA-SO-001"``).
        run_id: A run‑specific identifier (e.g. a UUID or timestamp string).
        source_infos: Dict mapping source name to its snapshot info:
            ``{"stackoverflow": {"sha256": "...", "acquisition_date": "...",
            "records": 11000, "accepted": 11000, "rejected": 0, ...}, ...}
        record_count: Total number of records examined across all sources.
        accepted_count: Total records that passed quality gates.
        rejected_count: Total records that failed quality gates.
        validator_version: The AST validator implementation used.
        tokenizer_version: The custom tokenizer version, if available
            (``None`` until ``PYTHIA-TOK-v0.1`` exists).
        extra: Any extra fields the caller wishes to record.

    Returns:
        A ``dict`` suitable for serialisation with ``json.dump``.
    """
    manifest: Dict[str, any] = {
        # Identification
        "experiment_id": experiment_id,
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        # Environment
        "python_version": _python_version(),
        "pip_packages": _pip_packages(),
        "os_info": _os_info(),
        "data_root": _data_root(),
        # Git provenance (project root)
        "git_commit": _git_commit(),
        "git_diff_summary": _git_diff_summary(),
        # Configuration
        "config_thresholds": _config_thresholds(),
        "validator_version": validator_version,
        "tokenizer_version": tokenizer_version,
        # Experiment scope
        "source_infos": source_infos,
        "record_count": record_count,
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "acceptance_rate": round(accepted_count / record_count, 4) if record_count else 0.0,
        # Optional extras
    }
    if extra:
        manifest.update(extra)
    return manifest


def write_manifest(
    manifest: Dict[str, any],
    path: Path | str,
) -> Path:
    """Write the manifest dict as JSON to *path*.

    The file is written with ``indent=2`` and a trailing newline so that
    it is both human‑readable and machine‑parsable.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    return p


# ---------------------------------------------------------------------------
# Helper: build source_infos from a collection of record evaluations
# ---------------------------------------------------------------------------

def build_source_infos_from_evaluations(
    evaluations_by_source: Dict[str, List[dict[str, any]]],
) -> Dict[str, Dict[str, any]]:
    """Convert per‑source record evaluations into the ``source_infos`` format.

    Each entry in *evaluations_by_source* maps a source name to a list of
    quality‑evaluation dicts (as produced by :func:`scripts.quality_gate.
    evaluate_record`).

    The returned dict has, for each source:
      - ``sha256``: of the raw source snapshot (if available)
      - ``acquisition_date``: earliest/recorded acquisition date
      - ``records``: total records examined
      - ``accepted``: records passing quality gates
      - ``rejected``: records failing quality gates
      - ``quality_gate_status``: "ACCEPTED" or "REJECTED" (majority verdict)
      - ``token_count_status``: most common ``token_count_status`` across records
      - ``license_status``: most common license status across records
      - ``provenance_complete``: count of records with complete provenance
    """
    source_infos: Dict[str, Dict[str, any]] = {}

    for source_name, evaluations in evaluations_by_source.items():
        n = len(evaluations)
        if n == 0:
            continue

        accepted = sum(1 for e in evaluations if e.get("quality_gate_status") == "ACCEPTED")
        rejected = n - accepted

        # Most common token_count_status
        tcs_counts: Dict[str, int] = {}
        for e in evaluations:
            tcs = e.get("token_count_status")
            if tcs:
                tcs_counts[tcs] = tcs_counts.get(tcs, 0) + 1
        most_common_tcs = max(tcs_counts, key=tcs_counts.get) if tcs_counts else None

        # Most common license status
        lic_counts: Dict[str, int] = {}
        for e in evaluations:
            lic = e.get("license_status")
            if lic:
                lic_counts[lic] = lic_counts.get(lic, 0) + 1
        most_common_lic = max(lic_counts, key=lic_counts.get) if lic_counts else None

        # Provenance completeness
        complete = sum(
            1 for e in evaluations
            if all(e.get(k) is not None for k in ("source", "record_id", "content_hash", "acquisition_date"))
        )

        # SHA-256 of the raw source snapshot — if the evaluations carry it
        sha256 = None
        first_e = evaluations[0]
        if first_e and first_e.get("content_hash"):
            sha256 = first_e["content_hash"]

        source_infos[source_name] = {
            "sha256": sha256,
            "acquisition_date": max(
                (e.get("acquisition_date", "") for e in evaluations if e.get("acquisition_date")),
                default="",
            ),
            "records": n,
            "accepted": accepted,
            "rejected": rejected,
            "quality_gate_status": (
                "ACCEPTED" if accepted > rejected else "REJECTED"
            ),
            "token_count_status": most_common_tcs,
            "license_status": most_common_lic,
            "provenance_complete": complete,
        }

    return source_infos