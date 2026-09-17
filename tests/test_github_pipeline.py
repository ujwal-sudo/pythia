import unittest
from unittest import mock
import json
import os
import tempfile
from pathlib import Path

# Ensure the package is importable
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "pythia-data-pipeline"))

from scripts.scrapers.github import (
    discover_repos,
    capture_license,
    safe_clone,
    count_python_files_and_loc,
    detect_generated_or_vendor,
    compute_doc_metrics,
    capture_pypi_overlap,
    provisional_token_estimate,
    _rate_limit_sleep,
    _request,
    GITHUB_API_BACKOFF_SECONDS,
)


class TestGitHubDiscovery(unittest.TestCase):
    def test_discover_repos_returns_list(self):
        # discovery makes real API calls; just verify function runs without crash
        # we limit to 1 page to avoid excessive network
        with mock.patch(
            "scripts.scrapers.github.requests.get"
        ) as mock_get:
            mock_get.return_value.json.return_value = {
                "total_count": 5,
                "items": [
                    {
                        "full_name": "owner/repo1",
                        "name": "repo1",
                        "stargazers_count": 200,
                        "forks_count": 50,
                        "language": "Python",
                        "license": {"key": "MIT", "spdx_id": "MIT", "url": "https://opensource.org/licenses/MIT"},
                        "default_branch": "main",
                        "html_url": "https://github.com/owner/repo1",
                        "topics": ["python"],
                        "archived": False,
                        "size": 10000,
                        "created_at": "2020-01-01T00:00:00Z",
                        "updated_at": "2025-01-01T00:00:00Z",
                    }
                ],
            }
            mock_get.return_value.status_code = 200
            # Patch rate‑limit sleep so it does nothing
            with mock.patch("scripts.scrapers.github.time.sleep"):
                # We need to patch the module-level GITHUB_PAGINATION_MAX_PAGES to 1 for this test
                with mock.patch(
                    "scripts.scrapers.github.GITHUB_PAGINATION_MAX_PAGES", 1
                ):
                    result = discover_repos(min_stars=100)
                    # Should return at least one candidate
                    self.assertIsInstance(result, list)
                    self.assertGreater(len(result), 0)
                    self.assertEqual(result[0]["full_name"], "owner/repo1")

    def test_capture_license(self):
        with mock.patch(
            "scripts.scrapers.github.requests.get"
        ) as mock_get:
            mock_get.return_value.json.return_value = {
                "license": {"key": "Apache-2.0", "spdx_id": "Apache-2.0", "url": "https://www.apache.org/licenses/LICENSE-2.0.txt"}
            }
            mock_get.return_value.status_code = 200
            with mock.patch("scripts.scrapers.github.time.sleep"):
                lic = capture_license("owner/repo")
                self.assertEqual(lic["identifier"], "Apache-2.0")
                self.assertEqual(lic["url"], "https://www.apache.org/licenses/LICENSE-2.0.txt")

    def test_capture_license_unknown(self):
        with mock.patch(
            "scripts.scrapers.github.requests.get"
        ) as mock_get:
            mock_get.return_value.json.return_value = {}
            mock_get.return_value.status_code = 200
            with mock.patch("scripts.scrapers.github.time.sleep"):
                lic = capture_license("owner/repo")
                self.assertIsNone(lic["identifier"])

    def test_count_python_files_and_loc(self):
        # create a temporary directory with some .py files
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # good python file
            (tmp_path / "module1.py").write_text("def foo():\n    pass\n")
            # non‑python file
            (tmp_path / "readme.md").write_text("# Hi")
            # empty python file
            (tmp_path / "empty.py").write_text("")
            # file with comments only
            (tmp_path / "comments.py").write_text("# comment\n# another comment\n")

            stats = count_python_files_and_loc(tmp_path)
            self.assertEqual(stats["python_files"], 3)  # module1, empty, comments
            # LOC counts: module1 has 2 lines (def + pass) -> 2 non‑comment non‑blank lines
            # empty.py -> 0, comments.py -> 0 (all comments)
            self.assertEqual(stats["python_lines"], 2)

    def test_detect_generated_or_vendor(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # create a vendor directory with a python file
            vendor_dir = tmp_path / "vendor"
            vendor_dir.mkdir()
            (vendor_dir / "lib.py").write_text("def bar(): pass")
            # create a normal python file
            (tmp_path / "foo.py").write_text("def baz(): pass")
            # create a file with GENERATED header
            (tmp_path / "gen.py").write_text("# GENERATED\nprint('hi')")

            gv = detect_generated_or_vendor(tmp_path)
            self.assertGreater(gv["flagged"], 0)  # vendor lib and gen.py should be flagged
            self.assertGreater(gv["scanned"], 0)

    def test_compute_doc_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "README.md").write_text("# Project")
            (tmp_path / "docs").mkdir()
            (tmp_path / "module.py").write_text('"""docstring"""def foo(): pass')
            doc = compute_doc_metrics(tmp_path)
            self.assertTrue(doc["readme_present"])
            self.assertTrue(doc["docs_directory_present"])

    def test_capture_pypi_overlap_returns_dict(self):
        # No real PyPI list; just verify function returns expected keys
        result = capture_pypi_overlap("owner/repo")
        self.assertIn("potential_pypi_overlap", result)
        self.assertIn("repo_name", result)

    def test_provisional_token_estimate(self):
        # Very rough; just ensure it returns an int
        tokens = provisional_token_estimate(10000)
        self.assertIsInstance(tokens, int)

    def test_acquisition_summary_keys(self):
        # Ensure the helper constants are importable
        self.assertIsNotNone(GITHUB_API_BACKOFF_SECONDS)


if __name__ == "__main__":
    unittest.main()