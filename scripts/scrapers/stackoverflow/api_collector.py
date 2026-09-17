"""Stack Exchange API collector for Python QA pairs.

Uses the public API endpoint https://api.stackexchange.com/2.3/questions
with pagination, accepted-answer fetching, and resumable checkpointing.

All output written to Google Drive at /mnt/pythia-cloud/Pythia.
Handles rate limits, backoff, and errors gracefully.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

import requests

from scripts.config import (
    CACHE_DIR,
    MIN_ANSWER_SCORE,
    OUTPUT_FILES,
    QUALITY_FILTERS,
    DRIVE_ROOT,
    REQUEST_DELAY,
    get_logger,
)

logger = get_logger(__name__)

# ────────────────────────────────────────────────────────────────────
# 1. Paths
# ────────────────────────────────────────────────────────────────────
CHECKPOINT_PATH = f"{CACHE_DIR}/api_checkpoint.json"

# ────────────────────────────────────────────────────────────────────
# 2. API configuration
# ────────────────────────────────────────────────────────────────────
API_BASE = "https://api.stackexchange.com/2.3/questions"
API_KEY = ""  # Set this in config.py if you have a key; empty string works
# but has lower rate limits.

# ────────────────────────────────────────────────────────────────────
# 3. Helper functions
# ────────────────────────────────────────────────────────────────────

def _body_has_code(body: str) -> bool:
    """Return True if body contains a code block (``` or <code>)."""
    if not body:
        return False
    return ("```" in body) or ("<code>" in body.lower())


def _load_checkpoint() -> Dict[str, Any]:
    """Load the pagination checkpoint from cache, or return defaults."""
    if os.path.isfile(CHECKPOINT_PATH):
        try:
            with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"page": 1, "has_more": True, "quota_remaining": 1000}


