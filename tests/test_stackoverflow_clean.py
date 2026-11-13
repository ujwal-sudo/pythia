"""Synthetic tests for the Stack Overflow cleaning processor."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.processors.stackoverflow_clean import (
    HtmlToText,
    PreflightError,
    TransformStats,
    clean_html,
    duplicate_audit,
    parse_tags,
    process,
    sha256_file,
    validate_output_record,
    validate_source_record,
)


def make_record(
    answer_id: int = 2,
    question_id: int = 1,
    answer: str = "<p>Example answer.</p>",
    question_instruction: str = "<p>Example question.</p>",
    tags: str = "['python', 'testing']",
    score: int = 1,
    char_count: int | None = None,
) -> dict:
    return {
        "source": "huggingface",
        "dataset_name": "koutch/stackoverflow_python",
        "question_instruction": question_instruction,
        "answer": answer,
        "question_title": "Example title",
        "score": score,
        "tags": tags,
        "has_code": True,
        "char_count": len(answer) if char_count is None else char_count,
        "collected_at": "2026-09-18T08:45:59+00:00",
        "question_id": question_id,
        "answer_id": answer_id,
        "question_date": "2008-08-02T15:11:16Z",
        "answer_date": "2008-08-02T16:56:53Z",
    }


def write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


class TestParsingAndValidation(unittest.TestCase):
    def test_parse_jsonl_and_invalid_json_fails_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.jsonl"
            path.write_text(json.dumps(make_record()) + "\n{bad json\n", encoding="utf-8")
            with self.assertRaises(PreflightError):
                process([path], dry_run=True, expected_baseline=None)

    def test_non_object_json_fails_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.jsonl"
            path.write_text("[1, 2, 3]\n", encoding="utf-8")
            with self.assertRaises(PreflightError):
                process([path], dry_run=True, expected_baseline=None)

    def test_required_fields_and_types(self) -> None:
        record = make_record()
        self.assertEqual(validate_source_record(record, 1), [])
        del record["answer"]
        record["score"] = "high"
        errors = validate_source_record(record, 1)
        self.assertTrue(any("missing required field 'answer'" in error for error in errors))
        self.assertTrue(any("field 'score'" in error for error in errors))

    def test_blank_content_is_rejected_by_validation(self) -> None:
        record = make_record(answer="   ")
        errors = validate_source_record(record, 1)
        self.assertTrue(any("'answer' is blank" in error for error in errors))

    def test_tags_use_safe_literal_eval(self) -> None:
        self.assertEqual(parse_tags("['python', 'list']"), ["python", "list"])
        with self.assertRaises(ValueError):
            parse_tags("__import__('os').system('echo nope')")
        with self.assertRaises(ValueError):
            parse_tags("['python', 1]")
        with self.assertRaises(ValueError):
            parse_tags("python")


class TestHtmlTransformation(unittest.TestCase):
    def test_entity_decoding_happens_once(self) -> None:
        self.assertEqual(clean_html("<p>&lt;tag&gt; &amp; &nbsp; x</p>"), "<tag> & x")
        self.assertEqual(clean_html("<p>&amp;lt;</p>"), "&lt;")
        self.assertNotIn("&lt;", clean_html("<p>&lt;</p>"))

    def test_paragraph_separation(self) -> None:
        self.assertEqual(clean_html("<p>one</p><p>two</p>"), "one\n\ntwo")

    def test_inline_code(self) -> None:
        self.assertEqual(clean_html("<p>Use <code>len(x)</code> here.</p>"), "Use `len(x)` here.")
        self.assertEqual(clean_html("<p><code>a`b</code></p>"), "``a`b``")

    def test_code_block_indentation_and_newlines(self) -> None:
        markup = "<pre><code>def f():\n    return 1\n</code></pre>"
        self.assertEqual(clean_html(markup), "```\ndef f():\n    return 1\n```")

    def test_br_inside_pre_becomes_newline(self) -> None:
        markup = "<pre><code>one<br>two</code></pre>"
        self.assertEqual(clean_html(markup), "```\none\ntwo\n```")

    def test_nested_html_and_inline_elements(self) -> None:
        markup = "<p>A <strong>bold <em>and italic</em></strong> <code>x</code> tail.</p>"
        self.assertEqual(clean_html(markup), "A bold and italic `x` tail.")

    def test_links_retain_visible_text_and_url(self) -> None:
        self.assertEqual(
            clean_html('<p>See <a href="https://example.test/docs">the docs</a>.</p>'),
            "See [the docs](https://example.test/docs).",
        )
        self.assertEqual(
            clean_html('<p><a href="https://example.test/">https://example.test/</a></p>'),
            "https://example.test/",
        )

    def test_images_retain_useful_alt_and_count_placeholders(self) -> None:
        stats = TransformStats()
        cleaned = clean_html(
            '<p><img src="a.png" alt="diagram"> '
            '<img src="b.png" alt="enter image description here"> '
            '<img src="c.png"></p>',
            stats,
        )
        self.assertIn("[image: diagram]", cleaned)
        self.assertEqual(cleaned.count("[image]"), 2)
        self.assertEqual(stats.images, 3)
        self.assertEqual(stats.images_with_useful_alt, 1)
        self.assertEqual(stats.images_without_useful_alt, 2)

    def test_unknown_tags_are_removed_but_text_kept(self) -> None:
        stats = TransformStats()
        self.assertEqual(clean_html("<p>Hello <foo>inside</foo> world</p>", stats), "Hello inside world")
        self.assertEqual(stats.unknown_tags, 1)

    def test_malformed_html_fragments(self) -> None:
        cleaned = clean_html("<p>one<p>two<ul><li>three</ul>")
        self.assertIn("one", cleaned)
        self.assertIn("two", cleaned)
        self.assertIn("- three", cleaned)
        self.assertNotIn("<p>", cleaned)

    def test_malformed_paragraph_before_code_block_stays_separated(self) -> None:
        cleaned = clean_html("<p>one<p>two<pre><code>x = 1</code></pre>")
        self.assertEqual(cleaned, "one\n\ntwo\n\n```\nx = 1\n```")

    def test_code_block_inside_list_keeps_code_indentation(self) -> None:
        cleaned = clean_html(
            "<ul><li><p>text</p><pre><code>    x\n        y</code></pre></li></ul>"
        )
        self.assertEqual(cleaned, "- text\n\n```\n    x\n        y\n```")

    def test_nested_code_related_tags(self) -> None:
        markup = "<pre><code><span>if x:</span>\n    <span>y = 1</span></code></pre>"
        self.assertEqual(clean_html(markup), "```\nif x:\n    y = 1\n```")

    def test_pre_nested_inside_code_stays_block_level(self) -> None:
        markup = "<p>Example:<code><pre>\nfiles = glob.glob('*.py')\n</pre></code></p>"
        self.assertEqual(clean_html(markup), "Example:\n\n```\nfiles = glob.glob('*.py')\n```")

    def test_literal_backticks_in_text_are_escaped(self) -> None:
        cleaned = clean_html("<p>```</p><pre><code>x = 1</code></pre>")
        self.assertEqual(cleaned, "\\`\\`\\`\n\n```\nx = 1\n```")
        self.assertNotEqual(cleaned.split("\n")[0], "```")

    def test_fence_collision_is_avoided(self) -> None:
        cleaned = clean_html("<pre><code>a\n```\nb</code></pre>")
        self.assertEqual(cleaned, "````\na\n```\nb\n````")

    def test_deterministic_transformation(self) -> None:
        markup = "<p>x</p><pre><code>y = 1\n    z = 2</code></pre><ul><li>a</li></ul>"
        self.assertEqual(clean_html(markup), clean_html(markup))

    def test_empty_and_script_content(self) -> None:
        self.assertEqual(clean_html(""), "")
        self.assertEqual(clean_html("<script>bad()</script><p>safe</p>"), "safe")


class TestRecordTransformationAndAudit(unittest.TestCase):
    def test_char_count_measures_cleaned_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.jsonl"
            write_jsonl(source, [make_record(answer="<p>abc</p>")])
            report = process(
                [source],
                output_root=Path(tmp) / "processed",
                run_id="char-count",
                expected_baseline=None,
            )
            output = Path(report["outputs"][0]["path"])
            record = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(record["answer"], "abc")
            self.assertEqual(record["char_count"], len("abc"))
            self.assertEqual(record["source_char_count"], len("<p>abc</p>"))

    def test_duplicate_audit_is_non_destructive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.jsonl"
            records = [
                make_record(answer_id=10, answer="<p>same</p>"),
                make_record(answer_id=11, answer="<p>same</p>"),
            ]
            write_jsonl(source, records)
            report = process(
                [source],
                output_root=Path(tmp) / "processed",
                run_id="dedup-audit",
                expected_baseline=None,
            )
            self.assertEqual(report["counts"]["source_records"], 2)
            self.assertEqual(report["counts"]["retained_records"], 2)
            self.assertEqual(
                report["duplicate_audit"]["exact_duplicate_raw_answers"]["duplicate_group_count"],
                1,
            )
            self.assertFalse(
                report["duplicate_audit"]["destructive_deduplication_performed"]
            )

    def test_multiple_answers_for_one_question_are_retained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.jsonl"
            write_jsonl(
                source,
                [
                    make_record(answer_id=10, question_id=7, answer="<p>one</p>"),
                    make_record(answer_id=11, question_id=7, answer="<p>two</p>"),
                ],
            )
            report = process(
                [source],
                output_root=Path(tmp) / "processed",
                run_id="multi-answer",
                expected_baseline=None,
            )
            self.assertEqual(report["counts"]["retained_records"], 2)
            self.assertEqual(report["duplicate_audit"]["distinct_question_ids"], 1)
            self.assertEqual(report["duplicate_audit"]["questions_with_multiple_answers"], 1)

    def test_license_status_remains_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.jsonl"
            write_jsonl(source, [make_record()])
            report = process(
                [source],
                output_root=Path(tmp) / "processed",
                run_id="license",
                expected_baseline=None,
            )
            output = json.loads(
                Path(report["outputs"][0]["path"]).read_text(encoding="utf-8").splitlines()[0]
            )
            self.assertEqual(output["license_status"], "LICENSE_REVIEW_REQUIRED")
            self.assertIsNone(output["license"])
            self.assertEqual(report["legal_readiness"], "BLOCKED_PENDING_LICENSE_REVIEW")


class TestExecutionSafety(unittest.TestCase):
    def test_source_files_remain_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.jsonl"
            write_jsonl(source, [make_record()])
            before = sha256_file(source)
            process(
                [source],
                output_root=Path(tmp) / "processed",
                run_id="unchanged",
                expected_baseline=None,
            )
            self.assertEqual(before, sha256_file(source))

    def test_refuses_to_overwrite_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.jsonl"
            write_jsonl(source, [make_record()])
            kwargs = {
                "output_root": Path(tmp) / "processed",
                "run_id": "same-run",
                "expected_baseline": None,
            }
            process([source], **kwargs)
            with self.assertRaises(FileExistsError):
                process([source], **kwargs)

    def test_missing_input_fails_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "processed"
            with self.assertRaises(PreflightError):
                process(
                    [Path(tmp) / "missing.jsonl"],
                    output_root=output_root,
                    run_id="missing",
                    expected_baseline=None,
                )
            self.assertFalse(output_root.exists())

    def test_missing_mount_root_fails_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.jsonl"
            write_jsonl(source, [make_record()])
            with self.assertRaises(PreflightError):
                process(
                    [source],
                    output_root=Path(tmp) / "processed",
                    run_id="missing-mount",
                    expected_baseline=None,
                    require_mount_root=Path(tmp) / "not-mounted",
                )
            self.assertFalse((Path(tmp) / "processed").exists())

    def test_dry_run_writes_no_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.jsonl"
            write_jsonl(source, [make_record()])
            report = process([source], dry_run=True, expected_baseline=None)
            self.assertTrue(report["dry_run"])
            self.assertFalse(list(Path(tmp).glob("processed*")))
            self.assertNotIn("outputs", report)

    def test_reproducible_output_and_manifest_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.jsonl"
            write_jsonl(source, [make_record()])
            report_a = process(
                [source],
                output_root=Path(tmp) / "runs-a",
                run_id="run-a",
                expected_baseline=None,
            )
            report_b = process(
                [source],
                output_root=Path(tmp) / "runs-b",
                run_id="run-b",
                expected_baseline=None,
            )
            output_a = Path(report_a["outputs"][0]["path"])
            output_b = Path(report_b["outputs"][0]["path"])
            self.assertEqual(output_a.read_bytes(), output_b.read_bytes())
            self.assertEqual(report_a["outputs"][0]["sha256"], report_b["outputs"][0]["sha256"])

            manifest = json.loads(Path(report_a["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["counts"]["source_records"], 1)
            self.assertEqual(manifest["counts"]["retained_records"], 1)
            self.assertEqual(manifest["counts"]["rejected_records"], 0)
            self.assertEqual(manifest["inputs"][0]["sha256"], sha256_file(source))
            self.assertEqual(
                manifest["outputs"][0]["sha256"],
                hashlib.sha256(output_a.read_bytes()).hexdigest(),
            )
            self.assertEqual(manifest["readiness"]["legal_redistribution"], "BLOCKED_PENDING_LICENSE_REVIEW")

    def test_output_schema_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.jsonl"
            write_jsonl(source, [make_record()])
            report = process(
                [source],
                output_root=Path(tmp) / "processed",
                run_id="schema",
                expected_baseline=None,
            )
            record = json.loads(
                Path(report["outputs"][0]["path"]).read_text(encoding="utf-8").splitlines()[0]
            )
            self.assertEqual(validate_output_record(record), [])
            self.assertEqual(record["transformation_version"], "html_to_text_v1")
            self.assertEqual(record["tags"], ["python", "testing"])
            self.assertEqual(record["tags_raw"], "['python', 'testing']")


if __name__ == "__main__":
    unittest.main()
