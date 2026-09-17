"""Phase 5 — Token budgeting mechanism for Stack Overflow candidate selection.

Implements deterministic selection policy:
1. rank/filter candidates by quality
2. preserve topic diversity
3. preserve temporal diversity
4. preserve answer diversity
5. exact deduplication
6. downstream near-deduplication
7. measure actual Pythia tokenizer token count

Source metadata token_count is provisional; final count must use actual Pythia tokenizer.
"""

from __future__ import annotations

import json
import os
import sys
from config import STACKOVERFLOW_DIR
import hashlib
from datetime import datetime, UTC
from collections import defaultdict

# Configuration
TARGET_FINAL_TOKENS_MIN = 600_000_000  # 600M final validated tokens
TARGET_FINAL_TOKENS_MAX = 700_000_000  # 700M final validated tokens

PROFILE_LIMIT = 100_000  # records to scan for characterization

# Quality tier thresholds (from Phase 3 profiling)
TIER_THRESHOLDS = {
    "A": {"accepted": True, "min_score": 10},
    "B": {"accepted": False, "min_score": 20},
    "C": {"accepted": True, "min_score": 5},
}

PYTHON_CORE_TAGS = {"python"}
PYTHON_ECOSYSTEM_TAGS = {"numpy", "pandas", "scipy", "matplotlib", "tensorflow", "pytorch", "django", "flask", "fastapi"}


def parse_tags(raw_tags) -> list[str]:
    """Parse pipe-separated tag string into list."""
    if raw_tags is None:
        return []
    if isinstance(raw_tags, str):
        return [t.strip() for t in raw_tags.split("|") if t.strip()]
    elif isinstance(raw_tags, list):
        return [str(t).strip() for t in raw_tags if t]
    return []


def is_python_relevant(tags: list[str], core_only: bool = False) -> bool:
    """Check if tags indicate Python relevance.

    Args:
        tags: list of tag strings
        core_only: if True, only check for <python> core tag
    """
    tag_set = set(tags)

    if core_only:
        return bool(tag_set & PYTHON_CORE_TAGS)

    # Check core tag
    has_core = bool(tag_set & PYTHON_CORE_TAGS)
    if has_core:
        return True

    # Check ecosystem tags (only if genuinely relevant - not silently include ML tags)
    python_eco = {"numpy", "pandas", "scipy", "matplotlib", "tensorflow", "pytorch",
                  "django", "flask", "fastapi"}
    has_eco = bool(tag_set & python_eco)
    return has_eco