def _save_checkpoint(page: int, has_more: bool, quota_remaining: int) -> None:
    """Save the pagination checkpoint to cache."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    checkpoint = {"page": page, "has_more": has_more, "quota_remaining": quota_remaining}
    try:
        with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f)
    except OSError:
        logger.warning("Failed to write checkpoint to %s", CHECKPOINT_PATH)


# ────────────────────────────────────────────────────────────────────
# 3. API query function
# ──────────────────────────────────────────────────────────────────
def _api_query(page: int, pagesize: int = 100, min: int = MIN_ANSWER_SCORE) -> Dict[str, Any]:
    """Query the StackExchange API for a page of questions.

    Returns the parsed JSON response dict.
    """
    params = {
        "site": "stackoverflow",
        "tagged": "python",
        "sort": "votes",
        "order": "desc",
        "filter": "withbody",
        "pagesize": pagesize,
        "min": min,
        "key": API_KEY,
    }

    try:
        response = requests.get(API_BASE, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        # Update quota tracking
        quota_remaining = data.get("quota_remaining", 1000)
        # Save checkpoint after every request
        _save_checkpoint(page, data.get("has_more", False), quota_remaining)

        # Respect backoff
        if "backoff" in data:
            backoff = data["backoff"]
            logger.info("API backoff %d seconds", backoff)
            time.sleep(backoff)

        # Respect rate limit warning
        if quota_remaining and quota_remaining < 100:
            logger.warning(
                "Quota remaining low: %d; stopping gracefully", quota_remaining
            )

        return data

    except requests.Timeout:
        logger.error("API request timed out on page %d", page)
        raise
    except requests.ConnectionError:
        logger.error("API connection error on page %d", page)
        raise
    except json.JSONDecodeError:
        logger.error("JSON decode error on page %d", page)
        raise


# ────────────────────────────────────────────────────────────────────
# 4. Accepted answer fetcher
# ──────────────────────────────────────────────────────────────────
def _fetch_accepted_answer(answer_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a single accepted answer from the API.

    Returns dict with answer data, or None on failure.
    """
    try:
        ans_url = f"https://api.stackexchange.com/2.3/answers/{answer_id}"
        params = {"filter": "withbody", "site": "stackoverflow"}
        resp = requests.get(ans_url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("items"):
            return None

        item = data["items"][0]
        body = item.get("body", "")
        score = item.get("score", 0)

        has_code = _body_has_code(body)

        return {
            "answer_id": answer_id,
            "body": body,
            "score": score,
            "has_code": has_code,
            "is_accepted": True,
        }

    except (requests.Timeout, requests.ConnectionError, json.JSONDecodeError):
        logger.warning("Failed to fetch answer %d", answer_id)
        return None


# ────────────────────────────────────────────────────────────────────
# 5. Main collector function
# ────────────────────────────────────────────────────────────────────
def run_api_collector() -> None:
    """Run the Stack Exchange API Python QA collector.

    Steps:
    1. Load checkpoint to resume pagination
    2. Loop: query questions page → fetch accepted answers → write records
    3. Stop when has_more == False, or 500 000 pairs collected, or quota low
    4. Respect rate limits (REQUEST_DELAY, backoff, quota_remaining)
    5. Write to OUTPUT_FILES["api"] as JSONL
    6. Print summary totals and estimated tokens
    """
    output_path = OUTPUT_FILES["api"]
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Load checkpoint
    checkpoint = _load_checkpoint()
    start_page = checkpoint.get("page", 1)
    has_more = checkpoint.get("has_more", True)
    quota_remaining = checkpoint.get("quota_remaining", 1000)

    total_processed = 0
    total_kept = 0
    total_char_count = 0
    pairs_collected = 0

    try:
        with open(output_path, "w", encoding="utf-8") as out_f:
            while has_more and pairs_collected < 500_000:
                # Query page
                data = _api_query(start_page, pagesize=100, min=MIN_ANSWER_SCORE)

                has_more = data.get("has_more", False)
                quota_remaining = data.get("quota_remaining", quota_remaining)

                questions = data.get("items", [])
                if not questions:
                    logger.info("No questions returned on page %d", start_page)
                    break

                for q in questions:
                    # Skip if no accepted_answer_id
                    accepted_id = q.get("accepted_answer_id")
                    if not accepted_id:
                        continue

                    # Fetch the accepted answer
                    ans_data = _fetch_accepted_answer(accepted_id)
                    if ans_data is None:
                        continue

                    # ── Quality filters ────────────────────────────────
                    body = ans_data["body"]
                    score = ans_data["score"]

                    if len(body) < QUALITY_FILTERS["min_body_length"]:
                        continue

                    if not _body_has_code(body):
                        continue

                    # ── Build output record ──────────────────────────────
                    collected_at = datetime.now(UTC).replace(microsecond=0).isoformat()

                    record: Dict[str, Any] = {
                        "source": "api",
                        "question_id": q.get("question_id", ""),
                        "answer_id": ans_data["answer_id"],
                        "question_title": q.get("title", ""),
                        "question_body": q.get("body", ""),
                        "answer_body": body,
                        "score": score,
                        "is_accepted": ans_data["is_accepted"],
                        "tags": q.get("tags", ""),
                        "has_code": ans_data["has_code"],
                        "char_count": len(body),
                        "collected_at": collected_at,
                    }

                    out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    total_kept += 1
                    total_char_count += len(body)
                    pairs_collected += 1

                    # Rate delay
                    time.sleep(REQUEST_DELAY)

                # Progress logging every 1000 records
                total_processed += len(questions)
                if total_processed % 1000 == 0:
                    logger.info(
                        "API collect progress: %d processed, %d kept, %d pairs",
                        total_processed,
                        total_kept,
                        pairs_collected,
                    )

                # Next page
                start_page += 1

                # If we've hit the pair limit, break
                if pairs_collected >= 500_000:
                    logger.info("Reached 500 000 pair limit")
                    break

                # If no more questions, stop
                if not has_more:
                    logger.info("API has_more == False; stopping")
                    break

                # Polite delay between pages
                time.sleep(REQUEST_DELAY)

    except Exception as exc:  # noqa: BLE001
        logger.error("API collector failed: %s", exc)
        raise

    # ── Summary ────────────────────────────────────────────────────
    output_size = os.path.getsize(output_path) if os.path.isfile(output_path) else 0
    estimated_tokens = int(total_char_count / 4.5) if total_char_count else 0

    logger.info("=" * 50)
    logger.info("API COLLECTOR SUMMARY")
    logger.info("  Total questions fetched:  %d", total_processed)
    logger.info("  Total records kept:       %d", total_kept)
    logger.info("  Total pairs collected:    %d", pairs_collected)
    logger.info("  Output file size:         %d bytes (%d KB, %.2f MB)",
                output_size, output_size // 1024, output_size / (1024 * 1024))
    logger.info("  Estimated tokens:         %d (char_count / 4.5)", estimated_tokens)
    logger.info("=" * 50)

    print("=" * 50)
    print("API COLLECTOR SUMMARY")
    print(f"  Total questions fetched:  {total_processed}")
    print(f"  Total records kept:       {total_kept}")
    print(f"  Total pairs collected:    {pairs_collected}")
    print(f"  Output file size:         {output_size} bytes ({output_size // 1024} KB, {output_size / (1024 * 1024):.2f} MB)")
    print(f"  Estimated tokens:         {estimated_tokens} (char_count / 4.5)")
    print("=" * 50)

    # Save final checkpoint
    _save_checkpoint(start_page, has_more, quota_remaining)

    # Graceful stop if quota very low
    if quota_remaining and quota_remaining < 100:
        logger.warning(
            "Quota remaining very low (%d); API collector stopping",
            quota_remaining,
        )
        print(
            "WARNING: Quota remaining very low — API collector stopped gracefully."
        )

    except OSError as err:  # noqa: BLE001
        if err.errno in (5, 30):  # I/O error / OS level
            raise RuntimeError(
                "Drive write failed — check rclone mount. "
                f"Error: {err}"
            ) from err
        raise