"""Phase 1 — Streaming sanity check for Stack Exchange data via Hugging Face."""

from __future__ import annotations

import sys
from datetime import datetime, UTC
from datasets import load_dataset

PROFILE_LIMIT = 100_000

SOURCE = "raj2708/stackexchange-all"
STACKOVERFLOW_COMMUNITY = "stackoverflow.com"
STACKOVERFLOW_URL = "stackoverflow.com"

PYTHON_CORE_TAGS = {"python"}
PYTHON_ECOSYSTEM_TAGS = {"numpy", "pandas", "scipy", "matplotlib", "tensorflow", "pytorch", "django", "flask", "fastapi"}


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
        # Exclude meta StackExchange sites
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
    print(f"=== Stack Overflow HF Streaming Sanity Check ===")
    print(f"Dataset: {SOURCE}")
    print(f"Profile limit: {PROFILE_LIMIT}")
    print()

    # Stream the training split
    ds = load_dataset(SOURCE, split="train", streaming=True)

    # Counters
    total_streamed = 0
    stackoverflow_records = 0
    python_core_records = 0
    python_ecosystem_records = 0
    other_python_tags: set[str] = set()
    accepted_counts: list[int] = []
    score_counts: list[int] = []
    token_counts: list[int] = []
    record_types: set[str] = set()
    community_counts: dict[str, int] = {}
    tags_dist: dict[str, int] = {}
    so_by_url = 0

    print("Streaming records (limit = {})...".format(PROFILE_LIMIT))

    for record in ds:
        if total_streamed >= PROFILE_LIMIT:
            break

        total_streamed += 1

        # Community metadata
        raw_community = record.get("metadata", {}).get("community", "")
        community = raw_community.split("|")[0] if "|" in raw_community else raw_community
        community_counts[community] = community_counts.get(community, 0) + 1

        # Check if this is a Stack Overflow record
        is_so = is_stackoverflow_record(record)

        if is_so:
            so_by_url += 1  # track if found by URL instead of community
            stackoverflow_records += 1

        # Tags - pipe-separated
        raw_tags = record.get("metadata", {}).get("tags", "")
        tags = parse_tags(raw_tags)

        # Check for Python relevance
        tag_set = set(tags)
        has_python_core = bool(tag_set & PYTHON_CORE_TAGS)
        has_python_ecosystem = bool(tag_set & PYTHON_ECOSYSTEM_TAGS)

        # Record type
        q_type = record.get("_type", record.get("type", "unknown"))
        record_types.add(q_type)

        # Inspect metadata fields
        metadata = record.get("metadata", {})
        question_score = metadata.get("question_score", None)
        answer_score = metadata.get("answer_score", None)
        is_accepted = metadata.get("is_accepted", None)
        question_id = metadata.get("question_id", None)
        answer_id = metadata.get("answer_id", None)
        token_count = metadata.get("token_count", None)

        if question_score is not None:
            score_counts.append(question_score)
        if answer_score is not None:
            score_counts.append(answer_score)
        if token_count is not None:
            token_counts.append(token_count)

        # Stack Overflow community only - inspect deeper
        if is_so:
            # Python tag analysis
            if has_python_core:
                python_core_records += 1
            if has_python_ecosystem:
                python_ecosystem_records += 1

            # Collect Python ecosystem tags not in core
            for tag in tags:
                if tag in PYTHON_ECOSYSTEM_TAGS and tag not in PYTHON_CORE_TAGS:
                    other_python_tags.add(tag)

            # Score/accepted distribution
            if is_accepted is not None:
                accepted_counts.append(1 if is_accepted else 0)

            # Tag distribution for Stack Overflow records
            for tag in tags:
                tags_dist[tag] = tags_dist.get(tag, 0) + 1

        # Progress logging every 20k
        if total_streamed % 20_000 == 0:
            print(f"  Streamed {total_streamed} records...", flush=True)

    print()
    print("=== Summary ===")
    print(f"Total streamed (capped at {PROFILE_LIMIT}): {total_streamed}")
    print(f"Stack Overflow records (community={STACKOVERFLOW_COMMUNITY} or URL={STACKOVERFLOW_URL}): {stackoverflow_records}")
    print(f"  Python core (<python> tag): {python_core_records}")
    print(f"  Python ecosystem tags: {python_ecosystem_records}")
    print(f"  Other Python ecosystem tags seen: {sorted(other_python_tags)}")
    print(f"Record types seen: {sorted(record_types)}")
    print(f"Communities seen: {sorted(community_counts.keys())}")
    print(f"Stack Overflow records found by URL (not community): {so_by_url}")
    print(f"Top tags (Stack Overflow):")
    for tag, count in sorted(tags_dist.items(), key=lambda x: -x[1])[:20]:
        print(f"  {tag}: {count}")
    print()

    # Score distribution stats
    if score_counts:
        print(f"Score values collected (n={len(score_counts)}): min={min(score_counts)}, max={max(score_counts)}")
    if token_counts:
        print(f"token_count values collected (n={len(token_counts)}): min={min(token_counts)}, max={max(token_counts)}")
    if accepted_counts:
        accepted_true = sum(1 for v in accepted_counts if v)
        accepted_false = len(accepted_counts) - accepted_true
        print(f"Accepted answer flags (n={len(accepted_counts)}): accepted={accepted_true}, not_accepted={accepted_false}")

    print()
    print("=== Phase 1 complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())