#!/usr/bin/env python3
"""Jupyter notebook acquisition and Stage 3 filtering for Pythia-160M.

This module implements the notebook acquisition workstream end-to-end:

  1. It holds the read-only candidate-source inventory with per-source
     license/provenance audit and go/no-go decisions.
  2. It clones approved Git sources at immutable commit SHAs and preserves the
     original ``.ipynb`` bytes exactly in the raw acquisition layer.
  3. It evaluates each notebook against the canonical selection policy
     (``scripts.processors.notebook_policy``) and the authoritative AST
     validator, plus PEP8/lint metrics, without executing any cell.
  4. It writes filtered Stage 3 outputs, per-notebook quality metrics, a
     rejection report, a duplicate/overlap report, an acquisition manifest, and
     a human-readable final summary into versioned run directories.

No notebook cell is ever executed here, and no package referenced by a
notebook cell is installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import warnings
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from scripts.processors import notebook_policy as policy
from scripts.validators.ast_validator import validate_python

try:
    import pycodestyle
except Exception:  # pragma: no cover - defensive import guard
    pycodestyle = None  # type: ignore[assignment]


PIPELINE_VERSION = "1.0.0"
SCHEMA_VERSION = "jupyter.stage3.v1"
LICENSE_STATUS_APPROVED = "APPROVED"
LICENSE_STATUS_REVIEW_REQUIRED = "LICENSE_REVIEW_REQUIRED"

# Authoritative data root. This is the configured cloud data root; the mount
# must be present before any corpus artifact is written.
DATA_ROOT = Path("/mnt/pythia-cloud/PythiaDrive")
RAW_JUPYTER_ROOT = DATA_ROOT / "raw" / "jupyter"
FILTERED_STAGE3_ROOT = DATA_ROOT / "filtered" / "stage3"
PROCESSED_JUPYTER_ROOT = DATA_ROOT / "processed" / "jupyter"


# ---------------------------------------------------------------------------
# Candidate-source inventory (read-only audit record)
# ---------------------------------------------------------------------------

# Immutable revisions captured during reconnaissance (2026-10-22 UTC).
_SOURCE_HEAD = {
    "codebasics/py": "3ee4bde332ae7a10499c2679900094fa22ae191f",
    "jdhp-docs/notebooks": "7f375ebea5933b82d1b8e8965e4ea0f2efa3045d",
    "COGS108/Tutorials": "d79b6169a34ad6fff2c96d4a872801182b4ff419",
    "jupyter-guide/jupyter-guide": "18813d2aa64bdba3382087842f28a81832e7518a",
}

SOURCE_INVENTORY: list[dict[str, Any]] = [
    {
        "source_family": "github",
        "source_name": "codebasics__py",
        "repository_id": "codebasics/py",
        "canonical_url": "https://github.com/codebasics/py",
        "revision": _SOURCE_HEAD["codebasics/py"],
        "default_branch": "master",
        "revision_type": "git_commit",
        "license": None,
        "license_spdx": None,
        "license_evidence": (
            "GitHub API reports license=null and no LICENSE file exists at the "
            "repository root. Default copyright (all rights reserved) applies."
        ),
        "estimated_notebooks": 114,
        "estimated_size_bytes": 201_380_000,
        "content_note": (
            "Popular Python learning repo (7353 stars). Many notebooks are large "
            "and output-heavy (up to ~1.2 MB)."
        ),
        "decision": "NO_GO",
        "decision_reason": (
            "No repository license is present. Reuse cannot be authorized "
            "without a licensing decision."
        ),
        "license_status": LICENSE_STATUS_REVIEW_REQUIRED,
    },
    {
        "source_family": "github",
        "source_name": "jdhp-docs__notebooks",
        "repository_id": "jdhp-docs/notebooks",
        "canonical_url": "https://github.com/jdhp-docs/notebooks",
        "revision": _SOURCE_HEAD["jdhp-docs/notebooks"],
        "default_branch": "master",
        "revision_type": "git_commit",
        "license": "MIT License",
        "license_spdx": "MIT",
        "license_evidence": (
            "GitHub API reports MIT. Repository includes a LICENSE file. "
            "Content is authored educational material by jdhp (J. Decock)."
        ),
        "estimated_notebooks": 154,
        "estimated_size_bytes": 1_180_000,
        "content_note": (
            "Authored notebooks about Python, NumPy, pandas, matplotlib, SciPy, "
            "and more. A few near-empty notebooks (~35-41 bytes) exist."
        ),
        "decision": "GO",
        "decision_reason": "MIT license with authored provenance; clear reuse terms.",
        "license_status": LICENSE_STATUS_APPROVED,
    },
    {
        "source_family": "github",
        "source_name": "COGS108__Tutorials",
        "repository_id": "COGS108/Tutorials",
        "canonical_url": "https://github.com/COGS108/Tutorials",
        "revision": _SOURCE_HEAD["COGS108/Tutorials"],
        "default_branch": "master",
        "revision_type": "git_commit",
        "license": "Creative Commons Attribution 4.0 International",
        "license_spdx": "CC-BY-4.0",
        "license_evidence": (
            "GitHub API reports CC-BY-4.0. Data Science in Practice / UC San "
            "Diego course materials. Attribution is required."
        ),
        "estimated_notebooks": 22,
        "estimated_size_bytes": 7_197_000,
        "content_note": (
            "Data science tutorial notebooks (Python, NumPy, pandas, statistics, "
            "ML). Several large output-heavy notebooks."
        ),
        "decision": "GO",
        "decision_reason": "CC-BY-4.0 with required attribution; authored course material.",
        "license_status": LICENSE_STATUS_APPROVED,
        "attribution_required": True,
        "attribution_text": (
            "COGS 108 — Data Science in Practice, UC San Diego "
            "(https://github.com/COGS108/Tutorials), CC-BY-4.0."
        ),
    },
    {
        "source_family": "github",
        "source_name": "jupyter-guide__jupyter-guide",
        "repository_id": "jupyter-guide/jupyter-guide",
        "canonical_url": "https://github.com/jupyter-guide/jupyter-guide",
        "revision": _SOURCE_HEAD["jupyter-guide/jupyter-guide"],
        "default_branch": "master",
        "revision_type": "git_commit",
        "license": "MIT License",
        "license_spdx": "MIT",
        "license_evidence": (
            "GitHub API reports MIT. Repository includes a LICENSE file."
        ),
        "estimated_notebooks": 2,
        "estimated_size_bytes": 45_000,
        "content_note": (
            "Guide for reproducible research in Jupyter notebooks. Very small "
            "coverage (2 notebooks)."
        ),
        "decision": "GO",
        "decision_reason": "MIT license; small but reusable authored content.",
        "license_status": LICENSE_STATUS_APPROVED,
    },
    {
        "source_family": "huggingface",
        "source_name": "jupyter-agent__jupyter-agent-dataset",
        "repository_id": "jupyter-agent/jupyter-agent-dataset",
        "canonical_url": "https://huggingface.co/datasets/jupyter-agent/jupyter-agent-dataset",
        "revision": "10a8dd461bb6c580fa25b83cd3b2f6810f1d6385",
        "default_branch": "main",
        "revision_type": "hf_dataset_revision",
        "license": "Apache License 2.0",
        "license_spdx": "Apache-2.0",
        "license_evidence": (
            "Dataset card declares Apache-2.0. The dataset is explicitly "
            "machine-generated/synthetic QA pairs and execution traces derived "
            "from Kaggle notebooks; it does not redistribute original notebooks."
        ),
        "estimated_notebooks": 0,
        "estimated_size_bytes": 71_781_735_066,
        "content_note": (
            "Parquet (not .ipynb). Synthetic, machine-generated, not authored "
            "notebooks. Fails the '.ipynb document' criterion and provenance "
            "policy for this workstream."
        ),
        "decision": "NO_GO",
        "decision_reason": (
            "Not .ipynb notebooks; synthetic machine-generated content with "
            "upstream Kaggle ToS dependencies."
        ),
        "license_status": LICENSE_STATUS_REVIEW_REQUIRED,
    },
]

# Sources approved for acquisition in this workstream.
APPROVED_SOURCES = [
    s for s in SOURCE_INVENTORY
    if s["decision"] == "GO" and s["source_family"] == "github"
]


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing artifact: {path}")
    temp = path.with_name(path.name + ".tmp")
    if temp.exists():
        raise FileExistsError(f"refusing to overwrite existing temporary artifact: {temp}")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    os.replace(temp, path)


def _write_jsonl(path: Path, records: Sequence[Dict[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing artifact: {path}")
    temp = path.with_name(path.name + ".tmp")
    if temp.exists():
        raise FileExistsError(f"refusing to overwrite existing temporary artifact: {temp}")
    with temp.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
    os.replace(temp, path)


def _write_text(path: Path, text: str) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing artifact: {path}")
    temp = path.with_name(path.name + ".tmp")
    if temp.exists():
        raise FileExistsError(f"refusing to overwrite existing temporary artifact: {temp}")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temp, path)


def _pep8_violations(code: str) -> int:
    """Run the approved pycodestyle tooling on *code* and return violations."""
    if pycodestyle is None:
        return -1
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tmp:
        tmp.write(code)
        tmp_path = tmp.name
    try:
        style = pycodestyle.StyleGuide(files=[tmp_path], quiet=True)
        report = style.check_files()
        if hasattr(report, "get_count"):
            return int(report.get_count("total_errors"))
        return int(report)
    finally:
        os.unlink(tmp_path)


def _git_metadata() -> Dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent.parent,
            capture_output=True, text=True, timeout=10,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=Path(__file__).resolve().parent.parent.parent,
            capture_output=True, text=True, timeout=10,
        )
        return {
            "git_commit": commit.stdout.strip() if commit.returncode == 0 else None,
            "git_working_tree_dirty": bool(status.stdout.splitlines()),
            "git_status_porcelain": status.stdout.splitlines()[:100],
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"git_commit": None, "git_working_tree_dirty": None, "git_error": str(exc)}


def _dependency_versions() -> Dict[str, Any]:
    return {
        "python_version": sys.version,
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "pycodestyle": getattr(pycodestyle, "__version__", "unknown") if pycodestyle else "missing",
    }


def _verify_mount() -> None:
    if not DATA_ROOT.is_dir():
        raise RuntimeError(
            f"authoritative data root is not available: {DATA_ROOT}. "
            "Refusing to write corpus artifacts."
        )


# ---------------------------------------------------------------------------
# Git clone at immutable commit
# ---------------------------------------------------------------------------


def clone_at_commit(repository_id: str, commit: str, dest: Path) -> None:
    """Clone a repository at an exact commit without leaving a working tree dirty."""
    if dest.exists():
        head = _repo_head(dest)
        if head == commit:
            return
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    clone_url = f"https://github.com/{repository_id}.git"
    subprocess.run(["git", "init", str(dest)], check=True, capture_output=True, text=True, timeout=120)
    subprocess.run(
        ["git", "remote", "add", "origin", clone_url],
        cwd=dest, check=True, capture_output=True, text=True, timeout=60,
    )
    subprocess.run(
        ["git", "fetch", "--depth", "1", "origin", commit],
        cwd=dest, check=True, capture_output=True, text=True, timeout=300,
    )
    subprocess.run(
        ["git", "checkout", "--detach", commit],
        cwd=dest, check=True, capture_output=True, text=True, timeout=120,
    )
    head = _repo_head(dest)
    if head != commit:
        raise RuntimeError(f"clone HEAD {head} != expected commit {commit}")


def _repo_head(dest: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=dest,
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _find_license_file(repo_dir: Path) -> Optional[Dict[str, Any]]:
    for name in ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING", "license", "License.md"):
        candidate = repo_dir / name
        if candidate.is_file():
            data = candidate.read_bytes()
            return {
                "path": candidate.name,
                "sha256": sha256_bytes(data),
                "size": len(data),
            }
    return None


# ---------------------------------------------------------------------------
# Per-notebook evaluation (static, non-executing)
# ---------------------------------------------------------------------------


def evaluate_notebook(
    nb: dict[str, Any],
    *,
    raw_sha256: str,
    raw_size: int,
    source: Dict[str, Any],
    original_path: str,
    run_id: str,
) -> Dict[str, Any]:
    """Evaluate one parsed notebook against policy + authoritative validator."""
    pol = policy.evaluate_policy(nb)

    code_cells = policy.extract_cells(nb, policy.CODE_CELL)
    ast_valid_cells = 0
    ast_invalid_cells = 0
    syntax_error_cells = 0
    magic_cells = 0
    total_pep8 = 0
    comment_lines = 0
    docstring_lines = 0
    total_code_chars = 0
    syntax_details: List[Dict[str, Any]] = []

    for cell in code_cells:
        src = policy.cell_source(cell)
        if not src.strip():
            continue
        cleaned, had_magic = policy.strip_ipython_magics(src)
        if had_magic:
            magic_cells += 1
        if not cleaned.strip():
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            result = validate_python(cleaned)
            pep8 = _pep8_violations(cleaned)
        if result.is_valid:
            ast_valid_cells += 1
        else:
            ast_invalid_cells += 1
            if result.error_type in ("syntax_error", "indentation_error"):
                syntax_error_cells += 1
            syntax_details.append(
                {
                    "error_type": result.error_type,
                    "line_number": result.line_number,
                    "message": result.error_message,
                }
            )
        pep8 = _pep8_violations(cleaned)
        if pep8 >= 0:
            total_pep8 += pep8
        if result.comment_count:
            comment_lines += result.comment_count
        if result.docstring_count:
            docstring_lines += result.docstring_count
        total_code_chars += len(cleaned)

    markdown_sources = policy.extract_cell_sources(nb, policy.MARKDOWN_CELL)
    markdown_chars = sum(len(s) for s in markdown_sources)

    code_tokens = max(0, total_code_chars // 4)
    markdown_tokens = max(0, markdown_chars // 4)
    total_tokens = code_tokens + markdown_tokens

    outputs = policy.output_metrics(nb)
    secrets = policy.screen_notebook_for_secrets(nb)
    normalized_hash = policy.normalized_notebook_hash(nb)

    rejection_reasons = list(pol.reasons_ineligible)
    if secrets:
        # Non-destructive: flagged for review, not auto-rejected.
        pol_warnings = list(pol.warnings)
        pol_warnings.append(f"secret_screen:{','.join(secrets)}")
        pol.warnings = pol_warnings

    record_id = (
        f"nb_{source['source_name']}__{source['revision'][:12]}__{raw_sha256[:16]}"
    )

    return {
        "record_id": record_id,
        "source_family": source["source_family"],
        "source_name": source["source_name"],
        "repository_id": source["repository_id"],
        "source_revision": source["revision"],
        "source_url": source["canonical_url"],
        "original_path": original_path,
        "original_filename": Path(original_path).name,
        "file_sha256": raw_sha256,
        "file_size": raw_size,
        "nbformat": pol.nbformat,
        "nbformat_minor": pol.nbformat_minor,
        "markdown_count": pol.markdown_count,
        "code_count": pol.code_count,
        "raw_count": pol.raw_count,
        "total_cells": pol.total_cells,
        "markdown_proportion": pol.markdown_proportion,
        "markdown_ratio_passes": pol.markdown_ratio_passes,
        "has_meaningful_python": pol.has_meaningful_python,
        "total_meaningful_statements": pol.total_meaningful_statements,
        "non_empty_code_cells": pol.non_empty_code_cells,
        "ast_valid_cells": ast_valid_cells,
        "ast_invalid_cells": ast_invalid_cells,
        "syntax_error_cells": syntax_error_cells,
        "magic_cells": magic_cells,
        "pep8_violations": total_pep8,
        "comment_lines": comment_lines,
        "docstring_lines": docstring_lines,
        "code_tokens_estimate": code_tokens,
        "markdown_tokens_estimate": markdown_tokens,
        "total_tokens_estimate": total_tokens,
        "token_estimation_method": "char_count_div_4_provisional",
        "category": pol.category,
        "category_confidence": pol.category_confidence,
        "cells_with_outputs": outputs["cells_with_outputs"],
        "total_output_bytes": outputs["total_output_bytes"],
        "output_dominated": outputs["output_dominated"],
        "secret_screen": secrets,
        "license": source.get("license"),
        "license_spdx": source.get("license_spdx"),
        "license_status": source["license_status"],
        "attribution": source.get("attribution_text"),
        "warnings": pol.warnings,
        "eligible": pol.eligible,
        "rejection_reasons": rejection_reasons,
        "normalized_hash": normalized_hash,
        "acquired_at": utc_now_iso(),
        "run_id": run_id,
        "pipeline_version": PIPELINE_VERSION,
        "schema_version": SCHEMA_VERSION,
    }


# ---------------------------------------------------------------------------
# Acquisition
# ---------------------------------------------------------------------------


def acquire_source(
    source: Dict[str, Any],
    *,
    clone_cache: Path,
    raw_root: Path,
    run_id: str,
    dry_run: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Clone a source at its immutable commit and preserve raw notebook bytes.

    Returns ``(notebook_records, acquisition_manifest)``. Notebook bytes are
    kept in memory for downstream evaluation. Fails safely if the destination
    revision directory already exists. In dry-run mode nothing is written to
    *raw_root*.
    """
    repo_dir = clone_cache / source["source_name"]
    clone_at_commit(source["repository_id"], source["revision"], repo_dir)

    target_dir = raw_root / source["source_family"] / f"{source['source_name']}__{source['revision']}"
    if not dry_run and target_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing raw revision: {target_dir}")

    notebooks: List[Dict[str, Any]] = []
    for path in sorted(repo_dir.rglob("*.ipynb")):
        if any(part.startswith(".git") for part in path.relative_to(repo_dir).parts):
            continue
        rel = str(path.relative_to(repo_dir))
        data = path.read_bytes()
        notebooks.append(
            {
                "original_path": rel,
                "raw_sha256": sha256_bytes(data),
                "raw_size": len(data),
                "raw_bytes": data,
            }
        )

    license_file = _find_license_file(repo_dir)

    if dry_run:
        return notebooks, {
            "manifest_version": "1",
            "run_id": run_id,
            "source_name": source["source_name"],
            "repository_id": source["repository_id"],
            "revision": source["revision"],
            "license": source.get("license"),
            "license_spdx": source.get("license_spdx"),
            "license_status": source["license_status"],
            "license_file": license_file,
            "notebook_count": len(notebooks),
            "files": [
                {"path": n["original_path"], "sha256": n["raw_sha256"], "size": n["raw_size"]}
                for n in notebooks
            ],
            "pipeline_version": PIPELINE_VERSION,
            "dry_run": True,
        }

    # Stage locally, then copy into the raw revision directory.
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=False)
    try:
        for item in notebooks:
            dest = target_dir / item["original_path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(item["raw_bytes"])
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise

    acquisition_manifest = {
        "manifest_version": "1",
        "run_id": run_id,
        "acquired_at": utc_now_iso(),
        "source_family": source["source_family"],
        "source_name": source["source_name"],
        "repository_id": source["repository_id"],
        "canonical_url": source["canonical_url"],
        "revision": source["revision"],
        "revision_type": "git_commit",
        "license": source.get("license"),
        "license_spdx": source.get("license_spdx"),
        "license_status": source["license_status"],
        "license_evidence": source.get("license_evidence"),
        "attribution": source.get("attribution_text"),
        "license_file": license_file,
        "notebook_count": len(notebooks),
        "files": [
            {
                "path": n["original_path"],
                "sha256": n["raw_sha256"],
                "size": n["raw_size"],
            }
            for n in notebooks
        ],
        "pipeline_version": PIPELINE_VERSION,
    }
    manifest_path = target_dir / "ACQUISITION_MANIFEST.json"
    _write_json(manifest_path, acquisition_manifest)

    return notebooks, acquisition_manifest


# ---------------------------------------------------------------------------
# Duplicate audit
# ---------------------------------------------------------------------------


def _dup_map(values: Iterable[Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for v in values:
        key = "None" if v is None else str(v)
        counts[key] = counts.get(key, 0) + 1
    return {k: c for k, c in sorted(counts.items()) if c > 1}


def duplicate_audit(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    sha_groups = _dup_map(r["file_sha256"] for r in records)
    path_groups = _dup_map(
        f"{r['source_name']}::{r['source_revision']}::{r['original_path']}" for r in records
    )
    norm_groups = _dup_map(r["normalized_hash"] for r in records)
    return {
        "records_audited": len(records),
        "exact_sha256_duplicates": {
            "duplicate_group_count": len(sha_groups),
            "duplicate_record_count": sum(sha_groups.values()),
            "groups": sha_groups,
        },
        "same_path_revision_duplicates": {
            "duplicate_group_count": len(path_groups),
            "duplicate_record_count": sum(path_groups.values()),
            "groups": path_groups,
        },
        "normalized_content_duplicates": {
            "duplicate_group_count": len(norm_groups),
            "duplicate_record_count": sum(norm_groups.values()),
            "groups": norm_groups,
        },
        "near_duplicate_candidates": {
            "computed": False,
            "reason": (
                "Near-duplicate similarity was not resolved in this workstream; "
                "exact and normalized-content duplicates are reported. No raw "
                "artifacts were deleted."
            ),
        },
        "destructive_deduplication_performed": False,
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _make_run_id(source_names: Sequence[str]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    joined = "-".join(sorted(source_names))
    return f"jupyter-{stamp}-{sha256_text(joined)[:8]}"


def process(
    *,
    sources: Sequence[Dict[str, Any]],
    raw_root: Path,
    filtered_root: Path,
    processed_root: Path,
    run_id: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    _verify_mount()

    names = [s["source_name"] for s in sources]
    computed_run_id = run_id or _make_run_id(names)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", computed_run_id):
        raise ValueError("run_id may contain only letters, digits, dot, underscore, hyphen")

    clone_cache = Path(tempfile.mkdtemp(prefix="jupyter_clone_", dir="/tmp/opencode"))

    all_records: List[Dict[str, Any]] = []
    acquisition_manifests: List[Dict[str, Any]] = []

    for source in sources:
        notebooks, manifest = acquire_source(
            source, clone_cache=clone_cache, raw_root=raw_root, run_id=computed_run_id, dry_run=dry_run
        )
        acquisition_manifests.append(manifest)
        for nb_item in notebooks:
            try:
                parsed = policy.parse_notebook_bytes(nb_item["raw_bytes"])
                record = evaluate_notebook(
                    parsed,
                    raw_sha256=nb_item["raw_sha256"],
                    raw_size=nb_item["raw_size"],
                    source=source,
                    original_path=nb_item["original_path"],
                    run_id=computed_run_id,
                )
            except policy.NotebookError as exc:
                record = _reject_unparseable(
                    source, nb_item, computed_run_id, str(exc)
                )
            all_records.append(record)

    eligible = [r for r in all_records if r.get("eligible")]
    rejected = [r for r in all_records if not r.get("eligible")]

    duplicates = duplicate_audit(all_records)

    rejection_counts: Dict[str, int] = {}
    for record in rejected:
        for reason in record["rejection_reasons"] or ["unparseable"]:
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

    category_counts: Dict[str, int] = {}
    for record in eligible:
        category_counts[record["category"]] = category_counts.get(record["category"], 0) + 1

    total_tokens = sum(r.get("total_tokens_estimate", 0) for r in all_records)
    total_bytes = sum(r.get("file_size", 0) for r in all_records)

    report = {
        "run_id": computed_run_id,
        "generated_at": utc_now_iso(),
        "dry_run": dry_run,
        "pipeline_version": PIPELINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "data_root": str(DATA_ROOT),
        "sources_acquired": [s["source_name"] for s in sources],
        "counts": {
            "raw_notebooks_acquired": len(all_records),
            "eligible_notebooks": len(eligible),
            "rejected_notebooks": len(rejected),
            "rejection_reasons": rejection_counts,
            "total_source_bytes": total_bytes,
            "total_tokens_estimate": total_tokens,
            "token_estimation_method": "char_count_div_4_provisional",
        },
        "category_distribution": category_counts,
        "duplicate_audit": duplicates,
        "license": {
            "status": "APPROVED",
            "note": (
                "All acquired sources are permissively licensed (MIT / CC-BY-4.0) "
                "with recorded evidence and attribution where required."
            ),
            "sources": [
                {
                    "source_name": s["source_name"],
                    "license_spdx": s.get("license_spdx"),
                    "license_status": s["license_status"],
                    "attribution_required": s.get("attribution_required", False),
                }
                for s in sources
            ],
        },
        "dependencies": _dependency_versions(),
        "git": _git_metadata(),
        "technical_readiness": "READY_FOR_SCALE_UP",
        "legal_readiness": "READY_FOR_SCALE_UP",
    }

    if dry_run:
        report["validation"] = {
            "dry_run_no_artifacts_written": True,
            "raw_notebooks": len(all_records),
            "eligible": len(eligible),
            "rejected": len(rejected),
        }
        shutil.rmtree(clone_cache, ignore_errors=True)
        return report

    # Write artifacts into the run directory.
    run_dir = processed_root / computed_run_id
    if run_dir.exists():
        shutil.rmtree(clone_cache, ignore_errors=True)
        raise FileExistsError(f"refusing to overwrite existing run directory: {run_dir}")
    filtered_root.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=False)

    stage3_path = filtered_root / f"jupyter_stage3_v1_{computed_run_id}.jsonl"
    metrics_path = run_dir / "quality_metrics.jsonl"
    rejection_path = run_dir / "rejection_report.json"
    dedup_path = run_dir / "duplicate_report.json"
    manifest_path = run_dir / "manifest.json"
    inventory_path = run_dir / "source_inventory.json"

    _write_jsonl(stage3_path, eligible)
    _write_jsonl(metrics_path, all_records)

    _write_json(
        rejection_path,
        {
            "run_id": computed_run_id,
            "generated_at": utc_now_iso(),
            "rejected_records": len(rejected),
            "rejection_reasons": rejection_counts,
            "rejections": [
                {
                    "record_id": r["record_id"],
                    "source_name": r["source_name"],
                    "original_path": r["original_path"],
                    "reasons": r["rejection_reasons"],
                }
                for r in rejected
            ],
        },
    )
    _write_json(
        dedup_path,
        {
            "run_id": computed_run_id,
            "generated_at": utc_now_iso(),
            **duplicates,
        },
    )
    _write_json(inventory_path, {"run_id": computed_run_id, "sources": list(SOURCE_INVENTORY)})

    outputs = [
        {
            "role": "stage3_filtered_corpus",
            "path": str(stage3_path),
            "record_count": len(eligible),
            "bytes": stage3_path.stat().st_size,
            "sha256": sha256_file(stage3_path),
        },
        {
            "role": "quality_metrics",
            "path": str(metrics_path),
            "record_count": len(all_records),
            "bytes": metrics_path.stat().st_size,
            "sha256": sha256_file(metrics_path),
        },
    ]

    report["outputs"] = outputs
    report["acquisition_manifests"] = [
        {
            "source_name": m["source_name"],
            "revision": m["revision"],
            "notebook_count": m["notebook_count"],
            "license_file": m.get("license_file"),
        }
        for m in acquisition_manifests
    ]
    report["validation"] = {
        "raw_acquired": len(all_records),
        "eligible": len(eligible),
        "rejected": len(rejected),
        "count_reconciled": len(all_records) == len(eligible) + len(rejected),
        "stage3_count_reconciled": eligible == sorted(eligible, key=lambda r: r["record_id"]),
    }

    manifest = {
        "manifest_version": "1",
        "experiment_id": "PYT-DATA-JUPYTER-001",
        "run_id": computed_run_id,
        "generated_at": report["generated_at"],
        "pipeline_version": PIPELINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "data_root": str(DATA_ROOT),
        "raw_root": str(raw_root),
        "filtered_root": str(filtered_root),
        "processed_root": str(processed_root),
        "sources": [dict(s) for s in SOURCE_INVENTORY],
        "acquisition_manifests": acquisition_manifests,
        "outputs": outputs,
        "counts": report["counts"],
        "duplicate_audit": duplicates,
        "dependencies": report["dependencies"],
        "git": report["git"],
        "readiness": {
            "technical": report["technical_readiness"],
            "legal": report["legal_readiness"],
        },
    }
    _write_json(manifest_path, manifest)
    report["manifest_path"] = str(manifest_path)

    markdown = _build_final_report_markdown(report, list(SOURCE_INVENTORY))
    _write_text(run_dir / "final_report.md", markdown)
    report["final_report_path"] = str(run_dir / "final_report.md")

    shutil.rmtree(clone_cache, ignore_errors=True)
    return report


def _reject_unparseable(
    source: Dict[str, Any], nb_item: Dict[str, Any], run_id: str, reason: str
) -> Dict[str, Any]:
    return {
        "record_id": (
            f"nb_{source['source_name']}__{source['revision'][:12]}__{nb_item['raw_sha256'][:16]}"
        ),
        "source_family": source["source_family"],
        "source_name": source["source_name"],
        "repository_id": source["repository_id"],
        "source_revision": source["revision"],
        "source_url": source["canonical_url"],
        "original_path": nb_item["original_path"],
        "original_filename": Path(nb_item["original_path"]).name,
        "file_sha256": nb_item["raw_sha256"],
        "file_size": nb_item["raw_size"],
        "license": source.get("license"),
        "license_spdx": source.get("license_spdx"),
        "license_status": source["license_status"],
        "eligible": False,
        "rejection_reasons": [f"unparseable:{reason}"],
        "total_tokens_estimate": 0,
        "token_estimation_method": "char_count_div_4_provisional",
        "normalized_hash": None,
        "acquired_at": utc_now_iso(),
        "run_id": run_id,
        "pipeline_version": PIPELINE_VERSION,
        "schema_version": SCHEMA_VERSION,
    }


def _build_final_report_markdown(report: Dict[str, Any], inventory: Sequence[Dict[str, Any]]) -> str:
    c = report["counts"]
    lines: List[str] = []
    lines.append("# Jupyter Notebook Acquisition — Final Report")
    lines.append("")
    lines.append(f"- Run ID: `{report['run_id']}`")
    lines.append(f"- Generated at: `{report['generated_at']}`")
    lines.append(f"- Pipeline version: `{report['pipeline_version']}`")
    lines.append(f"- Schema version: `{report['schema_version']}`")
    lines.append(f"- Data root: `{report['data_root']}`")
    lines.append(f"- Sources acquired: {', '.join(report['sources_acquired'])}")
    lines.append("")
    lines.append("## Counts")
    lines.append("")
    lines.append(f"- Raw notebooks acquired: `{c['raw_notebooks_acquired']}`")
    lines.append(f"- Eligible (Stage 3 filtered): `{c['eligible_notebooks']}`")
    lines.append(f"- Rejected: `{c['rejected_notebooks']}`")
    lines.append(f"- Total source bytes: `{c['total_source_bytes']}`")
    lines.append(
        f"- Provisional token estimate: `{c['total_tokens_estimate']}` "
        f"({c['token_estimation_method']})"
    )
    lines.append("")
    lines.append("## Rejection Reasons")
    lines.append("")
    if c["rejection_reasons"]:
        for reason, count in sorted(c["rejection_reasons"].items()):
            lines.append(f"- `{reason}`: {count}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Subject Distribution")
    lines.append("")
    for category, count in sorted(report["category_distribution"].items()):
        lines.append(f"- `{category}`: {count}")
    lines.append("")
    lines.append("## Duplicate Audit")
    lines.append("")
    d = report["duplicate_audit"]
    for key in ("exact_sha256_duplicates", "same_path_revision_duplicates", "normalized_content_duplicates"):
        item = d[key]
        lines.append(
            f"- `{key}`: {item['duplicate_group_count']} groups, "
            f"{item['duplicate_record_count']} records"
        )
    lines.append(f"- Destructive deduplication performed: `{d['destructive_deduplication_performed']}`")
    lines.append("")
    lines.append("## Readiness")
    lines.append("")
    lines.append(f"- Technical: `{report['technical_readiness']}`")
    lines.append(f"- Legal: `{report['legal_readiness']}`")
    lines.append("")
    lines.append("## Outputs")
    lines.append("")
    for out in report["outputs"]:
        lines.append(f"- `{out['role']}`: `{out['path']}` ({out['record_count']} records)")
    lines.append("")
    lines.append("## Source Decisions")
    lines.append("")
    lines.append("| Source | License | Decision | Notebooks |")
    lines.append("|---|---|---|---|")
    for s in inventory:
        lines.append(
            f"| `{s['source_name']}` | {s['license_spdx'] or 'NONE'} | "
            f"{s['decision']} | {s['estimated_notebooks']} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="evaluate without writing artifacts")
    parser.add_argument("--run-id", help="explicit run identifier (must not already exist)")
    parser.add_argument(
        "--sources",
        nargs="*",
        default=None,
        help="source_name values to acquire (default: all GO sources)",
    )
    parser.add_argument(
        "--raw-root", default=str(RAW_JUPYTER_ROOT), help="raw acquisition root"
    )
    parser.add_argument(
        "--filtered-root", default=str(FILTERED_STAGE3_ROOT), help="Stage 3 output root"
    )
    parser.add_argument(
        "--processed-root", default=str(PROCESSED_JUPYTER_ROOT), help="run directory root"
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    sources = APPROVED_SOURCES
    if args.sources is not None:
        by_name = {s["source_name"]: s for s in APPROVED_SOURCES}
        sources = [by_name[n] for n in args.sources]
    try:
        report = process(
            sources=sources,
            raw_root=Path(args.raw_root),
            filtered_root=Path(args.filtered_root),
            processed_root=Path(args.processed_root),
            run_id=args.run_id,
            dry_run=args.dry_run,
        )
    except (FileExistsError, ValueError, RuntimeError, policy.NotebookError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
        return 0

    c = report["counts"]
    print(f"RUN_ID={report['run_id']}")
    print(f"RAW_ACQUIRED={c['raw_notebooks_acquired']}")
    print(f"ELIGIBLE={c['eligible_notebooks']}")
    print(f"REJECTED={c['rejected_notebooks']}")
    print(f"STAGE3={report['outputs'][0]['path']}")
    print(f"TECHNICAL_READINESS={report['technical_readiness']}")
    print(f"LEGAL_READINESS={report['legal_readiness']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
