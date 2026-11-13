"""Fail-closed license classification for Python Enhancement Proposals.

A PEP may carry its own Copyright section.  Only an explicit public-domain or
CC0 statement counts as approved for the prose corpus; everything else is
quarantined for review.  The classifier is deliberately conservative and does
not infer a license from the repository or from PEP 1's guidance for new PEPs.
"""

from __future__ import annotations

import re
from typing import Any

LICENSE_APPROVED = "LICENSE_APPROVED_FOR_INTENDED_USE"
LICENSE_REVIEW_REQUIRED = "LICENSE_REVIEW_REQUIRED"
LICENSE_STATUS_CLEAR = "CLEAR"
LICENSE_STATUS_REVIEW = "RESTRICTED_OR_REVIEW"

_COPYRIGHT_RE = re.compile(r"(?im)^\s*copyright\s*$[\s\S]{0,600}$")
_PERMISSIVE_COPYRIGHT = re.compile(
    r"public domain|cc0|creative commons zero|cc0-1\.0", re.IGNORECASE
)


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def classify_pep_license(text: str) -> dict[str, Any]:
    """Classify a PEP from its own Copyright section.

    Returns contract-facing ``license_status`` (``CLEAR`` or
    ``RESTRICTED_OR_REVIEW``), a detailed fail-closed status, and the evidence
    used for the decision.
    """
    match = _COPYRIGHT_RE.search(text)
    section = match.group(0) if match else ""
    if _PERMISSIVE_COPYRIGHT.search(section):
        return {
            "license": "Public domain / CC0-1.0",
            "license_spdx": "CC0-1.0",
            "license_status": LICENSE_STATUS_CLEAR,
            "license_status_detail": LICENSE_APPROVED,
            "license_evidence": _collapse_ws(section)[:500],
        }

    if not match:
        return {
            "license": "UNKNOWN (no Copyright section)",
            "license_spdx": "UNKNOWN",
            "license_status": LICENSE_STATUS_REVIEW,
            "license_status_detail": LICENSE_REVIEW_REQUIRED,
            "license_evidence": "",
        }

    return {
        "license": "UNKNOWN (unexpected Copyright section)",
        "license_spdx": "UNKNOWN",
        "license_status": LICENSE_STATUS_REVIEW,
        "license_status_detail": LICENSE_REVIEW_REQUIRED,
        "license_evidence": _collapse_ws(section)[:500],
    }
