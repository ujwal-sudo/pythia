"""Tests for the prose-plus-code documentation extractor.

Uses synthetic reStructuredText and local git fixtures only. No network
access, no downloaded code is executed.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

import scripts.scrapers.prose_docs as prose
from scripts.scrapers.prose_docs import (
    APPROVED_SOURCES,
    SOURCE_INVENTORY,
    _admonition_label,
    _git,
    _split_segments,
    build_records,
    acquire_repo,
    discover_documents,
    find_headings,
    parse_blocks,
    resolve_includes,
    split_sections,
)


PEP_TEXT = """PEP: 8
Title: Example PEP
Author: Someone

================================
PEP 8 -- Example Title
================================

Introduction
------------

This introduction explains the motivation for the example in enough detail
that it clears the minimum prose threshold for retention.

Example
-------

The following function demonstrates the pattern in a small and readable way so that the prose is kept next to the code::

    def add(a, b):
        return a + b

Call the function with two integers to obtain their sum.

Copyright
=========

This document is placed in the public domain or under the
CC0-1.0-Universal license, whichever is more permissive.
"""


def _make_repo(root: Path, files: dict[str, str], branch: str = "main") -> Path:
    repo = root / "origin"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", branch], cwd=repo, check=True)
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            "commit",
            "-q",
            "-m",
            "fixture",
        ],
        cwd=repo,
        check=True,
    )
    return repo


def _source(**overrides):
    base = {
        "source_name": "peps",
        "project": "Python Enhancement Proposals",
        "source_family": "official_documentation",
        "decision": "ACCEPT",
        "license": "Public domain / CC0-1.0",
        "license_spdx": "CC0-1.0",
        "license_url": "https://peps.python.org/pep-0001/",
        "license_evidence": "fixture",
        "repo_url": "https://github.com/python/peps",
        "ref": "main",
        "raw_subdir": "peps",
        "document_glob": "repo/pep-*.rst",
        "exclude_globs": [],
        "source_url": "https://peps.python.org/",
        "documentation_version": "git:main",
    }
    base.update(overrides)
    return base


class InventoryTests(unittest.TestCase):
    def test_two_sources_approved(self):
        names = {s["source_name"] for s in SOURCE_INVENTORY}
        self.assertEqual(names, {"peps", "cpython_devguide"})

    def test_all_approved_are_cc0(self):
        self.assertEqual(len(APPROVED_SOURCES), 2)
        for source in APPROVED_SOURCES:
            self.assertEqual(source["decision"], "ACCEPT")
            self.assertEqual(source["license_spdx"], "CC0-1.0")

    def test_devguide_excludes_readme_and_include(self):
        devguide = next(s for s in SOURCE_INVENTORY if s["source_name"] == "cpython_devguide")
        self.assertIn("repo/README.rst", devguide["exclude_globs"])
        self.assertIn("repo/include/**", devguide["exclude_globs"])


class HeadingTests(unittest.TestCase):
    def test_overline_and_underlines_build_paths(self):
        lines = PEP_TEXT.expandtabs(4).splitlines()
        headings = find_headings(lines)
        self.assertTrue(headings[0].overline)
        self.assertEqual(headings[0].title, "PEP 8 -- Example Title")
        title, preamble, sections = split_sections(lines)
        self.assertEqual(title, "PEP 8 -- Example Title")
        self.assertTrue(any("PEP: 8" in line for line in preamble))
        paths = [section.path for section in sections]
        self.assertIn(["PEP 8 -- Example Title", "Introduction"], paths)
        self.assertIn(["PEP 8 -- Example Title", "Example"], paths)


class BlockParsingTests(unittest.TestCase):
    def test_literal_block_keeps_order(self):
        body = [
            "Use the following snippet::",
            "",
            "    x = 1",
            "    y = 2",
            "",
            "The values are then used later.",
        ]
        segments = parse_blocks(body)
        self.assertEqual([s.kind for s in segments], ["prose", "code", "prose"])
        self.assertIn("x = 1", segments[1].text)
        self.assertEqual(segments[1].language, "python")

    def test_code_block_strips_options(self):
        body = [
            ".. code-block:: python",
            "   :linenos:",
            "",
            "   def f():",
            "       return 1",
        ]
        segments = parse_blocks(body)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].kind, "code")
        self.assertEqual(segments[0].text, "def f():\n    return 1")
        self.assertEqual(segments[0].language, "python")

    def test_doctest_is_pycon(self):
        body = [
            ".. doctest::",
            "",
            "   >>> 1 + 1",
            "   2",
        ]
        segments = parse_blocks(body)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].kind, "code")
        self.assertEqual(segments[0].language, "pycon")
        self.assertIn(">>> 1 + 1", segments[0].text)

    def test_tab_container_keeps_label_and_nested_code(self):
        body = [
            ".. tab:: Linux",
            "",
            "   .. code-block:: bash",
            "",
            "      echo hi",
        ]
        segments = parse_blocks(body)
        self.assertEqual(segments[0].kind, "prose")
        self.assertEqual(segments[0].text, "Linux:")
        self.assertEqual(segments[1].kind, "code")
        self.assertEqual(segments[1].language, "bash")
        self.assertEqual(segments[1].text, "echo hi")

    def test_admonition_and_versions_labelled(self):
        self.assertEqual(_admonition_label("note", "careful"), "Note: careful")
        self.assertEqual(_admonition_label("versionadded", "3.10"), "New in version 3.10.")
        self.assertEqual(_admonition_label("versionchanged", "3.12"), "Changed in version 3.12.")
        self.assertEqual(_admonition_label("deprecated", "4.0"), "Deprecated since version 4.0.")
        self.assertEqual(_admonition_label("note", ""), "Note:")

    def test_prose_reflows_wrapped_lines(self):
        segments = parse_blocks(["This sentence is wrapped", "across two lines."])
        self.assertEqual(segments[0].text, "This sentence is wrapped across two lines.")

    def test_prose_keeps_list_structure(self):
        segments = parse_blocks(["- first item", "- second item"])
        self.assertEqual(segments[0].text, "- first item\n- second item")

    def test_unknown_directive_keeps_argument_and_body(self):
        body = [
            ".. custom-thing:: Some argument",
            "",
            "   Body prose that is kept.",
        ]
        segments = parse_blocks(body)
        self.assertIn("custom thing: Some argument", segments[0].text)
        self.assertIn("Body prose that is kept.", segments[1].text)

    def test_footnote_references_removed(self):
        segments = parse_blocks(["Use a hanging indent [#fn-hi]_ for clarity."])
        self.assertEqual(segments[0].text, "Use a hanging indent for clarity.")

    def test_skipped_directives_emit_nothing(self):
        body = [
            ".. image:: picture.png",
            "",
            ".. toctree::",
            "   :maxdepth: 2",
            "",
            "   child",
        ]
        self.assertEqual(parse_blocks(body), [])


class IncludeTests(unittest.TestCase):
    def test_relative_and_absolute_includes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "include").mkdir()
            (root / "include" / "shared.rst").write_text("Absolute shared content.", encoding="utf-8")
            (root / "sub").mkdir()
            (root / "sub" / "local.rst").write_text("Relative content.", encoding="utf-8")
            text = ".. include:: local.rst\n\n.. include:: /include/shared.rst"
            resolved = resolve_includes(text, root / "sub", root)
            self.assertIn("Relative content.", resolved)
            self.assertIn("Absolute shared content.", resolved)

    def test_include_cycle_terminates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.rst").write_text("A\n.. include:: b.rst\n", encoding="utf-8")
            (root / "b.rst").write_text("B\n.. include:: a.rst\n", encoding="utf-8")
            resolved = resolve_includes((root / "a.rst").read_text(), root, root)
            self.assertIn("A", resolved)
            self.assertIn("B", resolved)


class RecordTests(unittest.TestCase):
    def test_heading_reference_suffix_cleaned(self):
        lines = ["Title\n=====\n\n", "Working with Git_\n----------------\n"]
        headings = find_headings("".join(lines).splitlines())
        self.assertEqual(headings[-1].title, "Working with Git")

    def test_preamble_metadata_removed(self):
        records, _ = build_records(
            source=_source(),
            text=PEP_TEXT,
            document_id="pep-0008",
            document_title="",
            document_path="pep-0008.rst",
            document_url="https://peps.python.org/pep-0008/",
            revision="abc123",
            min_total_tokens=1,
            min_prose_tokens=1,
        )
        self.assertFalse(any(r["section_path"] == ["Preamble"] for r in records))
        for record in records:
            self.assertNotIn("PEP: 8", record["content"])
            self.assertNotIn("Author:", record["content"])

    def test_record_preserves_structure_and_provenance(self):
        records, stats = build_records(
            source=_source(),
            text=PEP_TEXT,
            document_id="pep-0008",
            document_title="",
            document_path="pep-0008.rst",
            document_url="https://peps.python.org/pep-0008/",
            revision="abc123",
            min_total_tokens=1,
            min_prose_tokens=1,
        )
        example = next(r for r in records if r["section_title"] == "Example")
        self.assertEqual(example["section_path"], ["PEP 8 -- Example Title", "Example"])
        self.assertEqual(example["document_title"], "PEP 8 -- Example Title")
        self.assertEqual(example["source_revision"], "abc123")
        self.assertEqual(example["license_spdx"], "CC0-1.0")
        self.assertEqual(example["license_status"], "CLEAR")
        self.assertEqual(example["schema_version"], "1.0")
        self.assertEqual(example["record_id"], example["id"])
        self.assertEqual(example["content_hash"], example["exact_hash"])
        self.assertEqual(example["source_type"], "raw")
        self.assertEqual(example["source_url"], example["document_url"])
        self.assertEqual(example["token_count"], example["provisional_token_count"])
        self.assertEqual(example["token_count_status"], "PROVISIONAL")
        self.assertEqual(example["source_version"], "abc123")
        self.assertEqual(example["validator_version"], prose.VALIDATOR_VERSION)
        self.assertEqual(example["provenance"]["commit"], "abc123")
        self.assertEqual(example["provenance"]["section"], example["section_path"])
        self.assertTrue(example["acquisition_date"])
        kinds = [s["type"] for s in example["segments"]]
        self.assertEqual(kinds, ["prose", "code", "prose"])
        self.assertEqual(example["segments"][1]["language"], "python")
        self.assertTrue(example["has_code"])
        self.assertEqual(example["code_block_count"], 1)
        self.assertTrue(example["code_blocks"][0]["syntax_valid"])
        self.assertIn("```python", example["content"])
        self.assertEqual(
            example["provisional_token_count"],
            example["prose_token_count"] + example["code_token_count"],
        )
        self.assertEqual(stats["retained"], len(records))

    def test_short_prose_section_is_rejected(self):
        records, stats = build_records(
            source=_source(),
            text=PEP_TEXT,
            document_id="pep-0008",
            document_title="",
            document_path="pep-0008.rst",
            document_url="https://peps.python.org/pep-0008/",
            revision="abc123",
            min_prose_tokens=1000,
        )
        self.assertEqual(records, [])
        self.assertGreaterEqual(stats["no_prose"], 1)

    def test_invalid_python_marked_not_executed(self):
        text = (
            "========\nBroken\n========\n\n"
            "Section\n=======\n\n"
            "This section has enough prose to be retained even though the code below is invalid syntax.\n\n"
            ".. code-block:: python\n\n"
            "   def broken(:\n"
        )
        records, _ = build_records(
            source=_source(),
            text=text,
            document_id="broken",
            document_title="",
            document_path="broken.rst",
            document_url="https://peps.python.org/broken/",
            revision="abc",
            min_total_tokens=1,
            min_prose_tokens=1,
        )
        self.assertEqual(len(records), 1)
        block = records[0]["code_blocks"][0]
        self.assertFalse(block["syntax_valid"])
        self.assertEqual(block["error_type"], "syntax_error")

    def test_long_section_splits_with_prose_in_each_part(self):
        paragraph = " ".join(["word"] * 8)
        text = "\n\n".join([paragraph, paragraph, paragraph, paragraph])
        segments = parse_blocks(text.splitlines())
        chunks = _split_segments(segments, max_tokens=10)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertTrue(any(s.kind == "prose" for s in chunk))

    def test_duplicate_sections_deduplicated(self):
        text = (
            "========\nTitle\n========\n\n"
            "Same\n====\n\n"
            "This paragraph is long enough to be retained and it is repeated below with identical text.\n\n"
            "Same\n====\n\n"
            "This paragraph is long enough to be retained and it is repeated below with identical text.\n"
        )
        records, stats = build_records(
            source=_source(),
            text=text,
            document_id="dup",
            document_title="",
            document_path="dup.rst",
            document_url="https://peps.python.org/dup/",
            revision="abc",
            min_total_tokens=1,
            min_prose_tokens=1,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(stats["duplicates"], 1)


class LicenseGateTests(unittest.TestCase):
    REVIEW_TEXT = """PEP: 2
