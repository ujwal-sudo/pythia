"""Stack Overflow data acquisition pipeline for Pythia-160M.

This package provides collectors for HuggingFace datasets, Archive.org dumps,
and the StackExchange API, followed by deduplication and quality filtering.

All output is written to Google Drive at /mnt/pythia-cloud/Pythia.
No data is written to local SSD except Python package imports.

Typical usage:
    from stackoverflow.config import OUTPUT_FILES, QUALITY_FILTERS
    from stackoverflow.hf_collector import run_hf_collector
    from stackoverflow.archive_collector import run_archive_collector
    from stackoverflow.api_collector import run_api_collector
    from stackoverflow.deduplicator.run import run_dedup
    from stackoverflow.run_all import run_pipeline
"""

from __future__ import annotations

# Ensure config is imported first (directories + logger initialisation)
from stackoverflow.config import *  # noqa: F401,F403

# Re-export commonly used names at package level
from scripts.logger import get_logger

__all__ = [
    "DRIVE_ROOT",
    "RAW_OUTPUT_DIR",
    "CACHE_DIR",
    "HF_CACHE_DIR",
    "OUTPUT_FILES",
    "QUALITY_FILTERS",
    "MIN_ANSWER_SCORE",
    "CHUNK_SIZE",
    "REQUEST_DELAY",
    "get_logger",
]