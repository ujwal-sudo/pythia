#!/usr/bin/env python3
"""Think Python acquisition (Session 2, Pythia-160M).

Acquires Allen Downey's Think Python, 2nd Edition from the authoritative
AllenDowney/ThinkPython2 repository into the dedicated think_python namespace.
Fully isolated from PyPI and PEP namespaces.

Source: github.com/AllenDowney/ThinkPython2 @ pinned commit bbe57aef...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime

REMOTE_ROOT = "pythia:Pythia/raw/think_python"
ARCHIVES = f"{REMOTE_ROOT}/archives"
METADATA = f"{REMOTE_ROOT}/metadata"
MANIFESTS = f"{REMOTE_ROOT}/manifests"
STATE_PATH = f"{METADATA}/think_python_acquisition_state_v1.json"

BASE_URL = "https://raw.githubusercontent.com/AllenDowney/ThinkPython2/bbe57aef0014f51cdb9cf43523210e075fb24da2"


def rclone_lsf(path):
    p = subprocess.run(["rclone", "lsf", path], capture_output=True)
    return p.stdout.decode("utf-8", "replace").splitlines()


def rclone_cat(path):
    p = subprocess.run(["rclone", "cat", path], capture_output=True)
    return p.stdout


def rclone_write_bytes(path, data):
    with open("/tmp/opencode/_tp_tmp", "wb") as f:
        f.write(data)
    subprocess.run(["rclone", "copyto", "/tmp/opencode/_tp_tmp", path], check=True)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def utc_now():
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def load_manifest():
    return json.loads(rclone_cat(f"{MANIFESTS}/think_python_candidates_v1.json").decode("utf-8"))


def load_state():
    try:
        return json.loads(rclone_cat(STATE_PATH).decode("utf-8"))
    except Exception:
        return {"records": {}}


def split_chapters(book_text):
    """Split book.tex into chapters by \\chapter{...} markers.
    Returns list of (index, title, chapter_text)."""
    # Find all \chapter positions
    pattern = re.compile(r"\\chapter\{([^}]*)\}")
    matches = list(pattern.finditer(book_text))
    chapters = []
    for i, m in enumerate(matches):
        title = m.group(1)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(book_text)
        chapters.append((i + 1, title, book_text[start:end]))
    return chapters


def acquire_one(cand, state):
    cid = cand["candidate_id"]
    if cid in state["records"]:
        return None
    rec = {
        "record_id": cid, "kind": cand["kind"], "unit": cand["unit"],
        "source_path": cand["source_path"], "source_url": cand["source_url"],
        "source_commit": "bbe57aef0014f51cdb9cf43523210e075fb24da2",
        "edition": "2nd Edition", "acquisition_timestamp": utc_now(),
        "acquisition_status": "PENDING",
    }
    try:
        import requests
        if cand["kind"] == "chapter":
            # chapter derived from book.tex
            book_text = requests.get(cand["source_url"], timeout=30).text
            chapters = split_chapters(book_text)
            idx = int(cand["chapter_index"])
            if idx > len(chapters):
                rec["acquisition_status"] = "INVALID"
                rec["failure_type"] = "missing_section"
                rec["error"] = f"chapter {idx} not found"
                return rec
            content = chapters[idx - 1][2].encode("utf-8")
        else:
            r = requests.get(cand["source_url"], timeout=30)
            if r.status_code != 200:
                rec["acquisition_status"] = "FAILED"
                rec["failure_type"] = "permanent_source" if r.status_code >= 400 else "transient"
                rec["error"] = f"http_{r.status_code}"
                return rec
            content = r.content
        if len(content) == 0:
            rec["acquisition_status"] = "INVALID"
            rec["failure_type"] = "empty_document"
            rec["error"] = "zero-length"
            return rec
        csha = sha256_bytes(content)
        # duplicate detection
        for existing in state["records"].values():
            if existing.get("content_hash") == csha and existing.get("acquisition_status") == "ACQUIRED":
                rec["acquisition_status"] = "DUPLICATE"
                rec["duplicate_of"] = existing["record_id"]
                rec["content_hash"] = csha
                return rec
        # archive path
        if cand["kind"] == "book":
            arch = f"{ARCHIVES}/book.tex"
        elif cand["kind"] == "chapter":
            arch = f"{ARCHIVES}/chapters/chapter-{int(cand['chapter_index']):02d}.tex"
        elif cand["kind"] == "code":
            arch = f"{ARCHIVES}/code/{cand['source_path'].split('/')[-1]}"
        elif cand["kind"] == "glossary":
            arch = f"{ARCHIVES}/glossary/{cand['source_path'].split('/')[-1]}"
        else:
            arch = f"{ARCHIVES}/meta/{cand['source_path'].split('/')[-1]}"
        rclone_write_bytes(arch, content)
        rec.update({
            "acquisition_status": "ACQUIRED", "content_hash": csha,
            "archive_path": arch, "content_length": len(content),
            "license": "MIT (LaTeX/code); book text CC BY-NC 3.0",
            "provenance": {
                "source": "AllenDowney/ThinkPython2",
                "source_url": cand["source_url"],
                "source_commit": "bbe57aef0014f51cdb9cf43523210e075fb24da2",
                "edition": "2nd Edition",
                "license": "MIT (LaTeX/code); book text CC BY-NC 3.0",
                "acquisition_date": utc_now(),
            },
        })
        rec.pop("failure_type", None); rec.pop("error", None)
        return rec
    except Exception as exc:
        rec["acquisition_status"] = "FAILED"
        rec["failure_type"] = "transient"
        rec["error"] = f"{type(exc).__name__}:{str(exc)[:120]}"
        return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    manifest = load_manifest()
    candidates = manifest["candidates"]
    if args.limit:
        candidates = candidates[: args.limit]

    state = load_state() if args.resume else {"records": {}}
    processed = 0
    for cand in candidates:
        rec = acquire_one(cand, state)
        if rec is None:
            continue
        state["records"][rec["record_id"]] = rec
        processed += 1
        if processed % 10 == 0:
            rclone_write_bytes(STATE_PATH, json.dumps(state, indent=2).encode())
            print(f"  processed {processed}...", flush=True)
    rclone_write_bytes(STATE_PATH, json.dumps(state, indent=2).encode())
    from collections import Counter
    counts = Counter(r["acquisition_status"] for r in state["records"].values())
    print(f"Total records in state: {len(state['records'])}")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()