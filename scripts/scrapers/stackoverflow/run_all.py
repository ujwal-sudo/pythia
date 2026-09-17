"""Orchestrator for the Stack Overflow data acquisition pipeline.

Runs collectors in order:
  Step 1 → hf_collector.py (fastest, run first)
  Step 2 → archive_collector.py
  Step 3 → api_collector.py (only if API_KEY is set, skip with warning if not)
  Step 4 → deduplicator.py

Each step is timed and logged. If any step fails, the error is logged
and the pipeline continues to the next step. A final summary is printed
to console and logged.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

from scripts.config import (
    DRIVE_ROOT,
    RAW_OUTPUT_DIR,
    CACHE_DIR,
    OUTPUT_FILES,
    get_logger,
)

logger = get_logger(__name__)

# ────────────────────────────────────────────────────────────────────
# 1. Drive mount check
# ────────────────────────────────────────────────────────────────────
def _check_drive_mount() -> None:
    """Verify Google Drive is mounted at /mnt/pythia-cloud.

    Raises RuntimeError if not mounted.
    """
    if not os.path.ismount("/mnt/pythia-cloud"):
        raise RuntimeError(
            "Google Drive not mounted. "
            "Run: rclone mount google-drive:/ /mnt/pythia-cloud"
        )


# ────────────────────────────────────────────────────────────────────
# 2. Step runner helper
# ────────────────────────────────────────────────────────────────────
def _run_step(
    step_name: str,
    step_func,
) -> Tuple[Optional[float], Optional[int]]:
    """Run a single pipeline step, timing it and logging results.

    Returns (elapsed_minutes, records_written) or (None, None) on failure.
    """
    start = time.time()
    try:
        step_func()
        elapsed = time.time() - start
        minutes = elapsed / 60.0
        logger.info("Step %s complete in %.2f minutes", step_name, minutes)
        print(f"Step {step_name} complete in {minutes:.2f} minutes")
        return minutes, None  # records count logged inside step_func
    except Exception as exc:  # noqa: BLE001
        logger.error("Step %s failed: %s", step_name, exc)
        print(f"Step {step_name} FAILED: {exc}")
        return None, None


# ────────────────────────────────────────────────────────────────────
# 3. Collector functions (imported from submodules)
# ────────────────────────────────────────────────────────────────────
from stackoverflow.hf_collector import run_hf_collector  # noqa: F401
from stackoverflow.archive_collector import run_archive_collector  # noqa: F401
from stackoverflow.api_collector import run_api_collector  # noqa: F401
from stackoverflow.deduplicator import run_dedup  # noqa: F401

# ────────────────────────────────────────────────────────────────────
# 4. Main orchestrator
# ────────────────────────────────────────────────────────────────────
def run_pipeline() -> None:
    """Run the full Stack Overflow acquisition pipeline in order.

    Step 1: hf_collector.py (fastest, run first)
    Step 2: archive_collector.py
    Step 3: api_collector.py (skip if no API_KEY)
    Step 4: deduplicator.py

    Prints final summary to console and logs.
    """
    # ── Drive mount check ────────────────────────────────────────
    _check_drive_mount()

    # ── Step 1: HF collector (fastest) ─────────────────────────────
    print("Starting Step 1: HuggingFace collector")
    minutes, _ = _run_step("HF collector", run_hf_collector)

    # ── Step 2: Archive collector ──────────────────────────────────
    print("Starting Step 2: Archive.org collector")
    minutes2, _ = _run_step("Archive.org collector", run_archive_collector)

    # ── Step 3: API collector (only if API_KEY is meaningfully set) ──
    from stackoverflow.config import API_KEY as _API_KEY
    has_api_key = _API_KEY and _API_KEY.strip()
    if has_api_key:
        print("Starting Step 3: StackExchange API collector")
        minutes3, _ = _run_step("API collector", run_api_collector)
    else:
        print(
            "Step 3: Skipping API collector — no API_KEY set in config.py "
            "(set API_KEY = \"your_key\" to enable)"
        )
        print("  (Continuing without API step)")

    # ── Step 4: Deduplicator ───────────────────────────────────────
    print("Starting Step 4: Deduplicator + quality filter")
    minutes4, _ = _run_step("Deduplicator + quality filter", run_dedup)

    # ── Final summary ──────────────────────────────────────────────
    print()
    print("═" * 65)
    print("STACK OVERFLOW PIPELINE COMPLETE")
    print("═" * 65)
    print(f"  HuggingFace     → output at: {OUTPUT_FILES['hf']}")
    print(f"  Archive         → output at: {OUTPUT_FILES['archive']}")
    print(f"  API             → output at: {OUTPUT_FILES['api']}")
    print(f"  After dedup     → output at: {OUTPUT_FILES['deduped']}")
    print()
    print(f"  All data at: /mnt/pythia-cloud/Pythia/data/raw/stackoverflow/")
    print("═" * 65)

    # Log summary
    logger.info("Stack Overflow pipeline complete")
    logger.info("  HF output: %s", OUTPUT_FILES["hf"])
    logger.info("  Archive output: %s", OUTPUT_FILES["archive"])
    logger.info("  API output: %s", OUTPUT_FILES["api"])
    logger.info("  Deduped output: %s", OUTPUT_FILES["deduped"])