"""Deduplicator for Stack Overflow QA pairs from multiple sources.

Reads all three output files (huggingface, archive, API), deduplicates
using exact and near-dedup on answer body, then runs quality filters.

All output written to Google Drive at /mnt/pythia-cloud/Pythia.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import datetime, UTC
from typing import Any, Dict, List, Set, Tuple

from scripts.config import OUTPUT_FILES, QUALITY_FILTERS, MIN_ANSWER_SCORE, get_logger

logger = get_logger(__name__)

# ────────────────────────────────────────────────────────────────────
# 1. Trigram similarity for near-dedup
# ────────────────────────────────────────────────────────────────────

def _trigrams(text: str) -> Set[str]:
    """Return the set of trigrams (lower-cased, alphanumeric only) for a string."""
    text = text.lower()
    alnum = "".join(ch for ch in text if ch.isalnum() or ch.isspace())
    if len(alnum) < 3:
        return set()
    return {alnum[i : i + 3] for i in range(len(alnum) - 2)}


def _trigram_similarity(a: str, b: str) -> float:
    """Jaccard similarity over trigrams in [0, 1].

    Two answers sharing >85% of their trigrams are considered near-duplicates.
    """
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    intersection = len(ta & tb)
    union = len(ta | tb)
    return intersection / union


# ────────────────────────────────────────────────────────────────────
# 2. Exact dedup: hash of answer_body.strip().lower()
# ────────────────────────────────────────────────────────────────────
def _answer_hash(answer_body: str) -> str:
    """Exact dedup hash: SHA-256 of stripped, lower-cased answer body."""
    return hashlib.sha256(answer_body.strip().lower().encode("utf-8")).hexdigest()


# ────────────────────────────────────────────────────────────────────
# 3. Read one JSONL file and return list of records
# ────────────────────────────────────────────────────────────────────
def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    """Read a JSONL file and return list of record dicts."""
    records = []
    if not os.path.isfile(path):
        logger.warning("File not found: %s", path)
        return records
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        logger.warning("Could not read %s", path)
    return records


# ────────────────────────────────────────────────────────────────────
# 3. Main deduplication function
# ────────────────────────────────────────────────────────────────────
def run_dedup() -> None:
    """Run the full deduplication + quality-filter pipeline.

    Steps:
    1. Read all three source files: so_huggingface.jsonl, so_archive.jsonl, so_api.jsonl
    2. Exact dedup: drop records with duplicate answer_body hash
    3. Near-dedup: if two answers share >85% trigram similarity, keep higher-score one
    4. Quality filters: body >= 200 chars, has code, score >= MIN_ANSWER_SCORE
    5. Write final output to OUTPUT_FILES["deduped"]
    6. Print final report with counts and estimated tokens
    """
    # ── 1. Read all three sources ────────────────────────────────
    sources: Dict[str, List[Dict[str, Any]]] = {}
    for name, path in OUTPUT_FILES.items():
        # Skip the deduped file if it already exists
        if name == "deduped" and os.path.isfile(path):
            logger.info("Skipping %s — already exists", name)
            continue
        records = _read_jsonl(path)
        sources[name] = records
        logger.info("Read %d records from %s", len(records), name)

    # ── 2. Exact dedup ───────────────────────────────────────────
    seen_hashes: Set[str] = set()
    deduped: List[Dict[str, Any]] = []

    # Process all records from all sources in order: HF, Archive, API
    source_order = ["hf", "archive", "api"]
    all_records: List[Dict[str, Any]] = []
    for sname in source_order:
        all_records.extend(sources.get(sname, []))

    logger.info("Processing %d total records for dedup", len(all_records))

    for rec in all_records:
        answer_body = rec.get("answer_body", "")
        a_hash = _answer_hash(answer_body)

        # If we've seen this exact hash, skip (exact dedup)
        if a_hash in seen_hashes:
            continue

        seen_hashes.add(a_hash)
        deduped.append(rec)

    logger.info("After exact dedup: %d records", len(deduped))

    # ── 3. Near-dedup (trigram Jaccard > 85%) ────────────────────
    # Build a list for near-dedup comparison
    kept_hashes: Set[str] = set(_answer_hash(r.get("answer_body", "")).strip().lower() for r in deduped)

    # For each new candidate, check against kept records
    final: List[Dict[str, Any]] = []
    for rec in deduped:
        rec_body = rec.get("answer_body", "")
        skip = False

        # Compare against all already-kept records
        for kept in final:
            kept_body = kept.get("answer_body", "")
            sim = _trigram_similarity(rec_body, kept_body)
            if sim > 0.85:
                # Keep the higher-score one
                if rec.get("score", 0) > kept.get("score", 0):
                    # Replace kept with current
                    final.remove(kept)
                    final.append(rec)
                    skip = True
                    break
                else:
                    # Keep the existing one, discard current
                    skip = True
                    break

        if not skip:
            final.append(rec)

    logger.info("After near-dedup: %d records", len(final))

    # ── 4. Quality filters ───────────────────────────────────────
    filtered: List[Dict[str, Any]] = []
    for rec in final:
        body = rec.get("answer_body", "")
        score = rec.get("score", 0)

        # body length >= 200 chars
        if len(body) < QUALITY_FILTERS["min_body_length"]:
            continue

        # contains at least one code block (` ``` ` or <code> tag)
        if not _body_has_code(body):
            continue

        # score >= MIN_ANSWER_SCORE
        if score < MIN_ANSWER_SCORE:
            continue

        # not empty
        if not body.strip():
            continue

        filtered.append(rec)

    logger.info("After quality filter: %d records", len(filtered))

    # ── 5. Write final output ────────────────────────────────────
    output_path = OUTPUT_FILES["deduped"]
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    total_char_count = 0
    with open(output_path, "w", encoding="utf-8") as out_f:
        for rec in filtered:
            body = rec.get("answer_body", "")
            total_char_count += len(body)
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ── 6. Final report ──────────────────────────────────────────
    # Count per source
    counts_per_source: Dict[str, int] = {}
    for sname in source_order:
        srecords = sources.get(sname, [])
        # Count how many from this source survived all filters
        surviving = sum(
            1
            for r in all_records
            if r.get("source") == sname
            and any(
                r is f2 for f2 in filtered
            )  # simplified: just count original records from this source
        )
        # Actually let's just count from the original source records that made it through
        # by checking source field
        s_count = sum(1 for r in all_records if r.get("source") == sname)
        counts_per_source[sname] = s_count

    # Total before any dedup
    before_dedup = len(all_records)

    # After exact dedup
    after_exact = len(deduped)

    # After near dedup
    after_near = len(final)

    # After quality filter
    after_quality = len(filtered)

    # Estimated tokens (using average 550 tokens per QA pair estimate)
    estimated_tokens = int(total_char_count / 4.5) if total_char_count else 0

    # Output size on Drive
    output_size = os.path.getsize(output_path) if os.path.isfile(output_path) else 0

    # Print final report
    logger.info("=" * 60)
    logger.info("DEDUPLICATION + QUALITY FILTER REPORT")
    logger.info("  Total from HuggingFace:      %d", counts_per_source.get("hf", 0))
    logger.info("  Total from Archive:          %d", counts_per_source.get("archive", 0))
    logger.info("  Total from API:              %d", counts_per_source.get("api", 0))
    logger.info("  Before dedup:                %d", before_dedup)
    logger.info("  After exact dedup:           %d", after_exact)
    logger.info("  After near dedup:            %d", after_near)
    logger.info("  After quality filter:        %d", after_quality)
    logger.info("  ─────────────────────────────")
    logger.info("  Final pairs:                 %d", after_quality)
    logger.info("  Estimated tokens:            %d (pairs × ~550)", estimated_tokens)
    logger.info("  Output size on Drive:        %d MB", output_size / (1024 * 1024))
    logger.info("=" * 60)

    print("=" * 60)
    print("DEDUPLICATION + QUALITY FILTER REPORT")
    print(f"  Total from HuggingFace:      {counts_per_source.get('hf', 0)}")
    print(f"  Total from Archive:          {counts_per_source.get('archive', 0)}")
    print(f"  Total from API:              {counts_per_source.get('api', 0)}")
    print(f"  Before dedup:                {before_dedup}")
    print(f"  After exact dedup:           {after_exact}")
    print(f"  After near dedup:            {after_near}")
    print(f"  After quality filter:        {after_quality}")
    print("  ─────────────────────────────")
    print(f"  Final pairs:                 {after_quality}")
    print(f"  Estimated tokens:            {estimated_tokens} (pairs × ~550)")
    print(f"  Output size on Drive:        {output_size / (1024 * 1024):.2f} MB")
    print("=" * 60)

    print()
    print(f"Final output written to: {output_path}")
    print(f"Estimated tokens: {estimated_tokens}")