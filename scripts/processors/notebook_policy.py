"""Jupyter notebook selection policy for the Pythia-160M Stage 3 workstream.

This module implements the canonical notebook eligibility policy as pure,
dependency-light functions over parsed notebook dictionaries. It deliberately
does NOT import the authoritative AST validator, the quality gate, or any
acquisition machinery: the caller (``scripts.scrapers.jupyter_acquire``) is
responsible for wiring in those components and for the source-byte provenance.

The policy is a static, non-executing evaluation. Notebook cells are never
executed here, and no packages referenced by notebook cells are installed.

Selection rules implemented here:

  1. A notebook must parse as a valid ``.ipynb`` JSON document with a ``cells``
     list (``nbformat >= 4``).
  2. Its Markdown proportion ``markdown_cells / total_cells`` must be strictly
     greater than ``0.40``. Exactly ``0.40`` is ineligible.
  3. It must contain meaningful Python code (not merely imports, placeholders,
     empty cells, or trivial boilerplate).
  4. A notebook with zero cells is structurally invalid.

Everything here is deterministic and side-effect free except where a function
explicitly documents that it hashes text.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import warnings
from dataclasses import dataclass
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MARKDOWN_CELL = "markdown"
CODE_CELL = "code"
RAW_CELL = "raw"
KNOWN_CELL_TYPES = {MARKDOWN_CELL, CODE_CELL, RAW_CELL}

# Markdown proportion must be STRICTLY greater than this value.
MARKDOWN_RATIO_THRESHOLD = 0.40

# nbformat major versions we accept without a documented conversion step.
SUPPORTED_NBFORMAT_MAJOR = (4,)

# Subject categories (task-mandated) with a stable, lower-case key.
CATEGORY_FUNDAMENTALS = "python_fundamentals"
CATEGORY_ALGORITHMS = "algorithms_data_structures"
CATEGORY_SOFTWARE_ENGINEERING = "software_engineering_testing"
CATEGORY_SCIENTIFIC = "numpy_pandas_scientific"
CATEGORY_STATS_VIZ = "statistics_visualization"
CATEGORY_DATA_ENGINEERING = "data_engineering_analysis"
CATEGORY_ML_DL = "machine_learning_deep_learning"
CATEGORY_PYTORCH = "pytorch_transformers"
CATEGORY_REPRODUCIBLE = "reproducible_research_advanced"
CATEGORY_UNCERTAIN = "uncategorized"

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class NotebookError(ValueError):
    """Raised when a notebook document is structurally invalid."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# Parsing and cell extraction
# ---------------------------------------------------------------------------


