#!/usr/bin/env python3
"""Prose-plus-code documentation extractor for Stage 1.

Turns approved reStructuredText documentation repositories (PEPs and the
CPython Developer's Guide) into training-ready explanatory records that keep
each code example attached to the prose that explains it.

Design principles:

  * Prose and code are emitted as ordered segments; no document structure is
    flattened away. Each record carries its section path, document identity,
    and source revision.
  * Code is parsed statically (AST) and never executed.
  * Acquisition is a shallow git clone of an official repository; the exact
    commit is recorded as the revision. Existing clones are reused read-only.
  * Nothing is overwritten: outputs and manifests are versioned and fail
    safely if the destination already exists.
  * This module never touches CodeSearchNet or PyPI outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tokenize
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from config import MAX_TOKEN_LENGTH, RAW_DIR, STAGE1_DIR
from scripts.scrapers.pep_license import (
    LICENSE_APPROVED,
    LICENSE_STATUS_CLEAR,
    classify_pep_license,
)
from scripts.scrapers.python_docs import (
    exact_hash,
    provisional_token_count,
    utc_now_iso,
)
from scripts.validators.ast_validator import validate_python


PIPELINE_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0"
STAGE = 1
KG_PENDING = "pending"
TOKEN_COUNT_METHOD = "whitespace_prose_plus_code_tokens_v1"
VALIDATOR_VERSION = "scripts.validators.ast_validator"
REPORT_ROOT = RAW_DIR / "prose_docs"

MIN_TOTAL_TOKENS = 40
MIN_PROSE_TOKENS = 20


SOURCE_INVENTORY: list[dict[str, Any]] = [
    {
        "source_name": "peps",
        "project": "Python Enhancement Proposals",
        "source_family": "official_documentation",
        "decision": "ACCEPT",
        "license": "Public domain / CC0-1.0",
        "license_spdx": "CC0-1.0",
        "license_status": LICENSE_STATUS_CLEAR,
        "license_status_detail": LICENSE_APPROVED,
        "license_url": "https://peps.python.org/pep-0001/",
        "license_evidence": (
            "Per-document fail-closed classification: only a PEP whose own "
            "Copyright section states public domain or CC0 is accepted."
        ),
        "repo_url": "https://github.com/python/peps",
        "ref": "main",
        "raw_subdir": "peps",
        "document_glob": "repo/peps/pep-*.rst",
        "exclude_globs": ["repo/peps/pep-0000.rst"],
        "source_url": "https://peps.python.org/",
        "documentation_version": "git:main",
    },
    {
        "source_name": "cpython_devguide",
        "project": "CPython Developer's Guide",
        "source_family": "official_documentation",
        "decision": "ACCEPT",
        "license": "CC0 1.0 Universal",
        "license_spdx": "CC0-1.0",
        "license_status": LICENSE_STATUS_CLEAR,
        "license_status_detail": LICENSE_APPROVED,
        "license_url": "https://github.com/python/devguide/blob/main/LICENSE",
        "license_evidence": (
            "The python/devguide repository LICENSE is CC0 1.0 Universal."
        ),
        "repo_url": "https://github.com/python/devguide",
        "ref": "main",
        "raw_subdir": "devguide",
        "document_glob": "repo/**/*.rst",
        "exclude_globs": ["repo/README.rst", "repo/include/**"],
        "source_url": "https://devguide.python.org/",
        "documentation_version": "git:main",
    },
]

APPROVED_SOURCES = [s for s in SOURCE_INVENTORY if s["decision"] == "ACCEPT"]


_HEADING_CHARS = set("=-~^\"'*+#`:._")
_DIRECTIVE_RE = re.compile(r"^\.\.\s+([A-Za-z0-9_-]+)::\s*(.*)$")
_PEP_HEADER_RE = re.compile(r"^([A-Z][A-Za-z-]*):\s*(.*)$")
_PEP_HEADER_FIELDS = {
    "PEP", "Title", "Author", "Sponsor", "PEP-Delegate", "Discussions-To",
    "Status", "Type", "Topic", "Requires", "Created", "Python-Version",
    "Post-History", "Replaces", "Superseded-By", "Resolution",
}
_CODE_DIRECTIVES = {"code-block", "code", "sourcecode", "parsed-literal", "doctest"}
_CONTAINER_DIRECTIVES = {
    "tab", "tab-item", "tab-set", "only", "container", "sidebar", "topic",
    "admonition", "rubric", "section", "compound",
}
_ADMONITIONS = {
    "note", "warning", "tip", "important", "caution", "danger", "error",
    "hint", "seealso", "versionadded", "versionchanged", "deprecated",
    "versionremoved", "todo", "attention",
}
_SKIP_DIRECTIVES = {
    "include", "image", "figure", "toctree", "contents", "index", "meta",
    "raw", "literalinclude", "highlight", "tabularcolumns", "graphviz",
    "mermaid", "math", "csv-table", "list-table", "table",
}
_PYTHON_LANGS = {"python", "py", "python3", "default", "ipython", "ipython3", ""}
_DOCTEST_LANGS = {"pycon", "doctest"}


@dataclass
class Segment:
    kind: str
    text: str
    language: Optional[str] = None


@dataclass
class Heading:
    start: int
    end: int
    title: str
    char: str
    level: int = 0
    overline: bool = False


@dataclass
class Section:
    path: list[str]
    body: list[str] = field(default_factory=list)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_punct_run(text: str) -> bool:
    return len(text) >= 3 and len(set(text)) == 1 and text[0] in _HEADING_CHARS


def _dedent(lines: Sequence[str]) -> list[str]:
    indents = [_indent(line) for line in lines if line.strip()]
    if not indents:
        return ["" for _ in lines]
    drop = min(indents)
    return [line[drop:] if line.strip() else "" for line in lines]


def _collect_indented(
    lines: Sequence[str], start: int, parent_indent: int
) -> tuple[list[str], int]:
    body: list[str] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            body.append("")
            index += 1
            continue
        if _indent(line) <= parent_indent:
            break
        body.append(line)
        index += 1
    return body, index


def _collect_until_blank(lines: Sequence[str], start: int) -> tuple[list[str], int]:
    body: list[str] = []
    index = start
    while index < len(lines) and lines[index].strip():
        body.append(lines[index])
        index += 1
    return body, index


# ---------------------------------------------------------------------------
# reStructuredText parsing (structure preserving)
# ---------------------------------------------------------------------------


def _clean_heading(text: str) -> str:
    cleaned = _clean_inline(text).strip()
    if cleaned.endswith("_") and not cleaned.endswith("__"):
        cleaned = cleaned[:-1].rstrip()
    return cleaned


def find_headings(lines: Sequence[str]) -> list[Heading]:
    headings: list[Heading] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if (
            stripped
            and _is_punct_run(stripped)
            and _indent(line) == 0
            and index + 2 < len(lines)
            and lines[index + 1].strip()
            and not _is_punct_run(lines[index + 1].strip())
            and _is_punct_run(lines[index + 2].strip())
            and set(lines[index + 2].strip()) == {stripped[0]}
        ):
            headings.append(
                Heading(
                    index,
                    index + 3,
                    _clean_heading(lines[index + 1].strip()),
                    stripped[0],
                    overline=True,
                )
            )
            index += 3
            continue
        if (
            stripped
            and not stripped.startswith("..")
            and _indent(line) == 0
            and index + 1 < len(lines)
            and _is_punct_run(lines[index + 1].strip())
            and _indent(lines[index + 1]) == 0
        ):
            headings.append(
                Heading(index, index + 2, _clean_heading(stripped), lines[index + 1].strip()[0])
            )
            index += 2
            continue
        index += 1
    return headings


def _assign_levels(headings: Sequence[Heading]) -> None:
    char_levels: dict[str, int] = {}
    for heading in headings:
        if heading.overline:
            heading.level = 0
        else:
            heading.level = char_levels.setdefault(heading.char, len(char_levels) + 1)


def split_sections(lines: Sequence[str]) -> tuple[str, list[str], list[Section]]:
    headings = find_headings(lines)
    _assign_levels(headings)
    if not headings:
        return "", list(lines), [Section(path=[])]

    document_title = ""
    if headings[0].overline:
        document_title = headings[0].title

    preamble = list(lines[: headings[0].start])
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []

    for position, heading in enumerate(headings):
        while stack and stack[-1][0] >= heading.level:
            stack.pop()
        parent = [title for _, title in stack]
        if heading.level == 0:
            path = [heading.title]
            stack.append((0, heading.title))
        else:
            path = ([document_title] if document_title and not parent else []) + parent + [heading.title]
            stack.append((heading.level, heading.title))
        end = headings[position + 1].start if position + 1 < len(headings) else len(lines)
        body = list(lines[heading.end : end])
        if body and body[0].strip() and _is_punct_run(body[0].strip()):
            body = body[1:]
        sections.append(Section(path=path, body=body))

    return document_title, preamble, sections


def _clean_inline(text: str) -> str:
    text = re.sub(r":([a-z][a-z0-9_-]*):`([^`]+)`", lambda m: m.group(2), text)
    text = re.sub(r"`([^`<]+?)\s*<([^>]+)>`_", r"\1 (\2)", text)
    text = re.sub(r"`([^`]+)`_", r"\1", text)
    text = re.sub(r"``([^`]+)``", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"\[[0-9A-Za-z#*._-]+\]_", "", text)
    text = re.sub(r"\|([^|]+)\|", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_prose(text: str) -> str:
    cleaned = _clean_inline(text)
    lines = [line for line in cleaned.splitlines() if line.strip()]
    structured = any(
        re.match(r"^\s*(?:[-*+]|\d+[.)]|#\.)\s+", line)
        or line.lstrip().startswith(("|", "+"))
        or _is_punct_run(line.strip())
        for line in lines
    )
    if structured:
        return "\n".join(lines).strip()
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _strip_code_options(code: str) -> str:
    lines = code.splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].lstrip()
        if not stripped or stripped.startswith(":"):
            index += 1
            continue
        break
    return "\n".join(lines[index:]).strip("\n")


_VERSION_LABELS = {
    "versionadded": "New in version",
    "versionchanged": "Changed in version",
    "deprecated": "Deprecated since version",
    "versionremoved": "Removed in version",
}


def _admonition_label(name: str, argument: str) -> str:
    if name in _VERSION_LABELS:
        label = _VERSION_LABELS[name]
        return f"{label} {argument}." if argument else f"{label}:"
    label = name.replace("-", " ").capitalize()
    return f"{label}: {argument}".strip() if argument else f"{label}:"


def parse_blocks(lines: Sequence[str], base_indent: int = 0) -> list[Segment]:
    segments: list[Segment] = []
    paragraph: list[str] = []
    index = 0

    def flush() -> None:
        if not paragraph:
            return
        text = _clean_prose("\n".join(paragraph))
        if text:
            segments.append(Segment("prose", text))
        paragraph.clear()

    while index < len(lines):
        raw = lines[index]
        if not raw.strip():
            flush()
            index += 1
            continue
        indent = _indent(raw)
        if indent < base_indent:
            break
        stripped = raw.strip()

        directive = _DIRECTIVE_RE.match(stripped)
        if directive:
            flush()
            name = directive.group(1).lower()
            argument = directive.group(2).strip()
            body, index = _collect_indented(lines, index + 1, indent)
            segments.extend(_handle_directive(name, argument, body))
            continue

        if stripped.startswith("..") and not stripped.startswith("::"):
            flush()
            _, index = _collect_indented(lines, index + 1, indent)
            continue

        if stripped.startswith(">>>"):
            flush()
            body, index = _collect_until_blank(lines, index)
            segments.append(Segment("code", "\n".join(body), "pycon"))
            continue

        if stripped.endswith("::") and not stripped.startswith(".."):
            flush()
            lead = stripped[:-2].rstrip()
            if lead:
                segments.append(Segment("prose", _clean_prose(lead)))
            body, index = _collect_indented(lines, index + 1, indent)
            code = _dedent(body)
            code_text = "\n".join(code).strip("\n")
            if code_text:
                segments.append(Segment("code", code_text, _guess_literal_language(code_text)))
            continue

        paragraph.append(stripped if indent == base_indent else raw[indent:])
        index += 1

    flush()
    return segments


def _handle_directive(name: str, argument: str, body: Sequence[str]) -> list[Segment]:
    if name in _CODE_DIRECTIVES:
        code = _strip_code_options("\n".join(_dedent(body)))
        if not code.strip():
            return []
        if name == "doctest":
            language = "pycon"
        elif argument:
            language = argument.split()[0].lower()
        else:
            language = _guess_literal_language(code)
        return [Segment("code", code, language)]

    if name in _SKIP_DIRECTIVES:
        return []

    if name in _ADMONITIONS:
        segments: list[Segment] = []
        label = _admonition_label(name, argument)
        if label:
            segments.append(Segment("prose", label))
        segments.extend(parse_blocks(_dedent(body), 0))
        return segments

    if name in _CONTAINER_DIRECTIVES:
        segments = []
        if name in {"tab", "tab-item"} and argument:
            segments.append(Segment("prose", f"{argument}:"))
        elif name == "admonition" and argument:
            segments.append(Segment("prose", f"{argument}:"))
        segments.extend(parse_blocks(_dedent(body), 0))
        return segments

    segments = []
    if argument:
        segments.append(Segment("prose", _clean_prose(f"{name.replace('-', ' ')}: {argument}")))
    segments.extend(parse_blocks(_dedent(body), 0))
    return segments


def resolve_includes(
    text: str, base_dir: Path, repo_root: Path, seen: Optional[set[Path]] = None, depth: int = 0
) -> str:
    if depth > 20:
        return text
    seen = seen if seen is not None else set()
    output: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^(\s*)\.\.\s+include::\s*(\S+)\s*$", line)
        if not match:
            output.append(line)
            continue
        indent = match.group(1)
        target = match.group(2)
        path = (repo_root / target.lstrip("/")) if target.startswith("/") else (base_dir / target)
        path = path.resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        included = path.read_text(encoding="utf-8", errors="replace")
        included = resolve_includes(included, path.parent, repo_root, seen, depth + 1)
        for included_line in included.splitlines():
            output.append(indent + included_line if included_line else "")
    return "\n".join(output)


# ---------------------------------------------------------------------------
# Record construction
# ---------------------------------------------------------------------------


def _code_tokens(text: str, language: Optional[str]) -> int:
    if (language or "").lower() in _PYTHON_LANGS:
        try:
            return provisional_token_count(text)
        except (tokenize.TokenError, SyntaxError, UnicodeError):
            return len(text.split())
    return len(text.split())


def _validate_python(code: str):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return validate_python(code)


def _guess_literal_language(code: str) -> str:
    if _validate_python(code).is_valid:
        return "python"
    return "text"


def _enrich_code(segment: Segment) -> dict[str, Any]:
    language = (segment.language or "").lower()
    entry: dict[str, Any] = {
        "language": language or "text",
        "code": segment.text,
        "token_count": _code_tokens(segment.text, language),
    }
    if language in _PYTHON_LANGS and language not in _DOCTEST_LANGS:
        validation = _validate_python(segment.text)
        entry["syntax_valid"] = validation.is_valid
        entry["error_type"] = validation.error_type
        entry["function_count"] = validation.function_count
        entry["class_count"] = validation.class_count
        entry["comment_ratio"] = validation.comment_ratio
    else:
        entry["syntax_valid"] = None
        entry["error_type"] = None
    return entry


def _render_content(section_path: Sequence[str], segments: Sequence[Segment], part: int, part_count: int) -> str:
    header = " > ".join(section_path) if section_path else "Document"
    if part_count > 1:
        header = f"{header} (part {part}/{part_count})"
    blocks = [f"## {header}"]
    for segment in segments:
        if segment.kind == "prose":
            blocks.append(segment.text)
        else:
            language = segment.language or "text"
            blocks.append(f"```{language}\n{segment.text}\n```")
    return "\n\n".join(blocks).strip()


def _split_oversized_segments(
    segments: Sequence[Segment], max_tokens: int
) -> tuple[list[Segment], list[dict[str, Any]]]:
    """Split oversized prose and quarantine oversized code segments.

    A single prose segment larger than the cap is split on word boundaries so
    no emitted record exceeds the cap.  A code segment cannot be split without
    changing the example, so it is removed and reported as a rejection.
    """
    prepared: list[Segment] = []
    rejected: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        tokens = (
            len(segment.text.split())
            if segment.kind == "prose"
            else _code_tokens(segment.text, segment.language)
        )
        if tokens <= max_tokens:
            prepared.append(segment)
            continue
        if segment.kind == "prose":
            words = segment.text.split()
            for start in range(0, len(words), max_tokens):
                prepared.append(Segment("prose", " ".join(words[start : start + max_tokens])))
            continue
        rejected.append(
            {
                "segment_index": index,
                "segment_type": segment.kind,
                "language": segment.language,
                "provisional_token_count": tokens,
                "reason": "oversized_code_segment",
            }
        )
    return prepared, rejected


def _split_segments(segments: Sequence[Segment], max_tokens: int) -> list[list[Segment]]:
    chunks: list[list[Segment]] = []
    current: list[Segment] = []
    current_tokens = 0
    for segment in segments:
        tokens = len(segment.text.split()) if segment.kind == "prose" else _code_tokens(segment.text, segment.language)
        if current and current_tokens + tokens > max_tokens:
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(segment)
        current_tokens += tokens
    if current:
        chunks.append(current)
    return chunks or [list(segments)]


def build_records(
    *,
    source: dict[str, Any],
    text: str,
    document_id: str,
    document_title: str,
    document_path: str,
    document_url: str,
    revision: str,
    min_total_tokens: int = MIN_TOTAL_TOKENS,
    min_prose_tokens: int = MIN_PROSE_TOKENS,
    max_tokens: int = MAX_TOKEN_LENGTH,
    license_info: Optional[dict[str, Any]] = None,
    acquisition_date: Optional[str] = None,
    rejected_out: Optional[list[dict[str, Any]]] = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    lines = text.expandtabs(4).splitlines()
    doc_title, preamble, sections = split_sections(lines)
    if not document_title:
        document_title = doc_title
    if not document_title and sections and sections[0].path:
        document_title = sections[0].path[-1]
    if not document_title:
        document_title = Path(document_path).stem.replace("-", " ").strip().title()

    if license_info is None:
        license_info = {
            "license": source["license"],
            "license_spdx": source["license_spdx"],
            "license_status": source.get("license_status", LICENSE_STATUS_CLEAR),
            "license_status_detail": source.get(
                "license_status_detail", LICENSE_APPROVED
            ),
            "license_evidence": source.get("license_evidence", ""),
        }
    acquisition_date = acquisition_date or utc_now_iso()

    stats = {
        "sections_seen": len(sections),
        "too_short": 0,
        "no_prose": 0,
        "duplicates": 0,
        "oversized_segments": 0,
        "retained": 0,
        "code_blocks": 0,
        "syntax_valid_code_blocks": 0,
        "syntax_invalid_code_blocks": 0,
        "prose_tokens": 0,
        "code_tokens": 0,
    }

    def reject(
        reason: str,
        *,
        section: Sequence[str],
        part: int = 0,
        part_count: int = 0,
        tokens: int = 0,
        segment: Optional[dict[str, Any]] = None,
    ) -> None:
        if rejected_out is None:
            return
        entry: dict[str, Any] = {
            "source": source["source_name"],
            "source_type": "raw",
            "document_id": document_id,
            "document_title": document_title,
            "document_path": document_path,
            "document_url": document_url,
            "section_path": list(section),
            "part": part,
            "part_count": part_count,
            "provisional_token_count": tokens,
            "reason": reason,
            "record_type": "section_or_chunk",
            "source_revision": revision,
            "acquisition_date": acquisition_date,
            "license_status": license_info["license_status"],
            "license_status_detail": license_info["license_status_detail"],
        }
        if segment is not None:
            entry.update(segment)
        rejected_out.append(entry)

    preamble_lines = []
    for line in preamble:
        if re.match(r"^\s*\.\.\s+_[^:]+:", line):
            continue
        header = re.match(r"^([A-Z][A-Za-z-]*):", line)
        if header and header.group(1) in _PEP_HEADER_FIELDS:
            continue
        preamble_lines.append(line)
    if preamble_lines and any(line.strip() for line in preamble_lines):
        sections.insert(0, Section(path=["Preamble"], body=preamble_lines))

    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for ordinal, section in enumerate(sections):
        if section.path and section.path[-1].strip().lower() == "copyright":
            continue
        segments = [s for s in parse_blocks(section.body, 0) if s.text.strip()]
        if not segments:
            continue
        prose_text = "\n\n".join(s.text for s in segments if s.kind == "prose")
        prose_tokens = len(prose_text.split())
        code_segments = [s for s in segments if s.kind == "code"]
        code_tokens = sum(_code_tokens(s.text, s.language) for s in code_segments)
        total_tokens = prose_tokens + code_tokens

        if prose_tokens < min_prose_tokens:
            stats["no_prose"] += 1
            reject("no_prose", section=section.path, tokens=total_tokens)
            continue
        if total_tokens < min_total_tokens:
            stats["too_short"] += 1
            reject("too_short", section=section.path, tokens=total_tokens)
            continue

        segments, oversized = _split_oversized_segments(segments, max_tokens)
        for item in oversized:
            stats["oversized_segments"] += 1
            reject(
                "oversized_code_segment",
                section=section.path,
                tokens=item["provisional_token_count"],
                segment=item,
            )
        if not segments:
            continue

        chunks = _split_segments(segments, max_tokens)
        for part_index, chunk in enumerate(chunks, start=1):
            chunk_prose = "\n\n".join(s.text for s in chunk if s.kind == "prose")
            chunk_code = [s for s in chunk if s.kind == "code"]
            chunk_prose_tokens = len(chunk_prose.split())
            chunk_code_tokens = sum(_code_tokens(s.text, s.language) for s in chunk_code)
            chunk_tokens = chunk_prose_tokens + chunk_code_tokens
            if chunk_prose_tokens == 0:
                stats["no_prose"] += 1
                reject(
                    "no_prose_chunk",
                    section=section.path,
                    part=part_index,
                    part_count=len(chunks),
                    tokens=chunk_tokens,
                )
                continue
            content = _render_content(section.path, chunk, part_index, len(chunks))
            content_hash = exact_hash(content)
            if content_hash in seen:
                stats["duplicates"] += 1
                reject(
                    "duplicate",
                    section=section.path,
                    part=part_index,
                    part_count=len(chunks),
                    tokens=chunk_tokens,
                )
                continue
            seen.add(content_hash)

            code_blocks = [_enrich_code(segment) for segment in chunk_code]
            for block in code_blocks:
                stats["code_blocks"] += 1
                if block.get("syntax_valid") is True:
                    stats["syntax_valid_code_blocks"] += 1
                elif block.get("syntax_valid") is False:
                    stats["syntax_invalid_code_blocks"] += 1

            record_id = (
                f"{source['source_name']}:{document_id}:{ordinal}:"
                f"{part_index}:{content_hash[:8]}"
            )
            records.append(
                {
                    "id": record_id,
                    "record_id": record_id,
                    "source": source["source_name"],
                    "source_type": "raw",
                    "source_url": document_url,
                    "source_family": source["source_family"],
                    "stage": STAGE,
                    "document_id": document_id,
                    "document_title": document_title,
                    "document_path": document_path,
                    "document_url": document_url,
                    "section_path": list(section.path),
                    "section_title": section.path[-1] if section.path else document_title,
                    "part": part_index,
                    "part_count": len(chunks),
                    "segments": [
                        {
                            "type": segment.kind,
                            "text": segment.text,
                            **({"language": segment.language} if segment.kind == "code" else {}),
                        }
                        for segment in chunk
                    ],
                    "content": content,
                    "prose": chunk_prose,
                    "code_blocks": code_blocks,
                    "prose_token_count": chunk_prose_tokens,
                    "code_token_count": chunk_code_tokens,
                    "provisional_token_count": chunk_tokens,
                    "token_count": chunk_tokens,
                    "token_count_status": "PROVISIONAL",
                    "token_count_method": TOKEN_COUNT_METHOD,
                    "has_code": bool(code_blocks),
                    "code_block_count": len(code_blocks),
                    "source_revision": revision,
                    "source_version": revision,
                    "acquisition_date": acquisition_date,
                    "license": license_info["license"],
                    "license_spdx": license_info["license_spdx"],
                    "license_url": source["license_url"],
                    "license_status": license_info["license_status"],
                    "license_status_detail": license_info["license_status_detail"],
                    "license_evidence": license_info["license_evidence"],
                    "provenance": {
                        "repository": source.get("repo_url"),
                        "commit": revision,
                        "path": document_path,
                        "section": list(section.path),
                        "part": part_index,
                    },
                    "validator_version": VALIDATOR_VERSION,
                    "retrieved_at": utc_now_iso(),
                    "kg_validation_status": KG_PENDING,
                    "exact_hash": content_hash,
                    "content_hash": content_hash,
                    "schema_version": SCHEMA_VERSION,
                    "pipeline_version": PIPELINE_VERSION,
                }
            )
            stats["retained"] += 1
            stats["prose_tokens"] += chunk_prose_tokens
            stats["code_tokens"] += chunk_code_tokens

    return records, stats


# ---------------------------------------------------------------------------
# Acquisition (official repos, pinned by commit, refuse-overwrite)
# ---------------------------------------------------------------------------


def _git(*args: str, cwd: Optional[Path] = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def acquire_repo(source: dict[str, Any], raw_root: Path) -> tuple[Path, str]:
    source_root = raw_root / source["raw_subdir"]
    repo_path = source_root / "repo"
    manifest_path = source_root / "ACQUISITION_MANIFEST.json"

    if repo_path.exists():
        revision = _git("rev-parse", "HEAD", cwd=repo_path)
        if not manifest_path.exists():
            raise RuntimeError(
                f"existing clone {repo_path} has no acquisition manifest; "
                "refusing to process it without a pinned commit"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = manifest.get("commit")
        if not expected:
            raise RuntimeError(
                f"acquisition manifest {manifest_path} has no commit; "
                "refusing to process an unpinned clone"
            )
        if expected != revision:
            raise RuntimeError(
                f"clone drift for {source['source_name']}: HEAD {revision} "
                f"does not match manifest commit {expected}"
            )
        return repo_path, revision

    source_root.mkdir(parents=True, exist_ok=True)
    _git("clone", "--depth", "1", "--branch", source["ref"], source["repo_url"], str(repo_path))
    revision = _git("rev-parse", "HEAD", cwd=repo_path)

    if not manifest_path.exists():
        manifest = {
            "manifest_version": "1",
            "acquired_at": utc_now_iso(),
            "source_name": source["source_name"],
            "project": source["project"],
            "source_family": source["source_family"],
            "decision": source["decision"],
            "repo_url": source["repo_url"],
            "ref": source["ref"],
            "commit": revision,
            "license": source["license"],
            "license_spdx": source["license_spdx"],
            "license_url": source["license_url"],
            "license_evidence": source["license_evidence"],
            "license_file": None,
            "pipeline_version": PIPELINE_VERSION,
        }
        license_path = repo_path / "LICENSE"
        if license_path.is_file():
            manifest["license_file"] = {
                "path": "LICENSE",
                "sha256": _sha256_file(license_path),
            }
        _write_json(manifest_path, manifest)
    return repo_path, revision


def discover_documents(repo_path: Path, source: dict[str, Any]) -> list[Path]:
    pattern = source["document_glob"]
    relative_pattern = pattern[len("repo/") :] if pattern.startswith("repo/") else pattern
    documents = sorted(repo_path.glob(relative_pattern))
    excluded = []
    for glob in source.get("exclude_globs", []):
        relative = glob[len("repo/") :] if glob.startswith("repo/") else glob
        excluded.extend(repo_path.glob(relative))
    excluded_set = set(excluded)
    return [path for path in documents if path.is_file() and path not in excluded_set]


def _document_identity(source: dict[str, Any], repo_path: Path, path: Path) -> tuple[str, str]:
    relative = path.relative_to(repo_path).as_posix()
    if source["source_name"] == "peps":
        document_id = path.stem
        url = f"https://peps.python.org/{document_id}/"
    else:
        document_id = relative[:-4] if relative.endswith(".rst") else relative
        url_path = "" if document_id == "index" else document_id + "/"
        url = f"https://devguide.python.org/{url_path}"
    return relative, url


def _document_id(source: dict[str, Any], path: Path, relative: str) -> str:
    if source["source_name"] == "peps":
        return path.stem
    return relative[:-4] if relative.endswith(".rst") else relative


def _source_license_info(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "license": source["license"],
        "license_spdx": source["license_spdx"],
        "license_status": source.get("license_status", LICENSE_STATUS_CLEAR),
        "license_status_detail": source.get("license_status_detail", LICENSE_APPROVED),
        "license_evidence": source.get("license_evidence", ""),
    }


def process_source(
    source: dict[str, Any],
    repo_path: Path,
    revision: str,
    *,
    output_path: Path,
    acquisition_date: Optional[str] = None,
    min_total_tokens: int = MIN_TOTAL_TOKENS,
    min_prose_tokens: int = MIN_PROSE_TOKENS,
    max_tokens: int = MAX_TOKEN_LENGTH,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stats: dict[str, Any] = {
        "documents_examined": 0,
        "documents_with_records": 0,
        "documents_license_rejected": 0,
        "sections_seen": 0,
        "sections_license_rejected": 0,
        "too_short": 0,
        "no_prose": 0,
        "duplicates": 0,
        "oversized_segments": 0,
        "retained": 0,
        "code_blocks": 0,
        "syntax_valid_code_blocks": 0,
        "syntax_invalid_code_blocks": 0,
        "prose_tokens": 0,
        "code_tokens": 0,
        "license_rejected_records": 0,
        "license_rejected_tokens": 0,
        "rejected_records": 0,
    }
    records: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    acquisition_date = acquisition_date or utc_now_iso()

    for path in discover_documents(repo_path, source):
        stats["documents_examined"] += 1
        relative, url = _document_identity(source, repo_path, path)
        text = resolve_includes(
            path.read_text(encoding="utf-8", errors="replace"), path.parent, repo_path
        )
        document_id = _document_id(source, path, relative)
        document_title = ""
        if source["source_name"] == "peps":
            header_title = re.search(r"^Title:\s*(.+)$", text, re.MULTILINE)
            if header_title:
                document_title = header_title.group(1).strip()
        license_info = (
            classify_pep_license(text)
            if source["source_name"] == "peps"
            else _source_license_info(source)
        )
        approved = license_info["license_status"] == LICENSE_STATUS_CLEAR
        document_records, document_stats = build_records(
            source=source,
            text=text,
            document_id=document_id,
            document_title=document_title,
            document_path=relative,
            document_url=url,
            revision=revision,
            min_total_tokens=min_total_tokens,
            min_prose_tokens=min_prose_tokens,
            max_tokens=max_tokens,
            license_info=license_info,
            acquisition_date=acquisition_date,
            rejected_out=rejected if approved else None,
        )

        if not approved:
            stats["documents_license_rejected"] += 1
            stats["sections_license_rejected"] += document_stats.get("sections_seen", 0)
            stats["license_rejected_records"] += len(document_records)
            stats["license_rejected_tokens"] += sum(
                record["provisional_token_count"] for record in document_records
            )
            for record in document_records:
                rejected.append(
                    {
                        "source": source["source_name"],
                        "source_type": "raw",
                        "document_id": document_id,
                        "document_title": record["document_title"],
                        "document_path": relative,
                        "document_url": url,
                        "section_path": record["section_path"],
                        "part": record["part"],
                        "part_count": record["part_count"],
                        "provisional_token_count": record["provisional_token_count"],
                        "reason": "license_not_approved",
                        "record_type": "candidate_record",
                        "would_be_record_id": record["id"],
                        "source_revision": revision,
                        "acquisition_date": acquisition_date,
                        "license": license_info["license"],
                        "license_spdx": license_info["license_spdx"],
                        "license_status": license_info["license_status"],
                        "license_status_detail": license_info["license_status_detail"],
                        "license_evidence": license_info["license_evidence"],
                    }
                )
            continue

        for key in (
            "sections_seen", "too_short", "no_prose", "duplicates", "retained",
            "code_blocks", "syntax_valid_code_blocks", "syntax_invalid_code_blocks",
            "prose_tokens", "code_tokens", "oversized_segments",
        ):
            stats[key] += document_stats.get(key, 0)
        if document_records:
            stats["documents_with_records"] += 1
        records.extend(document_records)

    rejected_path = output_path.with_name(output_path.stem + "_rejected.jsonl")
    _write_jsonl(output_path, records)
    _write_jsonl(rejected_path, rejected)
    stats["rejected_records"] = len(rejected)
    stats["rejected_path"] = str(rejected_path)
    return records, stats


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _make_run_id(source_names: Sequence[str]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    joined = "-".join(sorted(source_names))
    return f"prose-{stamp}-{hashlib.sha256(joined.encode()).hexdigest()[:8]}"


def process(
    *,
    sources: Sequence[dict[str, Any]],
    raw_root: Path = RAW_DIR,
    stage1_root: Path = STAGE1_DIR,
    run_id: Optional[str] = None,
    dry_run: bool = False,
    min_total_tokens: int = MIN_TOTAL_TOKENS,
    min_prose_tokens: int = MIN_PROSE_TOKENS,
    max_tokens: int = MAX_TOKEN_LENGTH,
) -> dict[str, Any]:
    computed_run_id = run_id or _make_run_id([s["source_name"] for s in sources])
    per_source: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = []
    total_records = 0
    report_dir = raw_root / "prose_docs" / "reports" / computed_run_id

    for source in sources:
        if source["decision"] != "ACCEPT":
            raise ValueError(f"source {source['source_name']} is not ACCEPT")

    if not dry_run:
        if report_dir.exists():
            raise FileExistsError(f"refusing to overwrite existing report dir: {report_dir}")
        stage1_root.mkdir(parents=True, exist_ok=True)
        for source in sources:
            output_path = stage1_root / f"prose_docs_{computed_run_id}_{source['source_name']}.jsonl"
            rejected_path = output_path.with_name(output_path.stem + "_rejected.jsonl")
            for path in (output_path, rejected_path):
                if path.exists():
                    raise FileExistsError(f"refusing to overwrite existing artifact: {path}")

    with tempfile.TemporaryDirectory() as temp_dir:
        for source in sources:
            source_root = raw_root / source["raw_subdir"]
            repo_path = source_root / "repo"
            if dry_run and not repo_path.exists():
                per_source.append(
                    {
                        "source_name": source["source_name"],
                        "status": "would_clone",
                        "documents_examined": 0,
                        "stats": {},
                    }
                )
                continue
            repo_path, revision = acquire_repo(source, raw_root)
            manifest_path = source_root / "ACQUISITION_MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            license_path = repo_path / "LICENSE"
            license_file_sha256 = None
            if license_path.is_file():
                license_file_sha256 = _sha256_file(license_path)
                manifest["license_file_sha256"] = license_file_sha256
            manifests.append(manifest)
            acquisition_date = manifest.get("acquired_at") or utc_now_iso()
            if dry_run:
                output_path = Path(temp_dir) / f"prose_docs_{source['source_name']}.jsonl"
            else:
                output_path = stage1_root / f"prose_docs_{computed_run_id}_{source['source_name']}.jsonl"
            records, stats = process_source(
                source,
                repo_path,
                revision,
                output_path=output_path,
                acquisition_date=acquisition_date,
                min_total_tokens=min_total_tokens,
                min_prose_tokens=min_prose_tokens,
                max_tokens=max_tokens,
            )
            total_records += len(records)
            per_source.append(
                {
                    "source_name": source["source_name"],
                    "documentation_version": source["documentation_version"],
                    "source_revision": revision,
                    "license_spdx": source["license_spdx"],
                    "license_file_sha256": license_file_sha256,
                    "acquisition_date": acquisition_date,
                    "output_path": str(output_path),
                    "rejected_path": stats.get("rejected_path"),
                    "stats": stats,
                }
            )

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
                "source_family": s["source_family"],
            }
            for s in sources
        ],
        "per_source": per_source,
        "counts": {
            "sources_processed": len(per_source),
            "total_retained": total_records,
            "total_rejected": sum(
                source["stats"].get("rejected_records", 0) for source in per_source
            ),
            "total_license_rejected": sum(
                source["stats"].get("license_rejected_records", 0)
                for source in per_source
            ),
            "total_candidate_records": total_records
            + sum(
                source["stats"].get("license_rejected_records", 0)
                for source in per_source
            ),
        },
    }
    if dry_run:
        return report

    stage1_root.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=False)
    _write_json(report_dir / "report.json", report)
    _write_json(report_dir / "source_inventory.json", {"run_id": computed_run_id, "sources": list(SOURCE_INVENTORY)})
    _write_json(report_dir / "acquisition_manifests.json", manifests)
    report["report_dir"] = str(report_dir)
    return report


# ---------------------------------------------------------------------------
# Writers
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
    parser.add_argument("--raw-root", default=str(RAW_DIR))
    parser.add_argument("--stage1-root", default=str(STAGE1_DIR))
    parser.add_argument("--min-total-tokens", type=int, default=MIN_TOTAL_TOKENS)
    parser.add_argument("--min-prose-tokens", type=int, default=MIN_PROSE_TOKENS)
    parser.add_argument("--max-tokens", type=int, default=MAX_TOKEN_LENGTH)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    sources = APPROVED_SOURCES
    if args.sources is not None:
        by_name = {s["source_name"]: s for s in APPROVED_SOURCES}
        missing = [name for name in args.sources if name not in by_name]
        if missing:
            print(f"ERROR: unknown or unapproved sources: {', '.join(missing)}", file=sys.stderr)
            return 2
        sources = [by_name[name] for name in args.sources]
    try:
        report = process(
            sources=sources,
            raw_root=Path(args.raw_root),
            stage1_root=Path(args.stage1_root),
            run_id=args.run_id,
            dry_run=args.dry_run,
            min_total_tokens=args.min_total_tokens,
            min_prose_tokens=args.min_prose_tokens,
            max_tokens=args.max_tokens,
        )
    except (FileExistsError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(f"RUN_ID={report['run_id']}")
        print(f"RETAINED={report['counts']['total_retained']}")
        print(f"REPORT_DIR={report.get('report_dir', '')}")
        for entry in report["per_source"]:
            print(
                f"{entry['source_name']}: documents={entry['stats'].get('documents_examined', 0)} "
                f"records={entry['stats'].get('retained', 0)}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
