#!/usr/bin/env python3
"""Scientific Python documentation acquisition for Stage 1 (license-first).

This module implements a license-first, pinned-URL acquisition of the official
HTML documentation archives for NumPy, SciPy, pandas, and Matplotlib.

Design principles:

  * Every source has a recorded license decision (ACCEPT / HOLD / REJECT)
    based on the license of the *documentation content* (not just the software
    repository), with evidence URLs.
  * Only ACCEPT sources are downloaded. Acquisition uses a pinned, versioned
    HTML-archive URL and records the SHA-256, byte size, last-modified header,
    documentation version, and license evidence.
  * Code blocks are extracted from the built HTML, AST-validated without
    execution, and filtered with the project's configured thresholds.
  * Nothing is overwritten: raw archives and manifests are versioned and
    fail safely if the destination already exists.

The authoritative AST validator and the approved pycodestyle tooling are
reused via ``scripts.scrapers.python_docs``. No downloaded code is executed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests
from bs4 import BeautifulSoup, Tag

from config import (
    MAX_TOKEN_LENGTH,
    MIN_COMMENT_RATIO,
    MIN_TOKEN_LENGTH,
    PEP8_MAX_VIOLATIONS,
    RAW_DIR,
    STAGE1_DIR,
)
from scripts.scrapers.python_docs import (
    common_archive_root,
    exact_hash,
    iter_html_documents,
    measure_pep8_violations,
    nearest_context,
    nearest_section,
    normalize_code,
    provisional_token_count,
    sha256_file,
    strip_doctest_prompts,
    utc_now_iso,
)
from scripts.validators.ast_validator import validate_python


PIPELINE_VERSION = "1.0.0"
STAGE = 1
KG_PENDING = "pending"
TOKEN_COUNT_METHOD = "provisional_python_tokenize_significant_tokens_v1"
RAW_ROOT = RAW_DIR / "scientific_docs"

# Sphinx/PyData highlight-language markers. The default Sphinx highlight
# language is Python, so a bare "highlight" (or "default") block is treated as
# Python unless an explicit non-Python language marker is present.
_PYTHON_MARKERS = {"python", "python3", "pycon", "default", "ipython", "ipython3", ""}
_NON_PYTHON_MARKERS = {
    "bash", "sh", "shell", "c", "c++", "cpp", "html", "xml", "css",
    "javascript", "js", "json", "text", "none", "rst", "sql", "console",
    "doscon", "make", "cmake", "diff", "fortran", "julia", "r", "yaml",
}


# ---------------------------------------------------------------------------
# Candidate-source inventory (license-first audit, 2026-10-22 UTC)
# ---------------------------------------------------------------------------

SOURCE_INVENTORY: list[dict[str, Any]] = [
    {
        "source_name": "numpy_docs",
        "project": "NumPy",
        "source_url": "https://numpy.org/doc/2.5/",
        "download_url": "https://numpy.org/doc/2.5/numpy-html.zip",
        "documentation_version": "2.5",
        "license": "BSD 3-Clause License",
        "license_spdx": "BSD-3-Clause",
        "license_url": "https://numpy.org/doc/stable/license.html",
        "license_evidence": (
            "NumPy documentation is published under the BSD 3-Clause license; the "
            "docs site carries the full license text on its license page. The "
            "numpy/numpy.org LICENSE is BSD-3-Clause."
        ),
        "download_evidence": (
            "Official versioned HTML archive: "
            "https://numpy.org/doc/2.5/numpy-html.zip (36,455,676 bytes, "
            "last-modified 2026-06-28)."
        ),
        "decision": "ACCEPT",
        "decision_reason": (
            "BSD-3-Clause documentation license clearly covers redistribution and "
            "derivative use; pinned versioned HTML archive with verifiable checksum."
        ),
    },
    {
        "source_name": "scipy_docs",
        "project": "SciPy",
        "source_url": "https://docs.scipy.org/doc/scipy-1.18.0/",
        "download_url": "https://docs.scipy.org/doc/scipy-1.18.0/scipy-html-1.18.0.zip",
        "documentation_version": "1.18.0",
        "license": "BSD 3-Clause License",
        "license_spdx": "BSD-3-Clause",
        "license_url": "https://docs.scipy.org/doc/scipy/dev/core-dev/index.html",
        "license_evidence": (
            "SciPy's developer guide states: 'SciPy is distributed under the "
            "modified (3-clause) BSD license. All code, documentation and other "
            "files added to SciPy by contributors is licensed under this license.'"
        ),
        "download_evidence": (
            "Official versioned HTML archive: "
            "https://docs.scipy.org/doc/scipy-1.18.0/scipy-html-1.18.0.zip "
            "(76,758,514 bytes, last-modified 2026-06-19)."
        ),
        "decision": "ACCEPT",
        "decision_reason": (
            "BSD-3-Clause explicitly covers documentation; pinned versioned HTML "
            "archive with verifiable checksum."
        ),
    },
    {
        "source_name": "pandas_docs",
        "project": "pandas",
        "source_url": "https://pandas.pydata.org/pandas-docs/version/2.3.3/",
        "download_url": "https://pandas.pydata.org/pandas-docs/version/2.3.3/pandas.zip",
        "documentation_version": "2.3.3",
        "license": "BSD 3-Clause License",
        "license_spdx": "BSD-3-Clause",
        "license_url": "https://pandas.pydata.org/pandas-docs/version/2.3.3/getting_started/overview.html",
        "license_evidence": (
            "pandas documentation describes the project as 'an open source, "
            "BSD-licensed library'; the overview page carries the BSD 3-Clause "
            "license text."
        ),
        "download_evidence": (
            "Official versioned HTML archive ('Zipped HTML'): "
            "https://pandas.pydata.org/pandas-docs/version/2.3.3/pandas.zip "
            "(40,509,391 bytes, last-modified 2026-10-21). Latest stable 3.0.6 "
            "lacks a versioned archive URL, so the latest versioned archive is used."
        ),
        "decision": "ACCEPT",
        "decision_reason": (
            "BSD-3-Clause documentation license; versioned HTML archive with "
            "verifiable checksum."
        ),
    },
    {
        "source_name": "matplotlib_docs",
        "project": "Matplotlib",
        "source_url": "https://matplotlib.org/stable/",
        "download_url": None,
        "documentation_version": "3.11.2",
        "license": "Matplotlib License (PSF-derived, BSD-compatible)",
        "license_spdx": "Matplotlib",
        "license_url": "https://matplotlib.org/stable/project/license.html",
        "license_evidence": (
            "Matplotlib's license is based on the PSF license and only uses "
            "BSD-compatible code; the license explicitly covers 'associated "
            "documentation'."
        ),
        "download_evidence": (
            "No versioned HTML archive is published (only a PDF: "
            "https://matplotlib.org/stable/Matplotlib.pdf). An HTML-archive "
            "acquisition path has not been established."
        ),
        "decision": "HOLD",
        "decision_reason": (
            "License is clear and permissive, but there is no immutable HTML "
            "archive to acquire; a source-repo or PDF acquisition path would "
            "require a separate mechanism decision."
        ),
    },
]

APPROVED_SOURCES = [s for s in SOURCE_INVENTORY if s["decision"] == "ACCEPT"]


@dataclass(frozen=True, slots=True)
class ExtractedBlock:
    code: str
    context: str
    section: str
    source_url: str
    detection_method: str


# ---------------------------------------------------------------------------
# HTML code-block detection (Sphinx / PyData theme)
# ---------------------------------------------------------------------------


def detect_python_block(block: Tag, raw_code: str) -> str | None:
    """Return a detection method for a Sphinx highlight block, or None.

    A bare/default highlight block is treated as Python (Sphinx's default
    highlight language) unless an explicit non-Python marker is present.
    """
    classes: set[str] = set()
    for parent in [block, *block.parents]:
        for class_name in getattr(parent, "get", lambda *_: [])("class", []):
            value = str(class_name).lower()
            if value.startswith("highlight-"):
                value = value[len("highlight-"):]
            elif value.startswith("highlight"):
                value = value[len("highlight"):]
            classes.add(value)

    if "pycon" in classes or looks_like_doctest(raw_code):
        return "doctest"
    if classes & _NON_PYTHON_MARKERS:
        return None
    if classes & _PYTHON_MARKERS:
        return "explicit_python" if (classes & {"python", "python3"}) else "default_python"
    # No highlight language at all: fall back to doctest heuristic only.
    return "doctest" if looks_like_doctest(raw_code) else None


def looks_like_doctest(raw_code: str) -> bool:
    return any(line.lstrip().startswith((">>> ", "... ")) for line in raw_code.splitlines())


def iter_python_blocks(archive_path: Path, source_url: str) -> Iterable[ExtractedBlock]:
    for relative_path, html in iter_html_documents(archive_path):
        soup = BeautifulSoup(html, "html.parser")
        page_url = requests.compat.urljoin(source_url, relative_path.as_posix())
        seen_code: set[str] = set()
        for pre in soup.find_all("pre"):
            highlight_div = pre.find_parent(
                "div", class_=lambda value: value and "highlight" in str(value)
            )
            if highlight_div is None:
                continue
            raw_code = pre.get_text()
            detection = detect_python_block(highlight_div, raw_code)
            if detection is None:
                continue
            code = strip_doctest_prompts(raw_code) if detection == "doctest" else raw_code
            if code in seen_code:
                continue
            seen_code.add(code)
            yield ExtractedBlock(
                code=code,
                context=nearest_context(highlight_div),
                section=nearest_section(highlight_div),
                source_url=page_url,
                detection_method=detection,
            )


# ---------------------------------------------------------------------------
# Download (pinned, checksummed, refuse-overwrite)
# ---------------------------------------------------------------------------


def _http_last_modified(response: requests.Response) -> str | None:
    return response.headers.get("last-modified") or response.headers.get("Last-Modified")


def _rmdir_if_empty(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass


def download_archive(
    source: dict[str, Any],
    destination_root: Path = RAW_ROOT,
    timeout: int = 120,
) -> tuple[Path, dict[str, Any]]:
    """Download a pinned archive into a versioned directory (refuse-overwrite)."""
    url = source["download_url"]
    if not url:
        raise ValueError(f"source {source['source_name']} has no download URL")
    target_dir = destination_root / f"{source['source_name']}__{source['documentation_version']}"
    if target_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing raw archive dir: {target_dir}")

    archive_name = Path(url).name
    partial = destination_root / ".inprogress" / source["source_name"] / f"{archive_name}.part"
    partial.parent.mkdir(parents=True, exist_ok=True)

    headers: dict[str, str] = {}
    existing = partial.stat().st_size if partial.exists() else 0
    if existing:
        headers["Range"] = f"bytes={existing}-"

    response = requests.get(url, headers=headers, stream=True, timeout=timeout)
    response.raise_for_status()
    mode = "ab" if existing and response.status_code == 206 else "wb"
    with partial.open(mode) as handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                handle.write(chunk)

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=False)
    archive_path = target_dir / archive_name
    try:
        os.replace(partial, archive_path)
    except OSError:
        # Cross-device fallback.
        import shutil

        shutil.move(str(partial), str(archive_path))

    # Remove the now-empty in-progress staging directories.
    _rmdir_if_empty(partial.parent)
    _rmdir_if_empty(partial.parent.parent)

    checksum = sha256_file(archive_path)
    manifest = {
        "manifest_version": "1",
        "acquired_at": utc_now_iso(),
        "source_name": source["source_name"],
        "project": source["project"],
        "source_url": source["source_url"],
        "download_url": url,
        "documentation_version": source["documentation_version"],
        "license": source["license"],
        "license_spdx": source["license_spdx"],
        "license_url": source["license_url"],
        "license_evidence": source["license_evidence"],
        "decision": source["decision"],
        "archive_name": archive_name,
        "sha256": checksum,
        "size_bytes": archive_path.stat().st_size,
        "http_last_modified": _http_last_modified(response),
        "pipeline_version": PIPELINE_VERSION,
    }
    manifest_path = target_dir / "ACQUISITION_MANIFEST.json"
    _write_json(manifest_path, manifest)
    return archive_path, manifest


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------


def process_source(
    source: dict[str, Any],
    archive_path: Path,
    *,
    output_path: Path,
    min_tokens: int = MIN_TOKEN_LENGTH,
    max_tokens: int = MAX_TOKEN_LENGTH,
    min_comment_ratio: float = MIN_COMMENT_RATIO,
    pep8_max_violations: int = PEP8_MAX_VIOLATIONS,
) -> dict[str, Any]:
    stats = {
        "blocks_examined": 0,
        "syntax_valid": 0,
        "syntax_invalid": 0,
        "too_short": 0,
        "too_long": 0,
        "low_documentation": 0,
        "pep8_rejected": 0,
        "exact_duplicates": 0,
        "retained": 0,
    }
    retained: list[dict[str, Any]] = []
    seen: set[str] = set()

    for block in iter_python_blocks(archive_path, source["source_url"]):
        stats["blocks_examined"] += 1
        code = normalize_code(block.code)
        if not code:
            stats["syntax_invalid"] += 1
            continue
        code_hash = exact_hash(code)
        if code_hash in seen:
            stats["exact_duplicates"] += 1
            continue
        seen.add(code_hash)

        validation = validate_python(code)
        if not validation.is_valid:
            stats["syntax_invalid"] += 1
            continue
        stats["syntax_valid"] += 1

        token_count = provisional_token_count(code)
        pep8_violations = measure_pep8_violations(code)

        if token_count < min_tokens:
            stats["too_short"] += 1
            continue
        if token_count > max_tokens:
            stats["too_long"] += 1
            continue
        if validation.comment_ratio < min_comment_ratio:
            stats["low_documentation"] += 1
            continue
        if pep8_violations > pep8_max_violations:
            stats["pep8_rejected"] += 1
            continue

        retained.append(
            {
                "id": f"{source['source_name']}:{source['documentation_version']}:{code_hash[:16]}",
                "code": code,
                "context": block.context,
                "source": source["source_name"],
                "stage": STAGE,
                "documentation_version": source["documentation_version"],
                "section": block.section,
                "source_url": block.source_url,
                "license": source["license"],
                "license_spdx": source["license_spdx"],
                "license_url": source["license_url"],
                "retrieved_at": utc_now_iso(),
                "provisional_token_count": token_count,
                "token_count_method": TOKEN_COUNT_METHOD,
                "comment_ratio": validation.comment_ratio,
                "comment_count": validation.comment_count,
                "docstring_count": validation.docstring_count,
                "pep8_violations": pep8_violations,
                "syntax_valid": True,
                "kg_validation_status": KG_PENDING,
                "exact_hash": code_hash,
                "detection_method": block.detection_method,
                "ast_metadata": {
                    "node_count": validation.node_count,
                    "function_count": validation.function_count,
                    "class_count": validation.class_count,
                    "import_count": validation.import_count,
                    "loop_count": validation.loop_count,
                    "conditional_count": validation.conditional_count,
                    "return_count": validation.return_count,
                },
            }
        )
        stats["retained"] += 1

    _write_jsonl(output_path, retained)
    return {"stats": stats, "records": retained}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _make_run_id(source_names: Sequence[str]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    joined = "-".join(sorted(source_names))
    return f"scidocs-{stamp}-{hashlib.sha256(joined.encode()).hexdigest()[:8]}"


def process(
    *,
    sources: Sequence[dict[str, Any]],
    raw_root: Path = RAW_ROOT,
    stage1_root: Path = STAGE1_DIR,
    run_id: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    computed_run_id = run_id or _make_run_id([s["source_name"] for s in sources])
    if not re.fullmatch(r"[A-Za-z0-9._-]+", computed_run_id):
        raise ValueError("run_id may contain only letters, digits, dot, underscore, hyphen")

    manifests: list[dict[str, Any]] = []
    per_source: list[dict[str, Any]] = []
    all_records: list[dict[str, Any]] = []

    for source in sources:
        if dry_run:
            # No network / no write: just record the decision for the dry run.
            per_source.append(
                {"source_name": source["source_name"], "decision": source["decision"], "dry_run": True}
            )
            continue
        archive_path, manifest = download_archive(source, destination_root=raw_root)
        manifests.append(manifest)
        output_path = stage1_root / f"scientific_docs_{computed_run_id}_{source['source_name']}.jsonl"
        result = process_source(source, archive_path, output_path=output_path)
        all_records.extend(result["records"])
        per_source.append(
            {
                "source_name": source["source_name"],
                "documentation_version": source["documentation_version"],
                "archive_sha256": manifest["sha256"],
                "stats": result["stats"],
                "output_path": str(output_path),
            }
        )

    total_records = len(all_records)
    report = {
        "run_id": computed_run_id,
        "generated_at": utc_now_iso(),
        "dry_run": dry_run,
        "pipeline_version": PIPELINE_VERSION,
        "sources": [
            {
                "source_name": s["source_name"],
                "decision": s["decision"],
                "license_spdx": s["license_spdx"],
                "documentation_version": s["documentation_version"],
            }
            for s in sources
        ],
        "per_source": per_source,
        "counts": {
            "sources_processed": len(per_source),
            "total_retained": total_records,
        },
    }
    if dry_run:
        return report

    stage1_root.mkdir(parents=True, exist_ok=True)
    report_dir = raw_root / "reports" / computed_run_id
    if report_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing report dir: {report_dir}")
    report_dir.mkdir(parents=True, exist_ok=False)
    _write_json(report_dir / "report.json", report)
    _write_json(report_dir / "source_inventory.json", {"run_id": computed_run_id, "sources": list(SOURCE_INVENTORY)})
    _write_json(report_dir / "acquisition_manifests.json", manifests)
    report["report_dir"] = str(report_dir)
    return report


# ---------------------------------------------------------------------------
# JSON writers (atomic, refuse-overwrite)
# ---------------------------------------------------------------------------


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


def _write_jsonl(path: Path, records: Sequence[dict[str, Any]]) -> None:
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--sources", nargs="*", default=None, help="source_name values (default: all ACCEPT)")
    parser.add_argument("--raw-root", default=str(RAW_ROOT))
    parser.add_argument("--stage1-root", default=str(STAGE1_DIR))
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
            stage1_root=Path(args.stage1_root),
            run_id=args.run_id,
            dry_run=args.dry_run,
        )
    except (FileExistsError, ValueError, requests.RequestException) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    print(f"RUN_ID={report['run_id']}")
    print(f"RETAINED={report['counts']['total_retained']}")
    print(f"REPORT_DIR={report['report_dir']}")
    for item in report["per_source"]:
        s = item["stats"]
        print(f"{item['source_name']}: blocks={s['blocks_examined']} retained={s['retained']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