def parse_notebook_json(text: str) -> dict[str, Any]:
    """Parse a ``.ipynb`` document from JSON text.

    Raises :class:`NotebookError` for malformed JSON, a non-object document,
    a missing/non-list ``cells`` field, or an unsupported notebook format.
    """
    if text is None or not isinstance(text, str):
        raise NotebookError("notebook_content_is_not_text")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NotebookError(f"invalid_json:{exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise NotebookError("notebook_json_is_not_an_object")

    nbformat = parsed.get("nbformat")
    if not isinstance(nbformat, int):
        raise NotebookError("missing_or_non_integer_nbformat")
    if nbformat not in SUPPORTED_NBFORMAT_MAJOR:
        raise NotebookError(f"unsupported_nbformat_{nbformat}")

    cells = parsed.get("cells")
    if not isinstance(cells, list):
        raise NotebookError("missing_or_non_list_cells")
    return parsed


def parse_notebook_bytes(data: bytes) -> dict[str, Any]:
    """Decode UTF-8 bytes and parse as a notebook.

    Empty byte payloads are treated as structurally invalid. Raises
    :class:`NotebookError` on failure.
    """
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise NotebookError("empty_or_non_bytes_payload")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NotebookError(f"not_valid_utf8:{exc.reason}") from exc
    return parse_notebook_json(text)


def cell_type(cell: dict[str, Any]) -> str:
    """Return the cell type, defaulting to ``raw`` for unknown/missing types."""
    value = cell.get("cell_type") if isinstance(cell, dict) else None
    if value in KNOWN_CELL_TYPES:
        return value
    return RAW_CELL


def cell_source(cell: dict[str, Any]) -> str:
    """Return the joined source text of a cell (list-of-strings or string)."""
    if not isinstance(cell, dict):
        return ""
    source = cell.get("source", "")
    if isinstance(source, str):
        return source
    if isinstance(source, list):
        parts = [part if isinstance(part, str) else str(part) for part in source]
        return "".join(parts)
    return ""


def count_cells(nb: dict[str, Any]) -> dict[str, int]:
    """Count cells by type plus total and empty counts."""
    counts = {
        "total": 0,
        "markdown": 0,
        "code": 0,
        "raw": 0,
        "empty": 0,
        "empty_code": 0,
        "empty_markdown": 0,
    }
    for cell in nb.get("cells", []):
        counts["total"] += 1
        ctype = cell_type(cell)
        counts[ctype] += 1
        source = cell_source(cell)
        if not source.strip():
            counts["empty"] += 1
            if ctype == CODE_CELL:
                counts["empty_code"] += 1
            elif ctype == MARKDOWN_CELL:
                counts["empty_markdown"] += 1
    return counts


def markdown_proportion(markdown_count: int, total_count: int) -> float:
    """Return ``markdown_count / total_count`` (0.0 when total is zero)."""
    if total_count <= 0:
        return 0.0
    return markdown_count / total_count


def passes_markdown_ratio(markdown_count: int, total_count: int) -> bool:
    """Return True only when the Markdown proportion is strictly > 0.40."""
    if total_count <= 0:
        return False
    return markdown_count / total_count > MARKDOWN_RATIO_THRESHOLD


def extract_cell_sources(nb: dict[str, Any], wanted_type: str) -> list[str]:
    """Return the source text of every cell of the given type, in order."""
    out: list[str] = []
    for cell in nb.get("cells", []):
        if cell_type(cell) == wanted_type:
            out.append(cell_source(cell))
    return out


def extract_cells(nb: dict[str, Any], wanted_type: str) -> list[dict[str, Any]]:
    """Return the raw cell dicts of the given type, in order."""
    return [c for c in nb.get("cells", []) if cell_type(c) == wanted_type]


# ---------------------------------------------------------------------------
# IPython magics / shell handling
# ---------------------------------------------------------------------------

_MAGIC_LINE_RE = re.compile(r"^\s*(%|!|%%|%%!)")
_SHELL_WORDS = (
    "get_ipython(",
    "system(",
    "run_line_magic(",
    "getoutput(",
)


def strip_ipython_magics(code: str) -> tuple[str, bool]:
    """Remove IPython magics and shell-bang lines from notebook code.

    Returns ``(cleaned_code, had_magic)``. A line whose first non-whitespace
    character is ``%`` or ``!`` is treated as a magic/shell command and dropped,
    so a genuine Python syntax check is not polluted by IPython-only syntax.
    """
    if not isinstance(code, str):
        return "", False
    had_magic = False
    kept: list[str] = []
    for line in code.split("\n"):
        if _MAGIC_LINE_RE.match(line):
            had_magic = True
            continue
        kept.append(line)
    cleaned = "\n".join(kept)
    return cleaned, had_magic


# ---------------------------------------------------------------------------
# Meaningful-Python detection
# ---------------------------------------------------------------------------


def _is_meaningful_statement(node: ast.stmt) -> bool:
    """Classify an AST statement as substantive (vs import/pass/constant)."""
    if isinstance(node, (ast.Import, ast.ImportFrom, ast.Pass)):
        return False
    if isinstance(node, ast.Expr):
        value = node.value
        if isinstance(value, ast.Constant):
            return False
        if isinstance(value, (ast.Name, ast.Attribute)):
            return False
        return True
    return True


def meaningful_statement_count(source: str) -> int:
    """Count substantive statements in Python source without executing it.

    Returns 0 for empty, whitespace-only, or syntactically invalid source.
    """
    if not source or not source.strip():
        return 0
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return 0
    return sum(1 for node in ast.walk(tree) if isinstance(node, ast.stmt) and _is_meaningful_statement(node))


def analyze_code_cells(nb: dict[str, Any]) -> dict[str, Any]:
    """Summarize the Python code cells of a notebook without executing them.

    Returns a dict with non-empty code cell count, total meaningful statement
    count, import-only detection, and a per-cell magic/shell breakdown.
    """
    code_cells = extract_cells(nb, CODE_CELL)
    non_empty = 0
    total_meaningful = 0
    magic_cells = 0
    import_only_cells = 0
    per_cell: list[dict[str, Any]] = []
    for idx, cell in enumerate(code_cells):
        source = cell_source(cell)
        if not source.strip():
            continue
        non_empty += 1
        cleaned, had_magic = strip_ipython_magics(source)
        if had_magic:
            magic_cells += 1
        meaningful = meaningful_statement_count(cleaned)
        total_meaningful += meaningful
        import_only = False
        if cleaned.strip() and meaningful == 0:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", SyntaxWarning)
                    tree = ast.parse(cleaned)
                import_only = any(
                    isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(tree)
                ) and not any(
                    isinstance(n, ast.stmt) and _is_meaningful_statement(n) for n in ast.walk(tree)
                )
            except (SyntaxError, ValueError):
                import_only = False
        if import_only:
            import_only_cells += 1
        per_cell.append(
            {
                "index": idx,
                "has_magic": had_magic,
                "cleaned_is_empty": not cleaned.strip(),
                "meaningful_statements": meaningful,
                "import_only": import_only,
            }
        )
    return {
        "code_cells": len(code_cells),
        "non_empty_code_cells": non_empty,
        "magic_cells": magic_cells,
        "import_only_cells": import_only_cells,
        "total_meaningful_statements": total_meaningful,
        "has_meaningful_python": non_empty >= 1 and total_meaningful >= 1,
        "per_cell": per_cell,
    }


# ---------------------------------------------------------------------------
# Subject classification (keyword heuristic; uncertain when ambiguous)
# ---------------------------------------------------------------------------

_CLASSIFIER_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (CATEGORY_PYTORCH, ("torch", "pytorch", "transformer", "nn.module", "attention")),
    (CATEGORY_ML_DL, ("keras", "tensorflow", "sklearn", "scikit", "xgboost", "neural network",
                      "deep learning", "machine learning", "classification", "regression",
                      "clustering", "embedding", "gradient descent", "activation")),
    (CATEGORY_STATS_VIZ, ("matplotlib", "seaborn", "plotly", "histogram", "distribution",
                          "visualization", "statistic", "probability", "p-value", "hypothesis")),
    (CATEGORY_SCIENTIFIC, ("numpy", "pandas", "scipy", "astropy", "xarray", "sympy", "mpmath")),
    (CATEGORY_ALGORITHMS, ("algorithm", "sort", "search", "tree", "graph", "stack", "queue",
                           "linked list", "recursion", "dynamic programming", "complexity")),
    (CATEGORY_SOFTWARE_ENGINEERING, ("pytest", "unittest", "testing", "test-driven", "refactor",
                                     "debugging", "exception", "type hint", "module", "package")),
    (CATEGORY_DATA_ENGINEERING, ("etl", "pipeline", "data cleaning", "data wrangling",
                                 "dataframe", "csv", "json", "database", "sql", "api")),
    (CATEGORY_REPRODUCIBLE, ("reproduc", "watermark", "environment", "jupyter", "version control",
                             "git", "binder", "docker")),
    (CATEGORY_FUNDAMENTALS, ("python basics", "variables", "strings", "lists", "dictionary",
                             "loops", "functions", "class", "iterator", "generator", "regex",
                             "date", "time", "format", "collection", "comprehension")),
)


