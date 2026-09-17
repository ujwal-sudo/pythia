"""Phase 4 — Save a raw selected snapshot of Stack Overflow candidate records."""

from __future__ import annotations

import json
import sys
from datetime import datetime, UTC
from config import STACKOVERFLOW_DIR

PROFILE_LIMIT = 100_000

SOURCE = "raj2708/stackexchange-all"
STACKOVERFLOW_COMMUNITY = "stackoverflow.com"
STACKOVERFLOW_URL = "stackoverflow.com"

OUTPUT_PATH = STACKOVERFLOW_DIR / "stackoverflow_candidates_v1.jsonl"


def is_stackoverflow_record(record: dict) -> bool:
    """Check if a record is from Stack Overflow community.

    Primary: community field == "stackoverflow.com"
    Secondary: URL contains "stackoverflow.com" (not meta variants)
    """
    metadata = record.get("metadata", {})
    community = metadata.get("community", "")

    # Primary filter: community field
    if community == STACKOVERFLOW_COMMUNITY:
        return True

    # Secondary filter: URL contains stackoverflow.com (not .meta.stackexchange.com)
    url = metadata.get("url", "")
    if STACKOVERFLOW_URL in url:
        if "meta.stackexchange" not in url:
            return True

    return False


def parse_tags(raw_tags) -> list[str]:
    """Parse tag string into list of tag names.

    Tags are pipe-separated: "tag1|tag2|tag3"
    """
    if raw_tags is None:
        return []
    if isinstance(raw_tags, str):
        return [t.strip() for t in raw_tags.split("|") if t.strip()]
    elif isinstance(raw_tags, list):
        return [str(t).strip() for t in raw_tags if t]
    return []


def main() -> int:
    print(f"=== Phase 4: Save Raw Stack Overflow Candidate Snapshot ===")
    print(f"Dataset: {SOURCE}")
    print(f"Output: {OUTPUT_PATH}")
    print()

    # Stream the training split
    ds = load_dataset(SOURCE, split="train", streaming=True)

    # Ensure output directory exists
    import os
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    selected_count = 0
    total_streamed = 0

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for record in ds:
            if total_streamed >= PROFILE_LIMIT:
                break

            total_streamed += 1

            is_so = is_stackoverflow_record(record)

            if not is_so:
                continue

            # Build the selected record
            metadata = record.get("metadata", {})
            tags = parse_tags(metadata.get("tags", ""))

            # Extract text fields - the dataset has 'instruction' (question) and 'response' (answer)
            instruction = record.get("instruction", "")
            response = record.get("response", "")

            # Also get the high-level text field
            text = record.get("text", "")

            # Determine question and answer from text/instruction/response
            # The dataset format: instruction = question, response = answer
            # But text may contain both

            question_text = instruction if instruction else (text[:500] if text else "")
            answer_text = response if response else ""

            record_obj = {
                "question_id": metadata.get("question_id", ""),
                "answer_id": metadata.get("answer_id", ""),
                "title": instruction[:200] if instruction else "",
                "question_text": question_text,
                "answer_text": answer_text,
                "question_score": metadata.get("question_score", None),
                "answer_score": metadata.get("answer_score", None),
                "is_accepted": metadata.get("is_accepted", None),
                "tags": tags,
                "community": metadata.get("community", ""),
                "source_url": metadata.get("url", ""),
                "source_license": metadata.get("license", ""),
                "source_dataset": SOURCE,
                "source_dataset_revision": None,  # Not available from streaming
                "source_token_count": metadata.get("token_count", None),
                "record_type": record.get("type", "unknown"),
                "acquisition_timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
            }

            f.write(json.dumps(record_obj, sort_keys=True) + "\n")
            selected_count += 1

    print(f"Selection complete:")
    print(f"  Total streamed (capped at {PROFILE_LIMIT}): {total_streamed}")
    print(f"  Stack Overflow candidates selected: {selected_count}")
    print(f"  Output written to: {OUTPUT_PATH}")
    print()
    print("=== Phase 4 complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())