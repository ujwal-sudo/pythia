"""Configuration for Stack Overflow data acquisition pipeline.

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

RAW_OUTPUT_DIR = f"{DRIVE_ROOT}/data/raw/stackoverflow"
"""Raw output directory for all SO collectors."""

CACHE_DIR = f"{DRIVE_ROOT}/cache/stackoverflow"""
"""Cache directory for downloaded dumps and extracted data."""

HF_CACHE_DIR = f"{DRIVE_ROOT}/cache/huggingface"""
"""HuggingFace datasets cache directory."""

# ── Output files ──────────────────────────────────────────────────────

OUTPUT_FILES = {
    "hf": f"{RAW_OUTPUT_DIR}/so_huggingface.jsonl",
    "archive": f"{RAW_OUTPUT_DIR}/so_archive.jsonl",
    "api": f"{RAW_OUTPUT_DIR}/so_api.jsonl",
    "deduped": f"{RAW_OUTPUT_DIR}/so_final_deduped.jsonl",
}

# ── Quality filters ─────────────────────────────────────────────────

QUALITY_FILTERS = {
    "min_score": 10,
    "min_body_length": 200,
    "min_code_chars": 50,
    "must_be_accepted": True,
}

MIN_ANSWER_SCORE = 10
CHUNK_SIZE = 8192
REQUEST_DELAY = 0.1


# ── Initialise directories and logger on import ───────────────────────

# Ensure all output/cache directories exist
for _dir in [DRIVE_ROOT, RAW_OUTPUT_DIR, CACHE_DIR, HF_CACHE_DIR]:
    os.makedirs(_dir, exist_ok=True)
    logger.info("Ensured directory exists: %s", _dir)

# Log the configuration
logger.info("Stack Overflow pipeline config initialised")
logger.info("  DRIVE_ROOT:          %s", DRIVE_ROOT)
logger.info("  RAW_OUTPUT_DIR:      %s", RAW_OUTPUT_DIR)
logger.info("  CACHE_DIR:           %s", CACHE_DIR)
logger.info("  HF_CACHE_DIR:        %s", HF_CACHE_DIR)
logger.info("  OUTPUT_FILES:        %s", list(OUTPUT_FILES.values()))
logger.info("  QUALITY_FILTERS:     %s", QUALITY_FILTERS)
logger.info("  MIN_ANSWER_SCORE:    %d", MIN_ANSWER_SCORE)
logger.info("  CHUNK_SIZE:          %d", CHUNK_SIZE)
logger.info("  REQUEST_DELAY:       %.1f", REQUEST_DELAY)