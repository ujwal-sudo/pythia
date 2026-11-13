"""Tests for scientific-docs acquisition (license-first, no execution).

Uses synthetic HTML-archive fixtures only. No network access and no
downloaded code is executed.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from bs4 import BeautifulSoup

import scripts.scrapers.scientific_docs as sci
from scripts.scrapers.scientific_docs import (
    SOURCE_INVENTORY,
    detect_python_block,
    iter_python_blocks,
)


def _div(html_snippet: str):
    return BeautifulSoup(html_snippet, "html.parser").find("div")


class InventoryTests(unittest.TestCase):
    def test_four_sources_audited(self):
        names = {s["source_name"] for s in SOURCE_INVENTORY}
        self.assertEqual(
            names,
            {"numpy_docs", "scipy_docs", "pandas_docs", "matplotlib_docs"},
        )

    def test_accept_and_hold_decisions(self):
        decisions = {s["source_name"]: s["decision"] for s in SOURCE_INVENTORY}
        self.assertEqual(decisions["numpy_docs"], "ACCEPT")
        self.assertEqual(decisions["scipy_docs"], "ACCEPT")
        self.assertEqual(decisions["pandas_docs"], "ACCEPT")
        self.assertEqual(decisions["matplotlib_docs"], "HOLD")

    def test_approved_has_download_urls(self):
        approved = sci.APPROVED_SOURCES
        self.assertEqual(len(approved), 3)
        self.assertTrue(all(s["download_url"] for s in approved))

    def test_hold_source_has_no_download_url(self):
        mpl = next(s for s in SOURCE_INVENTORY if s["source_name"] == "matplotlib_docs")
        self.assertIsNone(mpl["download_url"])


class DetectionTests(unittest.TestCase):
    def test_python_block_detected(self):
        block = _div('<div class="highlight-python notranslate"><pre>x = 1</pre></div>')
        self.assertEqual(detect_python_block(block, "x = 1"), "explicit_python")

    def test_default_block_detected(self):
        block = _div('<div class="highlight notranslate"><pre>x = 1</pre></div>')
        self.assertEqual(detect_python_block(block, "x = 1"), "default_python")

    def test_pycon_doctest_detected(self):
        block = _div('<div class="highlight-pycon notranslate"><pre>&gt;&gt;&gt; 1+1</pre></div>')
        self.assertEqual(detect_python_block(block, ">>> 1+1"), "doctest")

    def test_bash_block_skipped(self):
        block = _div('<div class="highlight-bash notranslate"><pre>ls</pre></div>')
        self.assertIsNone(detect_python_block(block, "ls"))


def _make_zip(path: Path) -> None:
    html = (
        "<html><body>"
        '<div class="highlight-python notranslate"><div class="highlight"><pre>'
        "def add(a, b):\n    return a + b\n"
        "</pre></div></div>"
        '<div class="highlight-bash notranslate"><div class="highlight"><pre>'
        "pip install numpy\n"
        "</pre></div></div>"
        "</body></html>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("docs/index.html", html)


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = Path(self._tmp.name)
        self._zip = self._dir / "docs.zip"
        _make_zip(self._zip)

    def tearDown(self):
        self._tmp.cleanup()

    def test_extracts_python_and_skips_bash(self):
        blocks = list(iter_python_blocks(self._zip, "https://example.org/"))
        codes = [b.code for b in blocks]
        self.assertTrue(any("def add" in c for c in codes))
        self.assertFalse(any("pip install" in c for c in codes))

    def test_no_duplicate_pre_from_nested_divs(self):
        blocks = list(iter_python_blocks(self._zip, "https://example.org/"))
        add_blocks = [b for b in blocks if "def add" in b.code]
        self.assertEqual(len(add_blocks), 1)


class ProcessSourceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = Path(self._tmp.name)
        self._zip = self._dir / "docs.zip"
        _make_zip(self._zip)

    def tearDown(self):
        self._tmp.cleanup()

    def test_process_retains_valid_and_skips_bash(self):
        source = next(s for s in SOURCE_INVENTORY if s["source_name"] == "numpy_docs")
        output = self._dir / "out.jsonl"
        result = sci.process_source(
            source,
            self._zip,
            output_path=output,
            min_tokens=1,
            max_tokens=10000,
            min_comment_ratio=0.0,
            pep8_max_violations=100,
        )
        self.assertGreaterEqual(result["stats"]["retained"], 1)
        self.assertTrue(output.exists())
        lines = output.read_text().strip().splitlines()
        self.assertEqual(len(lines), result["stats"]["retained"])
        codes = [json.loads(line)["code"] for line in lines]
        self.assertTrue(any("def add" in c for c in codes))
        self.assertFalse(any("pip install" in c for c in codes))

    def test_record_schema_fields(self):
        source = next(s for s in SOURCE_INVENTORY if s["source_name"] == "numpy_docs")
        output = self._dir / "out.jsonl"
        sci.process_source(
            source, self._zip, output_path=output,
            min_tokens=1, max_tokens=10000, min_comment_ratio=0.0, pep8_max_violations=100,
        )
        record = json.loads(output.read_text().splitlines()[0])
        for field in ("id", "code", "source", "stage", "documentation_version",
                      "source_url", "license", "license_spdx", "license_url",
                      "provisional_token_count", "token_count_method", "comment_ratio",
                      "pep8_violations", "syntax_valid", "exact_hash", "detection_method",
                      "ast_metadata"):
            self.assertIn(field, record, field)
        self.assertEqual(record["source"], "numpy_docs")
        self.assertEqual(record["license_spdx"], "BSD-3-Clause")
        self.assertTrue(record["syntax_valid"])


class WriteRefusalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_download_refuses_existing_target(self):
        source = next(s for s in SOURCE_INVENTORY if s["source_name"] == "numpy_docs")
        target = self._dir / "raw" / f"numpy_docs__{source['documentation_version']}"
        target.mkdir(parents=True)
        with self.assertRaises(FileExistsError):
            sci.download_archive(source, destination_root=self._dir / "raw")

    def test_write_json_refuses_overwrite(self):
        path = self._dir / "m.json"
        sci._write_json(path, {"a": 1})
        with self.assertRaises(FileExistsError):
            sci._write_json(path, {"b": 2})


class DryRunTests(unittest.TestCase):
    def test_dry_run_no_network_no_write(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            report = sci.process(
                sources=sci.APPROVED_SOURCES,
                raw_root=base / "raw",
                stage1_root=base / "stage1",
                run_id="test-dry-run-001",
                dry_run=True,
            )
            self.assertTrue(report["dry_run"])
            self.assertEqual(report["counts"]["sources_processed"], 3)
            self.assertFalse((base / "raw").exists())


if __name__ == "__main__":
    unittest.main()
