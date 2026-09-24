
"""Canonical PyPI metadata schema.

Defines record_id, content_hash, provenance_chain, and associated fields
for PyPI package integration into the Pythia-160M corpus.

DO NOT fabricate values. All fields must be deterministically derived from
actual package metadata or left as NULL/UNKNOWN where unavailable.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def make_record_id(package_name: str, package_version: str) -> str:
    """Deterministic record_id for a PyPI package.

    Format: pypi:{package_name}:{package_version}
    Uniquely identifies a PyPI package record across the corpus.
    """
    package_name = package_name.lower().replace('-', '_').replace('.', '_')
    package_version = package_version
    return f"pypi:{package_name}:{package_version}"


def normalize_code_for_hash(code: str) -> str:
    """Normalize Python code for content hash computation.

    Canonical normalization per data_contract.md:
    - \r\n -> \n (line ending normalization)
    - Strip trailing whitespace per line
    - Remove docstrings
    """
    normalized = code.replace("\r\n", "\n")
    lines = normalized.split("\n")
    normalized = "\n".join(line.rstrip() for line in lines)
    # Remove docstrings - simple approach: track """ state
    result = []
    i = 0
    in_docstring = False
    while i < len(normalized):
        if normalized[i:i+3] == '"""':
            in_docstring = not in_docstring
            i += 3
            continue
        if in_docstring:
            i += 1
            continue
        result.append(normalized[i])
        i += 1
    normalized = "".join(result)
    return normalized


def content_hash(code: str) -> str:
    """Compute SHA-256 content hash of normalized Python code.

    Uses the canonical normalization from data_contract.md.
    This is the canonical dedup key.
    """
    normalized = normalize_code_for_hash(code)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def make_provenance_chain(
    source: str,
    source_url: str,
    acquisition_date: str,
    experiment_id: str,
    preprocessing_version: Optional[str] = None,
    validator_version: Optional[str] = None,
    dataset_version: Optional[str] = None,
    pipeline_stages: Optional[Dict[str, str]] = None,
) -> Dict[str, any]:
    """Construct a provenance chain for a PyPI package.

    Canonical conceptual chain (only stages that actually occurred):
      raw_source -> acquisition -> archive -> extraction -> preprocessing ->
      validation -> filtering -> final_corpus

    Unknown stages are represented with appropriate unavailable markers.
    """
    chain = {
        "source": source,
        "source_url": source_url,
        "acquisition_date": acquisition_date,
        "experiment_id": experiment_id,
    }

    if preprocessing_version is not None:
        chain["preprocessing_version"] = preprocessing_version
    if validator_version is not None:
        chain["validator_version"] = validator_version
    if dataset_version is not None:
        chain["dataset_version"] = dataset_version
    if pipeline_stages is not None:
        chain["pipeline_stages"] = pipeline_stages

    # Add unknown markers for any stages not recorded
    if "preprocessing_version" not in chain:
        chain["preprocessing_version"] = "UNKNOWN (not recorded)"
    if "validator_version" not in chain:
        chain["validator_version"] = "UNKNOWN (not recorded)"
    if "dataset_version" not in chain:
        chain["dataset_version"] = "UNKNOWN (not recorded)"

    return chain


def make_quality_metadata(
    ast_valid: Optional[Union[bool, int]] = None,
    ast_invalid: Optional[Union[bool, int]] = None,
    license_status: Optional[str] = None,
    token_count_status: Optional[str] = None,
    generated_or_vendor: Optional[Union[bool, int]] = None,
) -> Dict[str, any]:
    """Construct quality metadata dict for a PyPI package.

    Preserves existing PyPI quality information such as:
    - AST-valid/invalid (accepts bool or int 0/1 from pilot reports)
    - License status
    - Token-count status where available
    - Generated/vendor classification
    """
    metadata: Dict[str, any] = {}

    # Convert 0/1 to bool if provided
    if ast_valid is not None:
        metadata["ast_valid"] = bool(ast_valid)
    if ast_invalid is not None:
        metadata["ast_invalid"] = bool(ast_invalid)
    if license_status is not None:
        metadata["license_status"] = license_status
    if token_count_status is not None:
        metadata["token_count_status"] = token_count_status
    if generated_or_vendor is not None:
        metadata["generated_or_vendor"] = bool(generated_or_vendor)

    # Only return if at least one field was provided
    if metadata:
        return metadata
    return {"ast_valid": None, "ast_invalid": None, "license_status": None, "token_count_status": None}


PILOT_REPORT_FIELDS = {
    "ast_valid": "ast_valid",
    "ast_invalid": "ast_invalid", 
    "comment_ratio": "comment_ratio",
    "docstring_ratio": "docstring_ratio",
    "license_status_dist": "license_status_dist",
}


def pilot_to_quality_metadata(pilot_data: Dict[str, any]) -> Dict[str, any]:
    """Convert pilot report data to quality_metadata dict.

    Maps pilot report data to the canonical quality_metadata schema.
    """
    metadata = make_quality_metadata(
        ast_valid=pilot_data.get("ast_valid"),
        ast_invalid=pilot_data.get("ast_invalid"),
    )
    # Preserve any extra fields from the pilot
    for key, value in pilot_data.items():
        if key not in ("ast_valid", "ast_invalid", "comment_ratio", "docstring_ratio",
                       "duplicate_count", "experiment_id", "generated_vendor_total",
                       "license_status_dist", "packages_acquired", "packages_discovered",
                       "packages_failed", "packages_skipped", "pilot_size",
                       "python_files_total", "storage_used_bytes"):
            metadata[key] = value
    return metadata
