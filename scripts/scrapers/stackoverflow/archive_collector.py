"""Archive.org Python StackExchange dump collector.

Downloads python.stackexchange.com.7z by streaming to Drive,
extracts Posts.xml using iterative parsing (ET.iterparse), and
writes question/answer pairs to JSONL.

All output written to Google Drive at /mnt/pythia-cloud/Pythia.
No full XML loaded into memory.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional, Tuple

import xml.etree.ElementTree as ET

from scripts.config import (
    CACHE_DIR,
    CHUNK_SIZE,
    MIN_ANSWER_SCORE,
    OUTPUT_FILES,
    QUALITY_FILTERS,
    DRIVE_ROOT,
    get_logger,
)

logger = get_logger(__name__)

# ────────────────────────────────────────────────────────────────────
# 1. Paths
# ────────────────────────────────────────────────────────────────────
DUMP_PATH = f"{CACHE_DIR}/python_stackexchange.7z"
EXTRACT_DIR = f"{CACHE_DIR}/python_stackexchange_extracted/"
POSTS_XML = f"{EXTRACT_DIR}Posts.xml"

# ────────────────────────────────────────────────────────────────────
# 2. Download the 7z dump from Archive.org, streaming to Drive
# ────────────────────────────────────────────────────────────────────
def _download_dump() -> None:
    """Download python.stackexchange.com.7z streaming directly to Drive.

    If file already exists > 100 MB, skip download and use cached dump.
    Progress shown in MB downloaded / total MB.
    """
    import urllib.request

    archive_url = "https://archive.org/download/stackexchange/python.stackexchange.com.7z"

    # Check cached dump
    if os.path.isfile(DUMP_PATH):
        cached_size = os.path.getsize(DUMP_PATH)
        if cached_size > 100 * 1024 * 1024:  # > 100 MB
            logger.info("Using cached dump at %s", DUMP_PATH)
            return
        # File too small — redownload
        logger.info("Cached dump too small (%d bytes), redownloading", cached_size)

    os.makedirs(os.path.dirname(DUMP_PATH), exist_ok=True)

    logger.info("Downloading %s to %s", archive_url, DUMP_PATH)

    total_mb = 0
    downloaded_mb = 0

    try:
        with urllib.request.urlopen(archive_url) as response:
            total_size = response.length or 0
            total_mb = total_size / (1024 * 1024) if total_size else 0

            with open(DUMP_PATH, "wb") as out_f:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    out_f.write(chunk)
                    downloaded_mb += len(chunk) / (1024 * 1024)
                    logger.info(
                        "Download progress: %.2f / %.2f MB",
                        downloaded_mb,
                        total_mb,
                    )

    except Exception as exc:  # noqa: BLE001
        logger.error("Download failed: %s", exc)
        # Remove partial file
        if os.path.isfile(DUMP_PATH):
            os.remove(DUMP_PATH)
        raise

    logger.info("Download complete: %s (%d MB)", DUMP_PATH, int(downloaded_mb))


# ────────────────────────────────────────────────────────────────────
# 3. Extract 7z using py7zr (iterative, no full XML in memory)
# ────────────────────────────────────────────────────────────────────
def _extract_dump() -> None:
    """Extract python.stackexchange.com.7z to EXTRACT_DIR using py7zr.

    If already extracted (Posts.xml exists), skip extraction.
    """
    import py7zr

    os.makedirs(EXTRACT_DIR, exist_ok=True)

    # Skip if already extracted
    if os.path.isfile(POSTS_XML):
        logger.info("Already extracted — skipping: %s", POSTS_XML)
        return

    logger.info("Extracting %s to %s", DUMP_PATH, EXTRACT_DIR)

    try:
        with py7zr.SevenZipFile(DUMP_PATH, "r") as z:
            z.extractall(path=EXTRACT_DIR)
    except Exception as exc:  # noqa: BLE001
        logger.error("Extraction failed: %s", exc)
        raise

    logger.info("Extraction complete: %s", EXTRACT_DIR)


# ────────────────────────────────────────────────────────────────────
# 4. Parse Posts.xml using ET.iterparse — never load full XML into memory
# ────────────────────────────────────────────────────────────────────
def _parse_posts_xml(
    out_f: Any,
) -> Tuple[int, int]:
    """Parse Posts.xml using ET.iterparse.

    Walks the XML tree incrementally, collecting question/answer pairs.

    Returns:
        (questions_kept, answers_kept) counts
    """
    # In-memory buffers for pairing: question_id → question data
    # Limited size to avoid memory blowup; flush periodically
    QUEUE_MAX = 10_000
    question_queue: Dict[int, Dict[str, Any]] = {}

    questions_kept = 0
    answers_kept = 0
    context = ""

    # iterparse events: "start", "end"
    for event, elem in ET.iterparse(
        POSTS_XML,
        events=("start", "end"),
        tag=("row",),
    ):
        if event == "end" and elem.tag == "row":
            # Extract attributes
            post_id = int(elem.attrib.get("Id", "0"))
            post_type = int(elem.attrib.get("PostTypeId", "0"))
            score = int(elem.attrib.get("Score", "0"))
            tags = elem.attrib.get("Tags", "")
            body = elem.attrib.get("Body", "")

            # Decode simple XML entities manually (good enough for Stack Exchange)
            body = body.replace("<", "<").replace(">", ">").replace(""", '"')

            # ─── Question (PostTypeId == 1) ────────────────────────
            if post_type == 1:
                # Store question temporarily, pairing later with answers
                question_queue[post_id] = {
                    "id": post_id,
                    "score": score,
                    "tags": tags,
                    "title": elem.attrib.get("Title", ""),
                    "body": body,
                    "accepted_answer_id": elem.attrib.get("AcceptedAnswerId", ""),
                }

                # Flush queue if too large to keep memory low
                if len(question_queue) > QUEUE_MAX:
                    # Remove oldest entries (by ID) — simple FIFO via sorted keys
                    oldest = min(question_queue.keys())
                    question_queue.pop(oldest, None)

                # Clear element to keep memory low
                elem.clear()

            # ─── Answer (PostTypeId == 2) ──────────────────────────
            elif post_type == 2:
                # Try to pair with its parent question
                parent_id = elem.attrib.get("ParentId", "")
                accepted = elem.attrib.get("AcceptedAnswerId") == str(post_id)

                question_data = question_queue.pop(int(parent_id), None) if parent_id else None

                if question_data is None:
                    # No matching question found; still write standalone answer
                    # but we skip it for the Q/A pair output
                    elem.clear()
                    continue

                # ── Filter answer ────────────────────────────────────
                if score < MIN_ANSWER_SCORE:
                    elem.clear()
                    continue

                # Code presence
                has_code = _body_has_code(body)  # will be defined later; using inline check
                # Actually let's use the function from config/helper
                from scripts.stackoverflow.hf_collector import _body_has_code
                has_code = _body_has_code(body)

                # Body length filter
                if len(body) < QUALITY_FILTERS["min_body_length"]:
                    elem.clear()
                    continue

                # Build output record
                collected_at = datetime.now(UTC).replace(microsecond=0).isoformat()

                record: Dict[str, Any] = {
                    "source": "python_stackexchange_dump",
                    "question_id": question_data["id"],
                    "answer_id": post_id,
                    "question_title": question_data.get("title", ""),
                    "question_body": question_data.get("body", ""),
                    "answer_body": body,
                    "score": score,
                    "is_accepted": accepted,
                    "tags": tags,
                    "has_code": has_code,
                    "char_count": len(body),
                    "collected_at": collected_at,
                }

                out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                answers_kept += 1
                questions_kept += 1  # count pair once

                # We count questions only once when their answer is processed

            # ─── Clear element to keep memory low ────────────────────
            elem.clear()

    # ── After XML walk: count remaining questions without answers ────
    # (they are not written, so questions_kept already only counts paired ones)
    logger.info(
        "XML parse done: %d questions paired, %d answers kept",
        questions_kept,
        answers_kept,
    )

    return questions_kept, answers_kept


