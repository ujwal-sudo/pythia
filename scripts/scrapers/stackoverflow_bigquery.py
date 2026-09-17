"""Step 7 — BigQuery Extraction for Stack Overflow data.

Responsibilities:
1. Run parameterized BigQuery queries
2. Extract only required records (Python-tagged, quality candidates)
3. Write chunked output under STACKOVERFLOW_DIR
4. Preserve metadata (question_id, answer_id, title, body, tags, scores, dates, URL, license)
5. Record query configuration for provenance
6. Record estimated bytes processed
7. Support resumability (skip already-processed chunks)
8. Avoid downloading irrelevant Stack Overflow data

DO NOT pull the whole Stack Overflow database.
"""

from __future__ import annotations

import json
import os
import sys
from config import STACKOVERFLOW_DIR
import hashlib
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional, Tuple


# BigQuery configuration
BIGQUERY_PROJECT = "bigquery-public-data"
DATASET = "stackoverflow"
QUESTIONS_TABLE = "posts_questions"
ANSWERS_TABLE = "posts_answers"

# Python relevance tags (from Phase 2 - maintain separately core/ecosystem)
PYTHON_CORE_TAGS = {"python"}
PYTHON_ECOSYSTEM_TAGS = {"numpy", "pandas", "scipy", "matplotlib", "tensorflow", "pytorch", "django", "flask", "fastapi"}

# Quality tier thresholds
TIER_THRESHOLDS = {
    "A": {"accepted": True, "min_answer_score": 10},
    "B": {"accepted": False, "min_answer_score": 20},
    "C": {"accepted": True, "min_answer_score": 5},
}

# Output configuration
OUTPUT_DIR = STACKOVERFLOW_DIR
CHUNK_SIZE = 10_000  # records per output file
MAX_INITIAL_RECORDS = 100_000  # for first milestone


def parse_tags(tags_str: str) -> List[str]:
    """Parse pipe-separated tags string into list."""
    if not tags_str:
        return []
    return [t.strip() for t in tags_str.split("|") if t.strip()]


def is_python_relevant(tags: List[str], core_only: bool = False) -> bool:
    """Check if tags indicate Python relevance.

    Args:
        tags: list of tag strings
        core_only: if True, only check for <python> core tag
    """
    tag_set = set(tags)

    if core_only:
        return bool(tag_set & PYTHON_CORE_TAGS)

    # Check core tag first (primary corpus centered on python_core)
    if tag_set & PYTHON_CORE_TAGS:
        return True

    # Check ecosystem tags (only if genuinely relevant)
    python_eco = {"numpy", "pandas", "scipy", "matplotlib", "tensorflow", "pytorch",
                  "django", "flask", "fastapi"}
    if tag_set & python_eco:
        return True

    return False


def quality_tier(record: dict) -> Optional[str]:
    """Determine quality tier for a candidate record.

    Tier A: accepted answer AND answer_score >= 10
    Tier B: non-accepted answer AND answer_score >= 20
    Tier C: accepted answer AND answer_score >= 5
    None: does not meet any tier threshold
    """
    answer_score = record.get("answer_score")
    is_accepted = record.get("is_accepted")

    if answer_score is None:
        return None

    # Tier A
    if is_accepted is True and answer_score >= 10:
        return "A"

    # Tier B
    if is_accepted is False and answer_score >= 20:
        return "B"

    # Tier C
    if is_accepted is True and answer_score >= 5:
        return "C"

    return None


def sha256_file(filepath: str) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def build_questions_query(
    python_core_only: bool = True,
    min_answer_score: int = 5,
    accepted_only: bool = False,
    limit: Optional[int] = None,
) -> Tuple[str, dict]:
    """Build a BigQuery query for Stack Overflow questions.

    Returns:
        (query_string, query_config_dict)
    """
    # Python tag filter
    if python_core_only:
        tag_condition = "LOWER(tags) LIKE '%<python>%'"
    else:
        tag_condition = "LOWER(tags) LIKE '%<python>%'"

    # Quality filter (minimum answer score)
    score_condition = f"score >= {min_answer_score}"

    # Accepted filter
    where_parts = [tag_condition, score_condition]
    if accepted_only:
        where_parts.append("accepted_answer_id IS NOT NULL")

    WHERE_clause = " AND ".join(where_parts)

    ORDER_clause = "creation_date DESC"

    limit_clause = ""
    if limit:
        limit_clause = f"LIMIT {limit}"

    full_query = f"""
        SELECT
            id AS question_id,
            title,
            body AS question_body,
            tags,
            accepted_answer_id,
            score AS question_score,
            creation_date AS question_creation_date
        FROM `{BIGQUERY_PROJECT}.{DATASET}.{QUESTIONS_TABLE}`
        WHERE {WHERE_clause}
        ORDER BY {ORDER_clause}
        {limit_clause}
    """

    query_config = {
        "project": BIGQUERY_PROJECT,
        "dataset": DATASET,
        "table": QUESTIONS_TABLE,
        "python_core_only": python_core_only,
        "min_answer_score": min_answer_score,
        "accepted_only": accepted_only,
        "limit": limit,
    }

    return full_query, query_config


