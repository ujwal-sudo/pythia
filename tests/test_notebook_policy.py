"""Tests for the Jupyter notebook selection policy (notebook_policy).

These tests use synthetic notebook fixtures only. No notebook cell is
executed and no network or filesystem access is required.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from scripts.processors import notebook_policy as policy
from scripts.processors.notebook_policy import NotebookError


def nb(*cells):
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": list(cells),
    }


def md(source):
    return {"cell_type": "markdown", "metadata": {}, "source": source}


def code(source):
    return {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": source,
    }


def raw(source):
    return {"cell_type": "raw", "metadata": {}, "source": source}


def nb_bytes(notebook):
    return json.dumps(notebook).encode("utf-8")


class ParsingTests(unittest.TestCase):
    def test_valid_notebook_parses(self):
        parsed = policy.parse_notebook_json(json.dumps(nb(md("# hi"))))
        self.assertEqual(parsed["nbformat"], 4)

    def test_invalid_json_raises(self):
        with self.assertRaises(NotebookError):
            policy.parse_notebook_json("{not json")

    def test_non_object_raises(self):
        with self.assertRaises(NotebookError):
            policy.parse_notebook_json("[1,2,3]")

    def test_missing_cells_raises(self):
        with self.assertRaises(NotebookError):
            policy.parse_notebook_json(json.dumps({"nbformat": 4}))

    def test_unsupported_nbformat_raises(self):
        with self.assertRaises(NotebookError):
            policy.parse_notebook_json(json.dumps({"nbformat": 3, "cells": []}))

    def test_empty_bytes_raise(self):
        with self.assertRaises(NotebookError):
            policy.parse_notebook_bytes(b"")

    def test_invalid_utf8_raises(self):
        with self.assertRaises(NotebookError):
            policy.parse_notebook_bytes(b"\xff\xfe\x00")


class CellCountTests(unittest.TestCase):
    def test_counts_by_type(self):
        counts = policy.count_cells(nb(md("a"), md("b"), code("x = 1"), raw("r")))
        self.assertEqual(counts["total"], 4)
        self.assertEqual(counts["markdown"], 2)
        self.assertEqual(counts["code"], 1)
        self.assertEqual(counts["raw"], 1)

    def test_empty_cells_counted(self):
        counts = policy.count_cells(nb(md(""), code("")))
        self.assertEqual(counts["empty"], 2)
        self.assertEqual(counts["empty_markdown"], 1)
        self.assertEqual(counts["empty_code"], 1)

    def test_list_of_strings_source_joined(self):
        cell = md(["# head", "ing"])
        self.assertEqual(policy.cell_source(cell), "# heading")


class MarkdownRatioTests(unittest.TestCase):
    def test_ratio_calculation(self):
        self.assertEqual(policy.markdown_proportion(3, 5), 0.6)
        self.assertEqual(policy.markdown_proportion(0, 0), 0.0)

    def test_strictly_greater_than_40_percent(self):
        self.assertTrue(policy.passes_markdown_ratio(3, 5))   # 0.60
        self.assertTrue(policy.passes_markdown_ratio(41, 100))  # 0.41

    def test_exactly_40_percent_is_ineligible(self):
        self.assertFalse(policy.passes_markdown_ratio(2, 5))   # 0.40
        self.assertFalse(policy.passes_markdown_ratio(40, 100))

    def test_zero_cells_is_ineligible(self):
        self.assertFalse(policy.passes_markdown_ratio(0, 0))


class MeaningfulPythonTests(unittest.TestCase):
    def test_function_is_meaningful(self):
        self.assertGreater(policy.meaningful_statement_count("def f():\n    return 1\n"), 0)

    def test_import_only_is_not_meaningful(self):
        self.assertEqual(policy.meaningful_statement_count("import os\nfrom x import y\n"), 0)

    def test_empty_and_invalid_are_zero(self):
        self.assertEqual(policy.meaningful_statement_count(""), 0)
        self.assertEqual(policy.meaningful_statement_count("def broken(:\n"), 0)

    def test_constant_expression_not_meaningful(self):
        self.assertEqual(policy.meaningful_statement_count("42\n"), 0)

    def test_call_is_meaningful(self):
        self.assertGreater(policy.meaningful_statement_count("print('hello')\n"), 0)

    def test_markdown_only_notebook_has_no_meaningful_python(self):
        analysis = policy.analyze_code_cells(nb(md("# a"), md("## b")))
        self.assertFalse(analysis["has_meaningful_python"])
        self.assertEqual(analysis["non_empty_code_cells"], 0)


class MagicTests(unittest.TestCase):
    def test_strips_line_magic(self):
        cleaned, had_magic = policy.strip_ipython_magics("%matplotlib inline\nx = 1\n")
        self.assertTrue(had_magic)
        self.assertNotIn("matplotlib", cleaned)
        self.assertIn("x = 1", cleaned)

    def test_strips_shell_bang(self):
        cleaned, had_magic = policy.strip_ipython_magics("!pip install x\ny = 2\n")
        self.assertTrue(had_magic)
        self.assertIn("y = 2", cleaned)

    def test_no_magic_no_change(self):
        cleaned, had_magic = policy.strip_ipython_magics("x = 1\n")
        self.assertFalse(had_magic)
        self.assertEqual(cleaned, "x = 1\n")


class ClassificationTests(unittest.TestCase):
    def test_numpy_classified_scientific(self):
        category, _ = policy.classify_notebook(nb(md("numpy and pandas tutorial"), code("import numpy")))
        self.assertEqual(category, policy.CATEGORY_SCIENTIFIC)

    def test_unknown_when_no_evidence(self):
        category, conf = policy.classify_notebook(nb(md("")))
        self.assertEqual(category, policy.CATEGORY_UNCERTAIN)
        self.assertEqual(conf, 0.0)


class OutputAndSecretTests(unittest.TestCase):
    def test_output_metrics(self):
        cell = code("x = 1")
        cell["outputs"] = [{"output_type": "stream", "text": "hi"}]
        metrics = policy.output_metrics(nb(cell))
        self.assertEqual(metrics["cells_with_outputs"], 1)
        self.assertGreater(metrics["total_output_bytes"], 0)

    def test_output_dominated_detection(self):
        cell = code("x = 1")
        cell["outputs"] = [{"output_type": "stream", "text": "x" * 300_000}]
        self.assertTrue(policy.output_metrics(nb(cell))["output_dominated"])

    def test_secret_screening(self):
        self.assertIn("aws_access_key", policy.screen_for_secrets("AKIAIOSFODNN7EXAMPLE"))

    def test_no_secrets_clean(self):
        self.assertEqual(policy.screen_for_secrets("print('ok')"), [])


class NormalizationAndHashTests(unittest.TestCase):
    def test_normalized_hash_deterministic(self):
        doc = nb(md("# t"), code("x = 1"))
        self.assertEqual(
            policy.normalized_notebook_hash(doc),
            policy.normalized_notebook_hash(doc),
        )

    def test_outputs_do_not_change_hash(self):
        a = nb(code("x = 1"))
        b = nb(code("x = 1"))
        b["cells"][0]["outputs"] = [{"output_type": "stream", "text": "big"}]
        self.assertEqual(
            policy.normalized_notebook_hash(a),
            policy.normalized_notebook_hash(b),
        )

    def test_markdown_difference_changes_hash(self):
        a = nb(md("# one"), code("x = 1"))
        b = nb(md("# two"), code("x = 1"))
        self.assertNotEqual(
            policy.normalized_notebook_hash(a),
            policy.normalized_notebook_hash(b),
        )


class EligibilityTests(unittest.TestCase):
    def _eligible_notebook(self):
        return nb(md("# a"), md("## b"), md("### c"), code("def add(a, b):\n    return a + b\n"))

    def test_eligible(self):
        result = policy.evaluate_policy(self._eligible_notebook())
        self.assertTrue(result.eligible)
        self.assertTrue(result.markdown_ratio_passes)
        self.assertTrue(result.has_meaningful_python)
        self.assertEqual(result.total_cells, 4)
        self.assertEqual(result.markdown_count, 3)

    def test_zero_cells_rejected(self):
        result = policy.evaluate_policy(nb())
        self.assertFalse(result.eligible)
        self.assertIn("zero_cells", result.reasons_ineligible)

    def test_exactly_40_percent_rejected(self):
        doc = nb(md("a"), md("b"), code("x=1"), code("y=2"), code("z=3"))
        result = policy.evaluate_policy(doc)
        self.assertFalse(result.eligible)
        self.assertTrue(any("markdown_proportion" in r for r in result.reasons_ineligible))

    def test_markdown_only_rejected(self):
        result = policy.evaluate_policy(nb(md("# a"), md("## b")))
        self.assertFalse(result.eligible)
        self.assertIn("no_meaningful_python", result.reasons_ineligible)

    def test_report_numerator_denominator_proportion(self):
        result = policy.evaluate_policy(self._eligible_notebook())
        self.assertEqual(result.markdown_count, 3)
        self.assertEqual(result.total_cells, 4)
        self.assertAlmostEqual(result.markdown_proportion, 0.75)


if __name__ == "__main__":
    unittest.main()
