"""Tests verifying that data paths resolve correctly via PYTHIA_DATA_ROOT."""

from __future__ import annotations

import importlib
import os
import unittest


class TestPathsWithPYTHIA_DATA_ROOT(unittest.TestCase):
    """Verify path configuration with PYTHIA_DATA_ROOT set and unset."""

    def setUp(self) -> None:
        # Save original env var state
        self._original = os.environ.pop("PYTHIA_DATA_ROOT", None)

    def tearDown(self) -> None:
        # Restore original state
        if self._original is not None:
            os.environ["PYTHIA_DATA_ROOT"] = self._original
        else:
            os.environ.pop("PYTHIA_DATA_ROOT", None)

    def _import_config(self):
        """Import config module, reloading if already loaded."""
        import config
        return importlib.reload(config)

    def test_with_pythia_data_root_cloud(self) -> None:
        """With PYTHIA_DATA_ROOT=/mnt/pythia-cloud, paths resolve to Google Drive."""
        os.environ["PYTHIA_DATA_ROOT"] = "/mnt/pythia-cloud"
        try:
            config = self._import_config()

            self.assertEqual(str(config.DATA_ROOT), "/mnt/pythia-cloud")
            self.assertEqual(str(config.RAW_DIR), "/mnt/pythia-cloud/raw")
            self.assertEqual(str(config.FILTERED_DIR), "/mnt/pythia-cloud/filtered")
            self.assertEqual(str(config.FINAL_DIR), "/mnt/pythia-cloud/final")
            self.assertEqual(str(config.MANIFEST_DIR), "/mnt/pythia-cloud/manifests")
            self.assertEqual(str(config.SNAPSHOT_DIR), "/mnt/pythia-cloud/snapshots")
            self.assertEqual(str(config.PYTHON_DOCS_DIR), "/mnt/pythia-cloud/raw/python_docs")
            self.assertEqual(str(config.STACKOVERFLOW_DIR), "/mnt/pythia-cloud/raw/stackoverflow")
            self.assertEqual(str(config.PYPI_DIR), "/mnt/pythia-cloud/raw/pypi")
            self.assertEqual(str(config.STAGE1_DIR), "/mnt/pythia-cloud/filtered/stage1")
            self.assertEqual(str(config.STAGE2_DIR), "/mnt/pythia-cloud/filtered/stage2")
            self.assertEqual(str(config.GITHUB_RAW_DIR), "/mnt/pythia-cloud/raw/github")
            self.assertEqual(str(config.GITHUB_MANIFEST_DIR), "/mnt/pythia-cloud/raw/github/manifests")
        finally:
            # Clean up - tearDown will restore, but let's be explicit
            os.environ.pop("PYTHIA_DATA_ROOT", None)

    def test_without_pythia_data_root_fallback(self) -> None:
        """Without PYTHIA_DATA_ROOT, paths fall back to local data directory."""
        # env var already popped in setUp, so it's absent
        try:
            config = self._import_config()
            self.assertTrue(
                str(config.DATA_ROOT).endswith("/data"),
                f"Expected local fallback without env var, got {config.DATA_ROOT}",
            )
        finally:
            pass  # tearDown will restore