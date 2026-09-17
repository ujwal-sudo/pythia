"""Global deduplication scaffold — Pythia-160M.

This module defines the INTERFACES and CONTRACT for future global deduplication.
It does NOT execute deduplication on any active datasets.
It does NOT modify source data.

Intended future order:
  exact dedup → near dedup → provenance preservation → final corpus selection
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional


# === Normalized Hashing Contract ===

def normalized_hash(code: str) -> str:
    """Compute the normalized hash for a Python code string.

    Normalization steps (to be finalized before dedup execution):
    1. Normalize line endings: \r\n, \r → \n
    2. Strip trailing whitespace per line
    3. Collapse sequences of blank lines to a single blank line
    4. Hash with SHA-256

    Args:
        code: Raw Python code string.

    Returns:
        SHA-256 hex digest of the normalized code.
    """
    code = code.replace("\r\n", "\n").replace("\r", "\n")
    lines = code.split("\n")
    lines = [l.rstrip() for l in lines]
    # Collapse blank lines
    normalized_lines: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            # Skip duplicate blank line
            continue
        normalized_lines.append(line)
        prev_blank = is_blank
    normalized = "\n".join(normalized_lines)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# === Provenance Preservation Contract ===

class ProvenancePreserver:
    """Contract for preserving provenance when duplicates are found.

    When identical content is found across multiple sources, this contract
    ensures that ALL contributing source references are preserved in the
    final corpus record, even though only one version is kept for training.
    """

    def __init__(self, kept_source: str, discarded_sources: List[str]):
        self.kept_source = kept_source
        self.discarded_sources = discarded_sources
        self.kept_provenance: Dict[str, any] = {
            "kept_source": kept_source,
            "discarded_sources": discarded_sources,
            "content_hash": "",
            "acquisition_timestamps": {},
        }

    def record_acquisition_timestamp(self, source: str, timestamp: str) -> None:
        """Record when each source was acquired."""
        self.kept_provenance["acquisition_timestamps"][source] = timestamp

    def to_dict(self) -> Dict[str, any]:
        """Convert provenance to dict for JSON serialization."""
        return self.kept_provenance


# === Execution Guard ===

DEDUP_EXECUTION_GUARD = """
IMPORTANT: Do NOT execute global deduplication on active datasets.

This scaffold defines interfaces and contracts only. Do NOT:

* Run global deduplication on data/raw/stackoverflow/
* Run global deduplication on data/raw/github/
* Run global deduplication on data/raw/pypi/
* Modify source JSONL files in data/raw/*/
* Rewrite manifests under data/filtered/

Until the dedicated global deduplication processor is given the
explicit go-ahead by the Lead, this scaffold should be used for:

* Interface design review
* Contract specification
* Dependency planning
* Provenance policy documentation
"""


# === Quick Self-Check ===

if __name__ == "__main__":
    print(__doc__)
    print("\nScaffold loaded. No deduplication executed.")
    print("See DEDUP_EXECUTION_GUARD for constraints.")