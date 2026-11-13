"""Tests for prose-plus-code acquisition (license-first, no execution).

Synthetic reStructuredText and HTML fixtures only. No network access and no
downloaded code is executed.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

import scripts.scrapers.prose_plus_code as ppc
from scripts.scrapers.prose_plus_code import (
    APPROVED_SOURCES,
    LICENSE_APPROVED,
    LICENSE_REVIEW_REQUIRED,
    SOURCE_INVENTORY,
    Unit,
    build_records,
    classify_pep_license,
    html_units,
    parse_rst,
)


LONG_PROSE = (
    "This section explains why readable code matters for everybody and offers "
    "enough words to count as meaningful explanatory prose. Clear names and "
    "small functions help readers understand the intent of a program."
)


def _source(**overrides):
    source = {
        "source_name": "peps",
        "kind": "rst_git",
        "repo": "https://github.com/python/peps.git",
        "repo_owner": "python",
        "repo_name": "peps",
        "ref": "main",
        "documentation_version": None,
        "license": "Public domain / CC0-1.0",
        "license_spdx": "CC0-1.0",
        "license_status": LICENSE_APPROVED,
        "license_url": "https://example.org/LICENSE",
        "license_evidence": "verified",
        "decision": "ACCEPT",
    }
    source.update(overrides)
    return source


def _license(**overrides):
    info = {
        "license": "Public domain / CC0-1.0",
        "license_spdx": "CC0-1.0",
        "license_status": LICENSE_APPROVED,
        "license_url": "https://example.org/LICENSE",
        "license_evidence": "verified",
    }
    info.update(overrides)
    return info


RST_DOC = """==========
Style Guide
==========

PEP: 8
Title: Style Guide for Python Code
Author: Guido van Rossum
Status: Active

Introduction
============

This section explains why readable code matters for everybody and offers enough words to count as meaningful explanatory prose.

Example
-------

Use the following function::

    def add(a, b):
        return a + b

.. code-block:: python

    def multiply(a, b):
        return a * b

.. code-block:: bash

    pip install black

.. doctest::

    >>> add(1, 2)
    3

.. note::

    Notes are explanatory prose and should be kept in the corpus.

.. toctree::
   :maxdepth: 2

   hidden-page

See `the style guide <https://example.org/style>`_ and :pep:`8` for ``details``.

Copyright
=========

This document is placed in the public domain or under the CC0-1.0-Universal license, whichever is more permissive.
"""

HTML_DOC = """<html><head><title>Docs</title></head><body>
<nav>Navigation junk</nav>
<aside class="sphinxsidebar">Sidebar junk</aside>
<main>
  <h1>My Page</h1>
  <p>This is explanatory prose about arrays and how they work in practice.</p>
  <h2>Examples</h2>
  <div class="highlight-python notranslate"><div class="highlight"><pre>
<span class="k">import</span> <span class="nn">numpy</span> <span class="k">as</span> <span class="nn">np</span>
<span class="n">x</span> <span class="o">=</span> <span class="n">np</span><span class="o">.</span><span class="n">array</span><span class="p">([</span><span class="mi">1</span><span class="p">,</span> <span class="mi">2</span><span class="p">])</span>
</pre></div></div>
  <div class="highlight-bash notranslate"><div class="highlight"><pre>pip install numpy</pre></div></div>
  <div class="highlight-pycon notranslate"><div class="highlight"><pre>&gt;&gt;&gt; 1 + 1
