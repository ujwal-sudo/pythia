#!/usr/bin/env python3
"""Prose-plus-code acquisition for Pythia-160M (Stage 1, license-first).

Extracts *explanatory prose* together with the Python examples it explains from
documentation sources, instead of discarding the narrative and keeping only
code blocks (the previous docs pipeline behaviour).

Supported document types:

  * reStructuredText (``.rst``) — PEPs and the CPython Developer's Guide.
  * Built HTML archives/directories — scikit-learn and SymPy docs.

Design rules:

  * License-first: every source carries verified license evidence; only
    ``LICENSE_APPROVED_FOR_INTENDED_USE`` sources are promoted. PEPs are
    classified per document from the PEP's own ``Copyright`` section.
  * Provenance: immutable commit SHA / pinned docs version, page path, section,
    canonical URL, archive checksum (for ZIP), and license-file hash.
  * No execution: Python code examples are AST-validated only.
  * Deterministic, refuse-overwrite writers; exact-dedup by content hash.
  * Prose-only sections are kept (explanatory text is the scarce signal);
    sections with code are marked ``prose_with_code``.

Canonical record fields follow ``research/data_contract.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import requests
from bs4 import BeautifulSoup, Tag

from config import RAW_DIR, STAGE1_DIR
from scripts.scrapers.python_docs import (
    exact_hash,
    iter_html_documents,
    looks_like_doctest,
    normalize_code,
    sha256_file,
    strip_doctest_prompts,
    utc_now_iso,
)
from scripts.scrapers.scientific_docs import detect_python_block
from scripts.validators.ast_validator import validate_python


PIPELINE_VERSION = "1.0.0"
SCHEMA_VERSION = "prose_plus_code.v1"
TOKEN_COUNT_METHOD = "provisional_char_count_div_4"
VALIDATOR_VERSION = "scripts.validators.ast_validator"
STAGE = 1

LICENSE_APPROVED = "LICENSE_APPROVED_FOR_INTENDED_USE"
LICENSE_REVIEW_REQUIRED = "LICENSE_REVIEW_REQUIRED"
LICENSE_INELIGIBLE = "LICENSE_INELIGIBLE"
PROVENANCE_INSUFFICIENT = "PROVENANCE_INSUFFICIENT"

MIN_PROSE_TOKENS = 30
MAX_UNIT_TOKENS = 2048
KG_PENDING = "pending"

RAW_ROOT = RAW_DIR / "prose_plus_code"

_PY_LANGS = {"python", "python3", "py", "pycon", "default", "ipython", "ipython3", ""}
_NON_PY_LANGS = {
    "bash", "sh", "shell", "console", "c", "c++", "cpp", "html", "xml", "css",
    "javascript", "js", "json", "yaml", "toml", "sql", "text", "none", "rst",
    "make", "cmake", "diff", "ini", "cfg", "output", "testoutput", "doctest-output",
}
_NOTE_DIRECTIVES = {
    "note", "warning", "seealso", "versionadded", "versionchanged", "important",
    "tip", "caution", "danger", "error", "hint", "attention", "admonition",
    "topic", "rubric", "epigraph", "deprecated",
}
_SKIP_DIRECTIVES = {
    "toctree", "contents", "index", "meta", "only", "raw", "include",
    "literalinclude", "image", "figure", "csv-table", "list-table", "container",
    "class", "role", "default-role", "highlight",
}

# ---------------------------------------------------------------------------
# Verified source inventory (license + version evidence, 2026-10-22)
# ---------------------------------------------------------------------------

SOURCE_INVENTORY: List[Dict[str, Any]] = [
    {
        "source_name": "peps",
        "kind": "rst_git",
        "repo": "https://github.com/python/peps.git",
        "repo_owner": "python",
        "repo_name": "peps",
        "ref": "main",
        "docs_glob": "peps/pep-*.rst",
        "web_base": "https://peps.python.org/",
        "documentation_version": None,
        "license": "Public domain / CC0-1.0 (per-PEP Copyright section)",
        "license_spdx": "CC0-1.0",
        "license_status": LICENSE_APPROVED,
        "license_url": "https://github.com/python/peps/blob/main/peps/pep-0001.rst",
        "license_evidence": (
            "Each PEP ends with a Copyright section that places the document in "
            "the public domain or under CC0-1.0, whichever is more permissive. "
            "Licence is verified per document from that section."
        ),
        "per_document_license": True,
        "decision": "ACCEPT",
    },
    {
        "source_name": "cpython_devguide",
        "kind": "rst_git",
        "repo": "https://github.com/python/devguide.git",
        "repo_owner": "python",
        "repo_name": "devguide",
        "ref": "main",
        "docs_glob": "**/*.rst",
        "web_base": "https://devguide.python.org/",
        "documentation_version": None,
        "license": "CC0-1.0",
        "license_spdx": "CC0-1.0",
        "license_status": LICENSE_APPROVED,
        "license_url": "https://github.com/python/devguide/blob/main/LICENSE",
        "license_evidence": (
            "Repository LICENSE file is CC0 1.0 Universal (verified 2026-10-22)."
        ),
        "per_document_license": False,
        "decision": "ACCEPT",
    },
    {
        "source_name": "scikit_learn_docs",
        "kind": "html_zip",
        "download_url": "https://scikit-learn.org/stable/_downloads/scikit-learn-docs.zip",
        "web_base": "https://scikit-learn.org/stable/",
        "documentation_version": "1.9.1",
        "license": "BSD-3-Clause",
        "license_spdx": "BSD-3-Clause",
        "license_status": LICENSE_APPROVED,
        "license_url": "https://github.com/scikit-learn/scikit-learn/blob/main/COPYING",
        "license_evidence": (
            "scikit-learn COPYING is the BSD 3-Clause License (verified 2026-10-22); "
            "the documentation archive ships with the project."
        ),
        "per_document_license": False,
        "decision": "ACCEPT",
    },
    {
        "source_name": "sympy_docs",
        "kind": "git_sparse_html",
        "repo": "https://github.com/sympy/sympy_doc.git",
        "repo_owner": "sympy",
        "repo_name": "sympy_doc",
        "ref": "gh-pages",
        "sparse_dir": "latest",
        "web_base": "https://docs.sympy.org/latest/",
        "documentation_version": "1.14.0",
        "license": "BSD-3-Clause",
        "license_spdx": "BSD-3-Clause",
        "license_status": LICENSE_APPROVED,
        "license_url": "https://github.com/sympy/sympy_doc/blob/gh-pages/LICENSE",
        "license_evidence": (
            "sympy_doc LICENSE is a 3-clause BSD license (SymPy Development Team); "
            "verified 2026-10-22. Docs are generated from SymPy 1.14.0."
        ),
        "per_document_license": False,
        "decision": "ACCEPT",
    },
]

APPROVED_SOURCES = [s for s in SOURCE_INVENTORY if s["decision"] == "ACCEPT"]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _prose_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text.strip() else 0


def _dedent(lines: Sequence[str]) -> str:
    non_empty = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    if not non_empty:
        return ""
    indent = min(non_empty)
    out = []
    for line in lines:
        out.append(line[indent:] if len(line) >= indent else line.lstrip())
    return "\n".join(out)


def _clean_inline(text: str) -> str:
    """Reduce common reStructuredText inline markup to plain text."""
    text = re.sub(r"`([^`<]+?)\s*<[^>]+>`__?", r"\1", text)      # links
    text = re.sub(r":[A-Za-z0-9_:+.-]+:`([^`]+)`", r"\1", text)  # roles
    text = re.sub(r"``([^`]+)``", r"\1", text)                    # literals
    text = re.sub(r"`([^`]+)`_{1,2}", r"\1", text)                # refs
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\|[^|\n]+\|", "", text)                      # substitutions
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"\[[0-9#*]+\]_", "", text)                    # footnote refs
    text = text.replace("\u00b6", "")
    return _collapse_ws(text)


def _collapse_ws(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def _normalize_prose(paragraphs: Sequence[str]) -> str:
    seen: set[str] = set()
    kept: List[str] = []
    for paragraph in paragraphs:
        cleaned = _collapse_ws(paragraph)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        kept.append(cleaned)
    return "\n\n".join(kept)


# ---------------------------------------------------------------------------
# reStructuredText extraction
# ---------------------------------------------------------------------------

_UNDERLINE_CHARS = set("=-~^\"'`+*#<>")
_LEVELS = {"=": 1, "-": 2, "~": 3, "^": 4, '"': 5, "'": 6, "`": 7, "+": 8, "*": 9, "#": 10, "<": 11, ">": 12}


def _is_underline(line: str) -> bool:
    stripped = line.strip()
    return len(stripped) >= 3 and len(set(stripped)) == 1 and stripped[0] in _UNDERLINE_CHARS


def _level(line: str) -> int:
    return _LEVELS.get(line.strip()[0], 6)


def _collect_indented(lines: Sequence[str], start: int) -> Tuple[List[str], int]:
    """Collect an indented (or blank) block beginning at ``start``."""
    block: List[str] = []
    i = start
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            block.append("")
            i += 1
            continue
        indent = len(line) - len(line.lstrip())
        if indent > 0:
            block.append(line)
            i += 1
        else:
            break
    while block and not block[0].strip():
        block.pop(0)
    while block and not block[-1].strip():
        block.pop()
    return block, i


def _clean_block_text(block: Sequence[str]) -> str:
    text = _dedent(block)
    kept: List[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(":"):  # directive options
            continue
        kept.append(_clean_inline(stripped))
    return _collapse_ws(" ".join(kept))


@dataclass
class Unit:
    title: str
    level: int
    order: int
    paragraphs: List[str] = field(default_factory=list)
    code_blocks: List[Dict[str, Any]] = field(default_factory=list)
    page_title: str = ""


_PEP_METADATA_RE = re.compile(
    r"^(PEP|Title|Author|Sponsor|Status|Type|Content-Type|Created|Post-History|"
    r"Resolution|Requires|Replaces|Superseded-By|Discussions-To|Version|"
    r"Last-Modified|Topic|Python-Version)\s*:",
    re.IGNORECASE,
)


def parse_rst(text: str, default_language: str = "python") -> List[Unit]:
    """Parse reStructuredText into units of prose + Python code blocks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    lines = text.split("\n")
    units: List[Unit] = [Unit(title="", level=0, order=0)]
    state = {"language": default_language}
    i, n = 0, len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        # Overlined heading.
        if _is_underline(line) and i + 2 < n and lines[i + 1].strip() and _is_underline(lines[i + 2]):
            title = _clean_inline(lines[i + 1].strip())
            if title:
                units.append(Unit(title=title, level=_level(line), order=len(units)))
            i += 3
            continue

        # Underlined heading.
        if (
            i + 1 < n
            and not line.startswith((" ", "\t", ".."))
            and _is_underline(lines[i + 1])
            and len(lines[i + 1].strip()) >= 3
        ):
            title = _clean_inline(stripped)
            if title:
                units.append(Unit(title=title, level=_level(lines[i + 1]), order=len(units)))
            i += 2
            continue

        # Explicit markup: directive / comment / target / substitution.
        if stripped.startswith(".."):
            match = re.match(r"^\.\.\s+([A-Za-z0-9_+-]+)::\s*(.*)$", line)
            if match:
                name = match.group(1).lower()
                argument = match.group(2).strip()
                block, next_i = _collect_indented(lines, i + 1)
                if name in {"code-block", "code", "sourcecode", "code-block::", "highlight-block"}:
                    language = (argument.split()[0].lower() if argument else state["language"])
                    code = _dedent(block)
                    if language in _PY_LANGS and code.strip():
                        units[-1].code_blocks.append(
                            {"code": code, "language": "python", "detection_method": f"rst:{name}"}
                        )
                elif name in {"doctest", "testcode", "testoutput"}:
                    code = _dedent(block)
                    if name != "testoutput" and code.strip():
                        if looks_like_doctest(code):
                            code = strip_doctest_prompts(code)
                        units[-1].code_blocks.append(
                            {"code": code, "language": "python", "detection_method": f"rst:{name}"}
                        )
                elif name == "highlight":
                    state["language"] = argument.split()[0].lower() if argument else "python"
                elif name in _NOTE_DIRECTIVES:
                    note = _clean_block_text(block)
                    if note:
                        units[-1].paragraphs.append(note)
                # Other directives (toctree, image, ...) are skipped.
                i = next_i if next_i > i else i + 1
                continue
            # Comment / target / substitution: skip its indented body.
            _, next_i = _collect_indented(lines, i + 1)
            i = next_i if next_i > i + 1 else i + 1
            continue

        # PEP header metadata (``PEP: 8``, ``Title: ...``, ...) — skip.
        if _PEP_METADATA_RE.match(line):
            _, next_i = _collect_indented(lines, i + 1)
            i = next_i if next_i > i + 1 else i + 1
            continue

        # Field list (metadata) — skip.
        if re.match(r"^:[A-Za-z0-9_-]+:", stripped):
            i += 1
            continue

        # Top-level doctest block.
        if stripped.startswith(">>>") and (len(line) - len(line.lstrip())) == 0:
            block: List[str] = []
            j = i
            while j < n and (lines[j].startswith((">>>", "...")) or not lines[j].strip()):
                block.append(lines[j])
                j += 1
            code = strip_doctest_prompts("\n".join(block)).strip()
            if code:
                units[-1].code_blocks.append(
                    {"code": code, "language": "python", "detection_method": "rst:doctest"}
                )
            i = j
            continue

        # Literal block introduced by a trailing "::".
        if stripped.endswith("::"):
            prose_line = stripped[:-2].rstrip()
            if prose_line:
                units[-1].paragraphs.append(_clean_inline(prose_line))
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n and (len(lines[j]) - len(lines[j].lstrip())) > 0:
                block, next_i = _collect_indented(lines, j)
                code = _dedent(block)
                if code.strip() and (state["language"] in _PY_LANGS or looks_like_doctest(code)):
                    units[-1].code_blocks.append(
                        {"code": code, "language": "python", "detection_method": "rst:literal"}
                    )
                i = next_i
                continue
            i = j
            continue

        # Ordinary prose (including list items / definition terms).
        units[-1].paragraphs.append(_clean_inline(re.sub(r"^[-*+]\s+|^\d+[.)]\s+", "", stripped)))
        i += 1

    page_title = next((u.title for u in units if u.title), "")
    result = [u for u in units if u.paragraphs or u.code_blocks]
    for unit in result:
        unit.page_title = page_title
    return result


