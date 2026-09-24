"""HuggingFace dataset collector for CodeSearchNet Python code snippets and comments.

Collector tries the CodeSearchNet dataset and filters for Python relevance,
minimum code/comment length, and Python function definition presence.

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
HF_CACHE_DIR = f"{DRIVE_ROOT}/cache/codesearchnet"
os.environ["HF_DATASETS_CACHE"] = HF_CACHE_DIR
os.environ["HF_HOME"] = f"{DRIVE_ROOT}/cache/hf_home"

# Now safe to import datasets
from datasets import load_dataset  # noqa: E402, imported after env set

# ────────────────────────────────────────────────────────────────────
# 2. Configuration (inline to avoid import issues)
# ────────────────────────────────────────────────────────────────────
CODESEARCHNET_DATASETS = [
    "sentence-transformers/codesearchnet",
]

MIN_CODE_CHARS = 20
MIN_COMMENT_CHARS = 20

# ────────────────────────────────────────────────────────────────────
# 3. Helper functions
# ────────────────────────────────────────────────────────────────────
PYTHON_TAG = "python"


def _has_python_tag(code: Any, comment: Any) -> bool:
    """Return True if code or comment contains 'def ' (Python function signature)."""
    code_str = str(code) if code else ""
    comment_str = str(comment) if comment else ""
    return ("def " in code_str.lower()) or ("def " in comment_str.lower())


def _body_has_code(code: str) -> bool:
    """Return True if code contains a code block (``` or <code>)."""
    if not code:
        return False
    return ("```" in code) or ("<code>" in code.lower())


# ────────────────────────────────────────────────────────────────────
# 4. Main collector function
# ────────────────────────────────────────────────────────────────────
def run_codesearchnet_collector() -> None:
    """Collect Python code snippets and comments from CodeSearchNet datasets.

    Tries datasets in CODESEARCHNET_DATASETS order. For each dataset:
    - Filters rows with Python tag ('def ' in code or comment),
      minimum code length, minimum comment length
    - Appends filtered rows to OUTPUT_FILES["codesearchnet"]
    - Prints/logs progress every 10 000 rows
    - On failure, logs and tries the next dataset

    After completion prints:
    - Total rows processed
    - Total rows kept after filter
    - Output file size on Drive
    - Estimated tokens (char_count_total / 4.5)
    """
    # Define output path inline
    output_path = f"{DRIVE_ROOT}/raw/codesearchnet/so_codesearchnet.jsonl"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    total_processed = 0
    total_kept = 0
    total_char_count = 0
    python_rejected = 0

    # Open output file once for appending
    try:
        with open(output_path, "w", encoding="utf-8") as out_f:
            for dataset_name in CODESEARCHNET_DATASETS:
                logger_msg = f"Attempting dataset: {dataset_name}"
                print(logger_msg)

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
                        code = row.get("code") or row.get("code", "")
                        comment = row.get("comment") or row.get("comment", "")
                        if not _has_python_tag(code, comment):
                            python_rejected += 1
                            continue

                        # ── Filter: minimum code length ────────────────────
                        code_len = len(str(code)) if code else 0
                        if code_len < MIN_CODE_CHARS:
                            continue

                        # ── Filter: minimum comment length ─────────────────
                        comment_len = len(str(comment)) if comment else 0
                        if comment_len < MIN_COMMENT_CHARS:
                            continue

                        # ── Build output record ────────────────────────────
                        collected_at = datetime.now(UTC).replace(microsecond=0).isoformat()

                        record: Dict[str, Any] = {
                            "source": "huggingface",
                            "dataset_name": dataset_name,
                            "comment": comment,
                            "code": code,
                            "code_char_count": code_len,
                            "comment_char_count": comment_len,
                            "collected_at": collected_at,
                        }

                        out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                        total_kept += 1
                        total_char_count += code_len
                        kept_in_dataset += 1

                        # Progress every 10 000 rows
                        if total_processed % 10_000 == 0:
                            print(f"CS collect progress: {total_processed} processed, {total_kept} kept")

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
        print("CODESEARCHNET COLLECTOR SUMMARY")
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
    run_codesearchnet_collector()