2</pre></div></div>
</main>
<footer>Footer junk</footer>
</body></html>"""


class InventoryTests(unittest.TestCase):
    def test_four_sources_approved(self):
        names = {s["source_name"] for s in SOURCE_INVENTORY}
        self.assertEqual(
            names,
            {"peps", "cpython_devguide", "scikit_learn_docs", "sympy_docs"},
        )
        self.assertEqual(len(APPROVED_SOURCES), 4)
        self.assertTrue(all(s["license_status"] == LICENSE_APPROVED for s in APPROVED_SOURCES))

    def test_peps_use_per_document_license(self):
        decisions = {s["source_name"]: s["per_document_license"] for s in SOURCE_INVENTORY}
        self.assertTrue(decisions["peps"])
        self.assertFalse(decisions["cpython_devguide"])
        self.assertFalse(decisions["scikit_learn_docs"])
        self.assertFalse(decisions["sympy_docs"])

    def test_evidence_present(self):
        for source in SOURCE_INVENTORY:
            self.assertTrue(source["license_evidence"])
            self.assertTrue(source["license_url"])
            self.assertTrue(source["license_spdx"])


class RstParsingTests(unittest.TestCase):
    def test_page_title_and_sections(self):
        units = parse_rst(RST_DOC)
        self.assertTrue(units)
        self.assertEqual(units[0].page_title, "Style Guide")
        titles = [u.title for u in units]
        self.assertIn("Introduction", titles)
        self.assertIn("Example", titles)
        self.assertIn("Copyright", titles)

    def test_pep_metadata_is_not_prose(self):
        units = parse_rst(RST_DOC)
        prose = "\n".join(p for u in units for p in u.paragraphs)
        self.assertNotIn("Guido van Rossum", prose)
        self.assertNotIn("Title: Style Guide", prose)

    def test_python_code_blocks_only(self):
        units = parse_rst(RST_DOC)
        blocks = [c for u in units for c in u.code_blocks]
        codes = [c["code"] for c in blocks]
        self.assertTrue(any("def add" in c for c in codes))
        self.assertTrue(any("def multiply" in c for c in codes))
        self.assertFalse(any("pip install" in c for c in codes))
        for block in blocks:
            self.assertEqual(block["language"], "python")
            self.assertFalse(block["code"].startswith("\n"))

    def test_doctest_prompts_are_stripped(self):
        units = parse_rst(RST_DOC)
        codes = [c["code"] for u in units for c in u.code_blocks]
        self.assertIn("add(1, 2)", codes)

    def test_note_kept_and_toctree_skipped(self):
        units = parse_rst(RST_DOC)
        prose = "\n".join(p for u in units for p in u.paragraphs)
        self.assertIn("Notes are explanatory prose", prose)
        self.assertNotIn("hidden-page", prose)
        self.assertNotIn("maxdepth", prose)

    def test_inline_markup_cleaned(self):
        units = parse_rst(RST_DOC)
        prose = "\n".join(p for u in units for p in u.paragraphs)
        self.assertIn("the style guide", prose)
        self.assertIn("details", prose)
        self.assertNotIn("<https://example.org/style>", prose)
        self.assertNotIn("``", prose)

    def test_highlight_state_suppresses_non_python_literal(self):
        doc = """
Title
=====

Some explanation of a shell command::

.. highlight:: bash

Run this::

    ls -la
