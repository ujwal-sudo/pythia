"""Synthetic tests for the CodeSearchNet acquisition processor."""

from __future__ import annotations

import gzip
import json
import os
import pickle
import tempfile
import unittest
from pathlib import Path

from scripts.scrapers.codesearchnet_acquire import (
    LICENSE_APPROVED,
    LICENSE_REVIEW_REQUIRED,
    PROVENANCE_INSUFFICIENT,
    _RestrictedUnpickler,
    _repair_output_tail,
    _safe_join,
    _write_checkpoint,
    acquire,
    build_canonical_record,
    classify_license,
    content_hash,
    detect_license_identifier,
    duplicate_audit,
    evaluate_code_quality,
    load_licenses_pkl,
    make_record_id,
    read_jsonl_gz,
    validate_source_record,
)


def make_source_record(**overrides) -> dict:
    record = {
        "repo": "org/repo",
        "path": "src/mod.py",
        "func_name": "add",
        "original_string": 'def add(a, b):\n    """Add two numbers."""\n    return a + b\n',
        "language": "python",
        "code": 'def add(a, b):\n    """Add two numbers."""\n    return a + b\n',
        "code_tokens": ["def", "add", "(", "a", ",", "b", ")", ":"],
        "docstring": "Add two numbers.",
        "docstring_tokens": ["Add", "two", "numbers", "."],
        "sha": "abc123def456",
        "partition": "train",
        "url": "https://github.com/org/repo/blob/abc123def456/src/mod.py#L1-L3",
    }
    record.update(overrides)
    return record


MIT_TEXT = "MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a copy"
APACHE_TEXT = "Apache License\nVersion 2.0, January 2004\nhttp://www.apache.org/licenses/LICENSE-2.0"
GPL_TEXT = "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007"
BSD3_TEXT = "Redistribution and use in source and binary forms, with or without modification\n...\n3. Neither the name of the copyright holder"


class TestLicenseDetection(unittest.TestCase):
    def test_detect_mit(self) -> None:
        self.assertEqual(detect_license_identifier(MIT_TEXT), "MIT")

    def test_detect_apache(self) -> None:
        self.assertEqual(detect_license_identifier(APACHE_TEXT), "Apache-2.0")

    def test_detect_gpl(self) -> None:
        self.assertEqual(detect_license_identifier(GPL_TEXT), "GPL-3.0")

    def test_detect_bsd3(self) -> None:
        self.assertEqual(detect_license_identifier(BSD3_TEXT), "BSD-3-Clause")

    def test_detect_unknown(self) -> None:
        self.assertIsNone(detect_license_identifier("Some random text without a license"))
        self.assertIsNone(detect_license_identifier(""))

    def test_classify_permissive_approved(self) -> None:
        decision = classify_license("org/repo", [("LICENSE", MIT_TEXT)])
        self.assertEqual(decision["license_status"], LICENSE_APPROVED)
        self.assertEqual(decision["license_identifier"], "MIT")

    def test_classify_copyleft_review(self) -> None:
        decision = classify_license("org/repo", [("LICENSE", GPL_TEXT)])
        self.assertEqual(decision["license_status"], LICENSE_REVIEW_REQUIRED)
        self.assertEqual(decision["license_identifier"], "GPL-3.0")

    def test_classify_no_text_review(self) -> None:
        decision = classify_license("org/repo", [])
        self.assertEqual(decision["license_status"], LICENSE_REVIEW_REQUIRED)

    def test_classify_missing_repo_provenance(self) -> None:
        decision = classify_license("", [])
        self.assertEqual(decision["license_status"], PROVENANCE_INSUFFICIENT)