def classify_notebook(nb: dict[str, Any]) -> tuple[str, float]:
    """Classify a notebook into a coarse subject category.

    Returns ``(category, confidence)``. Confidence is a simple fraction of the
    maximum keyword score over total scores; low-confidence or multi-category
    notebooks are reported as :data:`CATEGORY_UNCERTAIN` by the caller when the
    evidence is weak.
    """
    text_blob = _classification_text(nb)
    if not text_blob.strip():
        return CATEGORY_UNCERTAIN, 0.0

    lowered = text_blob.lower()
    scores: dict[str, int] = {}
    for category, keywords in _CLASSIFIER_KEYWORDS:
        score = sum(lowered.count(kw) for kw in keywords)
        scores[category] = score

    total = sum(scores.values())
    if total == 0:
        return CATEGORY_UNCERTAIN, 0.0
    best = max(scores, key=scores.get)
    confidence = scores[best] / total
    return best, round(confidence, 4)


def _classification_text(nb: dict[str, Any]) -> str:
    parts: list[str] = []
    parts.append(" ".join(extract_cell_sources(nb, MARKDOWN_CELL)))
    parts.append(" ".join(extract_cell_sources(nb, CODE_CELL)))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Outputs and attachments
# ---------------------------------------------------------------------------


def output_metrics(nb: dict[str, Any]) -> dict[str, Any]:
    """Inspect saved cell outputs without executing anything.

    Reports the number of cells carrying outputs, total output byte size (a
    conservative estimate of the JSON-serialized size of all ``outputs``
    fields), and whether the notebook is output-dominated.
    """
    cells = nb.get("cells", [])
    cells_with_outputs = 0
    total_output_bytes = 0
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        outputs = cell.get("outputs")
        if isinstance(outputs, list) and outputs:
            cells_with_outputs += 1
            try:
                total_output_bytes += len(json.dumps(outputs, ensure_ascii=False))
            except (TypeError, ValueError):
                total_output_bytes += 0
    output_dominated = total_output_bytes > 0 and total_output_bytes > 250_000
    return {
        "cells_with_outputs": cells_with_outputs,
        "total_output_bytes": total_output_bytes,
        "output_dominated": output_dominated,
    }