# ---------------------------------------------------------------------------
# HTML extraction (Sphinx / PyData themes)
# ---------------------------------------------------------------------------

_NOISE_TAGS = ("script", "style", "nav", "footer", "header", "form", "noscript")
_NOISE_CLASS = (
    "sphinxsidebar", "related", "breadcrumb", "prev-next", "headerlink",
    "viewcode-link", "toctree-wrapper", "document-toc", "navbar", "bd-sidebar",
    "bd-toc", "copybtn", "highlight-language", "admonition-title", "sidebar",
)


def _strip_html_noise(soup: BeautifulSoup) -> None:
    for name in _NOISE_TAGS:
        for tag in soup.find_all(name):
            tag.decompose()
    for tag in soup.find_all(True):
        classes = " ".join(tag.get("class", [])).lower()
        if classes and any(token in classes for token in _NOISE_CLASS):
            tag.decompose()


def _clean_html_text(text: str) -> str:
    return _collapse_ws(text.replace("\u00b6", ""))


def html_units(html: str, page_url: str = "") -> List[Unit]:
    soup = BeautifulSoup(html, "html.parser")
    _strip_html_noise(soup)
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find("div", class_=lambda c: "document" in c.lower())
        or soup.body
        or soup
    )
    h1 = main.find("h1")
    page_title = h1.get_text(" ", strip=True) if h1 is not None else (
        soup.title.get_text(strip=True) if soup.title is not None else ""
    )
    units: List[Unit] = [Unit(title=page_title, level=1, order=0)]

    for el in main.find_all(["h1", "h2", "h3", "h4", "p", "dt", "dd", "blockquote", "li", "pre", "div"]):
        classes = " ".join(el.get("class", [])).lower()
        if el.name == "div":
            if "highlight" in classes and el.find_parent(
                "div", class_=lambda c: "highlight" in c.lower()
            ) is None:
                pre = el.find("pre")
                if pre is not None:
                    raw = pre.get_text()
                    detection = detect_python_block(el, raw)
                    if detection is not None:
                        code = strip_doctest_prompts(raw) if detection == "doctest" else raw
                        units[-1].code_blocks.append(
                            {"code": code, "language": "python", "detection_method": f"html:{detection}"}
                        )
            continue
        if el.name == "pre":
            if el.find_parent("div", class_=lambda c: "highlight" in c.lower()) is not None:
                continue
            raw = el.get_text()
            detection = detect_python_block(el, raw)
            if detection is not None:
                code = strip_doctest_prompts(raw) if detection == "doctest" else raw
                units[-1].code_blocks.append(
                    {"code": code, "language": "python", "detection_method": f"html:{detection}"}
                )
            continue
        if el.name in ("h1", "h2", "h3", "h4"):
            title = el.get_text(" ", strip=True)
            if title:
                units.append(Unit(title=title, level=int(el.name[1]), order=len(units)))
            continue
        if el.find_parent("pre") is not None:
            continue
        if el.find_parent("div", class_=lambda c: "highlight" in c.lower()) is not None:
            continue
        if el.name == "li" and el.find("p") is not None:
            continue
        text = el.get_text(" ", strip=True)
        if text:
            units[-1].paragraphs.append(_clean_html_text(text))

    result = [u for u in units if u.paragraphs or u.code_blocks]
    for unit in result:
        unit.page_title = page_title
    return result


