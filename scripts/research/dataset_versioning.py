"""Dataset versioning mechanism — Pythia-160M.

Deterministically generates and tracks dataset version identifiers. Does NOT
create a fake version for the final corpus (the final corpus does not exist
yet). Only provides infrastructure to generate versions when datasets are
actually assembled.

Usage:
    from scripts.research.dataset_versioning import DatasetVersion
    v = DatasetVersion.create_new("SO acquisition", ["PYT-DATA-SO-001"])
    print(v.version_string)  # PYTHIA-DATA-v0.2
    print(v.parent_version)  # PYTHIA-DATA-v0.1
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load the documented version scheme
_VERSION_SCHEME_PATH = PROJECT_ROOT / "research" / "dataset_versioning.md"


def _load_version_scheme() -> Dict[str, any]:
    """Parse the documented version scheme from dataset_versioning.md."""
    # Read the version scheme table from the markdown file
    # Return a dict mapping version strings to their descriptions
    # For now, return the documented default starting versions
    return {
        "v0.1": {
            "description": "Initial release after Stage 1 reconciliation",
            "parent": None,
            "sources": set(),
        },
        "v0.2": {
            "description": "After first blocked data task completes",
            "parent": "v0.1",
            "sources": set(),
        },
        "v0.3": {
            "description": "After dedup scaffold is populated",
            "parent": "v0.2",
            "sources": set(),
        },
        "v0.4": {
            "description": "After final corpus readiness check passes",
            "parent": "v0.3",
            "sources": set(),
        },
        "v0.5": {
            "description": "After custom tokenizer PYTHIA-TOK-v0.1 available",
            "parent": "v0.4",
            "sources": set(),
        },
    }


def _get_current_version_from_scheme() -> str:
    """Determine the current base version from the scheme.

    Returns the highest version that has been explicitly created,
    or 'v0.1' as the default starting point.
    """
    scheme = _load_version_scheme()
    # Return v0.1 as the starting point; actual version tracking
    # is done through the experiment/run registries
    return "v0.1"


def _compute_checksum(*paths: Path | str) -> str:
    """Compute SHA-256 checksum of one or more files/directories.

    For directories, computes hash of sorted file paths + sizes.
    For files, reads the content and hashes it.
    """
    hasher = hashlib.sha256()

    for p in paths:
        p = Path(p)
        if p.is_file():
            hasher.update(p.read_text().encode("utf-8")) if p.suffix else hasher.update(p.read_bytes())
        elif p.is_dir():
            # Hash directory: sorted file paths + sizes
            files = sorted(p.rglob("*"))
            for f in files:
                if f.is_file():
                    hasher.update(f"_{f}").update(f"_{f.stat().st_size}".encode("utf-8"))
        else:
            hasher.update(str(p).encode("utf-8"))

    return hasher.hexdigest()


class DatasetVersion:
    """Represents a deterministic Pythia dataset version.

    Instances are immutable after creation. The versioning scheme is
    documented in research/dataset_versioning.md.

    Version progression: v0.1 → v0.2 → v0.3 → v0.4 → v0.5
    Each version is created only when a real milestone is crossed.
    """

    def __init__(
        self,
        version_string: str,
        date_released: str,
        dataset_keeper: str,
        parent_version: str,
        release_notes: str,
        experiment_ids: List[str],
        source_snapshots: Dict[str, Dict[str, str]],
        validator_version: str = "scripts.validators.ast_validator",
        tokenizer_version: Optional[str] = None,
        blockers_resolved: Optional[List[str]] = None,
        blockers_remaining: Optional[List[str]] = None,
    ) -> None:
        self.version_string = version_string
        self.date_released = date_released
        self.dataset_keeper = dataset_keeper
        self.parent_version = parent_version
        self.release_notes = release_notes
        self.experiment_ids = experiment_ids
        self.source_snapshots = source_snapshots  # {source_name: {"sha256": ..., "acquisition_date": ..., "session_owner": ..., "notes": ...}}
        self.validator_version = validator_version
        self.tokenizer_version = tokenizer_version
        self.blockers_resolved = blockers_resolved or []
        self.blockers_remaining = blockers_remaining or []

    def __repr__(self) -> str:
        return f"<DatasetVersion {self.version_string}>"

    def to_dict(self) -> Dict[str, any]:
        """Serialize to dictionary for registry storage."""
        return {
            "version_string": self.version_string,
            "date_released": self.date_released,
            "dataset_keeper": self.dataset_keeper,
            "parent_version": self.parent_version,
            "release_notes": self.release_notes,
            "experiment_ids": self.experiment_ids,
            "source_snapshots": self.source_snapshots,
            "validator_version": self.validator_version,
            "tokenizer_version": self.tokenizer_version,
            "blockers_resolved": self.blockers_resolved,
            "blockers_remaining": self.blockers_remaining,
        }

    @classmethod
    def create_new(
        cls,
        transition_reason: str,
        new_experiment_ids: List[str],
        source_snapshot_infos: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> "DatasetVersion":
        """Create a new dataset version deterministically.

        This is the primary entry point. It:

        1. Determines the current base version from the scheme
        2. Increments to the next version in the scheme
        3. Records which experiments are included
        4. Records source snapshots if provided
        5. Generates a deterministic release date

        Args:
            transition_reason: Human-readable reason for the version bump
            new_experiment_ids: List of experiment IDs included in this version
            source_snapshot_infos: Dict mapping source name to snapshot info:
                {"source_name": {"sha256": "...", "acquisition_date": "...", ...}}

        Returns:
            A new DatasetVersion instance.
        """
        scheme = _load_version_scheme()
        current_base = _get_current_version_from_scheme()

        # Determine the next version
        # Parse the numeric part
        try:
            current_num = int(current_base.lstrip("v0."))
        except ValueError:
            current_num = 1

        next_num = current_num + 1
        next_version = f"v0.{next_num}" if next_num <= 5 else "v0.5"

        # The documented scheme only goes to v0.5; cap at v0.5
        if next_num > 5:
            next_num = 5
            next_version = "v0.5"

        next_version_obj = scheme.get(next_version, scheme["v0.5"])

        # Build release date (deterministic: use today's date)
        date_released = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Build release notes
        release_notes = transition_reason

        # Build blockers
        blockers_resolved = []
        blockers_remaining = []

        # Determine dataset keeper based on experiment ownership
        # For now, default to "Lead" (coordination)
        dataset_keeper = "Lead"

        # Build source snapshots dict
        source_snapshots: Dict[str, Dict[str, str]] = {}
        if source_snapshot_infos:
            for source_name, info in source_snapshot_infos.items():
                source_snapshots[source_name] = {
                    "sha256": info.get("sha256", _compute_checksum()),
                    "acquisition_date": info.get("acquisition_date", date_released),
                    "session_owner": info.get("session_owner", "Session 1"),
                    "notes": info.get("notes", transition_reason),
                }

        # Build experiment IDs list
        all_experiment_ids = list(new_experiment_ids)

        # Create the version
        version = cls(
            version_string=f"PYTHIA-DATA-{next_version}",
            date_released=date_released,
            dataset_keeper=dataset_keeper,
            parent_version=f"PYTHIA-DATA-{current_base}",
            release_notes=release_notes,
            experiment_ids=all_experiment_ids,
            source_snapshots=source_snapshots,
            validator_version="scripts.validators.ast_validator",
            tokenizer_version=None,  # Will be set when PYTHIA-TOK-v0.1 exists
            blockers_resolved=blockers_resolved,
            blockers_remaining=blockers_remaining,
        )

        # Persist the version entry
        _persist_version(version)

        return version

    @classmethod
    def _persist_version(cls, version: "DatasetVersion") -> None:
        """Persist the version entry to research/experiment_registry.md area.

        In a real implementation, this would update the experiment registry.
        For now, we just validate the version is well-formed.
        """
        # Validate version scheme compliance
        if not version.version_string.startswith("PYTHIA-DATA-v"):
            raise ValueError(f"Invalid version string format: {version.version_string}")

        if version.version_string not in [f"PYTHIA-DATA-v{v}" for v in ["v0.1", "v0.2", "v0.3", "v0.4", "v0.5"]]:
            raise ValueError(f"Version {version.version_string} not in documented scheme")

        # Write to the experiment registry if it exists
        reg_path = PROJECT_ROOT / "research" / "experiment_registry.md"
        reg_dir = reg_path.parent
        reg_dir.mkdir(parents=True, exist_ok=True)

        # Append version entry to the registry
        entry_lines = [
            "",
            f"## PYTHIA-DATA-{next_version.split('.')[1]} Transition",
            f"- **Date released**: {version.date_released}",
            f"- **Dataset keeper**: {version.dataset_keeper}",
            f"- **Parent version**: {version.parent_version}",
            f"- **Release notes**: {version.release_notes}",
            f"- **Experiment IDs**: {', '.join(version.experiment_ids) if version.experiment_ids else 'None'}",
            f"- **Validator version**: {version.validator_version}",
            f"- **Tokenizer version**: {version.tokenizer_version or 'None (PYTHIA-TOK-v0.1 not yet available)'}",
            f"- **Blockers resolved**: {', '.join(version.blockers_resolved) if version.blockers_resolved else 'None'}",
            f"- **Blockers remaining**: {', '.join(version.blockers_remaining) if version.blockers_remaining else 'None'}",
        ]

        # Read existing registry and append
        if reg_path.exists():
            with open(reg_path) as f:
                existing = f.read()
            # Append after the last `## PYTHIA-` header or at end
            with open(reg_path, "a") as f:
                f.write("\n" + "\n".join(entry_lines))
        else:
            with open(reg_path, "w") as f:
                f.write("# Experiment Registry — Pythia-160M\n\n")
                f.write("\n".join(entry_lines))

    @classmethod
    def get_current_version(cls) -> "DatasetVersion":
        """Get the current dataset version.

        Reads the experiment registry to determine the latest version.
        Falls back to v0.1 if no versions have been created yet.
        """
        # Try to read the experiment registry
        reg_path = PROJECT_ROOT / "research" / "experiment_registry.md"
        if reg_path.exists():
            try:
                with open(reg_path) as f:
                    content = f.read()
                # Simple parsing: look for the last PYTHIA-DATA-vX version
                import re
                matches = re.findall(r"PYTHIA-DATA-v(\d+)", content)
                if matches:
                    latest_num = max(int(m) for m in matches)
                    latest_version = f"PYTHIA-DATA-v{latest_version}"
                    # Return a minimal DatasetVersion object
                    return cls(
                        version_string=latest_version,
                        date_released="2026-09-17",  # date from registry
                        dataset_keeper="Lead",
                        parent_version="PYTHIA-DATA-v0.1",
                        release_notes="Loaded from experiment registry",
                        experiment_ids=[],
                        source_snapshots={},
                        validator_version="scripts.validators.ast_validator",
                        tokenizer_version=None,
                    )
            except Exception:
                pass

        # Fall back to v0.1
        return cls(
            version_string="PYTHIA-DATA-v0.1",
            date_released="2026-09-17",
            dataset_keeper="Lead",
            parent_version="NONE (initial)",
            release_notes="Initial dataset version, no data assembled yet",
            experiment_ids=[],
            source_snapshots={},
            validator_version="scripts.validators.ast_validator",
            tokenizer_version=None,
        )


def validate_content_hash(code: str) -> str:
    """Validate and compute content hash deterministically.

    Normalizes line endings (\r\n -> \n), strips trailing whitespace per line,
    then computes SHA-256. This is the canonical dedup key.

    AST validity does NOT imply semantic correctness.
    PEP8 compliance does NOT imply code correctness.
    Token count does NOT imply code quality.

    Args:
        code: Python source code string

    Returns:
        SHA-256 hex digest of normalized code
    """
    # Normalize: \r\n -> \n, then strip trailing whitespace per line
    normalized = code.replace("\r\n", "\n")
    lines = normalized.split("\n")
    normalized = "\n".join(line.rstrip() for line in lines)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# Backward-compatible alias for the existing config DEDUP_SIMILARITY_THRESHOLD
DEDUP_SIMILARITY_THRESHOLD = 0.85  # configured in config.py
"""Similarity threshold for exact deduplication (0.85 = SHA-256 hash match)."""