_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("aws_secret_key", re.compile(r"\b(?=.*[A-Za-z])(?=.*[0-9])[A-Za-z0-9+/]{40}\b")),
    ("private_key_pem", re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[0-9A-Za-z]{36,}\b")),
)


def screen_for_secrets(text: str) -> list[str]:
    """Return the list of secret-like pattern names detected in *text*.

    This is a conservative, non-destructive screen; matches are not proof of a
    real credential and do not cause automatic rejection on their own.
    """
    if not text:
        return []
    found: list[str] = []
    for name, pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            found.append(name)
    return found


def screen_notebook_for_secrets(nb: dict[str, Any]) -> list[str]:
    """Screen a notebook's code, Markdown, and output text for secret patterns."""
    text = _classification_text(nb)
    for cell in nb.get("cells", []):
        if isinstance(cell, dict):
            try:
                text += "\n" + json.dumps(cell.get("outputs", []), ensure_ascii=False)
            except (TypeError, ValueError):
                pass
    return screen_for_secrets(text)


# ---------------------------------------------------------------------------
# Normalization and hashing (deduplication support)
# ---------------------------------------------------------------------------


def normalize_notebook_text(nb: dict[str, Any]) -> str:
    """Build a normalized, order-preserving text representation of a notebook.

    This is used for exact/near-exact duplicate detection. Markdown cells are
    kept so explanations are not flattened away; code cells keep their source.
    Outputs are deliberately excluded so two notebooks that differ only in
    executed outputs still compare equal.
    """
    blocks: list[str] = []
    for cell in nb.get("cells", []):
        ctype = cell_type(cell)
        source = cell_source(cell)
        if ctype == CODE_CELL:
            cleaned, _ = strip_ipython_magics(source)
            body = cleaned.strip()
        else:
            body = source.strip()
        if body:
            blocks.append(f"<{ctype}>\n{normalize_lines(body)}")
    return "\n\n".join(blocks)