# ---------------------------------------------------------------------------
# License classification (per-source or per-document)
# ---------------------------------------------------------------------------

_COPYRIGHT_RE = re.compile(r"(?im)^\s*copyright\s*$[\s\S]{0,600}$")
_PERMISSIVE_COPYRIGHT = re.compile(
    r"public domain|cc0|creative commons zero|cc0-1\.0", re.IGNORECASE
)


def classify_pep_license(text: str) -> Dict[str, Any]:
    """Classify a PEP from its own Copyright section."""
    match = _COPYRIGHT_RE.search(text)
    section = match.group(0) if match else ""
    if _PERMISSIVE_COPYRIGHT.search(section):
        return {
            "license": "Public domain / CC0-1.0",
            "license_spdx": "CC0-1.0",
            "license_status": LICENSE_APPROVED,
            "license_evidence": _collapse_ws(section)[:500],
        }
    return {
        "license": "UNKNOWN (unexpected Copyright section)",
        "license_spdx": "UNKNOWN",
        "license_status": LICENSE_REVIEW_REQUIRED,
        "license_evidence": _collapse_ws(section)[:500],
    }


def source_license_info(source: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "license": source["license"],
        "license_spdx": source["license_spdx"],
        "license_status": source["license_status"],
        "license_url": source.get("license_url"),
        "license_evidence": source.get("license_evidence"),
    }