# ────────────────────────────────────────────────────────────────────
# 5. Main archive collector function
# ────────────────────────────────────────────────────────────────────
def run_archive_collector() -> None:
    """Run the full Archive.org Python StackExchange dump pipeline.

    Steps:
    1. Download the 7z dump (or use cached if > 100 MB)
    2. Extract it using py7zr
    3. Parse Posts.xml with ET.iterpair, pairing questions+answers
    4. Write filtered pairs to OUTPUT_FILES["archive"]
    5. Delete extracted XML files (keep .7z)
    6. Print summary totals and estimated tokens
    """
    output_path = OUTPUT_FILES["archive"]
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Step 1: Download / use cached dump
    _download_dump()

    # Step 2: Extract
    _extract_dump()

    # Step 3: Parse Posts.xml and write output
    questions_kept = 0
    answers_kept = 0

    try:
        with open(output_path, "w", encoding="utf-8") as out_f:
            qk, ak = _parse_posts_xml(out_f)
            questions_kept = qk
            answers_kept = ak
    except Exception as exc:  # noqa: BLE001
        logger.error("Error during XML parsing: %s", exc)
        raise

    # Step 4: Delete extracted XML files to save space; keep .7z
    if os.path.isdir(EXTRACT_DIR):
        # Remove Posts.xml and any other extracted files
        for fname in os.listdir(EXTRACT_DIR):
            fpath = os.path.join(EXTRACT_DIR, fname)
            try:
                if fname == "Posts.xml" or fname.endswith(".xml"):
                    os.remove(fpath)
                    logger.info("Removed extracted file: %s", fpath)
            except OSError as err:  # noqa: BLE001
                logger.warning("Failed to remove %s: %s", fpath, err)

    # Step 5: Summary
    output_size = os.path.getsize(output_path) if os.path.isfile(output_path) else 0
    estimated_tokens = int(output_size / 1.8) if output_size else 0  # rough estimate

    logger.info("=" * 50)
    logger.info("ARCHIVE COLLECTOR SUMMARY")
    logger.info("  Total pairs collected:    %d", answers_kept)
    logger.info("  Output file size:         %d bytes (%d KB, %.2f MB)",
                output_size, output_size // 1024, output_size / (1024 * 1024))
    logger.info("  Estimated tokens:         %d", estimated_tokens)
    logger.info("  .7z file kept at:          %s", DUMP_PATH)
    logger.info("=" * 50)

    print("=" * 50)
    print("ARCHIVE COLLECTOR SUMMARY")
    print(f"  Total pairs collected:    {answers_kept}")
    print(f"  Output file size:         {output_size} bytes ({output_size // 1024} KB, {output_size / (1024 * 1024):.2f} MB)")
    print(f"  Estimated tokens:         {estimated_tokens}")
    print(f"  .7z file kept at:          {DUMP_PATH}")
    print("=" * 50)