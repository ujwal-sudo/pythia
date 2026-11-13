"""License normalisation and the curation policy.

The archive carries free-text license fields ("Public domain / CC0-1.0",
"CLEAR", "RESTRICTED_OR_REVIEW") next to real SPDX identifiers, and a
self-assigned `license_status` of APPROVED. We do not trust that status: the
decision is derived from the license value, and anything we cannot map becomes
HOLD rather than ALLOW.

Policy:
  ALLOW  permissive or public-domain; may ship, with attribution noted
  HOLD   unknown, ambiguous, or needs a legal call; never assembled silently
  DENY   explicitly non-commercial
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Decision(str, Enum):
    ALLOW = "ALLOW"
    HOLD = "HOLD"
    DENY = "DENY"


@dataclass(frozen=True, slots=True)
class Verdict:
    decision: Decision
    spdx: str
    reason: str
    attribution_required: bool = False


# Canonical forms, matched case-insensitively against the raw value.
_ALLOW = {
    "cc0-1.0": ("CC0-1.0", False),
    "cc0": ("CC0-1.0", False),
    "public domain": ("CC0-1.0", False),
    "unlicense": ("Unlicense", False),
    "mit": ("MIT", True),
    "mit license": ("MIT", True),
    "bsd-2-clause": ("BSD-2-Clause", True),
    "bsd-3-clause": ("BSD-3-Clause", True),
    "apache-2.0": ("Apache-2.0", True),
    "apache 2.0": ("Apache-2.0", True),
    "isc": ("ISC", True),
    "psf-2.0": ("PSF-2.0", True),
    "python-2.0": ("PSF-2.0", True),
    "python software foundation license": ("PSF-2.0", True),
    "cc-by-4.0": ("CC-BY-4.0", True),
    "creative commons attribution 4.0 international": ("CC-BY-4.0", True),
}

_HOLD = {
    "mpl-2.0": "file-level copyleft; needs a policy decision",
    "cc-by-sa-4.0": "share-alike is ambiguous for training corpora",
    "gpl-2.0": "copyleft; needs a policy decision",
    "gpl-3.0": "copyleft; needs a policy decision",
    "lgpl-2.1": "copyleft; needs a policy decision",
    "agpl-3.0": "network copyleft; needs a policy decision",
    "unclear": "license present but unresolvable",
    "clear": "internal marker, not an SPDX identifier",
    "restricted_or_review": "flagged for review upstream",
}

_NC = re.compile(r"\b(nc|non[- ]?commercial)\b", re.IGNORECASE)
_UNKNOWN_MARKERS = ("", "unknown", "none", "null", "n/a", "noassertion")


def classify(value: str | None, status: str | None = None) -> Verdict:
    """Map a raw license string to a policy verdict.

    ``status`` is recorded in the reason when it conflicts with the value, but
    never overrides it.
    """
    raw = (value or "").strip()
    key = raw.lower()
    status_note = ""
    if status and status.strip().upper() in {"APPROVED", "LICENSE_APPROVED_FOR_INTENDED_USE"}:
        status_note = f" (upstream status claimed: {status.strip()})"

    if key in _UNKNOWN_MARKERS:
        return Verdict(Decision.HOLD, "UNKNOWN", "no license value" + status_note)

    if _NC.search(key):
        return Verdict(Decision.DENY, "CC-BY-NC", f"non-commercial: {raw!r}" + status_note)

    if key in _ALLOW:
        spdx, attribution = _ALLOW[key]
        reason = f"permissive: {raw!r}" + status_note
        return Verdict(Decision.ALLOW, spdx, reason, attribution_required=attribution)

    # A bare SPDX id we recognise by prefix.
    for prefix, (spdx, attribution) in _ALLOW.items():
        if key.startswith(prefix):
            return Verdict(Decision.ALLOW, spdx, f"prefix match: {raw!r}", attribution)

    if key in _HOLD:
        return Verdict(Decision.HOLD, raw, _HOLD[key] + status_note)

    # "Public domain / CC0-1.0" and similar compound values.
    if "public domain" in key or "cc0" in key:
        return Verdict(Decision.ALLOW, "CC0-1.0", f"compound value: {raw!r}")

    return Verdict(Decision.HOLD, "UNKNOWN", f"unmapped license {raw!r}" + status_note)


def is_assemblable(verdict: Verdict) -> bool:
    return verdict.decision is Decision.ALLOW


@dataclass(frozen=True, slots=True)
class Policy:
    """Which decisions may enter the final corpus."""

    allow: frozenset[Decision] = frozenset({Decision.ALLOW})
    require_spdx: bool = False

    def admits(self, verdict: Verdict) -> bool:
        if self.require_spdx and verdict.spdx == "UNKNOWN":
            return False
        return verdict.decision in self.allow

    def describe(self) -> dict:
        return {
            "admits": sorted(d.value for d in self.allow),
            "require_spdx": self.require_spdx,
            "rules": "derived from license value; upstream status ignored",
        }


DEFAULT_POLICY = Policy()