Title: Review PEP
Author: Someone

Review
======

This section has enough prose to be retained even though the document is
under a different license and must be quarantined by the license gate. It
contains several complete sentences so that it clears the prose threshold
without relying on the code path or on any other document.

Copyright
=========

This document is licensed under the Open Publication License.
"""

    def test_process_filters_review_documents_and_writes_rejections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin = _make_repo(
                root,
                {"pep-0001.rst": PEP_TEXT, "pep-0002.rst": self.REVIEW_TEXT},
            )
            report = prose.process(
                sources=[_source(repo_url=str(origin))],
                raw_root=root / "raw",
                stage1_root=root / "stage1",
                run_id="license-gate",
            )
            accepted_path = root / "stage1" / "prose_docs_license-gate_peps.jsonl"
            rejected_path = root / "stage1" / "prose_docs_license-gate_peps_rejected.jsonl"
            accepted = [json.loads(line) for line in accepted_path.read_text().splitlines()]
            rejected = [json.loads(line) for line in rejected_path.read_text().splitlines()]
            self.assertTrue(accepted)
            self.assertTrue(all(r["document_id"] == "pep-0001" for r in accepted))
            self.assertTrue(all(r["license_status"] == "CLEAR" for r in accepted))
            license_rejects = [r for r in rejected if r["reason"] == "license_not_approved"]
            self.assertTrue(license_rejects)
            self.assertTrue(all(r["document_id"] == "pep-0002" for r in license_rejects))
            self.assertTrue(all(r["would_be_record_id"] for r in license_rejects))
            self.assertEqual(report["counts"]["total_retained"], len(accepted))
            self.assertEqual(report["counts"]["total_license_rejected"], len(license_rejects))
            self.assertEqual(
                report["counts"]["total_candidate_records"],
                len(accepted) + len(license_rejects),
            )
            for record in accepted:
                self.assertLessEqual(
                    record["provisional_token_count"], prose.MAX_TOKEN_LENGTH
                )

    def test_parser_rejections_are_written(self):
        text = """PEP: 3
