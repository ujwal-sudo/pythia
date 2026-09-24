"""Tests for reproducibility manifest mechanism."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.research.reproducibility_manifest import (
    build_source_infos_from_evaluations,
    generate_manifest,
    write_manifest,
)
import unittest


class BuildSourceInfosFromEvaluations(unittest.TestCase):
    """Test building source infos from evaluations."""

    def test_basic(self) -> None:
        """Basic construction and field presence."""
        evaluations = {
            "python_docs": [
                {
                    "ast_valid": True,
                    "content_hash": "abc123",
                    "acquisition_date": "2026-09-17",
                    "quality_gate_status": "ACCEPTED",
                    "token_count_status": "PROVISIONAL",
                    "license_status": "MIT",
                    "source": "python_docs",
                    "record_id": "r-0",
                },
                {
                    "ast_valid": False,
                    "content_hash": "def456",
                    "acquisition_date": "2026-09-17",
                    "quality_gate_status": "REJECTED",
                    "token_count_status": "PROVISIONAL",
                    "license_status": "Apache-2.0",
                    "source": "python_docs",
                    "record_id": "r-1",
                },
            ]
        }
        result = build_source_infos_from_evaluations(evaluations)
        self.assertIn("python_docs", result)
        self.assertEqual(result["python_docs"]["records"], 2)
        self.assertEqual(result["python_docs"]["accepted"], 1)
        self.assertEqual(result["python_docs"]["rejected"], 1)
        self.assertEqual(result["python_docs"]["quality_gate_status"], "REJECTED")
        self.assertEqual(result["python_docs"]["token_count_status"], "PROVISIONAL")
        self.assertEqual(result["python_docs"]["license_status"], "MIT")


class GenerateManifest(unittest.TestCase):
    """Test manifest generation."""

    def test_generate_manifest_has_required_fields(self) -> None:
        """Manifest should have all required top-level fields."""
        source_infos = {
            "python_docs": {
                "records": 2,
                "accepted": 1,
                "rejected": 1,
                "quality_gate_status": "REJECTED",
                "token_count_status": "PROVISIONAL",
                "license_status": "MIT",
            }
        }
        manifest = generate_manifest(
            experiment_id="PYT-DATA-SO-001",
            run_id="run-001",
            source_infos=source_infos,
            record_count=2,
            accepted_count=1,
            rejected_count=1,
            validator_version="scripts.validators.ast_validator",
            tokenizer_version=None,
        )
        required_fields = [
            "experiment_id",
            "run_id",
            "generated_at",
            "python_version",
            "pip_packages",
            "os_info",
            "data_root",
            "git_commit",
            "git_diff_summary",
            "config_thresholds",
            "validator_version",
            "tokenizer_version",
            "source_infos",
            "record_count",
            "accepted_count",
            "rejected_count",
            "acceptance_rate",
        ]
        for field in required_fields:
            self.assertIn(field, manifest)


class WriteManifest(unittest.TestCase):
    """Test writing manifest JSON."""

    def test_write_and_read(self) -> None:
        """Write manifest and verify it can be read back."""
        manifest = {
            "experiment_id": "PYT-DATA-SO-001",
            "run_id": "run-001",
            "generated_at": "2026-09-18T12:00:00+00:00",
            "data_root": "/test/path",
            "record_count": 2,
            "accepted_count": 1,
            "rejected_count": 1,
        }
        write_path = Path("/tmp/test_manifest.json")
        write_manifest(manifest, write_path)
        self.assertTrue(write_path.exists())
        with open(write_path) as f:
            read_back = json.load(f)
        self.assertEqual(read_back, manifest)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases."""

    def test_empty_evaluations(self) -> None:
        """Empty evaluations dict should return empty result."""
        result = build_source_infos_from_evaluations({})
        self.assertEqual(result, {})


def main() -> int:
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())