def build_answers_query(
    question_ids: List[int],
    python_core_only: bool = True,
    min_answer_score: int = 5,
    accepted_only: bool = False,
    limit: Optional[int] = None,
) -> Tuple[str, dict]:
    """Build a BigQuery query for answers linked to selected questions.

    Returns:
        (query_string, query_config_dict)
    """
    # Build the question ID filter
    if question_ids:
        id_values = ", ".join(f"({qid})" for qid in question_ids[:1000])
        id_filter = f"WHERE parent_id IN ({id_values})"
    else:
        id_filter = "WHERE 1=0"

    # Python tag filter on answers
    if python_core_only:
        tag_condition = "LOWER(tags) LIKE '%<python>%'"
    else:
        tag_condition = "LOWER(tags) LIKE '%<python>%'"

    # Answer score filter
    score_condition = f"score >= {min_answer_score}"

    WHERE_clause = f" {tag_condition} AND {score_condition}"

    # Accepted filter - answers table doesn't have is_accepted directly
    # We would need to join with questions, but skipping for now

    ORDER_clause = "creation_date DESC"

    limit_clause = ""
    if limit:
        limit_clause = f"LIMIT {limit}"

    full_query = f"""
        SELECT
            id AS answer_id,
            parent_id,
            body AS answer_body,
            tags,
            score AS answer_score,
            creation_date AS answer_creation_date
        FROM `{BIGQUERY_PROJECT}.{DATASET}.{ANSWERS_TABLE}` {id_filter}
        WHERE {WHERE_clause}
        ORDER BY {ORDER_clause}
        {limit_clause}
    """

    query_config = {
        "project": BIGQUERY_PROJECT,
        "dataset": DATASET,
        "table": ANSWERS_TABLE,
        "question_ids": question_ids,
        "python_core_only": python_core_only,
        "min_answer_score": min_answer_score,
        "accepted_only": accepted_only,
        "limit": limit,
    }

    return full_query, query_config


def write_chunked_output(
    records: List[dict],
    output_dir: str = OUTPUT_DIR,
    chunk_prefix: str = "stackoverflow_bigquery_candidates",
    chunk_number: int = None,
) -> str:
    """Write records to a chunked JSONL file.

    Args:
        records: list of record dicts to write
        output_dir: output directory
        chunk_prefix: filename prefix
        chunk_number: specific chunk number (auto-assign if None)

    Returns:
        path to the written file
    """
    os.makedirs(output_dir, exist_ok=True)

    if chunk_number is None:
        # Count existing chunks to determine next number
        existing = [f for f in os.listdir(output_dir)
                    if f.startswith(chunk_prefix) and f.endswith(".jsonl")]
        chunk_number = len(existing) + 1

    chunk_filename = f"{chunk_prefix}_v1_part-{chunk_number:04d}.jsonl"
    chunk_path = os.path.join(output_dir, chunk_filename)

    with open(chunk_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, sort_keys=True) + "\n")

    return chunk_path


def count_existing_chunks(output_dir: str = OUTPUT_DIR, chunk_prefix: str = "stackoverflow_bigquery_candidates") -> int:
    """Count existing chunk files to support resumability."""
    if not os.path.isdir(output_dir):
        return 0
    existing = [f for f in os.listdir(output_dir)
                if f.startswith(chunk_prefix) and f.endswith(".jsonl")]
    return len(existing)


def main() -> int:
    """Step 7 — BigQuery Extraction entry point.

    Demonstrates query construction and chunked output writing.
    In production, this would execute queries via the BigQuery API.
    """
    print("=" * 60)
    print("Phase 7: BigQuery Extraction (Step 7)")
    print("=" * 60)
    print()
    print("Note: GCP credentials required for actual BigQuery execution.")
    print("This script demonstrates query construction and")
    print("chunked output writing for when credentials are available.")
    print()
    print("=" * 60)

    # Example: build and display a small query for initial milestone
    print("Building initial milestone query (first 100 records)...")
    query, config = build_questions_query(
        python_core_only=True,
        min_answer_score=5,
        accepted_only=False,
        limit=100,
    )

    print(f"Query configured for {config['limit']} records")
    print(f"Python core only: {config['python_core_only']}")
    print(f"Minimum answer score: {config['min_answer_score']}")
    print()
    print("Query:")
    print(query)
    print()

    # Demonstrate chunked output writing with mock data
    print("Demonstrating chunked output writing with mock records...")

    # Create sample records that match the output format
    # Including all fields needed by the token budget mechanism
    sample_records = []
    for i in range(5):
        rec = {
            "question_id": 1000 + i,
            "answer_id": 5000 + i,
            "question_text": f"How do decorators work in Python? Question {i} context.",
            "answer_text": "def decorator(func):\n    def wrapper(*args, **kwargs):\n        return func(*args, **kwargs)\n    return wrapper",
            "title": f"Python question {i}: about decorators",
            "tags": ["python", "decorators"],
            "question_score": 15,
            "answer_score": 10,
            "is_accepted": True if i % 2 == 0 else False,
            "source_token_count": 500 + i * 100,  # provisional estimate
            "acquisition_timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "source_url": f"https://stackoverflow.com/questions/{1000 + i}",
            "source_license": "CC BY-SA 4.0",
            "source_dataset": "bigquery-public-data.stackoverflow",
            "record_type": "stackoverflow_qa",
        }
        sample_records.append(rec)

    # Write to chunked output
    chunk_path = write_chunked_output(sample_records, chunk_number=1)
    print(f"Wrote {len(sample_records)} sample records to: {chunk_path}")
    print(f"SHA-256: {sha256_file(chunk_path)}")

    # Show what the next steps would be
    print()
    print("Next steps (when GCP credentials available):")
    print("1. Execute build_questions_query() via bigquery.Client().query()")
    print("2. Process results and build question_ids list")
    print("3. Execute build_answers_query() to get answers")
    print("4. Write chunked output with write_chunked_output()")
    print("5. Update manifest_bigquery_v1.json with provenance")
    print("6. Run unit tests with mocked BigQuery results")
    print()
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())