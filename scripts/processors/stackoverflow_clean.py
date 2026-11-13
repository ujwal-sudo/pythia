"""Safe Stack Overflow Hugging Face JSONL cleaning processor.

This module is intentionally independent of the legacy ``scripts/prepare_so.py``
pipeline.  It reads explicit source files, never writes to them, and produces a
versioned cleaned corpus plus auditable manifests in a new run directory.

The processor is loss-minimizing: structurally valid records are retained even
when their score is low, their text is long, or their HTML is unusual.  License
status is deliberately not resolved here; every record remains marked
``LICENSE_REVIEW_REQUIRED``.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from bs4 import BeautifulSoup, Comment, Doctype, NavigableString, ProcessingInstruction


PROCESSOR_VERSION = "1.0.0"
SCHEMA_VERSION = "stackoverflow.clean.v1"
TRANSFORMATION_VERSION = "html_to_text_v1"
LICENSE_STATUS = "LICENSE_REVIEW_REQUIRED"
PARSER_NAME = "html.parser"
EXPECTED_SOURCE = "huggingface"
EXPECTED_DATASET = "koutch/stackoverflow_python"

PRODUCTION_BASELINE: Dict[str, Dict[str, Any]] = {
    "so_huggingface_pilot.jsonl": {
        "records": 1000,
        "bytes": 1897038,
        "sha256": "cc5ab6531914d03d7c73b46bbf0f6a45f39808a386dd2a1672dd06b21d6e3a21",
    },
    "so_huggingface_scaleup.jsonl": {
        "records": 10000,
        "bytes": 21797662,
        "sha256": "d28741a4f641093081a161a24b64a4b131ce8c1eb8a96604847e1410ec53a636",
    },
}

REQUIRED_FIELDS = (
    "source",
    "dataset_name",
    "question_instruction",
    "answer",
    "question_title",
    "score",
    "tags",
    "has_code",
    "char_count",
    "collected_at",
    "question_id",
    "answer_id",
    "question_date",
    "answer_date",
)

STRING_FIELDS = (
    "source",
    "dataset_name",
    "question_instruction",
    "answer",
    "question_title",
    "tags",
    "collected_at",
    "question_date",
    "answer_date",
)

INTEGER_FIELDS = ("score", "question_id", "answer_id", "char_count")

BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "details", "dialog", "div",
    "dl", "dt", "dd", "fieldset", "figcaption", "figure", "footer", "form",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "li", "main",
    "nav", "ol", "p", "pre", "section", "summary", "table", "tbody", "td",
    "tfoot", "th", "thead", "tr", "ul",
}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
SKIP_TAGS = {"script", "style", "noscript", "template"}
KNOWN_INLINE_TAGS = {
    "a", "abbr", "b", "bdi", "bdo", "big", "br", "cite", "code", "data",
    "del", "dfn", "em", "font", "i", "img", "ins", "kbd", "label", "mark",
    "q", "s", "samp", "small", "span", "strike", "strong", "sub", "sup",
    "time", "tt", "u", "var", "wbr",
}
IMAGE_ALT_PLACEHOLDERS = {
    "",
    "image",
    "img",
    "picture",
    "screenshot",
    "enter image description here",
}


class PreflightError(RuntimeError):
    """Raised when the source set cannot be processed safely."""


class OutputValidationError(RuntimeError):
    """Raised when a generated record or output file fails validation."""


@dataclass
class TransformStats:
    documents: int = 0
    paragraphs: int = 0
    headings: int = 0
    lists: int = 0
    list_items: int = 0
    inline_code: int = 0
    code_blocks: int = 0
    empty_code_blocks: int = 0
    links: int = 0
    images: int = 0
    images_with_useful_alt: int = 0
    images_without_useful_alt: int = 0
    blockquotes: int = 0
    line_breaks: int = 0
    unknown_tags: int = 0
    skipped_script_style: int = 0

    def to_dict(self) -> Dict[str, int]:
        return asdict(self)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def normalize_text_for_hash(text: str) -> str:
    text = normalize_newlines(text)
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    collapsed: List[str] = []
    previous_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and previous_blank:
            continue
        collapsed.append(line)
        previous_blank = is_blank
    return "\n".join(collapsed)


def normalized_qa_text(question_title: str, question_instruction: str, answer: str) -> str:
    parts = [
        normalize_text_for_hash(question_title),
        normalize_text_for_hash(question_instruction),
        normalize_text_for_hash(answer),
    ]
    return "\n\n".join(parts)


def parse_tags(raw: Any) -> List[str]:
    if not isinstance(raw, str):
        raise ValueError("tags is not a string")
    try:
        parsed = ast.literal_eval(raw)
    except (ValueError, SyntaxError) as exc:
        raise ValueError(f"tags is not a safe Python literal: {exc}") from exc
    if not isinstance(parsed, list):
        raise ValueError(f"tags literal is {type(parsed).__name__}, expected list")
    if not parsed:
        raise ValueError("tags list is empty")
    if not all(isinstance(item, str) for item in parsed):
        raise ValueError("tags list contains a non-string item")
    return list(parsed)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_blank(value: str) -> bool:
    return not value.strip()


def validate_source_record(record: Any, line_number: int) -> List[str]:
    errors: List[str] = []
    if not isinstance(record, dict):
        return [f"line {line_number}: parsed value is {type(record).__name__}, expected object"]

    for field_name in REQUIRED_FIELDS:
        if field_name not in record:
            errors.append(f"line {line_number}: missing required field {field_name!r}")

    for field_name in STRING_FIELDS:
        if field_name in record and not isinstance(record[field_name], str):
            errors.append(
                f"line {line_number}: field {field_name!r} is "
                f"{type(record[field_name]).__name__}, expected str"
            )

    for field_name in INTEGER_FIELDS:
        if field_name in record and not _is_int(record[field_name]):
            errors.append(
                f"line {line_number}: field {field_name!r} is "
                f"{type(record[field_name]).__name__}, expected int"
            )

    if "has_code" in record and not isinstance(record["has_code"], bool):
        errors.append(
            f"line {line_number}: field 'has_code' is "
            f"{type(record['has_code']).__name__}, expected bool"
        )

    for field_name in ("question_instruction", "answer"):
        value = record.get(field_name)
        if isinstance(value, str) and _is_blank(value):
            errors.append(f"line {line_number}: field {field_name!r} is blank")

    for field_name in ("question_id", "answer_id"):
        value = record.get(field_name)
        if _is_int(value) and value <= 0:
            errors.append(f"line {line_number}: field {field_name!r} must be positive")

    if "tags" in record:
        try:
            parse_tags(record["tags"])
        except ValueError as exc:
            errors.append(f"line {line_number}: {exc}")

    return errors


def read_jsonl_source(path: Path) -> Tuple[List[Tuple[int, Dict[str, Any]]], Dict[str, Any]]:
    if not path.is_file():
        raise PreflightError(f"input file does not exist: {path}")
    if not os.access(path, os.R_OK):
        raise PreflightError(f"input file is not readable: {path}")

    records: List[Tuple[int, Dict[str, Any]]] = []
    blank_lines = 0
    parse_errors: List[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip() == "":
                blank_lines += 1
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                parse_errors.append(f"line {line_number}: invalid JSON: {exc.msg}")
                continue
            if not isinstance(parsed, dict):
                parse_errors.append(
                    f"line {line_number}: parsed value is {type(parsed).__name__}, expected object"
                )
                continue
            records.append((line_number, parsed))

    if parse_errors:
        preview = "; ".join(parse_errors[:10])
        suffix = "" if len(parse_errors) <= 10 else f"; ... ({len(parse_errors)} total)"
        raise PreflightError(f"{path.name}: malformed JSONL input: {preview}{suffix}")

    info = {
        "path": str(path),
        "filename": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "records": len(records),
        "blank_lines": blank_lines,
    }
    return records, info


def _check_mount_root(require_mount_root: Path, input_paths: Sequence[Path], output_root: Optional[Path]) -> None:
    if not require_mount_root.is_dir():
        raise PreflightError(f"required mount root is not a readable directory: {require_mount_root}")
    if not os.access(require_mount_root, os.R_OK):
        raise PreflightError(f"required mount root is not readable: {require_mount_root}")
    root = require_mount_root.resolve()
    for path in input_paths:
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise PreflightError(f"input path is outside required mount root {root}: {path}") from exc
    if output_root is not None:
        try:
            output_root.resolve().relative_to(root)
        except ValueError as exc:
            raise PreflightError(f"output root is outside required mount root {root}: {output_root}") from exc


def preflight(
    input_paths: Sequence[Path],
    expected_baseline: Optional[Dict[str, Dict[str, Any]]] = None,
    require_mount_root: Optional[Path] = None,
    output_root: Optional[Path] = None,
) -> Tuple[List[Tuple[int, Dict[str, Any], Path]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not input_paths:
        raise PreflightError("at least one input path is required")
    if require_mount_root is not None:
        _check_mount_root(require_mount_root, input_paths, output_root)

    loaded: List[Tuple[int, Dict[str, Any], Path]] = []
    source_infos: List[Dict[str, Any]] = []
    validation_errors: List[Dict[str, Any]] = []

    for path in input_paths:
        records, info = read_jsonl_source(path)
        source_infos.append(info)
        for line_number, record in records:
            errors = validate_source_record(record, line_number)
            if errors:
                validation_errors.append(
                    {
                        "source_file": path.name,
                        "line": line_number,
                        "answer_id": record.get("answer_id"),
                        "errors": errors,
                    }
                )
            loaded.append((line_number, record, path))

    if expected_baseline is not None:
        for info in source_infos:
            expected = expected_baseline.get(info["filename"])
            if expected is None:
                raise PreflightError(
                    f"no expected baseline entry for input file {info['filename']!r}; "
                    "use --no-baseline-check only if this is intentional"
                )
            mismatches: List[str] = []
            if info["bytes"] != expected.get("bytes"):
                mismatches.append(f"bytes {info['bytes']} != expected {expected.get('bytes')}")
            if info["sha256"] != expected.get("sha256"):
                mismatches.append(f"sha256 {info['sha256']} != expected {expected.get('sha256')}")
            if info["records"] != expected.get("records"):
                mismatches.append(f"records {info['records']} != expected {expected.get('records')}")
            if mismatches:
                raise PreflightError(
                    f"baseline mismatch for {info['filename']}: " + "; ".join(mismatches)
                )
            info["baseline_verified"] = True

    return loaded, source_infos, validation_errors


class HtmlToText:
    def __init__(self, stats: Optional[TransformStats] = None) -> None:
        self.stats = stats if stats is not None else TransformStats()

    def convert(self, markup: str) -> str:
        self.stats.documents += 1
        if not isinstance(markup, str) or not markup.strip():
            return ""
        soup = BeautifulSoup(markup, PARSER_NAME)
        for code_node in list(soup.find_all("code")):
            if code_node.find("pre") is not None:
                code_node.unwrap()
        text = self._render_blocks(soup)
        return text.strip("\n")

    def _render_blocks(self, node: Any) -> str:
        parts: List[str] = []
        inline_buffer: List[str] = []

        def flush_inline() -> None:
            if not inline_buffer:
                return
            text = "".join(inline_buffer).strip()
            inline_buffer.clear()
            if text:
                parts.append(text)

        for child in node.children:
            if isinstance(child, (Comment, Doctype, ProcessingInstruction)):
                continue
            if isinstance(child, NavigableString):
                inline_buffer.append(self._normal_text(str(child)))
                continue
            name = (child.name or "").lower()
            if name in SKIP_TAGS:
                self.stats.skipped_script_style += 1
                continue
            if name in BLOCK_TAGS:
                flush_inline()
                block = self._render_block(child)
                if block:
                    parts.append(block)
            else:
                inline_buffer.append(self._render_inline(child))
        flush_inline()
        return "\n\n".join(parts)

    def _render_block(self, node: Any) -> str:
        name = (node.name or "").lower()
        if name in SKIP_TAGS:
            self.stats.skipped_script_style += 1
            return ""
        if name == "pre":
            return self._render_pre(node)
        if name == "hr":
            return "---"
        if name in HEADING_TAGS:
            self.stats.headings += 1
            level = int(name[1])
            return ("#" * level) + " " + self._inline_children(node).strip()
        if name in ("ul", "ol"):
            return self._render_list(node)
        if name == "blockquote":
            self.stats.blockquotes += 1
            inner = self._render_blocks(node)
            if not inner:
                return ""
            return "\n".join(("> " + line) if line else ">" for line in inner.split("\n"))
        if name == "p":
            self.stats.paragraphs += 1
            if any(
                not isinstance(child, NavigableString)
                and (child.name or "").lower() in BLOCK_TAGS
                for child in node.children
            ):
                return self._render_blocks(node)
            return self._inline_children(node).strip()
        if name in ("dt", "dd", "figcaption", "summary", "th", "td"):
            return self._inline_children(node).strip()
        if name in ("table", "thead", "tbody", "tfoot", "tr", "dl"):
            return self._render_blocks(node)
        if name in BLOCK_TAGS:
            return self._render_blocks(node)
        return self._render_inline(node)

    def _render_list(self, node: Any) -> str:
        self.stats.lists += 1
        ordered = (node.name or "").lower() == "ol"
        lines: List[str] = []
        index = 1
        for item in node.find_all("li", recursive=False):
            self.stats.list_items += 1
            marker = f"{index}. " if ordered else "- "
            content_parts: List[str] = []
            nested_lists: List[str] = []
            for child in item.children:
                if isinstance(child, (Comment, Doctype, ProcessingInstruction)):
                    continue
                if isinstance(child, NavigableString):
                    content_parts.append(self._normal_text(str(child)))
                    continue
                child_name = (child.name or "").lower()
                if child_name in ("ul", "ol"):
                    nested_lists.append(self._render_list(child))
                elif child_name in SKIP_TAGS:
                    self.stats.skipped_script_style += 1
                elif child_name in BLOCK_TAGS:
                    content_parts.append(self._render_block(child))
                else:
                    content_parts.append(self._render_inline(child))
            content = "\n\n".join(part.strip() for part in content_parts if part.strip())
            content_lines = content.split("\n") if content else [""]
            item_lines = [marker + content_lines[0]]
            continuation = " " * len(marker)
            fence_length: Optional[int] = None
            for line in content_lines[1:]:
                stripped = line.strip()
                if fence_length is None:
                    fence_match = re.fullmatch(r"`{3,}", stripped)
                    if fence_match:
                        fence_length = len(stripped)
                        item_lines.append(line)
                        continue
                    item_lines.append(continuation + line if line else "")
                else:
                    item_lines.append(line)
                    if re.fullmatch(r"`{%d,}" % fence_length, stripped):
                        fence_length = None
            for nested in nested_lists:
                for line in nested.split("\n"):
                    item_lines.append(("  " + line) if line else "")
            while item_lines and item_lines[-1] == "":
                item_lines.pop()
            lines.append("\n".join(item_lines))
            index += 1
        return "\n".join(lines)

    def _render_pre(self, node: Any) -> str:
        self.stats.code_blocks += 1
        content = normalize_newlines(self._raw_text(node)).strip("\n")
        if not content.strip():
            self.stats.empty_code_blocks += 1
            return ""
        longest_run = 0
        for match in re.finditer(r"`+", content):
            longest_run = max(longest_run, len(match.group(0)))
        fence = "`" * max(3, longest_run + 1)
        return f"{fence}\n{content}\n{fence}"

    def _raw_text(self, node: Any) -> str:
        chunks: List[str] = []
        for child in node.children:
            if isinstance(child, (Comment, Doctype, ProcessingInstruction)):
                continue
            if isinstance(child, NavigableString):
                chunks.append(str(child))
                continue
            name = (child.name or "").lower()
            if name in SKIP_TAGS:
                self.stats.skipped_script_style += 1
                continue
            if name == "br":
                chunks.append("\n")
                continue
            chunks.append(self._raw_text(child))
        return "".join(chunks)

    def _render_inline(self, node: Any) -> str:
        if isinstance(node, (Comment, Doctype, ProcessingInstruction)):
            return ""
        if isinstance(node, NavigableString):
            return self._normal_text(str(node))
        name = (node.name or "").lower()
        if name in SKIP_TAGS:
            self.stats.skipped_script_style += 1
            return ""
        if name == "br":
            self.stats.line_breaks += 1
            return "\n"
        if name == "code":
            self.stats.inline_code += 1
            return self._inline_code(normalize_newlines(self._raw_text(node)))
        if name == "a":
            self.stats.links += 1
            href = (node.get("href") or "").strip()
            text = self._inline_children(node).strip()
            if not text:
                text = href
            if href and text != href:
                return f"[{text}]({href})"
            return text or href
        if name == "img":
            self.stats.images += 1
            alt = (node.get("alt") or "").strip()
            if not alt:
                alt = (node.get("title") or "").strip()
            alt = re.sub(r"\s+", " ", alt).strip()
            if alt.lower() in IMAGE_ALT_PLACEHOLDERS or "enter image description" in alt.lower():
                self.stats.images_without_useful_alt += 1
                return "[image]"
            self.stats.images_with_useful_alt += 1
            return f"[image: {alt}]"
        if name in BLOCK_TAGS:
            return self._render_block(node)
        if name not in KNOWN_INLINE_TAGS:
            self.stats.unknown_tags += 1
        return self._inline_children(node)

    def _inline_children(self, node: Any) -> str:
        chunks: List[str] = []
        for child in node.children:
            if isinstance(child, (Comment, Doctype, ProcessingInstruction)):
                continue
            if isinstance(child, NavigableString):
                chunks.append(self._normal_text(str(child)))
            else:
                chunks.append(self._render_inline(child))
        return "".join(chunks)

    @staticmethod
    def _normal_text(text: str) -> str:
        text = re.sub(r"\s+", " ", text)
        return text.replace("`", r"\`")

    @staticmethod
    def _inline_code(content: str) -> str:
        if content == "":
            return ""
        longest_run = 0
        for match in re.finditer(r"`+", content):
            longest_run = max(longest_run, len(match.group(0)))
        delimiter = "`" * (longest_run + 1)
        needs_padding = (
            content.startswith("`")
            or content.endswith("`")
            or content.startswith(" ")
            or content.endswith(" ")
        )
        if needs_padding:
            return f"{delimiter} {content} {delimiter}"
        return f"{delimiter}{content}{delimiter}"


def clean_html(markup: str, stats: Optional[TransformStats] = None) -> str:
    return HtmlToText(stats).convert(markup)


def _date_warning(field_name: str, value: str) -> Optional[str]:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return f"{field_name}_not_iso8601"
    return None


def transform_record(
    record: Dict[str, Any],
    source_file: str,
    line_number: int,
    answer_stats: TransformStats,
    question_stats: TransformStats,
) -> Dict[str, Any]:
    warnings: List[str] = []

    tags = parse_tags(record["tags"])
    if "python" not in tags:
        warnings.append("python_tag_missing")
    if not record["has_code"]:
        warnings.append("has_code_false")
    lower_answer = record["answer"].lower()
    if "<pre" not in lower_answer and "<code" not in lower_answer:
        warnings.append("answer_missing_pre_or_code_markup")

    question_clean = clean_html(record["question_instruction"], question_stats)
    answer_clean = clean_html(record["answer"], answer_stats)

    if not question_clean.strip():
        warnings.append("cleaned_question_instruction_empty")
    if not answer_clean.strip():
        warnings.append("cleaned_answer_empty")
    if record["char_count"] != len(record["answer"]):
        warnings.append("source_char_count_mismatch")
    if record["source"] != EXPECTED_SOURCE:
        warnings.append("unexpected_source_identifier")
    if record["dataset_name"] != EXPECTED_DATASET:
        warnings.append("unexpected_dataset_name")
    for field_name in ("question_date", "answer_date"):
        warning = _date_warning(field_name, record[field_name])
        if warning:
            warnings.append(warning)

    normalized_answer = normalize_text_for_hash(answer_clean)
    normalized_qa = normalized_qa_text(
        record["question_title"], question_clean, answer_clean
    )

    known_fields = set(REQUIRED_FIELDS)
    extra_fields = {key: value for key, value in record.items() if key not in known_fields}

    return {
        "schema_version": SCHEMA_VERSION,
        "transformation_version": TRANSFORMATION_VERSION,
        "record_id": f"so_{record['question_id']}_{record['answer_id']}",
        "source": record["source"],
        "source_family": "stackoverflow",
        "source_type": "processed",
        "dataset_name": record["dataset_name"],
        "source_file": source_file,
        "source_line": line_number,
        "question_id": record["question_id"],
        "answer_id": record["answer_id"],
        "question_title": record["question_title"],
        "question_instruction": question_clean,
        "question_instruction_html": record["question_instruction"],
        "answer": answer_clean,
        "answer_html": record["answer"],
        "question_date": record["question_date"],
        "answer_date": record["answer_date"],
        "tags": tags,
        "tags_raw": record["tags"],
        "score": record["score"],
        "score_semantics": "question_level_constant_per_question_id_in_source",
        "has_code": record["has_code"],
        "char_count": len(answer_clean),
        "char_count_semantics": "len(cleaned_answer_unicode_code_points)",
        "source_char_count": record["char_count"],
        "collected_at": record["collected_at"],
        "content_hash": sha256_text(answer_clean),
        "content_hash_measures": "cleaned_answer_utf8",
        "normalized_answer_hash": sha256_text(normalized_answer),
        "normalized_qa_hash": sha256_text(normalized_qa),
        "normalized_hash_measures": "line_endings_and_trailing_whitespace_normalized_unicode_text",
        "license": None,
        "license_status": LICENSE_STATUS,
        "provenance_notes": (
            "No original source URL, author attribution, or per-record license "
            "metadata was present in the source record. Licensing is unresolved."
        ),
        "retained": True,
        "warnings": warnings,
        "source_extra_fields": extra_fields,
    }


OUTPUT_REQUIRED_FIELDS = {
    "schema_version": str,
    "transformation_version": str,
    "record_id": str,
    "source": str,
    "source_family": str,
    "source_type": str,
    "dataset_name": str,
    "source_file": str,
    "source_line": int,
    "question_id": int,
    "answer_id": int,
    "question_title": str,
    "question_instruction": str,
    "question_instruction_html": str,
    "answer": str,
    "answer_html": str,
    "question_date": str,
    "answer_date": str,
    "tags": list,
    "tags_raw": str,
    "score": int,
    "score_semantics": str,
    "has_code": bool,
    "char_count": int,
    "char_count_semantics": str,
    "source_char_count": int,
    "collected_at": str,
    "content_hash": str,
    "content_hash_measures": str,
    "normalized_answer_hash": str,
    "normalized_qa_hash": str,
    "normalized_hash_measures": str,
    "license": type(None),
    "license_status": str,
    "provenance_notes": str,
    "retained": bool,
    "warnings": list,
    "source_extra_fields": dict,
}


def validate_output_record(record: Any) -> List[str]:
    errors: List[str] = []
    if not isinstance(record, dict):
        return [f"output record is {type(record).__name__}, expected object"]
    for field_name, expected_type in OUTPUT_REQUIRED_FIELDS.items():
        if field_name not in record:
            errors.append(f"missing output field {field_name!r}")
            continue
        value = record[field_name]
        if expected_type is bool:
            if not isinstance(value, bool):
                errors.append(f"output field {field_name!r} is not bool")
        elif expected_type is int:
            if not _is_int(value):
                errors.append(f"output field {field_name!r} is not int")
        elif not isinstance(value, expected_type):
            errors.append(
                f"output field {field_name!r} is {type(value).__name__}, "
                f"expected {expected_type.__name__}"
            )
    if isinstance(record.get("tags"), list) and not all(
        isinstance(item, str) for item in record["tags"]
    ):
        errors.append("output field 'tags' contains a non-string item")
    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append("output schema_version does not match processor schema")
    if record.get("transformation_version") != TRANSFORMATION_VERSION:
        errors.append("output transformation_version does not match processor version")
    if record.get("license_status") != LICENSE_STATUS:
        errors.append("output license_status is not LICENSE_REVIEW_REQUIRED")
    if isinstance(record.get("answer"), str) and record.get("char_count") != len(record["answer"]):
        errors.append("output char_count does not equal len(output answer)")
    if isinstance(record.get("answer"), str) and record.get("content_hash") != sha256_text(
        record["answer"]
    ):
        errors.append("output content_hash does not match output answer")
    return errors


def _duplicate_map(values: Iterable[Any]) -> Dict[str, int]:
    counts = Counter(values)
    return {str(key): count for key, count in sorted(counts.items()) if count > 1}


def duplicate_audit(records: Sequence[Dict[str, Any]], source_records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    answer_ids = [record["answer_id"] for record in records]
    pairs = [(record["question_id"], record["answer_id"]) for record in records]
    raw_answer_hashes = [sha256_text(record["answer_html"]) for record in records]
    normalized_qa_hashes = [record["normalized_qa_hash"] for record in records]
    normalized_answer_hashes = [record["normalized_answer_hash"] for record in records]

    answers_per_question = Counter(record["question_id"] for record in records)
    distribution = Counter(answers_per_question.values())

    scores_by_question: Dict[int, set] = defaultdict(set)
    for record in source_records:
        scores_by_question[record["question_id"]].add(record["score"])
    inconsistent_scores = {
        str(qid): sorted(scores)
        for qid, scores in scores_by_question.items()
        if len(scores) > 1
    }

    duplicate_pair_map = _duplicate_map(pairs)
    duplicate_answer_map = _duplicate_map(answer_ids)
    duplicate_raw_map = _duplicate_map(raw_answer_hashes)
    duplicate_normalized_qa_map = _duplicate_map(normalized_qa_hashes)
    duplicate_normalized_answer_map = _duplicate_map(normalized_answer_hashes)

    return {
        "records_audited": len(records),
        "distinct_question_ids": len(answers_per_question),
        "questions_with_one_answer": distribution.get(1, 0),
        "questions_with_multiple_answers": sum(
            1 for n in answers_per_question.values() if n > 1
        ),
        "answers_per_question_distribution": {
            str(n): count for n, count in sorted(distribution.items())
        },
        "duplicate_answer_ids": {
            "duplicate_group_count": len(duplicate_answer_map),
            "duplicate_record_count": sum(duplicate_answer_map.values()),
            "groups": duplicate_answer_map,
        },
        "duplicate_question_answer_pairs": {
            "duplicate_group_count": len(duplicate_pair_map),
            "duplicate_record_count": sum(duplicate_pair_map.values()),
            "groups": duplicate_pair_map,
        },
        "exact_duplicate_raw_answers": {
            "duplicate_group_count": len(duplicate_raw_map),
            "duplicate_record_count": sum(duplicate_raw_map.values()),
            "groups": duplicate_raw_map,
        },
        "exact_duplicate_normalized_qa_pairs": {
            "duplicate_group_count": len(duplicate_normalized_qa_map),
            "duplicate_record_count": sum(duplicate_normalized_qa_map.values()),
            "groups": duplicate_normalized_qa_map,
        },
        "exact_duplicate_normalized_answers": {
            "duplicate_group_count": len(duplicate_normalized_answer_map),
            "duplicate_record_count": sum(duplicate_normalized_answer_map.values()),
            "groups": duplicate_normalized_answer_map,
        },
        "repeated_question_ids": {
            "count": sum(1 for n in answers_per_question.values() if n > 1),
            "answer_counts": {
                str(qid): n
                for qid, n in sorted(answers_per_question.items())
                if n > 1
            },
        },
        "question_score_consistency": {
            "questions_with_inconsistent_scores": len(inconsistent_scores),
            "details": inconsistent_scores,
        },
        "near_duplicate_similarity_candidates": {
            "computed": False,
            "reason": (
                "Optional similarity candidates were not computed in the first "
                "loss-minimizing cleaning run; exact and normalized hashes are "
                "reported instead. No records were removed."
            ),
        },
        "destructive_deduplication_performed": False,
    }


def _select_examples(records: Sequence[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    selectors = [
        ("inline_code", lambda r: "`" in r["answer"] and "\n```" not in r["answer"]),
        ("code_block", lambda r: "\n```" in r["answer"] or r["answer"].startswith("```")),
        ("entity", lambda r: "&" in r["answer_html"]),
        ("link", lambda r: "](" in r["answer"]),
        ("list", lambda r: "\n- " in r["answer"] or r["answer"].startswith("- ")),
        ("blockquote", lambda r: "\n> " in r["answer"] or r["answer"].startswith("> ")),
        ("image", lambda r: "[image" in r["answer"]),
        ("heading", lambda r: "\n# " in r["answer"] or r["answer"].startswith("# ")),
    ]
    examples: List[Dict[str, Any]] = []
    used = set()
    for label, predicate in selectors:
        for record in records:
            if record["record_id"] in used:
                continue
            if predicate(record):
                used.add(record["record_id"])
                examples.append(
                    {
                        "feature": label,
                        "record_id": record["record_id"],
                        "question_id": record["question_id"],
                        "answer_id": record["answer_id"],
                        "source_answer_html": record["answer_html"][:2000],
                        "cleaned_answer": record["answer"][:2000],
                        "warnings": record["warnings"],
                    }
                )
                break
        if len(examples) >= limit:
            break
    return examples


def _git_metadata() -> Dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent.parent,
            capture_output=True,
            text=True,
            timeout=10,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=Path(__file__).resolve().parent.parent.parent,
            capture_output=True,
            text=True,
            timeout=10,
        )
        commit_value = commit.stdout.strip() if commit.returncode == 0 else None
        status_lines = [line for line in status.stdout.splitlines() if line]
        return {
            "git_commit": commit_value,
            "git_working_tree_dirty": bool(status_lines),
            "git_status_porcelain": status_lines[:100],
            "git_status_truncated": len(status_lines) > 100,
        }
    except Exception as exc:
        return {
            "git_commit": None,
            "git_working_tree_dirty": None,
            "git_status_porcelain": [],
            "git_status_truncated": False,
            "git_error": str(exc),
        }


def _dependency_versions() -> Dict[str, Any]:
    try:
        import bs4

        bs4_version = bs4.__version__
    except Exception:
        bs4_version = "unknown"
    return {
        "python_version": sys.version,
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "beautifulsoup4": bs4_version,
        "html_parser": PARSER_NAME,
    }


def _transformation_rules() -> Dict[str, Any]:
    return {
        "parser": "beautifulsoup4 with Python html.parser",
        "entity_decoding": "one parser-level entity decode; no repeated html.unescape calls",
        "paragraphs_and_blocks": "block elements separated by one blank line",
        "headings": "ATX Markdown headings (# .. ######) derived from h1-h6",
        "lists": "unordered lists use '- '; ordered lists use 'N. '; nested items indented",
        "inline_code": "wrapped in a backtick delimiter longer than any backtick run in the content",
        "code_blocks": "preformatted blocks wrapped in a backtick fence longer than any backtick run in the code",
        "code_whitespace": "code indentation and internal newlines preserved; only leading/trailing blank lines removed",
        "line_breaks": "br elements become newlines",
        "literal_backticks": "backticks in ordinary text are backslash-escaped so they cannot form accidental Markdown fences",
        "nested_code_pre": "a code element that wraps pre content is unwrapped so the preformatted block stays block-level",
        "links": "visible text retained; URL retained as a Markdown link when it differs from the visible text",
        "images": "useful alt/title text retained as [image: alt]; placeholder or missing alt becomes [image]",
        "blockquotes": "rendered block content prefixed with '> '",
        "unknown_tags": "tag removed but descendant text retained; count reported",
        "script_style": "script/style/noscript/template content dropped and counted",
        "malformed_html": "parsed leniently by html.parser; perfect recovery is not claimed",
        "char_count": "len(cleaned_answer) in Unicode code points; source char_count preserved separately",
        "content_hash": "SHA-256 of cleaned answer UTF-8 text",
        "normalized_hash": "SHA-256 after line-ending, trailing-whitespace, and repeated-blank-line normalization",
        "filtering_policy": "retain every structurally valid record; no score, length, similarity, or usefulness filtering",
        "deduplication_policy": "audit only; no records removed or collapsed",
        "license_policy": "LICENSE_REVIEW_REQUIRED; no license, attribution, or URL invented",
    }


def _config_snapshot() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "processor_version": PROCESSOR_VERSION,
        "transformation_version": TRANSFORMATION_VERSION,
        "expected_source": EXPECTED_SOURCE,
        "expected_dataset": EXPECTED_DATASET,
        "output_source_type": "processed",
        "license_status": LICENSE_STATUS,
        "retention_policy": "retain_all_structurally_valid_records",
        "deduplication_policy": "audit_only",
    }


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


def _validate_written_output(path: Path, expected_count: int) -> Dict[str, Any]:
    record_count = 0
    errors: List[str] = []
    answer_ids = set()
    pair_ids = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip() == "":
                errors.append(f"blank output line {line_number}")
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_number}: invalid output JSON: {exc.msg}")
                continue
            record_errors = validate_output_record(record)
            if record_errors:
                errors.extend(f"line {line_number}: {error}" for error in record_errors)
            record_count += 1
            answer_ids.add(record.get("answer_id"))
            pair_ids.add((record.get("question_id"), record.get("answer_id")))
    if record_count != expected_count:
        errors.append(f"output record count {record_count} != expected {expected_count}")
    return {
        "record_count": record_count,
        "expected_record_count": expected_count,
        "count_reconciles": record_count == expected_count,
        "schema_valid": not errors,
        "errors": errors[:50],
        "error_count": len(errors),
        "distinct_answer_ids": len(answer_ids),
        "distinct_question_answer_pairs": len(pair_ids),
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _make_run_id(input_infos: Sequence[Dict[str, Any]]) -> str:
    combined = hashlib.sha256()
    for info in sorted(input_infos, key=lambda item: item["filename"]):
        combined.update(info["sha256"].encode("ascii"))
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"so-clean-{TRANSFORMATION_VERSION}-{timestamp}-{combined.hexdigest()[:8]}"


def _build_markdown_report(report: Dict[str, Any], manifest_path: str) -> str:
    counts = report["counts"]
    inputs = report["inputs"]
    outputs = report.get("outputs", [])
    validation = report.get("validation", {})
    duplicates = report["duplicate_audit"]
    stats = report["html_transformation_stats"]
    lines: List[str] = []
    lines.append("# Stack Overflow Cleaning Audit")
    lines.append("")
    lines.append(f"- Run ID: `{report['run_id']}`")
    lines.append(f"- Generated at: `{report['generated_at']}`")
    lines.append(f"- Processor version: `{report['processor_version']}`")
    lines.append(f"- Schema version: `{report['schema_version']}`")
    lines.append(f"- Transformation version: `{report['transformation_version']}`")
    lines.append(f"- Dry run: `{report['dry_run']}`")
    lines.append(f"- Manifest: `{manifest_path}`")
    lines.append("")
    lines.append("## Readiness")
    lines.append("")
    lines.append(f"- Technical readiness: `{report['technical_readiness']}`")
    lines.append(f"- Legal/redistribution readiness: `{report['legal_readiness']}`")
    lines.append(f"- Licensing status: `{LICENSE_STATUS}`")
    lines.append("")
    lines.append(
        "Licensing review remains separate from technical processing. The source "
        "records do not contain original source URLs, attribution, or per-record "
        "license metadata; no license or attribution was invented."
    )
    lines.append("")
    lines.append("### Licensing Next Actions")
    lines.append("")
    for action in report["source_provenance"]["required_next_actions"]:
        lines.append(f"- {action}")
    lines.append("")
    lines.append("## Inputs")
    lines.append("")
    lines.append("| File | Records | Bytes | SHA-256 | Baseline verified |")
    lines.append("|---|---:|---:|---|---|")
    for info in inputs:
        lines.append(
            f"| `{info['path']}` | {info['records']} | {info['bytes']} | "
            f"`{info['sha256']}` | {info.get('baseline_verified', False)} |"
        )
    lines.append("")
    lines.append("## Counts")
    lines.append("")
    lines.append(f"- Source records: {counts['source_records']}")
    lines.append(f"- Retained records: {counts['retained_records']}")
    lines.append(f"- Rejected records: {counts['rejected_records']}")
    lines.append(f"- Rejection reasons: {json.dumps(counts['rejection_reasons'], sort_keys=True)}")
    lines.append("")
    lines.append("## Outputs")
    lines.append("")
    if outputs:
        lines.append("| File | Records | Bytes | SHA-256 |")
        lines.append("|---|---:|---:|---|")
        for info in outputs:
            record_count = info.get("record_count", info.get("records", "n/a"))
            lines.append(
                f"| `{info['path']}` | {record_count} | "
                f"{info.get('bytes', 'n/a')} | `{info.get('sha256', 'n/a')}` |"
            )
    else:
        lines.append("No corpus artifacts were written (dry run).")
    lines.append("")
    lines.append("## Validation")
    lines.append("")
    for key, value in validation.items():
        if key in ("errors",):
            continue
        lines.append(f"- `{key}`: {value}")
    if validation.get("errors"):
        lines.append(f"- Errors: `{validation['errors']}`")
    lines.append("")
    lines.append("## HTML Transformation")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(stats, indent=2, sort_keys=True))
    lines.append("```")
    lines.append("")
    lines.append(
        "Code blocks preserve indentation and internal newlines. Fences are "
        "lengthened when the code itself contains backtick runs. Inline code "
        "uses an explicit backtick delimiter. Links retain both visible text and "
        "URL when they differ. Images retain useful alt text; placeholder alts "
        "are counted as not useful."
    )
    lines.append("")
    lines.append("## Duplicate Audit (Non-Destructive)")
    lines.append("")
    for key in (
        "duplicate_answer_ids",
        "duplicate_question_answer_pairs",
        "exact_duplicate_raw_answers",
        "exact_duplicate_normalized_qa_pairs",
        "exact_duplicate_normalized_answers",
    ):
        item = duplicates[key]
        lines.append(
            f"- `{key}`: {item['duplicate_group_count']} duplicate groups, "
            f"{item['duplicate_record_count']} duplicate records"
        )
    lines.append(f"- Distinct question IDs: {duplicates['distinct_question_ids']}")
    lines.append(
        f"- Questions with multiple answers: {duplicates['questions_with_multiple_answers']}"
    )
    lines.append(
        f"- Questions with inconsistent scores: "
        f"{duplicates['question_score_consistency']['questions_with_inconsistent_scores']}"
    )
    lines.append("- Destructive deduplication performed: false")
    lines.append("")
    lines.append("## Limitations and Anomalies")
    lines.append("")
    if report.get("record_warnings"):
        for warning, count in sorted(report["record_warnings"].items()):
            lines.append(f"- `{warning}`: {count}")
    else:
        lines.append("- No per-record warnings.")
    lines.append(
        "- Malformed HTML is handled leniently, not perfectly; no external "
        "validation of upstream HTML correctness was possible."
    )
    lines.append(
        "- `score` is preserved as supplied and is question-level in this "
        "corpus; it was not used as an answer-level quality signal."
    )
    lines.append("")
    lines.append("## Sample Cleaned Records")
    lines.append("")
    for example in report.get("examples", []):
        lines.append(f"### {example['feature']} — `{example['record_id']}`")
        lines.append("")
        lines.append("Source HTML (truncated):")
        lines.append("")
        lines.append("```html")
        lines.append(example["source_answer_html"])
        lines.append("```")
        lines.append("")
        lines.append("Cleaned answer (truncated):")
        lines.append("")
        lines.append("```text")
        lines.append(example["cleaned_answer"])
        lines.append("```")
        lines.append("")
    return "\n".join(lines) + "\n"


def process(
    input_paths: Sequence[str | Path],
    output_root: Optional[str | Path] = None,
    run_id: Optional[str] = None,
    dry_run: bool = False,
    expected_baseline: Optional[Dict[str, Dict[str, Any]]] = PRODUCTION_BASELINE,
    require_mount_root: Optional[str | Path] = None,
    examples: int = 0,
) -> Dict[str, Any]:
    input_path_list = [Path(path) for path in input_paths]
    output_root_path = Path(output_root) if output_root is not None else None
    mount_root_path = Path(require_mount_root) if require_mount_root is not None else None

    if not dry_run and output_root_path is None:
        raise ValueError("output_root is required for a non-dry run")

    loaded, source_infos, validation_errors = preflight(
        input_path_list,
        expected_baseline=expected_baseline,
        require_mount_root=mount_root_path,
        output_root=output_root_path,
    )

    rejected: List[Dict[str, Any]] = list(validation_errors)
    invalid_keys = {
        (item["source_file"], item["line"]) for item in validation_errors
    }

    answer_stats = TransformStats()
    question_stats = TransformStats()
    output_records: List[Dict[str, Any]] = []
    source_records_for_audit: List[Dict[str, Any]] = []

    for line_number, record, path in loaded:
        if (path.name, line_number) in invalid_keys:
            continue
        source_records_for_audit.append(record)
        try:
            transformed = transform_record(
                record,
                source_file=path.name,
                line_number=line_number,
                answer_stats=answer_stats,
                question_stats=question_stats,
            )
        except Exception as exc:
            rejected.append(
                {
                    "source_file": path.name,
                    "line": line_number,
                    "answer_id": record.get("answer_id"),
                    "errors": [f"transformation failed: {exc}"],
                }
            )
            continue
        record_errors = validate_output_record(transformed)
        if record_errors:
            rejected.append(
                {
                    "source_file": path.name,
                    "line": line_number,
                    "answer_id": record.get("answer_id"),
                    "errors": record_errors,
                }
            )
            continue
        output_records.append(transformed)

    rejection_reasons: Dict[str, int] = {}
    for item in rejected:
        for error in item["errors"]:
            message = re.sub(r"^line \d+: ", "", error)
            key = message.split(":", 1)[0]
            rejection_reasons[key] = rejection_reasons.get(key, 0) + 1

    duplicates = duplicate_audit(output_records, source_records_for_audit)
    warning_counts = Counter(
        warning for record in output_records for warning in record["warnings"]
    )

    computed_run_id = run_id or _make_run_id(source_infos)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", computed_run_id):
        raise ValueError("run_id may contain only letters, digits, dot, underscore, and hyphen")

    report: Dict[str, Any] = {
        "run_id": computed_run_id,
        "generated_at": utc_now_iso(),
        "dry_run": dry_run,
        "processor_version": PROCESSOR_VERSION,
        "schema_version": SCHEMA_VERSION,
        "transformation_version": TRANSFORMATION_VERSION,
        "inputs": source_infos,
        "counts": {
            "source_records": len(loaded),
            "retained_records": len(output_records),
            "rejected_records": len(rejected),
            "rejection_reasons": rejection_reasons,
            "rejections": rejected,
        },
        "duplicate_audit": duplicates,
        "html_transformation_stats": {
            "answers": answer_stats.to_dict(),
            "questions": question_stats.to_dict(),
        },
        "record_warnings": dict(sorted(warning_counts.items())),
        "transformation_rules": _transformation_rules(),
        "config": _config_snapshot(),
        "dependencies": _dependency_versions(),
        "git": _git_metadata(),
        "source_provenance": {
            "source": EXPECTED_SOURCE,
            "dataset_name": EXPECTED_DATASET,
            "license_status": LICENSE_STATUS,
            "license_review_required": True,
            "missing_provenance": [
                "original source URL per record",
                "author attribution per record",
                "per-record license metadata",
            ],
            "note": (
                "A previous audit reported an upstream Hugging Face dataset-card "
                "claim of Kaggle origin and CC BY-SA 3.0. That claim was not "
                "independently established for every record, and no license or "
                "attribution was invented."
            ),
            "required_next_actions": [
                "Obtain and record authoritative upstream dataset and license terms for every contributing record.",
                "Keep the corpus marked LICENSE_REVIEW_REQUIRED until that review is complete.",
                "Do not redistribute or label the corpus license-approved before review.",
                "Add per-record source URL and attribution only from authoritative provenance; do not infer missing values.",
            ],
        },
        "examples": _select_examples(output_records, examples) if examples else [],
        "technical_readiness": "READY_FOR_NEXT_ACQUISITION_STAGE",
        "legal_readiness": "BLOCKED_PENDING_LICENSE_REVIEW",
    }

    if dry_run:
        report["validation"] = {
            "dry_run_no_artifacts_written": True,
            "preflight_baseline_verified": all(
                info.get("baseline_verified", False) for info in source_infos
            ),
            "input_record_count": len(loaded),
            "retained_record_count": len(output_records),
            "rejected_record_count": len(rejected),
        }
        return report

    assert output_root_path is not None
    output_dir = output_root_path / computed_run_id
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing run directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)

    output_jsonl = output_dir / "stackoverflow_clean.jsonl"
    report_json_path = output_dir / "audit_report.json"
    report_md_path = output_dir / "audit_report.md"
    manifest_path = output_dir / "manifest.json"

    _write_jsonl(output_jsonl, output_records)

    post_write = _validate_written_output(output_jsonl, expected_count=len(output_records))

    source_after: List[Dict[str, Any]] = []
    for info in source_infos:
        path = Path(info["path"])
        source_after.append(
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "records": info["records"],
            }
        )
    sources_unchanged = all(
        before["bytes"] == after["bytes"] and before["sha256"] == after["sha256"]
        for before, after in zip(source_infos, source_after)
    )

    report["outputs"] = [
        {
            "path": str(output_jsonl),
            "record_count": len(output_records),
            "bytes": output_jsonl.stat().st_size,
            "sha256": sha256_file(output_jsonl),
        }
    ]
    report["manifest_path"] = str(manifest_path)
    report["readiness_decision"] = report["technical_readiness"]
    report["validation"] = {
        "output_schema_valid": post_write["schema_valid"],
        "output_count_reconciles": post_write["count_reconciles"],
        "output_record_count": post_write["record_count"],
        "expected_output_record_count": post_write["expected_record_count"],
        "distinct_answer_ids": post_write["distinct_answer_ids"],
        "distinct_question_answer_pairs": post_write["distinct_question_answer_pairs"],
        "output_errors": post_write["errors"],
        "output_error_count": post_write["error_count"],
        "source_files_unchanged": sources_unchanged,
        "source_hashes_after": source_after,
        "source_records": len(loaded),
        "retained_records": len(output_records),
        "rejected_records": len(rejected),
        "record_count_reconciled": len(loaded) == len(output_records) + len(rejected),
    }

    _write_json(report_json_path, report)
    report_md_path_text = _build_markdown_report(report, str(manifest_path))
    _write_text(report_md_path, report_md_path_text)

    manifest = {
        "manifest_version": "1",
        "experiment_id": "PYT-DATA-SO-CLEAN-001",
        "run_id": computed_run_id,
        "generated_at": report["generated_at"],
        "processor_version": PROCESSOR_VERSION,
        "schema_version": SCHEMA_VERSION,
        "transformation_version": TRANSFORMATION_VERSION,
        "output_root": str(output_root_path),
        "inputs": source_infos,
        "outputs": [
            {
                "role": "cleaned_corpus",
                "path": str(output_jsonl),
                "record_count": len(output_records),
                "bytes": output_jsonl.stat().st_size,
                "sha256": sha256_file(output_jsonl),
            },
            {
                "role": "audit_report_json",
                "path": str(report_json_path),
                "bytes": report_json_path.stat().st_size,
                "sha256": sha256_file(report_json_path),
            },
            {
                "role": "audit_report_markdown",
                "path": str(report_md_path),
                "bytes": report_md_path.stat().st_size,
                "sha256": sha256_file(report_md_path),
            },
        ],
        "counts": {
            "source_records": len(loaded),
            "retained_records": len(output_records),
            "rejected_records": len(rejected),
            "rejection_reasons": rejection_reasons,
        },
        "validation": report["validation"],
        "duplicate_audit": duplicates,
        "transformation_rules": report["transformation_rules"],
        "config": report["config"],
        "dependencies": report["dependencies"],
        "git": report["git"],
        "source_provenance": report["source_provenance"],
        "readiness": {
            "decision": report["technical_readiness"],
            "technical": report["technical_readiness"],
            "legal_redistribution": report["legal_readiness"],
            "license_status": LICENSE_STATUS,
            "license_next_actions": report["source_provenance"]["required_next_actions"],
        },
        "determinism": {
            "same_inputs_and_configuration_produce_identical_jsonl": True,
            "run_metadata_is_not_embedded_in_records": True,
            "input_order_preserved": True,
        },
    }
    _write_json(manifest_path, manifest)

    report["manifest_sha256"] = sha256_file(manifest_path)
    report["manifest_bytes"] = manifest_path.stat().st_size
    return report


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="explicit source JSONL path (repeat for multiple files)",
    )
    parser.add_argument(
        "--output-root",
        help="new run directory parent; required unless --dry-run is used",
    )
    parser.add_argument("--run-id", help="explicit run identifier; must not already exist")
    parser.add_argument("--dry-run", action="store_true", help="transform in memory only")
    parser.add_argument(
        "--no-baseline-check",
        action="store_true",
        help="disable the built-in production baseline hash/count check",
    )
    parser.add_argument(
        "--require-mount-root",
        help="fail unless inputs and output are under this mounted root",
    )
    parser.add_argument(
        "--examples",
        type=int,
        default=0,
        help="include N representative cleaned examples in the report/output",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    expected_baseline = None if args.no_baseline_check else PRODUCTION_BASELINE
    try:
        report = process(
            input_paths=args.input,
            output_root=args.output_root,
            run_id=args.run_id,
            dry_run=args.dry_run,
            expected_baseline=expected_baseline,
            require_mount_root=args.require_mount_root,
            examples=args.examples,
        )
    except (PreflightError, FileExistsError, OutputValidationError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
        return 0

    print(f"RUN_DIR={Path(report['outputs'][0]['path']).parent}")
    print(f"RUN_ID={report['run_id']}")
    print(f"SOURCE_RECORDS={report['counts']['source_records']}")
    print(f"RETAINED_RECORDS={report['counts']['retained_records']}")
    print(f"REJECTED_RECORDS={report['counts']['rejected_records']}")
    print(f"OUTPUT_RECORDS={report['validation']['output_record_count']}")
    print(f"OUTPUT_SHA256={report['outputs'][0]['sha256']}")
    print(f"OUTPUT_BYTES={report['outputs'][0]['bytes']}")
    print(f"MANIFEST={report['manifest_path']}")
    print(f"TECHNICAL_READINESS={report['technical_readiness']}")
    print(f"LEGAL_READINESS={report['legal_readiness']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