def normalize_lines(text: str) -> str:
    """Normalize line endings and collapse repeated blank lines."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    collapsed: list[str] = []
    prev_blank = False
    for line in lines:
        blank = line.strip() == ""
        if blank and prev_blank:
            continue
        collapsed.append(line)
        prev_blank = blank
    while collapsed and collapsed[0] == "":
        collapsed.pop(0)
    while collapsed and collapsed[-1] == "":
        collapsed.pop()
    return "\n".join(collapsed)


def sha256_text(text: str) -> str:
    """Return the SHA-256 hex digest of UTF-8 encoded *text*."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalized_notebook_hash(nb: dict[str, Any]) -> str:
    """SHA-256 of the normalized notebook text (dedup key)."""
    return sha256_text(normalize_notebook_text(nb))


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


@dataclass
class PolicyResult:
    """Aggregate eligibility assessment for one notebook."""

    eligible: bool
    markdown_count: int
    code_count: int
    raw_count: int
    total_cells: int
    markdown_proportion: float
    markdown_ratio_passes: bool
    parses: bool
    nbformat: Any
    nbformat_minor: Any
    has_meaningful_python: bool
    total_meaningful_statements: int
    non_empty_code_cells: int
    category: str
    category_confidence: float
    reasons_ineligible: list[str]
    warnings: list[str]


def evaluate_policy(nb: dict[str, Any]) -> PolicyResult:
    """Evaluate a parsed notebook against the canonical selection policy.

    This is the policy-only gate. It does not run the authoritative AST
    validator or PEP8/lint tooling (the caller does that) and never executes
    cells.
    """
    counts = count_cells(nb)
    total = counts["total"]
    markdown_count = counts["markdown"]
    code_count = counts["code"]
    raw_count = counts["raw"]

    reasons: list[str] = []
    warnings: list[str] = []

    nbformat = nb.get("nbformat")
    nbformat_minor = nb.get("nbformat_minor")

    parses = isinstance(nbformat, int) and nbformat in SUPPORTED_NBFORMAT_MAJOR and isinstance(
        nb.get("cells"), list
    )

    proportion = markdown_proportion(markdown_count, total)
    ratio_passes = passes_markdown_ratio(markdown_count, total)

    code_analysis = analyze_code_cells(nb)
    has_meaningful = code_analysis["has_meaningful_python"]
    total_meaningful = code_analysis["total_meaningful_statements"]
    non_empty_code = code_analysis["non_empty_code_cells"]

    if total == 0:
        reasons.append("zero_cells")
    if not parses:
        reasons.append("structurally_invalid")
    if parses and total > 0 and not ratio_passes:
        reasons.append("markdown_proportion_not_gt_0.4")
    if parses and not has_meaningful:
        reasons.append("no_meaningful_python")

    if parses and total > 0 and code_count == 0:
        warnings.append("no_code_cells")

    category, confidence = classify_notebook(nb)
    if confidence < 0.34:
        category = CATEGORY_UNCERTAIN

    eligible = parses and total > 0 and ratio_passes and has_meaningful

    return PolicyResult(
        eligible=eligible,
        markdown_count=markdown_count,
        code_count=code_count,
        raw_count=raw_count,
        total_cells=total,
        markdown_proportion=round(proportion, 6),
        markdown_ratio_passes=ratio_passes,
        parses=parses,
        nbformat=nbformat,
        nbformat_minor=nbformat_minor,
        has_meaningful_python=has_meaningful,
        total_meaningful_statements=total_meaningful,
        non_empty_code_cells=non_empty_code,
        category=category,
        category_confidence=confidence,
        reasons_ineligible=reasons,
        warnings=warnings,
    )


__all__ = [
    "NotebookError",
    "parse_notebook_json",
    "parse_notebook_bytes",
    "count_cells",
    "markdown_proportion",
    "passes_markdown_ratio",
    "extract_cell_sources",
    "extract_cells",
    "strip_ipython_magics",
    "meaningful_statement_count",
    "analyze_code_cells",
    "classify_notebook",
    "output_metrics",
    "screen_for_secrets",
    "screen_notebook_for_secrets",
    "normalize_notebook_text",
    "normalize_lines",
    "sha256_text",
    "normalized_notebook_hash",
    "evaluate_policy",
    "PolicyResult",
    "MARKDOWN_RATIO_THRESHOLD",
    "CATEGORY_UNCERTAIN",
]