Title: Short Sections
Author: Someone

Tiny
====

Too short.

Copyright
=========

This document is placed in the public domain or under the
CC0-1.0-Universal license, whichever is more permissive.
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin = _make_repo(root, {"pep-0003.rst": text})
            prose.process(
                sources=[_source(repo_url=str(origin))],
                raw_root=root / "raw",
                stage1_root=root / "stage1",
                run_id="rejects",
            )
            accepted_path = root / "stage1" / "prose_docs_rejects_peps.jsonl"
            rejected_path = root / "stage1" / "prose_docs_rejects_peps_rejected.jsonl"
            self.assertEqual(accepted_path.read_text(), "")
            rejected = [json.loads(line) for line in rejected_path.read_text().splitlines()]
            self.assertTrue(any(r["reason"] in {"no_prose", "too_short"} for r in rejected))


class OversizedSegmentTests(unittest.TestCase):
    def test_oversized_prose_is_split(self):
        segment = prose.Segment("prose", " ".join(["word"] * 25))
        prepared, rejected = prose._split_oversized_segments([segment], max_tokens=10)
        self.assertEqual(rejected, [])
        self.assertGreater(len(prepared), 1)
        for item in prepared:
            self.assertLessEqual(len(item.text.split()), 10)

    def test_oversized_code_is_quarantined(self):
        segment = prose.Segment("code", "\n".join(["x = 1"] * 25), "python")
        prepared, rejected = prose._split_oversized_segments([segment], max_tokens=10)
        self.assertEqual(prepared, [])
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["reason"], "oversized_code_segment")