def quality_tier(record: dict) -> str | None:
    """Determine quality tier for a candidate record.

    Tier A: accepted answer AND answer_score >= 10
    Tier B: non-accepted answer AND answer_score >= 20
    Tier C: accepted answer AND answer_score >= 5 (useful explanatory context)
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


def compute_sha256(filepath: str) -> str | None:
    """Compute SHA-256 hash of a file."""
    if not os.path.isfile(filepath):
        return None
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def select_candidates_deterministic(
    input_path: str,
    output_path: str,
    target_tokens_min: int = TARGET_FINAL_TOKENS_MIN,
    target_tokens_max: int = TARGET_FINAL_TOKENS_MAX,
    python_relevant_only: bool = True,
    preserve_tiers: bool = True,
    tier_weights: dict | None = None,
) -> dict:
    """Deterministically select candidates from a JSONL file until token budget is met.

    Selection order (when preserve_tiers=True):
    1. Tier A first (highest quality)
    2. Tier B second
    3. Tier C third
    4. Remaining records with answer_score >= 5

    Within each tier, records are sorted deterministically by:
    - answer_score (descending)
    - acquisition_timestamp (ascending = older first for temporal diversity)
    - question_id (for topic diversity)

    Returns dict with selection statistics.
    """
    # Load all candidates
    candidates = []
    if not os.path.isfile(input_path):
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return {"error": f"input file not found: {input_path}"}

    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                candidates.append(rec)
            except json.JSONDecodeError:
                continue

    print(f"Loaded {len(candidates)} candidates from {input_path}")

    # Categorize by quality tier
    tier_a: list[dict] = []
    tier_b: list[dict] = []
    tier_c: list[dict] = []
    other: list[dict] = []

    for c in candidates:
        tier = quality_tier(c) if preserve_tiers else None

        # Check Python relevance
        tags = parse_tags(c.get("tags", ""))
        is_python = is_python_relevant(tags, core_only=python_relevant_only)

        # Assign to tier group
        if tier == "A":
            tier_a.append(c)
        elif tier == "B":
            tier_b.append(c)
        elif tier == "C":
            tier_c.append(c)
        else:
            # Records that have answer_score but don't meet tier thresholds
            # Include if they have acceptable score or Python relevance
            other.append(c)

    # Sort each tier deterministically
    # Sort by: answer_score descending, then acquisition_timestamp ascending, then question_id
    sort_key = lambda r: (
        -r.get("answer_score", 0),
        r.get("acquisition_timestamp", ""),
        r.get("question_id", ""),
    )

    tier_a.sort(key=sort_key)
    tier_b.sort(key=sort_key)
    tier_c.sort(key=sort_key)
    other.sort(key=sort_key)

    print(f"Tier distribution: A={len(tier_a)}, B={len(tier_b)}, C={len(tier_c)}, other={len(other)}")

    # Build selected record list with token budgeting
    selected = []
    total_tokens = 0
    selected_ids: set[str] = set()

    # Track diversity metrics
    seen_question_ids: set[str] = set()
    seen_answer_ids: set[str] = set()
    seen_dates: set[str] = set()
    seen_tags: set[frozenset[str]] = set()

    # Selection order: A -> B -> C -> other
    tier_order = [tier_a, tier_b, tier_c] if preserve_tiers else []

    tier_iterators = {}
    for i, tier_name in enumerate(["A", "B", "C"]):
        if i < len(tier_order):
            tier_iterators[tier_name] = iter(tier_order[i])

    def get_next_tier(tier_name: str) -> dict | None:
        """Get next record from a tier, ensuring diversity."""
        it = tier_iterators.get(tier_name)
        if it is None:
            return None

        for _ in range(len(tier_iterators[tier_name]) + 10):  # safety limit
            try:
                rec = next(it)
            except StopIteration:
                return None

            # Diversity checks
            qid = rec.get("question_id", "")
            aid = rec.get("answer_id", "")
            tags = parse_tags(rec.get("tags", ""))
            tags_fs = frozenset(tags)
            acq_ts = rec.get("acquisition_timestamp", "")

            # Check answer diversity (unique answer_id)
            if aid in seen_answer_ids:
                continue

            # Check question diversity (unique question_id)
            if qid in seen_question_ids:
                continue

            # Check topic diversity (unique tag combination)
            if tags_fs in seen_tags and len(seen_tags) > 1:
                continue

            # Check temporal diversity (unique acquisition date)
            # Extract date part
            if acq_ts:
                try:
                    date_part = acf_ts[:10] if len(acf_ts) >= 10 else acf_ts
                    if date_part in seen_dates:
                        continue
                    seen_dates.add(date_part)
                except (ValueError, IndexError):
                    pass

            # Mark as seen
            seen_answer_ids.add(aid)
            seen_question_ids.add(qid)
            seen_tags.add(tags_fs)

            return rec

        return None

    # Select records until token budget is met or exhausted
    phase = 0
    while total_tokens < target_tokens_min and (tier_a or tier_b or tier_c or other):
        selected_any = False

        # Phase 1: Tier A records
        if phase == 0 and preserve_tiers and tier_a:
            rec = get_next_tier("A")
            if rec is not None:
                tokens = rec.get("source_token_count") or rec.get("provisional_token_count") or 0
                qid = rec.get("question_id", "")
                aid = rec.get("answer_id", "")

                if qid not in {r.get("question_id", "") for r in selected}:
                    selected.append(rec)
                    total_tokens += max(tokens, 1)  # avoid zero
                    selected_ids.add(qid)
                    selected_ids.add(aid)
                    phase = 1  # move to phase 2 after first Tier A
                    selected_any = True
            else:
                phase = 1

        # Phase 2: Tier B records
        elif phase == 1 and preserve_tiers and tier_b:
            rec = get_next_tier("B")
            if rec is not None:
                tokens = rec.get("source_token_count") or rec.get("provisional_token_count") or 0
                selected.append(rec)
                total_tokens += max(tokens, 1)
                phase = 2
                selected_any = True
            else:
                phase = 2

        # Phase 3: Tier C records
        elif phase == 2 and preserve_tiers and tier_c:
            rec = get_next_tier("C")
            if rec is not None:
                tokens = rec.get("source_token_count") or rec.get("provisional_token_count") or 0
                selected.append(rec)
                total_tokens += max(tokens, 1)
                phase = 3
                selected_any = True
            else:
                phase = 3

        # Phase 4: Other records (fallback)
        elif phase >= 3 and other:
            rec = other.pop(0) if other else None
            if rec is not None:
                tokens = rec.get("source_token_count") or rec.get("provisional_token_count") or 0
                selected.append(rec)
                total_tokens += max(tokens, 1)
                selected_any = True
            else:
                break

        if not selected_any:
            # No more records to select; exit loop
            break

    # Final token count assessment
    final_token_estimate = total_tokens
    budget_met = target_tokens_min <= final_token_estimate <= target_tokens_max

    # Compute SHA-256 of output file before writing
    # (will be written first, then hash computed)

    # Write selected records
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for rec in selected:
            f.write(json.dumps(rec, sort_keys=True) + "\n")

    # Compute actual output file hash
    output_hash = compute_sha256(output_path)

    # Final statistics
    result = {
        "input_record_count": len(candidates),
        "selected_record_count": len(selected),
        "total_provisional_tokens": final_token_estimate,
        "target_tokens_min": target_tokens_min,
        "target_tokens_max": target_tokens_max,
        "budget_met": budget_met,
        "selection_order": "Tier A -> Tier B -> Tier C -> other (deterministic)",
        "python_relevant_only": python_relevant_only,
        "preserve_tiers": preserve_tiers,
        "output_path": output_path,
        "output_sha256": output_hash,
        "token_budget_status": (
            "MET" if budget_met
            else f"UNDER target ({final_token_estimate:.0f}M < 600M target)"
            if final_token_estimate < target_tokens_min
            else f"OVER target ({final_token_estimate:.0f}M > 700M target)"
        ),
        "note": "Provisional token counts using metadata.token_count; final count must use actual Pythia tokenizer",
    }

    return result


def main() -> int:
    """Demo Phase 5 token budgeting with the SO candidates snapshot."""
    input_file = str(STACKOVERFLOW_DIR / "stackoverflow_candidates_v1.jsonl")
    output_file = str(STACKOVERFLOW_DIR / "stackoverflow_selected_v1.jsonl")

    print("=" * 60)
    print("Phase 5: Token Budgeting Mechanism")
    print("=" * 60)
    print()

    # Run deterministic selection
    result = select_candidates_deterministic(
        input_path=input_file,
        output_path=output_file,
        target_tokens_min=TARGET_FINAL_TOKENS_MIN,
        target_tokens_max=TARGET_FINAL_TOKENS_MAX,
        python_relevant_only=True,
        preserve_tiers=True,
        tier_weights=None,
    )

    # Print summary
    print("=" * 60)
    print("SELECTION RESULTS")
    print("=" * 60)
    for key, value in result.items():
        if key != "selected_records":  # skip large list
            print(f"  {key}: {value}")

    print()
    if result.get("budget_met"):
        print(f"  >>> Token budget MET: {result['total_provisional_tokens'] / 1_000_000:.1f}M tokens "
              f"in range [{TARGET_FINAL_TOKENS_MIN/1_000_000:.0f}M - {TARGET_FINAL_TOKENS_MAX/1_000_000:.0f}M]")
    else:
        status = result["token_budget_status"]
        print(f"  >>> Token budget: {status}")

    print()
    print("=" * 60)
    print("Phase 5 complete")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())