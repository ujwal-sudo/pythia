"""Authoritative, non-executing AST validation for Python source."""

from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass
from typing import Final

from scripts.logger import get_logger


logger = get_logger(__name__)


_ERROR_EMPTY_SOURCE: Final[str] = "empty_source"
_ERROR_ENCODING: Final[str] = "encoding_error"
_ERROR_INDENTATION: Final[str] = "indentation_error"
_ERROR_INTERNAL: Final[str] = "internal_error"
_ERROR_SYNTAX: Final[str] = "syntax_error"
_ERROR_TOKENIZE: Final[str] = "tokenize_error"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Structured syntax and source-structure information for one sample.

    ``is_valid`` means the source is non-empty and was accepted by
    :func:`ast.parse`. It does not imply that the code is executable, correct,
    or valid according to a Knowledge Graph or style checker.

    The documentation ratio is the number of physical lines containing a
    comment or an AST-recognized module, class, or function docstring divided
    by the number of non-blank physical source lines. Overlapping lines count
    once. The ratio is reported only; ``MIN_COMMENT_RATIO`` is not enforced
    here.
    """

    is_valid: bool
    error_type: str | None = None
    error_message: str | None = None
    line_number: int | None = None
    column_offset: int | None = None
    node_count: int = 0
    has_comments: bool = False
    has_docstrings: bool = False
    comment_ratio: float = 0.0
    function_count: int = 0
    class_count: int = 0
    import_count: int = 0
    loop_count: int = 0
    conditional_count: int = 0
    return_count: int = 0
    comment_count: int = 0
    docstring_count: int = 0
    analysis_error_type: str | None = None
    analysis_error_message: str | None = None


def validate_python(source: str) -> ValidationResult:
    """Parse and analyze Python source without executing it.

    ``ast.parse`` is the authoritative syntax check. Invalid samples return a
    structured result and are never allowed to raise a normal parse error to a
    batch caller. Metadata collection is deterministic and uses only Python's
    standard-library AST and tokenizer modules.
    """
    if not isinstance(source, str):
        return ValidationResult(
            is_valid=False,
            error_type=_ERROR_INTERNAL,
            error_message="source must be a string",
        )

    if not source.strip():
        return ValidationResult(
            is_valid=False,
            error_type=_ERROR_EMPTY_SOURCE,
            error_message="source is empty or whitespace-only",
        )

    try:
        tree = ast.parse(source)
    except (IndentationError, SyntaxError) as error:
        return _syntax_error_result(error)
    except (MemoryError, RecursionError):
        raise
    except Exception as error:  # pragma: no cover - defensive interpreter guard
        logger.exception("Unexpected AST parsing failure")
        return ValidationResult(
            is_valid=False,
            error_type=_ERROR_INTERNAL,
            error_message=str(error),
        )

    try:
        result = _collect_metadata(tree, source)
    except (MemoryError, RecursionError):
        raise
    except Exception as error:  # pragma: no cover - defensive batch guard
        logger.exception("Unexpected AST metadata failure")
        return ValidationResult(
            is_valid=True,
            error_type=None,
            node_count=sum(1 for _ in ast.walk(tree)),
            analysis_error_type=_ERROR_INTERNAL,
            analysis_error_message=str(error),
        )

    return result


def _syntax_error_result(error: SyntaxError) -> ValidationResult:
    """Convert a parser exception into the public result shape."""
    error_type = _ERROR_INDENTATION if isinstance(error, IndentationError) else _ERROR_SYNTAX
    line_number = error.lineno
    column_offset = error.offset
    return ValidationResult(
        is_valid=False,
        error_type=error_type,
        error_message=error.msg,
        line_number=line_number,
        column_offset=column_offset,
    )


def _collect_metadata(tree: ast.AST, source: str) -> ValidationResult:
    """Collect AST and token metadata for a successfully parsed sample."""
    nodes = list(ast.walk(tree))
    function_count = sum(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in nodes
    )
    class_count = sum(isinstance(node, ast.ClassDef) for node in nodes)
    import_count = sum(isinstance(node, (ast.Import, ast.ImportFrom)) for node in nodes)
    loop_count = sum(
        isinstance(node, (ast.For, ast.AsyncFor, ast.While)) for node in nodes
    )
    conditional_count = sum(isinstance(node, ast.If) for node in nodes)
    return_count = sum(isinstance(node, ast.Return) for node in nodes)
    docstring_lines, docstring_count = _docstring_metadata(tree)

    (
        comment_lines,
        comment_count,
        analysis_error_type,
        analysis_error_message,
    ) = _comment_metadata(source)
    documented_lines = comment_lines | docstring_lines
    meaningful_lines = {
        line_number
        for line_number, line in enumerate(source.splitlines(), start=1)
        if line.strip()
    }
    comment_ratio = len(documented_lines) / len(meaningful_lines) if meaningful_lines else 0.0

    return ValidationResult(
        is_valid=True,
        node_count=len(nodes),
        has_comments=bool(comment_lines),
        has_docstrings=bool(docstring_count),
        comment_ratio=comment_ratio,
        function_count=function_count,
        class_count=class_count,
        import_count=import_count,
        loop_count=loop_count,
        conditional_count=conditional_count,
        return_count=return_count,
        comment_count=comment_count,
        docstring_count=docstring_count,
        analysis_error_type=analysis_error_type,
        analysis_error_message=analysis_error_message,
    )


def _docstring_metadata(tree: ast.AST) -> tuple[set[int], int]:
    """Return source lines and count for module/class/function docstrings."""
    lines: set[int] = set()
    count = 0
    docstring_owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)

    for node in ast.walk(tree):
        if not isinstance(node, docstring_owners) or not node.body:
            continue
        first_statement = node.body[0]
        if not _is_string_expression(first_statement):
            continue
        count += 1
        start_line = getattr(first_statement, "lineno", None)
        end_line = getattr(first_statement, "end_lineno", start_line)
        if start_line is not None and end_line is not None:
            lines.update(range(start_line, end_line + 1))

    return lines, count


def _is_string_expression(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _comment_metadata(
    source: str,
) -> tuple[set[int], int, str | None, str | None]:
    """Return comment lines/count and a non-fatal tokenizer error, if any."""
    comment_lines: set[int] = set()
    comment_count = 0
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type == tokenize.COMMENT:
                comment_count += 1
                start_line, _ = token.start
                end_line, _ = token.end
                comment_lines.update(range(start_line, end_line + 1))
    except (tokenize.TokenError, IndentationError, SyntaxError, UnicodeError) as error:
        logger.warning("Token analysis failed after successful AST parsing: %s", error)
        return comment_lines, comment_count, _ERROR_TOKENIZE, str(error)

    return comment_lines, comment_count, None, None


__all__ = ["ValidationResult", "validate_python"]