class DevguideTitleTests(unittest.TestCase):
    def test_title_falls_back_to_filename(self):
        records, _ = build_records(
            source=_source(source_name="cpython_devguide"),
            text="Just prose without a heading, long enough to be retained by the pipeline.",
            document_id="testing/foo-bar",
            document_title="",
            document_path="testing/foo-bar.rst",
            document_url="https://devguide.python.org/testing/foo-bar/",
            revision="abc",
            min_total_tokens=1,
            min_prose_tokens=1,
        )
        self.assertEqual(records[0]["document_title"], "Foo Bar")


class DiscoveryTests(unittest.TestCase):
    def test_glob_and_exclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "peps").mkdir(parents=True)
            (repo / "peps" / "pep-0001.rst").write_text("x", encoding="utf-8")
            (repo / "peps" / "pep-0000.rst").write_text("x", encoding="utf-8")
            found = discover_documents(
                repo,
                _source(
                    document_glob="repo/peps/pep-*.rst",
                    exclude_globs=["repo/peps/pep-0000.rst"],
                ),
            )
            self.assertEqual([p.name for p in found], ["pep-0001.rst"])


class AcquisitionTests(unittest.TestCase):
    def test_clone_records_commit_and_refuses_manifest_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin = _make_repo(root, {"pep-0001.rst": "content"})
            raw_root = root / "raw"
            source = _source(repo_url=str(origin))
            repo_path, revision = acquire_repo(source, raw_root)
            self.assertTrue((repo_path / "pep-0001.rst").is_file())
            manifest_path = raw_root / "peps" / "ACQUISITION_MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["commit"], revision)
            self.assertEqual(manifest["license_spdx"], "CC0-1.0")

            manifest_path.write_text(json.dumps({"sentinel": True}), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                acquire_repo(source, raw_root)
            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8")), {"sentinel": True})

    def test_clone_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin = _make_repo(root, {"pep-0001.rst": "content"})
            raw_root = root / "raw"
            source = _source(repo_url=str(origin))
            repo_path, revision = acquire_repo(source, raw_root)
            manifest_path = raw_root / "peps" / "ACQUISITION_MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["commit"] = "0" * 40
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                acquire_repo(source, raw_root)
            self.assertEqual(_git("rev-parse", "HEAD", cwd=repo_path), revision)


class ProcessTests(unittest.TestCase):
    def _run(self, root: Path, **kwargs):
        origin = _make_repo(root, {"pep-0001.rst": PEP_TEXT, "pep-0002.rst": PEP_TEXT})
        raw_root = root / "raw"
        stage1_root = root / "stage1"
        source = _source(repo_url=str(origin))
        report = prose.process(
            sources=[source],
            raw_root=raw_root,
            stage1_root=stage1_root,
            run_id="prose-test",
            **kwargs,
        )
        return report, raw_root, stage1_root

    def test_end_to_end_writes_outputs_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, raw_root, stage1_root = self._run(Path(tmp))
            output = stage1_root / "prose_docs_prose-test_peps.jsonl"
            self.assertTrue(output.is_file())
            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(report["counts"]["total_retained"], len(records))
            self.assertGreater(len(records), 0)
            self.assertTrue(report["per_source"][0]["source_revision"])
            report_dir = raw_root / "prose_docs" / "reports" / "prose-test"
            self.assertTrue((report_dir / "report.json").is_file())
            self.assertTrue((report_dir / "source_inventory.json").is_file())
            self.assertTrue((report_dir / "acquisition_manifests.json").is_file())

    def test_second_run_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._run(root)
            origin = root / "origin"
            source = _source(repo_url=str(origin))
            with self.assertRaises(FileExistsError):
                prose.process(
                    sources=[source],
                    raw_root=root / "raw",
                    stage1_root=root / "stage1",
                    run_id="prose-test",
                )

    def test_dry_run_writes_no_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, raw_root, stage1_root = self._run(Path(tmp), dry_run=True)
            self.assertTrue(report["dry_run"])
            self.assertFalse(stage1_root.exists())
            self.assertFalse((raw_root / "prose_docs").exists())

    def test_rejects_non_accept_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                prose.process(
                    sources=[_source(decision="HOLD")],
                    raw_root=Path(tmp) / "raw",
                    stage1_root=Path(tmp) / "stage1",
                    run_id="prose-test",
                )


if __name__ == "__main__":
    unittest.main()
