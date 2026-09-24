"""HuggingFace dataset collector for The Stack Python functions.

Collector tries the bigcode/python-stack-v1-functions-filtered dataset and
filters for Python function definitions (``def ``).

All output written to Google Drive at /mnt/pythia-cloud/Pythia.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

# ────────────────────────────────────────────────────────────────────
# 1. Set HF environment variables BEFORE any huggingface import
# ────────────────────────────────────────────────────────────────────
DRIVE_ROOT = "/mnt/pythia-cloud/Pythia"
HF_CACHE_DIR = f"{DRIVE_ROOT}/cache/the_stack"
os.environ["HF_DATASETS_CACHE"] = HF_CACHE_DIR
os.environ["HF_HOME"] = f"{DRIVE_ROOT}/cache/hf_home"

# Now safe to import datasets
from datasets import load_dataset  # noqa: E402, imported after env set

# ────────────────────────────────────────────────────────────────────
# 2. Configuration (inline to avoid import issues)
# ────────────────────────────────────────────────────────────────────
THE_STACK_DATASETS = [
    "bigcode/python-stack-v1-functions-filtered",
]

MIN_CONTENT_CHARS = 20

# ────────────────────────────────────────────────────────────────────
# 3. Helper functions
# ────────────────────────────────────────────────────────────────────
PYTHON_TAG = "python"


def _has_python_tag(content: Any) -> bool:
    """Return True if content contains 'def ' (Python function signature)."""
    content_str = str(content) if content else ""
    return "def " in content_str.lower()


def _body_has_code(content: str) -> bool:
    """Return True if content contains a code block (``` or <code>)."""
    if not content:
        return False
    return ("```" in content) or ("<code>" in content.lower())


# ────────────────────────────────────────────────────────────────────
# 4. Main acquisition function
# ────────────────────────────────────────────────────────────────────
def run_the_stack_pilot() -> None:
    """Collect Python functions from The Stack dataset.

    Uses the bigcode/python-stack-v1-functions-filtered HuggingFace dataset.
    Filters for Python function definitions containing 'def ' signatures.

    Output written to:
      /mnt/pythia-cloud/Pythia/raw/the_stack/so_the_stack_pilot.jsonl

    Prints:
    - Total records processed
    - Python records retained
    - Output file size on Drive
    - Estimated tokens (char_count_total / 4.5)
    """
    # Define output path inline
    output_path = f"{DRIVE_ROOT}/raw/the_stack/so_the_stack_pilot.jsonl"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    total_processed = 0
    total_kept = 0
    total_char_count = 0
    python_rejected = 0

    # Open output file once for appending
    try:
        with open(output_path, "w", encoding="utf-8") as out_f:
            for dataset_name in THE_STACK_DATASETS:
                print(f"Attempting dataset: {dataset_name}")

                try:
                    # Load with streaming
                    ds = load_dataset(
                        dataset_name,
                        split="train",
                        streaming=True,
                    )

                    kept_in_dataset = 0
                    processed_in_dataset = 0

                    for i, row in enumerate(ds):
                        processed_in_dataset += 1
                        total_processed += 1

                        # ── Filter: Python tag ──────────────────────────────
                        content = row.get("content") or ""
                        if not _has_python_tag(content):
                            python_rejected += 1
                            continue

                        # ── Filter: minimum content length ────────────────
                        content_len = len(content) if content else 0
                        if content_len < MIN_CONTENT_CHARS:
                            continue

                        # ── Build output record ────────────────────────────
                        collected_at = datetime.now(UTC).replace(microsecond=0).isoformat()

                        record: Dict[str, Any] = {
                            "source": "huggingface",
                            "dataset_name": dataset_name,
                            "content": content,
                            "content_char_count": content_len,
                            "sha1": row.get("sha1", ""),
                            "record_id": row.get("id", i),
                            "collected_at": collected_at,
                        }

                        out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                        total_kept += 1
                        total_char_count += content_len
                        kept_in_dataset += 1

                        # Progress every 100 records and check target
                        if total_kept % 100 == 1:
                            print(f"ST collect progress: {total_processed} processed, {total_kept} kept")

                        # Target check: stop at 1,000 new qualifying records
                        if total_kept >= 1000:
                            print(f"Target reached: 1,000 Python records acquired at {total_processed} processed")
                            break

                except Exception as exc:  # noqa: BLE001
                    print(f"Dataset {dataset_name} failed ({exc}); trying next dataset")
                    continue  # try next dataset

                print(
                    f"Dataset {dataset_name} done: {processed_in_dataset} processed, {kept_in_dataset} kept"
                )

        # ── Summary ────────────────────────────────────────────────
        estimated_tokens = int(total_char_count / 4.5) if total_char_count else 0
        output_size = os.path.getsize(output_path) if os.path.isfile(output_path) else 0

        print("=" * 50)
        print("THE STACK COLLECTOR SUMMARY")
        print(f"  Total records processed:     {total_processed}")
        print(f"  Total records kept:          {total_kept}")
        print(f"  Output file:                {output_path}")
        print(f"  Output size:               {output_size} bytes ({output_size // 1024} KB, {output_size / (1024 * 1024):.2f} MB)")
        print(f"  Estimated tokens:          {estimated_tokens} (char_count / 4.5)")
        print(f"  Python rejection count:    {python_rejected}")
        print("=" * 50)

    except OSError as err:
        raise RuntimeError(
            f"Drive write failed for CS collector. "
            f"Check that Google Drive is mounted at {DRIVE_ROOT}. "
            f"Error: {err}"
        ) from err


if __name__ == "__main__":
    run_the_stack_pilot()