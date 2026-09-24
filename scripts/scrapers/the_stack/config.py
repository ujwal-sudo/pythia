"""Configuration for The Stack Python data acquisition pipeline.

All paths are relative to Google Drive root at /mnt/pythia-cloud/Pythia.
Nothing is written to local SSD except Python package imports.
"""

from __future__ import annotations

import os
import logging

from scripts.logger import get_logger

logger = get_logger(__name__)

DRIVE_ROOT = "/mnt/pythia-cloud/Pythia"
"""Google Drive root mount point."""

RAW_OUTPUT_DIR = f"{DRIVE_ROOT}/raw/the_stack"
"""Raw output directory for The Stack data."""

CACHE_DIR = f"{DRIVE_ROOT}/cache/the_stack"
"""Cache directory for downloaded datasets."""

# ── Output files ──────────────────────────────────────────────────────

OUTPUT_FILES = {
    "the_stack": f"{RAW_OUTPUT_DIR}/so_the_stack_pilot.jsonl",
    """The Stack output file."""
}

# ── Quality filters ─────────────────────────────────────────────────

# Python filter: must contain 'def ' in content
PYTHON_TAG = "python"

QUALITY_FILTERS = {
    "min_content_chars": 20,
    "must_be_python": True,
}

# ── Initialise directories and logger on import ───────────────────────

# Ensure all output/cache directories exist
for _dir in [DRIVE_ROOT, RAW_OUTPUT_DIR, CACHE_DIR]:
    os.makedirs(_dir, exist_ok=True)
    logger.info("Ensured directory exists: %s", _dir)

# Log the configuration
logger.info("The Stack pipeline config initialised")
logger.info("  DRIVE_ROOT:          %s", DRIVE_ROOT)
logger.info("  RAW_OUTPUT_DIR:      %s", RAW_OUTPUT_DIR)
logger.info("  CACHE_DIR:           %s", CACHE_DIR)
logger.info("  OUTPUT_FILES:        %s", list(OUTPUT_FILES.values()))
logger.info("  QUALITY_FILTERS:     %s", QUALITY_FILTERS)
logger.info("  PYTHON_TAG:          %s", PYTHON_TAG)