class TestRestrictedUnpickler(unittest.TestCase):
    def test_safe_pickle_loads(self) -> None:
        payload = {"org/repo": [("LICENSE", MIT_TEXT)]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "licenses.pkl"
            with path.open("wb") as handle:
                pickle.dump(payload, handle)
            loaded = load_licenses_pkl(path)
            self.assertEqual(loaded["org/repo"], [("LICENSE", MIT_TEXT)])

    def test_malicious_pickle_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evil.pkl"
            with path.open("wb") as handle:
                pickle.dump(_Malicious(), handle)
            with self.assertRaises(Exception):
                load_licenses_pkl(path)

    def test_non_dict_pickle_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "list.pkl"
            with path.open("wb") as handle:
                pickle.dump([1, 2, 3], handle)
            with self.assertRaises(ValueError):
                load_licenses_pkl(path)


class _Malicious:
    def __reduce__(self):  # noqa: D401
        return (os.system, ("echo pwned",))


class TestHashing(unittest.TestCase):
    def test_content_hash_deterministic(self) -> None:
        code = 'def f():\n    return 1\n'
        self.assertEqual(content_hash(code), content_hash(code))

    def test_content_hash_normalizes_line_endings(self) -> None:
        a = "def f():\r\n    return 1\r\n"
        b = "def f():\n    return 1\n"
        self.assertEqual(content_hash(a), content_hash(b))

    def test_record_id_deterministic(self) -> None:
        rid1 = make_record_id("o/r", "p.py", "f", "s", "train", "h1")
        rid2 = make_record_id("o/r", "p.py", "f", "s", "train", "h1")
        rid3 = make_record_id("o/r", "p.py", "f", "s", "test", "h1")
        rid4 = make_record_id("o/r", "p.py", "f", "s", "train", "h2")
        self.assertEqual(rid1, rid2)
        self.assertNotEqual(rid1, rid3)
        self.assertNotEqual(rid1, rid4)
        self.assertTrue(rid1.startswith("csn_"))


class TestSourceValidation(unittest.TestCase):
    def test_valid_record_passes(self) -> None:
        self.assertEqual(validate_source_record(make_source_record(), 1), [])

    def test_missing_field_rejected(self) -> None:
        record = make_source_record()
        del record["repo"]
        errors = validate_source_record(record, 1)
        self.assertTrue(any("repo" in e for e in errors))

    def test_non_object_rejected(self) -> None:
        errors = validate_source_record([1, 2, 3], 1)
        self.assertEqual(len(errors), 1)

    def test_wrong_type_rejected(self) -> None:
        record = make_source_record(repo=123)
        errors = validate_source_record(record, 1)
        self.assertTrue(any("repo" in e for e in errors))


class TestQualityEvaluation(unittest.TestCase):
    def test_valid_function_accepted(self) -> None:
        q = evaluate_code_quality(
            'def add(a, b):\n    """Add."""\n    return a + b\n', "Add."
        )
        self.assertTrue(q["ast_valid"])
        self.assertEqual(q["quality_status"], "ACCEPTED")

    def test_empty_code_rejected(self) -> None:
        q = evaluate_code_quality("", "doc")
        self.assertFalse(q["ast_valid"])
        self.assertEqual(q["quality_status"], "REJECTED")

    def test_syntax_error_rejected(self) -> None:
        q = evaluate_code_quality("def broken(:\n", "doc")
        self.assertFalse(q["ast_valid"])
        self.assertEqual(q["quality_status"], "REJECTED")

    def test_trivial_stub_rejected(self) -> None:
        q = evaluate_code_quality('def f():\n    """Doc."""\n    pass\n', "Doc.")
        self.assertEqual(q["quality_status"], "REJECTED")
        self.assertIn("trivial_stub", q["rejection_reasons"])

    def test_missing_docstring_rejected(self) -> None:
        q = evaluate_code_quality("def f():\n    return 1\n", "")
        self.assertIn("missing_docstring", q["rejection_reasons"])

    def test_generated_marker_rejected(self) -> None:
        q = evaluate_code_quality(
            "# This file was generated automatically\ndef f():\n    return 1\n", "doc"
        )
        self.assertIn("generated_or_boilerplate", q["rejection_reasons"])


class TestCanonicalRecord(unittest.TestCase):
    def test_fields_present(self) -> None:
        rec = build_canonical_record(
            make_source_record(),
            classify_license("org/repo", [("LICENSE", MIT_TEXT)]),
            evaluate_code_quality(make_source_record()["code"], "Add two numbers."),
            source_file="python_train_0.jsonl.gz",
            line_number=3,
            run_id="run-1",
            acquisition_date="2026-10-22T00:00:00+00:00",
        )
        for field in ("record_id", "content_hash", "repository_name", "split", "license_status", "code", "docstring"):
            self.assertIn(field, rec)
        self.assertEqual(rec["split"], "train")
        self.assertEqual(rec["language"], "python")
        self.assertEqual(rec["license_status"], LICENSE_APPROVED)


class TestDuplicateAudit(unittest.TestCase):
    def test_unique_records(self) -> None:
        records = [
            {"record_id": "a", "content_hash": "h1", "original_record_id": "s1"},
            {"record_id": "b", "content_hash": "h2", "original_record_id": "s2"},
        ]
        audit = duplicate_audit(records)
        self.assertEqual(audit["records_audited"], 2)
        self.assertEqual(audit["distinct_record_ids"], 2)
        self.assertFalse(audit["destructive_deduplication_performed"])

    def test_duplicate_content_hash_detected(self) -> None:
        records = [
            {"record_id": "a", "content_hash": "h1", "original_record_id": "s1"},
            {"record_id": "b", "content_hash": "h1", "original_record_id": "s2"},
        ]
        audit = duplicate_audit(records)
        self.assertIn("h1", audit["duplicate_content_hashes"]["groups"])


class TestSafeJoin(unittest.TestCase):
    def test_zip_slip_blocked(self) -> None:
        base = Path("/tmp/out")
        self.assertIsNone(_safe_join(base, "../../etc/passwd"))

    def test_normal_path_ok(self) -> None:
        base = Path("/tmp/out")
        self.assertEqual(_safe_join(base, "python/a.jsonl.gz"), Path("/tmp/out/python/a.jsonl.gz"))


class TestReadJsonlGz(unittest.TestCase):
    def test_read_valid_gz(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "python_test_0.jsonl.gz"
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                handle.write(json.dumps(make_source_record()) + "\n")
            records, info = read_jsonl_gz(path)
            self.assertEqual(info["records"], 1)
            self.assertEqual(len(records), 1)


class TestAcquireIntegration(unittest.TestCase):
    def _write_gz(self, path: Path, records: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")

    def _write_licenses(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            pickle.dump(payload, handle)

    def test_acquire_pilot_from_synthetic_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as filtered, tempfile.TemporaryDirectory() as manifests:
            raw_dir = Path(raw)
            self._write_licenses(raw_dir / "python_licenses.pkl", {"org/repo": [("LICENSE", MIT_TEXT)]})
            self._write_gz(
                raw_dir / "python" / "final" / "jsonl" / "train" / "python_train_0.jsonl.gz",
                [make_source_record()],
            )
            self._write_gz(
                raw_dir / "python" / "final" / "jsonl" / "test" / "python_test_0.jsonl.gz",
                [make_source_record(func_name="sub", partition="test", code='def sub(a, b):\n    """Sub."""\n    return a - b\n')],
            )

            manifest = acquire(
                raw_dir=raw_dir,
                filtered_dir=Path(filtered),
                manifest_dir=Path(manifests),
                skip_download=True,
                skip_extract=True,
            )
            self.assertEqual(manifest["counts"]["records_processed"], 2)
            self.assertEqual(manifest["counts"]["records_accepted"], 2)
            self.assertEqual(manifest["split_counts"], {"train": 1, "test": 1})
            accepted_path = Path(manifest["outputs"]["accepted"])
            self.assertTrue(accepted_path.exists())
            with accepted_path.open() as handle:
                lines = handle.read().splitlines()
            self.assertEqual(len(lines), 2)

    def test_acquire_rejects_other_language(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as filtered, tempfile.TemporaryDirectory() as manifests:
            raw_dir = Path(raw)
            self._write_licenses(raw_dir / "python_licenses.pkl", {})
            self._write_gz(
                raw_dir / "python" / "final" / "jsonl" / "train" / "python_train_0.jsonl.gz",
                [make_source_record(language="java")],
            )
            manifest = acquire(
                raw_dir=raw_dir,
                filtered_dir=Path(filtered),
                manifest_dir=Path(manifests),
                skip_download=True,
                skip_extract=True,
            )
            self.assertEqual(manifest["counts"]["records_processed"], 1)
            self.assertEqual(manifest["counts"]["records_accepted"], 0)
            self.assertEqual(manifest["counts"]["records_rejected"], 1)


class TestResumeRepair(unittest.TestCase):
    def test_repair_truncates_uncheckpointed_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "accepted.jsonl"
            path.write_text("a\nb\nc\nd\n", encoding="utf-8")
            self.assertEqual(_repair_output_tail(path, 2), 2)
            self.assertEqual(path.read_text(encoding="utf-8"), "a\nb\n")

    def test_repair_noop_when_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rejected.jsonl"
            path.write_text("x\ny\n", encoding="utf-8")
            _repair_output_tail(path, 2)
            self.assertEqual(path.read_text(encoding="utf-8"), "x\ny\n")

    def test_repair_missing_file_with_expected_records_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                _repair_output_tail(Path(tmp) / "missing.jsonl", 5)

    def test_repair_fewer_lines_than_expected_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "short.jsonl"
            path.write_text("a\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                _repair_output_tail(path, 3)

    def test_write_checkpoint_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.json"
            _write_checkpoint(path, ["a.gz"], 10, 8, 2)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["completed_files"], ["a.gz"])
            self.assertEqual(payload["records_processed"], 10)
            self.assertEqual(payload["records_accepted"], 8)
            self.assertEqual(payload["records_rejected"], 2)


class TestAcquireResume(unittest.TestCase):
    def _write_gz(self, path: Path, records: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")

    def test_resume_drops_uncheckpointed_tail_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.TemporaryDirectory() as filtered, tempfile.TemporaryDirectory() as manifests:
            raw_dir = Path(raw)
            with (raw_dir / "python_licenses.pkl").open("wb") as handle:
                pickle.dump({"org/repo": [("LICENSE", MIT_TEXT)]}, handle)
            self._write_gz(
                raw_dir / "python" / "final" / "jsonl" / "train" / "python_train_0.jsonl.gz",
                [make_source_record()],
            )
            self._write_gz(
                raw_dir / "python" / "final" / "jsonl" / "test" / "python_test_0.jsonl.gz",
                [make_source_record(func_name="sub", partition="test")],
            )
            first = acquire(
                raw_dir=raw_dir, filtered_dir=Path(filtered), manifest_dir=Path(manifests),
                skip_download=True, skip_extract=True, run_id="resume-r1",
            )
            accepted = Path(first["outputs"]["accepted"])
            # Simulate a crash that wrote a record but not the checkpoint.
            with accepted.open("a", encoding="utf-8") as handle:
                handle.write('{"uncheckpointed":true}\n')
            Path(first["outputs"]["manifest"]).unlink()

            second = acquire(
                raw_dir=raw_dir, filtered_dir=Path(filtered), manifest_dir=Path(manifests),
                skip_download=True, skip_extract=True, run_id="resume-r1",
            )
            self.assertEqual(second["counts"]["records_accepted"], 2)
            lines = [line for line in accepted.read_text(encoding="utf-8").splitlines() if line]
            self.assertEqual(len(lines), 2)


if __name__ == "__main__":
    unittest.main()
