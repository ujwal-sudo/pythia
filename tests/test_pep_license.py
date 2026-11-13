"""Tests for fail-closed PEP license classification."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from scripts.scrapers.pep_license import classify_pep_license


class PepLicenseTests(unittest.TestCase):
    def test_public_domain_is_clear(self):
        result = classify_pep_license(
            "Copyright\n=========\n\n"
            "This document is placed in the public domain or under the\n"
            "CC0-1.0-Universal license, whichever is more permissive.\n"
        )
        self.assertEqual(result["license_status"], "CLEAR")
        self.assertEqual(result["license_spdx"], "CC0-1.0")

    def test_missing_copyright_is_review(self):
        result = classify_pep_license(
            "A document without a license section.\n"
        )
        self.assertEqual(result["license_status"], "RESTRICTED_OR_REVIEW")
        self.assertEqual(
            result["license_status_detail"], "LICENSE_REVIEW_REQUIRED"
        )
        self.assertEqual(result["license_evidence"], "")

    def test_open_publication_license_is_review(self):
        result = classify_pep_license(
            "Copyright\n=========\n\n"
            "This document is licensed under the Open Publication License.\n"
        )
        self.assertEqual(result["license_status"], "RESTRICTED_OR_REVIEW")
        self.assertIn("Open Publication License", result["license_evidence"])

    def test_restrictive_wording_is_review(self):
        result = classify_pep_license(
            "Copyright\n=========\n\n"
            "This document is the property of the Python Steering Union.\n"
            "Do not quote, copy, modify, or distribute it.\n"
        )
        self.assertEqual(result["license_status"], "RESTRICTED_OR_REVIEW")


if __name__ == "__main__":
    unittest.main()
