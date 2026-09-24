"""Configuration for CodeSearchNet data acquisition pipeline.

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

RAW_OUTPUT_DIR = f"{DRIVE_ROOT}/raw/codesearchnet"
"""Raw output directory for CodeSearchNet data."""

CACHE_DIR = f"{DRIVE_ROOT}/cache/codesearchnet"
"""Cache directory for downloaded datasets."""

# ── Output files ──────────────────────────────────────────────────────

OUTPUT_FILES = {
    "codesearchnet": f"{RAW_OUTPUT_DIR}/so_codesearchnet.jsonl",
    """CodesearchNet output file."""
}

# ── Quality filters ─────────────────────────────────────────────────

# Python filter: must contain 'def ' in code or comment
PYTHON_TAG = "python"

QUALITY_FILTERS = {
    "min_code_chars": 20,
    "min_comment_chars": 20,
    "must_be_python": True,
}

# ── Initialise directories and logger on import ───────────────────────

# Ensure all output/cache directories exist
for _dir in [DRIVE_ROOT, RAW_OUTPUT_DIR, CACHE_DIR]:
    os.makedirs(_dir, exist_ok=True)
    logger.info("Ensured directory exists: %s", _dir)

# Log the configuration
logger.info("CodeSearchNet pipeline config initialised")
logger.info("  DRIVE_ROOT:          %s", DRIVE_ROOT)
logger.info("  RAW_OUTPUT_DIR:      %s", RAW_OUTPUT_DIR)
logger.info("  CACHE_DIR:           %s", CACHE_DIR)
logger.info("  OUTPUT_FILES:        %s", list(OUTPUT_FILES.values()))
logger.info("  QUALITY_FILTERS:     %s", QUALITY_FILTERS)
logger.info("  PYTHON_TAG:          %s", PYTHON_TAG)