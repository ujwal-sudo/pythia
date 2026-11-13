"""Tests for the Jupyter acquisition and Stage 3 filtering pipeline.

Network and the cloud mount are never touched: ``acquire_source`` and
``_verify_mount`` are replaced, and all writes go to temporary directories.
No notebook cell is executed.
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

import scripts.scrapers.jupyter_acquire as jupyter_acquire
from scripts.processors import notebook_policy as policy


def nb(*cells):
    return {"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": list(cells)}


def md(source):
    return {"cell_type": "markdown", "metadata": {}, "source": source}


def code(source):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": source}


def eligible_nb_doc():
    return nb(
        md("# Title"),
        md("## Explanation"),
        md("### More explanation"),
        code("def add(a, b):\n    return a + b\n"),
    )


def unparseable_bytes():
    return b"{not valid json"


def make_notebook_item(raw_bytes, path="nbs/demo.ipynb"):
    return {
        "original_path": path,
        "raw_sha256": jupyter_acquire.sha256_bytes(raw_bytes),
        "raw_size": len(raw_bytes),
        "raw_bytes": raw_bytes,
    }


class EvaluateNotebookTests(unittest.TestCase):
    def test_eligible_notebook_evaluates(self):
        source = {
            "source_family": "github",
            "source_name": "test__repo",
            "repository_id": "test/repo",
            "revision": "a" * 40,
            "canonical_url": "https://github.com/test/repo",
            "license": "MIT",
            "license_spdx": "MIT",
            "license_status": "APPROVED",
        }
        doc = eligible_nb_doc()
        raw_bytes = json.dumps(doc).encode("utf-8")
        record = jupyter_acquire.evaluate_notebook(
            doc,
            raw_sha256=jupyter_acquire.sha256_bytes(raw_bytes),
            raw_size=len(raw_bytes),
            source=source,
            original_path="nbs/demo.ipynb",
            run_id="run-1",
        )
        self.assertTrue(record["eligible"])
        self.assertEqual(record["markdown_count"], 3)
        self.assertEqual(record["total_cells"], 4)
        self.assertEqual(record["rejection_reasons"], [])
        self.assertTrue(record["record_id"].startswith("nb_"))
        self.assertEqual(record["license_spdx"], "MIT")

    def test_import_only_rejected(self):
        source = {
            "source_family": "github",
            "source_name": "test__repo",
            "repository_id": "test/repo",
            "revision": "a" * 40,
            "canonical_url": "https://github.com/test/repo",
            "license": "MIT",
            "license_spdx": "MIT",
            "license_status": "APPROVED",
        }
        doc = nb(md("# a"), md("# b"), code("import numpy as np\n"))
        record = jupyter_acquire.evaluate_notebook(
            doc,
            raw_sha256="x" * 64,
            raw_size=10,
            source=source,
            original_path="n.ipynb",
            run_id="run-1",
        )
        self.assertFalse(record["eligible"])
        self.assertTrue(any("meaningful" in r for r in record["rejection_reasons"]))


class DuplicateAuditTests(unittest.TestCase):
    def test_exact_duplicate_detected(self):
        records = [
            {"file_sha256": "a", "source_name": "s", "source_revision": "r", "original_path": "p1", "normalized_hash": "h1"},
            {"file_sha256": "a", "source_name": "s", "source_revision": "r", "original_path": "p2", "normalized_hash": "h2"},
        ]
        audit = jupyter_acquire.duplicate_audit(records)
        self.assertEqual(audit["exact_sha256_duplicates"]["duplicate_record_count"], 2)
        self.assertFalse(audit["destructive_deduplication_performed"])

    def test_no_duplicates(self):
        records = [
            {"file_sha256": "a", "source_name": "s", "source_revision": "r", "original_path": "p1", "normalized_hash": "h1"},
            {"file_sha256": "b", "source_name": "s", "source_revision": "r", "original_path": "p2", "normalized_hash": "h2"},
        ]
        audit = jupyter_acquire.duplicate_audit(records)
        self.assertEqual(audit["exact_sha256_duplicates"]["duplicate_group_count"], 0)


class WriteRefusalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_json_refuses_overwrite(self):
        path = self._dir / "out.json"
        jupyter_acquire._write_json(path, {"a": 1})
        with self.assertRaises(FileExistsError):
            jupyter_acquire._write_json(path, {"b": 2})

    def test_jsonl_refuses_overwrite(self):
        path = self._dir / "out.jsonl"
        jupyter_acquire._write_jsonl(path, [{"a": 1}])
        with self.assertRaises(FileExistsError):
            jupyter_acquire._write_jsonl(path, [{"b": 2}])


class ProcessOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.raw_root = base / "raw"
        self.filtered_root = base / "filtered"
        self.processed_root = base / "processed"

        self._orig_verify = jupyter_acquire._verify_mount
        self._orig_acquire = jupyter_acquire.acquire_source
        jupyter_acquire._verify_mount = lambda: None

        good_doc = eligible_nb_doc()
        bad_doc = nb(md("# a"), md("# b"), code("import os\n"))
        self.good_item = make_notebook_item(json.dumps(good_doc).encode("utf-8"), "nbs/good.ipynb")
        self.bad_item = make_notebook_item(json.dumps(bad_doc).encode("utf-8"), "nbs/bad.ipynb")
        self.broken_item = make_notebook_item(unparseable_bytes(), "nbs/broken.ipynb")

        def fake_acquire(source, clone_cache, raw_root, run_id, dry_run=False):
            manifest = {
                "source_name": source["source_name"],
                "revision": source["revision"],
                "notebook_count": 3,
                "license_file": None,
            }
            return [self.good_item, self.bad_item, self.broken_item], manifest

        jupyter_acquire.acquire_source = fake_acquire

    def tearDown(self):
        jupyter_acquire._verify_mount = self._orig_verify
        jupyter_acquire.acquire_source = self._orig_acquire
        self._tmp.cleanup()

    def _source(self):
        return {
            "source_family": "github",
            "source_name": "test__repo",
            "repository_id": "test/repo",
            "revision": "a" * 40,
            "canonical_url": "https://github.com/test/repo",
            "license": "MIT",
            "license_spdx": "MIT",
            "license_status": "APPROVED",
        }

    def test_process_reconciles_counts(self):
        report = jupyter_acquire.process(
            sources=[self._source()],
            raw_root=self.raw_root,
            filtered_root=self.filtered_root,
            processed_root=self.processed_root,
            run_id="test-run-001",
        )
        c = report["counts"]
        self.assertEqual(c["raw_notebooks_acquired"], 3)
        self.assertEqual(c["eligible_notebooks"], 1)
        self.assertEqual(c["rejected_notebooks"], 2)
        self.assertTrue(report["validation"]["count_reconciled"])

    def test_stage3_written(self):
        report = jupyter_acquire.process(
            sources=[self._source()],
            raw_root=self.raw_root,
            filtered_root=self.filtered_root,
            processed_root=self.processed_root,
            run_id="test-run-002",
        )
        stage3_files = list(self.filtered_root.glob("jupyter_stage3_v1_*.jsonl"))
        self.assertEqual(len(stage3_files), 1)
        lines = stage3_files[0].read_text().strip().splitlines()
        self.assertEqual(len(lines), 1)

    def test_run_dir_contains_reports(self):
        jupyter_acquire.process(
            sources=[self._source()],
            raw_root=self.raw_root,
            filtered_root=self.filtered_root,
            processed_root=self.processed_root,
            run_id="test-run-003",
        )
        run_dir = self.processed_root / "test-run-003"
        for name in ("quality_metrics.jsonl", "rejection_report.json",
                     "duplicate_report.json", "manifest.json", "final_report.md"):
            self.assertTrue((run_dir / name).exists(), name)

    def test_refuses_to_overwrite_run_dir(self):
        jupyter_acquire.process(
            sources=[self._source()],
            raw_root=self.raw_root,
            filtered_root=self.filtered_root,
            processed_root=self.processed_root,
            run_id="test-run-004",
        )
        with self.assertRaises(FileExistsError):
            jupyter_acquire.process(
                sources=[self._source()],
                raw_root=self.raw_root,
                filtered_root=self.filtered_root,
                processed_root=self.processed_root,
                run_id="test-run-004",
            )


if __name__ == "__main__":
    unittest.main()
