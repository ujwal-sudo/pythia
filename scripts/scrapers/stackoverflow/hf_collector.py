"""HuggingFace dataset collector for Stack Overflow Python QA pairs.

Collector tries datasets in order and filters for Python relevance,
minimum score, body length, and code presence.

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
HF_CACHE_DIR = f"{DRIVE_ROOT}/cache/huggingface"
os.environ["HF_DATASETS_CACHE"] = HF_CACHE_DIR
os.environ["HF_HOME"] = f"{DRIVE_ROOT}/cache/hf_home"

# Now safe to import datasets
from datasets import load_dataset  # noqa: E402, imported after env set

from scripts.config import MIN_ANSWER_SCORE, OUTPUT_FILES, QUALITY_FILTERS, get_logger

logger = get_logger(__name__)

# ────────────────────────────────────────────────────────────────────
# 2. Dataset order (try each, move to next on failure)
# ────────────────────────────────────────────────────────────────────
HF_DATASETS = [
    "ArmelR/stack-exchange-instruction",
    "HuggingFaceH4/stack-exchange-preferences",
    "koutch/stackoverflow_python",
]

# ────────────────────────────────────────────────────────────────────
# 3. Helper: check if a record has Python relevance
# ────────────────────────────────────────────────────────────────────
PYTHON_TAG = "python"


def _has_python_tag(tags: Any) -> bool:
    """Return True if tags contain 'python' (case-insensitive)."""
    if tags is None:
        return False
    if isinstance(tags, str):
        return PYTHON_TAG in tags.lower()
    if isinstance(tags, list):
        return any(PYTHON_TAG in str(t).lower() for t in tags)
    return False


def _body_has_code(body: str) -> bool:
    """Return True if body contains a code block (``` or <code>)."""
    if not body:
        return False
    return ("```" in body) or ("<code>" in body.lower())


# ────────────────────────────────────────────────────────────────────
# 4. Main collector function
# ────────────────────────────────────────────────────────────────────
def run_hf_collector() -> None:
    """Collect Stack Overflow Python QA pairs from HuggingFace datasets.

    Tries datasets in HF_DATASETS order. For each dataset:
    - Filters rows with python tag, minimum score, body length, code block
    - Appends filtered rows to OUTPUT_FILES["hf"]
    - Prints/logs progress every 10 000 rows
    - On failure, logs and tries the next dataset

    After completion prints:
    - Total rows processed
    - Total rows kept after filter
    - Output file size on Drive
    - Estimated tokens (char_count_total / 4.5)
    """
    output_path = OUTPUT_FILES["hf"]
    min_score = MIN_ANSWER_SCORE
    min_body_len = QUALITY_FILTERS["min_body_length"]

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    total_processed = 0
    total_kept = 0
    total_char_count = 0
    dataset_names: List[str] = []

    # Open output file once for appending
    try:
        with open(output_path, "w", encoding="utf-8") as out_f:
            for dataset_name in HF_DATASETS:
                dataset_names.append(dataset_name)
                logger.info("Attempting dataset: %s", dataset_name)

                try:
                    # Load with streaming; limit to first 200k rows for speed
                    ds = load_dataset(
                        dataset_name,
                        split="train",
                        streaming=True,
                        trust_remote_code=True,
                    )

                    kept_in_dataset = 0
                    processed_in_dataset = 0

                    for i, row in enumerate(ds):
                        processed_in_dataset += 1
                        total_processed += 1

                        # ── Filter: Python tag ──────────────────────────────
                        tags = row.get("tags") or row.get("metadata", {}).get("tags", "")
                        if not _has_python_tag(tags):
                            continue

                        # ── Filter: minimum score ──────────────────────────
                        score = row.get("score") or row.get("metadata", {}).get("score", 0)
                        if isinstance(score, (int, float)) and score < min_score:
                            continue

                        # ── Filter: body length >= 200 chars ───────────────
                        body = row.get("body") or row.get("metadata", {}).get("body", "")
                        if not body or len(body) < min_body_len:
                            continue

                        # ── Filter: contains code block ────────────────────
                        if not _body_has_code(body):
                            continue

                        # ── Build output record ────────────────────────────
                        collected_at = datetime.now(UTC).replace(microsecond=0).isoformat()

                        # Determine question/answer — datasets vary in structure
                        # Most have 'question' and 'answer' or 'instruction' and 'response'
                        question_text = row.get("instruction") or row.get("question", "")
                        answer_text = row.get("response") or row.get("answer", "")

                        record: Dict[str, Any] = {
                            "source": "huggingface",
                            "dataset_name": dataset_name,
                            "question": question_text,
                            "answer": answer_text,
                            "score": int(score) if isinstance(score, (int, float)) else 0,
                            "tags": tags if isinstance(tags, str) else str(tags),
                            "has_code": _body_has_code(answer_text),
                            "char_count": len(answer_text),
                            "collected_at": collected_at,
                        }

                        out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                        total_kept += 1
                        total_char_count += len(answer_text)
                        kept_in_dataset += 1

                        # Progress every 10 000 rows
                        if total_processed % 10_000 == 0:
                            logger.info(
                                "HF collect progress: %d processed, %d kept",
                                total_processed,
                                total_kept,
                            )

                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Dataset %s failed (%s); trying next dataset",
                        dataset_name,
                        exc,
                    )
                    continue  # try next dataset

                logger.info(
                    "Dataset %s done: %d processed, %d kept",
                    dataset_name,
                    processed_in_dataset,
                    kept_in_dataset,
                )

        # ── Summary ────────────────────────────────────────────────
        estimated_tokens = int(total_char_count / 4.5) if total_char_count else 0
        output_size = os.path.getsize(output_path) if os.path.isfile(output_path) else 0

        logger.info("=" * 50)
        logger.info("HF COLLECTOR SUMMARY")
        logger.info("  Total rows processed:     %d", total_processed)
        logger.info("  Total rows kept:          %d", total_kept)
        logger.info("  Output file size:         %d bytes (%d KB, %.2f MB)",
                    output_size, output_size // 1024, output_size / (1024 * 1024))
        logger.info("  Estimated tokens:         %d (char_count / 4.5)", estimated_tokens)
        logger.info("=" * 50)

        print("=" * 50)
        print("HF COLLECTOR SUMMARY")
        print(f"  Total rows processed:     {total_processed}")
        print(f"  Total rows kept:          {total_kept}")
        print(f"  Output file size:         {output_size} bytes ({output_size // 1024} KB, {output_size / (1024 * 1024):.2f} MB)")
        print(f"  Estimated tokens:         {estimated_tokens} (char_count / 4.5)")
        print("=" * 50)

    except OSError as err:  # noqa: BLE001
        raise RuntimeError(
            f"Drive write failed for HF collector. "
            f"Check that Google Drive is mounted at {DRIVE_ROOT}. "
            f"Error: {err}"
        ) from err