# ---------------------------------------------------------------------------
# Record construction
# ---------------------------------------------------------------------------

_BOILERPLATE = {
    "table of contents", "previous topic", "next topic", "this page",
    "show source", "quick search", "navigation", "index", "contents",
    "report a bug", "edit on github", "see also", "references",
}


def _split_prose(prose: str, max_tokens: int) -> List[str]:
    """Split prose into chunks of at most ``max_tokens`` (char/4 estimate)."""
    max_chars = max(1, max_tokens * 4)
    if len(prose) <= max_chars:
        return [prose]
    paragraphs = [p for p in prose.split("\n\n") if p.strip()]
    chunks: List[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        # Paragraph itself too large: split on sentence boundaries.
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            while len(sentence) > max_chars:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(sentence[:max_chars])
                sentence = sentence[max_chars:]
            if not sentence:
                continue
            candidate = f"{current} {sentence}".strip() if current else sentence
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = sentence
    if current:
        chunks.append(current)
    return [c.strip() for c in chunks if c.strip()]


def _valid_code_blocks(raw_blocks: Sequence[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int, int]:
    valid: List[Dict[str, Any]] = []
    seen: set[str] = set()
    invalid = 0
    skipped = 0
    for block in raw_blocks:
        code = normalize_code(str(block.get("code", "")))
        if not code:
            skipped += 1
            continue
        digest = exact_hash(code)
        if digest in seen:
            skipped += 1
            continue
        seen.add(digest)
        validation = validate_python(code)
        if not validation.is_valid:
            invalid += 1
            continue
        valid.append(
            {
                "code": code,
                "language": "python",
                "detection_method": block.get("detection_method"),
                "content_hash": digest,
                "token_count": _prose_tokens(code),
                "ast_valid": True,
                "ast_node_count": validation.node_count,
                "function_count": validation.function_count,
                "class_count": validation.class_count,
                "comment_ratio": validation.comment_ratio,
            }
        )
    return valid, invalid, skipped


def build_records(
    *,
    source: Dict[str, Any],
    unit: Unit,
    page_path: str,
    page_url: str,
    source_version: Optional[str],
    license_info: Dict[str, Any],
    acquisition_date: str,
    min_prose_tokens: int = MIN_PROSE_TOKENS,
    max_unit_tokens: int = MAX_UNIT_TOKENS,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build accepted/rejected canonical records for one prose unit."""
    prose = _normalize_prose(unit.paragraphs)
    valid_code, invalid_code, skipped_code = _valid_code_blocks(unit.code_blocks)
    prose_tokens = _prose_tokens(prose)
    code_tokens = sum(c["token_count"] for c in valid_code)

    base = {
        "schema_version": SCHEMA_VERSION,
        "transformation_version": PIPELINE_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "stage": STAGE,
        "source": source["source_name"],
        "source_type": "raw",
        "source_url": page_url,
        "acquisition_date": acquisition_date,
        "license": license_info.get("license"),
        "license_spdx": license_info.get("license_spdx"),
        "license_status": license_info.get("license_status"),
        "license_url": license_info.get("license_url"),
        "license_evidence": license_info.get("license_evidence"),
        "source_version": source_version,
        "documentation_version": source.get("documentation_version"),
        "page_path": page_path,
        "page_title": unit.page_title or unit.title or page_path,
        "section_title": unit.title,
        "prose": prose,
        "prose_token_count": prose_tokens,
        "code_blocks": valid_code,
        "code_block_count": len(valid_code),
        "invalid_code_block_count": invalid_code,
        "skipped_code_block_count": skipped_code,
        "code_token_count": code_tokens,
        "total_token_count": prose_tokens + code_tokens,
        "token_count_method": TOKEN_COUNT_METHOD,
        "token_count_status": "PROVISIONAL",
        "has_code": bool(valid_code),
        "pairing": "prose_with_code" if valid_code else "prose_only",
        "provenance": {
            "repository": source.get("repo"),
            "commit": source_version,
            "path": page_path,
            "section": unit.title,
        },
        "kg_validation_status": KG_PENDING,
    }

    reasons: List[str] = []
    if not prose.strip():
        reasons.append("empty_prose")
    if prose_tokens and prose_tokens < min_prose_tokens:
        reasons.append(f"prose_too_short:{prose_tokens}")
    lowered = prose.lower().strip()
    if lowered in _BOILERPLATE:
        reasons.append("boilerplate_only")
    if len(re.findall(r"[A-Za-z]{3,}", prose)) < 5:
        reasons.append("insufficient_words")

    if reasons:
        rejected = {
            "source": source["source_name"],
            "source_version": source_version,
            "page_path": page_path,
            "section_title": unit.title,
            "prose_token_count": prose_tokens,
            "code_block_count": len(valid_code),
            "invalid_code_block_count": invalid_code,
            "skipped_code_block_count": skipped_code,
            "rejection_reasons": reasons,
        }
        return [], [rejected]

    if code_tokens >= max_unit_tokens:
        return [], [{
            "source": source["source_name"],
            "source_version": source_version,
            "page_path": page_path,
            "section_title": unit.title,
            "prose_token_count": prose_tokens,
            "code_token_count": code_tokens,
            "invalid_code_block_count": invalid_code,
            "skipped_code_block_count": skipped_code,
            "rejection_reasons": [f"code_too_long:{code_tokens}"],
        }]

    budget = max(min_prose_tokens, max_unit_tokens - code_tokens)
    chunks = _split_prose(prose, budget)
    accepted: List[Dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        attached_code = valid_code if index == 0 else []
        chunk_code_tokens = sum(c["token_count"] for c in attached_code)
        content = chunk + "\n\n" + "\n\n".join(c["code"] for c in attached_code) if attached_code else chunk
        content_hash = _sha256_text(content)
        record = dict(base)
        record.update(
            {
                "record_id": "prose_" + content_hash[:24],
                "content_hash": content_hash,
                "prose": chunk,
                "prose_token_count": _prose_tokens(chunk),
                "code_blocks": attached_code,
                "code_block_count": len(attached_code),
                "code_token_count": chunk_code_tokens,
                "total_token_count": _prose_tokens(chunk) + chunk_code_tokens,
                "has_code": bool(attached_code),
                "pairing": "prose_with_code" if attached_code else "prose_only",
                "chunk_index": index,
                "chunk_count": len(chunks),
                "eligibility": "eligible",
            }
        )
        accepted.append(record)
    return accepted, []


# ---------------------------------------------------------------------------
# Acquisition (pinned, checksummed, refuse-overwrite)
# ---------------------------------------------------------------------------


def _run(cmd: Sequence[str], cwd: Optional[Path] = None, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, check=True,
        capture_output=True, text=True, timeout=timeout,
    )


def _license_file_hash(raw_dir: Path) -> Optional[Dict[str, Any]]:
    for name in ("LICENSE", "LICENSE.txt", "LICENSE.rst", "COPYING", "COPYING.txt"):
        candidate = raw_dir / name
        if candidate.is_file():
            return {"path": name, "sha256": sha256_file(candidate), "bytes": candidate.stat().st_size}
    return None


def acquire_git_rst(source: Dict[str, Any], raw_root: Path = RAW_ROOT) -> Dict[str, Any]:
    staging = raw_root / ".inprogress" / source["source_name"]
    if staging.exists():
        shutil.rmtree(staging)
    staging.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "clone", "--depth", "1", "--branch", source["ref"], source["repo"], str(staging)])
    commit = _run(["git", "rev-parse", "HEAD"], cwd=staging).stdout.strip()
    dest = raw_root / f"{source['source_name']}__{commit[:12]}"
    if dest.exists():
        raise FileExistsError(f"refusing to overwrite existing raw dir: {dest}")
    os.replace(staging, dest)
    manifest = {
        "source_name": source["source_name"], "kind": source["kind"],
        "repo": source["repo"], "ref": source["ref"], "commit": commit,
        "acquired_at": _now(), "license": source["license"],
        "license_spdx": source["license_spdx"], "license_url": source.get("license_url"),
        "license_file": _license_file_hash(dest), "pipeline_version": PIPELINE_VERSION,
    }
    _write_json(dest / "ACQUISITION_MANIFEST.json", manifest)
    return {"raw_dir": dest, "content_path": dest, "source_version": commit, "manifest": manifest}


def _download_resumable(
    url: str, partial: Path, *, timeout: int = 300, attempts: int = 3
) -> Dict[str, Any]:
    """Download ``url`` to ``partial``, resuming and retrying on failure."""
    partial.parent.mkdir(parents=True, exist_ok=True)
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        existing = partial.stat().st_size if partial.exists() else 0
        headers = {"Range": f"bytes={existing}-"} if existing else {}
        try:
            with requests.get(url, headers=headers, stream=True, timeout=timeout) as response:
                if existing and response.status_code == 200:
                    mode = "wb"
                else:
                    response.raise_for_status()
                    mode = "ab" if existing and response.status_code == 206 else "wb"
                with partial.open(mode) as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
                return {
                    "http_last_modified": response.headers.get("last-modified"),
                    "http_content_length": response.headers.get("content-length"),
                }
        except (requests.RequestException, OSError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(attempt)
    if last_error is not None:
        raise last_error
    raise RuntimeError("download failed without an exception")


def acquire_html_zip(source: Dict[str, Any], raw_root: Path = RAW_ROOT, timeout: int = 300) -> Dict[str, Any]:
    dest = raw_root / f"{source['source_name']}__{source['documentation_version']}"
    if dest.exists():
        raise FileExistsError(f"refusing to overwrite existing raw dir: {dest}")
    url = source["download_url"]
    archive_name = Path(url).name
    partial = raw_root / ".inprogress" / source["source_name"] / f"{archive_name}.part"
    download_meta = _download_resumable(url, partial, timeout=timeout)
    dest.mkdir(parents=True, exist_ok=False)
    archive_path = dest / archive_name
    shutil.move(str(partial), str(archive_path))
    _rmdir_if_empty(partial.parent)
    _rmdir_if_empty(partial.parent.parent)
    manifest = {
        "source_name": source["source_name"], "kind": source["kind"],
        "download_url": url, "documentation_version": source["documentation_version"],
        "acquired_at": _now(), "sha256": sha256_file(archive_path),
        "size_bytes": archive_path.stat().st_size,
        "http_last_modified": download_meta["http_last_modified"],
        "license": source["license"], "license_spdx": source["license_spdx"],
        "license_url": source.get("license_url"), "pipeline_version": PIPELINE_VERSION,
    }
    _write_json(dest / "ACQUISITION_MANIFEST.json", manifest)
    return {"raw_dir": dest, "content_path": archive_path, "source_version": source["documentation_version"], "manifest": manifest}


def acquire_git_sparse_html(source: Dict[str, Any], raw_root: Path = RAW_ROOT) -> Dict[str, Any]:
    staging = raw_root / ".inprogress" / source["source_name"]
    if staging.exists():
        shutil.rmtree(staging)
    staging.parent.mkdir(parents=True, exist_ok=True)
    _run([
        "git", "clone", "--depth", "1", "--branch", source["ref"],
        "--filter=blob:none", "--sparse", source["repo"], str(staging),
    ])
    _run(["git", "sparse-checkout", "set", source["sparse_dir"]], cwd=staging)
    commit = _run(["git", "rev-parse", "HEAD"], cwd=staging).stdout.strip()
    dest = raw_root / f"{source['source_name']}__{source['documentation_version']}__{commit[:12]}"
    if dest.exists():
        raise FileExistsError(f"refusing to overwrite existing raw dir: {dest}")
    os.replace(staging, dest)
    manifest = {
        "source_name": source["source_name"], "kind": source["kind"],
        "repo": source["repo"], "ref": source["ref"], "commit": commit,
        "sparse_dir": source["sparse_dir"], "documentation_version": source["documentation_version"],
        "acquired_at": _now(), "license": source["license"], "license_spdx": source["license_spdx"],
        "license_url": source.get("license_url"), "license_file": _license_file_hash(dest),
        "pipeline_version": PIPELINE_VERSION,
    }
    _write_json(dest / "ACQUISITION_MANIFEST.json", manifest)
    return {"raw_dir": dest, "content_path": dest / source["sparse_dir"], "source_version": commit, "manifest": manifest}


def acquire(source: Dict[str, Any], raw_root: Path = RAW_ROOT) -> Dict[str, Any]:
    kind = source["kind"]
    if kind == "rst_git":
        return acquire_git_rst(source, raw_root)
    if kind == "html_zip":
        return acquire_html_zip(source, raw_root)
    if kind == "git_sparse_html":
        return acquire_git_sparse_html(source, raw_root)
    raise ValueError(f"unknown source kind: {kind}")


# ---------------------------------------------------------------------------
# Document iteration + orchestration
# ---------------------------------------------------------------------------


def iter_documents(source: Dict[str, Any], acquisition: Dict[str, Any]) -> Iterator[Tuple[str, str, str]]:
    kind = source["kind"]
    raw_dir = acquisition["raw_dir"]
    commit = acquisition["source_version"]
    if kind == "rst_git":
        pattern = source.get("docs_glob", "**/*.rst")
        for path in sorted(raw_dir.rglob(pattern)):
            relative = path.relative_to(raw_dir)
            if any(part in {".git", "_build", ".github"} for part in relative.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            page_url = (
                f"https://github.com/{source['repo_owner']}/{source['repo_name']}"
                f"/blob/{commit}/{relative.as_posix()}"
            )
            yield relative.as_posix(), text, page_url
        return

    if kind == "html_zip":
        for relative, html in iter_html_documents(acquisition["content_path"]):
            page_url = requests.compat.urljoin(source["web_base"], relative.as_posix())
            yield relative.as_posix(), html, page_url
        return

    if kind == "git_sparse_html":
        for relative, html in iter_html_documents(acquisition["content_path"]):
            page_url = requests.compat.urljoin(source["web_base"], relative.as_posix())
            yield relative.as_posix(), html, page_url
        return

    raise ValueError(f"unknown source kind: {kind}")


def process_source(
    source: Dict[str, Any],
    acquisition: Dict[str, Any],
    *,
    output_dir: Path,
    min_prose_tokens: int = MIN_PROSE_TOKENS,
    max_unit_tokens: int = MAX_UNIT_TOKENS,
) -> Dict[str, Any]:
    acquisition_date = _now()
    per_document_license = source.get("per_document_license", False)
    default_license = source_license_info(source)

    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    stats = {
        "documents": 0,
        "units": 0,
        "units_with_valid_code": 0,
        "accepted": 0,
        "rejected": 0,
        "exact_duplicates": 0,
        "invalid_code_blocks": 0,
        "skipped_code_blocks": 0,
    }
    seen_hashes: set[str] = set()

    for page_path, text, page_url in iter_documents(source, acquisition):
        stats["documents"] += 1
        if source["kind"] == "rst_git":
            units = parse_rst(text)
        else:
            units = html_units(text, page_url)

        license_info = classify_pep_license(text) if per_document_license else default_license
        if license_info["license_status"] != LICENSE_APPROVED:
            for unit in units:
                stats["units"] += 1
                rejected.append({
                    "source": source["source_name"],
                    "source_version": acquisition["source_version"],
                    "page_path": page_path,
                    "section_title": unit.title,
                    "license_status": license_info["license_status"],
                    "rejection_reasons": ["license_not_approved"],
                })
            continue

        for unit in units:
            stats["units"] += 1
            records, rejects = build_records(
                source=source, unit=unit, page_path=page_path, page_url=page_url,
                source_version=acquisition["source_version"], license_info=license_info,
                acquisition_date=acquisition_date, min_prose_tokens=min_prose_tokens,
                max_unit_tokens=max_unit_tokens,
            )
            stats["units_with_valid_code"] += 1 if records and records[0]["has_code"] else 0
            stats["invalid_code_blocks"] += (
                (records[0]["invalid_code_block_count"] if records else 0)
                + sum(r.get("invalid_code_block_count", 0) for r in rejects)
            )
            stats["skipped_code_blocks"] += (
                (records[0]["skipped_code_block_count"] if records else 0)
                + sum(r.get("skipped_code_block_count", 0) for r in rejects)
            )
            for record in records:
                if record["content_hash"] in seen_hashes:
                    stats["exact_duplicates"] += 1
                    continue
                seen_hashes.add(record["content_hash"])
                accepted.append(record)
                stats["accepted"] += 1
            rejected.extend(rejects)

    stats["rejected"] = len(rejected)

    output_dir.mkdir(parents=True, exist_ok=True)
    accepted_path = output_dir / f"prose_plus_code_{source['source_name']}_accepted.jsonl"
    rejected_path = output_dir / f"prose_plus_code_{source['source_name']}_rejected.jsonl"
    _write_jsonl(accepted_path, accepted)
    _write_jsonl(rejected_path, rejected)

    return {
        "source_name": source["source_name"],
        "source_version": acquisition["source_version"],
        "stats": stats,
        "accepted_path": str(accepted_path),
        "rejected_path": str(rejected_path),
        "accepted_records": len(accepted),
        "rejected_records": len(rejected),
        "prose_tokens": sum(r["prose_token_count"] for r in accepted),
        "code_tokens": sum(r["code_token_count"] for r in accepted),
        "total_tokens": sum(r["total_token_count"] for r in accepted),
    }


def process(
    *,
    sources: Sequence[Dict[str, Any]],
    raw_root: Path = RAW_ROOT,
    stage1_root: Path = STAGE1_DIR,
    run_id: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    computed_run_id = run_id or f"prose-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    if not re.fullmatch(r"[A-Za-z0-9._-]+", computed_run_id):
        raise ValueError("run_id may contain only letters, digits, dot, underscore, hyphen")

    output_dir = stage1_root / computed_run_id
    per_source: List[Dict[str, Any]] = []
    manifests: List[Dict[str, Any]] = []
    for source in sources:
        if dry_run:
            per_source.append({"source_name": source["source_name"], "decision": source["decision"], "dry_run": True})
            continue
        acquisition = acquire(source, raw_root=raw_root)
        manifests.append({"source_name": source["source_name"], **acquisition["manifest"]})
        result = process_source(source, acquisition, output_dir=output_dir)
        per_source.append(result)

    report = {
        "run_id": computed_run_id,
        "generated_at": _now(),
        "dry_run": dry_run,
        "pipeline_version": PIPELINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "sources": [
            {"source_name": s["source_name"], "decision": s["decision"], "license_spdx": s["license_spdx"]}
            for s in sources
        ],
        "per_source": per_source,
        "counts": {
            "sources_processed": len(per_source),
            "accepted_records": sum(p.get("accepted_records", 0) for p in per_source),
            "rejected_records": sum(p.get("rejected_records", 0) for p in per_source),
            "prose_tokens": sum(p.get("prose_tokens", 0) for p in per_source),
            "code_tokens": sum(p.get("code_tokens", 0) for p in per_source),
            "total_tokens": sum(p.get("total_tokens", 0) for p in per_source),
        },
    }
    if dry_run:
        return report

    report_dir = raw_root / "reports" / computed_run_id
    if report_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing report dir: {report_dir}")
    report_dir.mkdir(parents=True, exist_ok=False)
    _write_json(report_dir / "report.json", report)
    _write_json(report_dir / "source_inventory.json", {"run_id": computed_run_id, "sources": list(SOURCE_INVENTORY)})
    _write_json(report_dir / "acquisition_manifests.json", manifests)
    report["report_dir"] = str(report_dir)
    report["output_dir"] = str(output_dir)
    return report


# ---------------------------------------------------------------------------
# Writers (atomic, refuse-overwrite)
# ---------------------------------------------------------------------------


def _rmdir_if_empty(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass


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
        sources = [by_name[name] for name in args.sources]
    try:
        report = process(
            sources=sources,
            raw_root=Path(args.raw_root),
            stage1_root=Path(args.stage1_root),
            run_id=args.run_id,
            dry_run=args.dry_run,
        )
    except (FileExistsError, ValueError, requests.RequestException, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    print(f"RUN_ID={report['run_id']}")
    print(f"ACCEPTED={report['counts']['accepted_records']}")
    print(f"PROSE_TOKENS={report['counts']['prose_tokens']}")
    print(f"TOTAL_TOKENS={report['counts']['total_tokens']}")
    print(f"OUTPUT_DIR={report['output_dir']}")
    print(f"REPORT_DIR={report['report_dir']}")
    for item in report["per_source"]:
        s = item["stats"]
        print(
            f"{item['source_name']}: docs={s['documents']} units={s['units']} "
            f"accepted={s['accepted']} rejected={s['rejected']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