"""
        units = parse_rst(doc)
        codes = [c["code"] for u in units for c in u.code_blocks]
        self.assertFalse(any("ls -la" in c for c in codes))


class HtmlParsingTests(unittest.TestCase):
    def test_page_title_and_sections(self):
        units = html_units(HTML_DOC, "https://example.org/page.html")
        self.assertTrue(units)
        self.assertEqual(units[0].page_title, "My Page")
        self.assertEqual(units[0].title, "My Page")
        self.assertIn("Examples", [u.title for u in units])

    def test_noise_removed(self):
        units = html_units(HTML_DOC)
        prose = "\n".join(p for u in units for p in u.paragraphs)
        self.assertNotIn("Navigation junk", prose)
        self.assertNotIn("Sidebar junk", prose)
        self.assertNotIn("Footer junk", prose)

    def test_python_code_extracted_once(self):
        units = html_units(HTML_DOC)
        codes = [c["code"] for u in units for c in u.code_blocks]
        self.assertEqual(sum("np.array" in c for c in codes), 1)
        self.assertFalse(any("pip install" in c for c in codes))

    def test_html_doctest_detected(self):
        units = html_units(HTML_DOC)
        detections = [c["detection_method"] for u in units for c in u.code_blocks]
        self.assertIn("html:doctest", detections)
        self.assertIn("html:explicit_python", detections)


class LicenseTests(unittest.TestCase):
    def test_public_domain_approved(self):
        info = classify_pep_license(RST_DOC)
        self.assertEqual(info["license_status"], LICENSE_APPROVED)
        self.assertEqual(info["license_spdx"], "CC0-1.0")

    def test_cc0_approved(self):
        text = "Copyright\n=========\n\nThis document is licensed under CC0-1.0.\n"
        self.assertEqual(classify_pep_license(text)["license_status"], LICENSE_APPROVED)

    def test_unexpected_copyright_requires_review(self):
        text = "Copyright\n=========\n\nAll rights reserved by the author.\n"
        info = classify_pep_license(text)
        self.assertEqual(info["license_status"], LICENSE_REVIEW_REQUIRED)
        self.assertEqual(info["license_spdx"], "UNKNOWN")

    def test_missing_copyright_requires_review(self):
        info = classify_pep_license("A document with no copyright section at all.\n")
        self.assertEqual(info["license_status"], LICENSE_REVIEW_REQUIRED)


class BuildRecordsTests(unittest.TestCase):
    def _build(self, unit, **kwargs):
        kwargs.setdefault("min_prose_tokens", 10)
        kwargs.setdefault("max_unit_tokens", 2048)
        return build_records(
            source=_source(),
            unit=unit,
            page_path="peps/pep-0008.rst",
            page_url="https://github.com/python/peps/blob/deadbeef/peps/pep-0008.rst",
            source_version="deadbeef",
            license_info=_license(),
            acquisition_date="2026-10-22T00:00:00+00:00",
            **kwargs,
        )

    def test_prose_with_code_record(self):
        unit = Unit(title="Example", level=1, order=1, page_title="Style Guide")
        unit.paragraphs.append(LONG_PROSE)
        unit.code_blocks.append(
            {"code": "def add(a, b):\n    return a + b\n", "language": "python", "detection_method": "rst:code-block"}
        )
        records, rejects = self._build(unit)
        self.assertEqual(len(records), 1)
        self.assertEqual(rejects, [])
        record = records[0]
        self.assertEqual(record["source"], "peps")
        self.assertEqual(record["source_type"], "raw")
        self.assertEqual(record["license_status"], LICENSE_APPROVED)
        self.assertEqual(record["page_title"], "Style Guide")
        self.assertEqual(record["section_title"], "Example")
        self.assertEqual(record["pairing"], "prose_with_code")
        self.assertTrue(record["has_code"])
        self.assertEqual(record["code_block_count"], 1)
        self.assertTrue(record["code_blocks"][0]["ast_valid"])
        self.assertTrue(record["record_id"].startswith("prose_"))
        self.assertEqual(len(record["record_id"]), len("prose_") + 24)
        for field in (
            "source", "source_type", "source_url", "record_id", "content_hash",
            "acquisition_date", "license", "license_status", "prose",
            "prose_token_count", "total_token_count", "token_count_status",
            "page_path", "provenance", "validator_version", "pipeline_version",
        ):
            self.assertIn(field, record, field)
        self.assertEqual(record["token_count_status"], "PROVISIONAL")

    def test_prose_only_record(self):
        unit = Unit(title="Intro", level=1, order=1, paragraphs=[LONG_PROSE])
        records, _ = self._build(unit)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["pairing"], "prose_only")
        self.assertFalse(records[0]["has_code"])
        self.assertEqual(records[0]["code_token_count"], 0)

    def test_short_prose_rejected(self):
        unit = Unit(title="Stub", level=1, order=1, paragraphs=["Too short."])
        records, rejects = self._build(unit)
        self.assertEqual(records, [])
        self.assertEqual(len(rejects), 1)
        reasons = rejects[0]["rejection_reasons"]
        self.assertTrue(any(r.startswith("prose_too_short") for r in reasons))

    def test_empty_prose_rejected(self):
        unit = Unit(
            title="Code only", level=1, order=1,
            code_blocks=[{"code": "x = 1\n", "language": "python", "detection_method": "rst:literal"}],
        )
        records, rejects = self._build(unit)
        self.assertEqual(records, [])
        self.assertIn("empty_prose", rejects[0]["rejection_reasons"])

    def test_invalid_code_counted_and_dropped(self):
        unit = Unit(title="Broken", level=1, order=1, paragraphs=[LONG_PROSE])
        unit.code_blocks.append(
            {"code": "def broken(:\n", "language": "python", "detection_method": "rst:code-block"}
        )
        records, _ = self._build(unit)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["invalid_code_block_count"], 1)
        self.assertFalse(records[0]["has_code"])
        self.assertEqual(records[0]["pairing"], "prose_only")

    def test_duplicate_code_blocks_deduped(self):
        unit = Unit(title="Dup", level=1, order=1, paragraphs=[LONG_PROSE])
        block = {"code": "x = 1\n", "language": "python", "detection_method": "rst:literal"}
        unit.code_blocks.extend([block, dict(block)])
        records, _ = self._build(unit)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["code_block_count"], 1)
        self.assertEqual(records[0]["skipped_code_block_count"], 1)

    def test_chunking_attaches_code_once(self):
        unit = Unit(title="Long", level=1, order=1)
        unit.paragraphs.extend([f"{LONG_PROSE} Part {index}." for index in range(6)])
        unit.code_blocks.append(
            {"code": "x = 1\n", "language": "python", "detection_method": "rst:literal"}
        )
        records, _ = self._build(unit, max_unit_tokens=120)
        self.assertGreater(len(records), 1)
        self.assertTrue(records[0]["has_code"])
        self.assertTrue(all(not r["has_code"] for r in records[1:]))
        self.assertEqual(records[0]["chunk_count"], len(records))
        self.assertEqual([r["chunk_index"] for r in records], list(range(len(records))))
        self.assertEqual(len({r["content_hash"] for r in records}), len(records))
        self.assertEqual(len({r["record_id"] for r in records}), len(records))

    def test_content_hash_matches_content(self):
        unit = Unit(title="Hash", level=1, order=1, paragraphs=[LONG_PROSE])
        records, _ = self._build(unit)
        expected = ppc._sha256_text(records[0]["prose"])
        self.assertEqual(records[0]["content_hash"], expected)

    def test_code_too_long_rejected(self):
        unit = Unit(title="Huge code", level=1, order=1, paragraphs=[LONG_PROSE])
        unit.code_blocks.append(
            {"code": "x = 1\ny = 2\nz = 3\n", "language": "python", "detection_method": "rst:literal"}
        )
        records, rejects = self._build(unit, max_unit_tokens=2)
        self.assertEqual(records, [])
        self.assertTrue(any(r["rejection_reasons"][0].startswith("code_too_long") for r in rejects))


class SplitProseTests(unittest.TestCase):
    def test_chunks_respect_limit(self):
        prose = " ".join(["This sentence has several words."] * 50)
        chunks = ppc._split_prose(prose, max_tokens=20)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 20 * 4 for c in chunks))

    def test_long_token_is_not_truncated(self):
        prose = "x" * 500
        chunks = ppc._split_prose(prose, max_tokens=20)
        self.assertEqual("".join(chunks), prose)


class ProcessSourceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = Path(self._tmp.name)
        self._raw = self._dir / "raw"
        self._raw.mkdir()
        self._out = self._dir / "out"

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name: str, body: str) -> None:
        path = self._raw / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def _acquisition(self):
        return {
            "raw_dir": self._raw,
            "content_path": self._raw,
            "source_version": "deadbeef",
            "manifest": {},
        }

    def test_per_document_license_gate(self):
        approved = RST_DOC
        unapproved = RST_DOC.replace(
            "This document is placed in the public domain or under the CC0-1.0-Universal license, whichever is more permissive.",
            "All rights reserved. Redistribution is not permitted.",
        )
        self._write("pep-approved.rst", approved)
        self._write("pep-review.rst", unapproved)
        result = ppc.process_source(
            _source(per_document_license=True), self._acquisition(), output_dir=self._out,
        )
        self.assertGreaterEqual(result["stats"]["accepted"], 1)
        rejected = [
            json.loads(line)
            for line in Path(result["rejected_path"]).read_text().splitlines()
        ]
        self.assertTrue(any("license_not_approved" in r["rejection_reasons"] for r in rejected))
        accepted = [
            json.loads(line)
            for line in Path(result["accepted_path"]).read_text().splitlines()
        ]
        self.assertTrue(all(r["license_status"] == LICENSE_APPROVED for r in accepted))

    def test_exact_duplicates_removed_across_documents(self):
        self._write("a.rst", RST_DOC)
        self._write("b.rst", RST_DOC)
        result = ppc.process_source(
            _source(per_document_license=True), self._acquisition(), output_dir=self._out,
        )
        self.assertGreaterEqual(result["stats"]["exact_duplicates"], 1)
        accepted = Path(result["accepted_path"]).read_text().splitlines()
        self.assertEqual(len(accepted), result["stats"]["accepted"])

    def test_source_level_review_license_rejects_all(self):
        self._write("a.rst", RST_DOC)
        source = _source(per_document_license=False, license_status=LICENSE_REVIEW_REQUIRED)
        result = ppc.process_source(source, self._acquisition(), output_dir=self._out)
        self.assertEqual(result["stats"]["accepted"], 0)
        self.assertGreater(result["stats"]["rejected"], 0)

    def test_output_schema_and_refuse_overwrite(self):
        self._write("a.rst", RST_DOC)
        result = ppc.process_source(
            _source(per_document_license=True), self._acquisition(), output_dir=self._out,
        )
        records = [
            json.loads(line)
            for line in Path(result["accepted_path"]).read_text().splitlines()
        ]
        self.assertTrue(records)
        self.assertTrue(all(r["record_id"].startswith("prose_") for r in records))
        with self.assertRaises(FileExistsError):
            ppc.process_source(
                _source(per_document_license=True), self._acquisition(), output_dir=self._out,
            )


class IterDocumentsTests(unittest.TestCase):
    def test_rst_iteration_provenance_and_skips(self):
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td)
            (raw / "peps").mkdir()
            (raw / "peps" / "pep-0001.rst").write_text("Title\n=====\n", encoding="utf-8")
            (raw / ".git").mkdir()
            (raw / ".git" / "junk.rst").write_text("junk", encoding="utf-8")
            acquisition = {"raw_dir": raw, "content_path": raw, "source_version": "abc123", "manifest": {}}
            docs = list(ppc.iter_documents(_source(docs_glob="peps/*.rst"), acquisition))
            self.assertEqual(len(docs), 1)
            path, text, url = docs[0]
            self.assertEqual(path, "peps/pep-0001.rst")
            self.assertIn("/blob/abc123/peps/pep-0001.rst", url)
            self.assertIn("Title", text)

    def test_license_file_hash(self):
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td)
            (raw / "LICENSE").write_text("CC0", encoding="utf-8")
            info = ppc._license_file_hash(raw)
            self.assertEqual(info["path"], "LICENSE")
            self.assertEqual(info["bytes"], 3)
            self.assertEqual(len(info["sha256"]), 64)


class WriterTests(unittest.TestCase):
    def test_write_json_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "m.json"
            ppc._write_json(path, {"a": 1})
            self.assertEqual(json.loads(path.read_text()), {"a": 1})
            with self.assertRaises(FileExistsError):
                ppc._write_json(path, {"b": 2})
            self.assertFalse(path.with_name("m.json.tmp").exists())

    def test_write_jsonl_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "r.jsonl"
            ppc._write_jsonl(path, [{"a": 1}])
            self.assertEqual(path.read_text().strip(), '{"a":1}')
            with self.assertRaises(FileExistsError):
                ppc._write_jsonl(path, [{"b": 2}])
            self.assertFalse(path.with_name("r.jsonl.tmp").exists())


class DryRunTests(unittest.TestCase):
    def test_dry_run_no_network_no_write(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            report = ppc.process(
                sources=APPROVED_SOURCES,
                raw_root=base / "raw",
                stage1_root=base / "stage1",
                run_id="test-dry-run-001",
                dry_run=True,
            )
            self.assertTrue(report["dry_run"])
            self.assertEqual(report["counts"]["sources_processed"], 4)
            self.assertFalse((base / "raw").exists())
            self.assertFalse((base / "stage1").exists())


if __name__ == "__main__":
    unittest.main()
