#!/usr/bin/env python3
"""ATBS (Automate the Boring Stuff with Python) acquisition (Session 2).

Acquires the 3rd edition chapters/appendices from the authoritative author site
(automatetheboringstuff.com) into the dedicated atbs namespace.
Fully isolated from PyPI, PEP, and Think Python namespaces.

Text license: CC BY-NC-SA 3.0 US. Code examples: MIT (preserved separately).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime

REMOTE_ROOT = "pythia:Pythia/raw/atbs"
ARCHIVES = f"{REMOTE_ROOT}/archives"
METADATA = f"{REMOTE_ROOT}/metadata"
MANIFESTS = f"{REMOTE_ROOT}/manifests"
STATE_PATH = f"{METADATA}/atbs_acquisition_state_v1.json"


def rclone_lsf(path):
    p = subprocess.run(["rclone", "lsf", path], capture_output=True)
    return p.stdout.decode("utf-8", "replace").splitlines()


def rclone_cat(path):
    p = subprocess.run(["rclone", "cat", path], capture_output=True)
    return p.stdout


def rclone_write_bytes(path, data):
    with open("/tmp/opencode/_atbs_tmp", "wb") as f:
        f.write(data)
    subprocess.run(["rclone", "copyto", "/tmp/opencode/_atbs_tmp", path], check=True)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def utc_now():
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def load_manifest():
    return json.loads(rclone_cat(f"{MANIFESTS}/atbs_candidates_v1.json").decode("utf-8"))


def load_state():
    try:
        return json.loads(rclone_cat(STATE_PATH).decode("utf-8"))
    except Exception:
        return {"records": {}}


def acquire_one(cand, state):
    cid = cand["candidate_id"]
    existing = state["records"].get(cid)
    if existing and existing.get("acquisition_status") == "ACQUIRED":
        return None  # already successfully acquired (skip on resume)
    # FAILED/INVALID records are retried on resume.
    rec = {
        "record_id": cid, "kind": cand["kind"], "edition": cand["edition"],
        "chapter_index": cand.get("chapter_index"), "title": cand.get("title"),
        "source_url": cand["source_url"], "format": cand["format"],
        "acquisition_timestamp": utc_now(), "acquisition_status": "PENDING",
    }
    try:
        import requests
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
        if cand["kind"] == "chapter":
            arch = f"{ARCHIVES}/chapter-{cand['chapter_index']:02d}.html"
        else:
            arch = f"{ARCHIVES}/appendix-{cid.split(':')[-1]}.html"
        rclone_write_bytes(arch, content)
        rec.update({
            "acquisition_status": "ACQUIRED", "content_hash": csha,
            "archive_path": arch, "content_length": len(content),
            "license_text": cand["license"],
            "license_code": "MIT (book source code, per author)",
            "license_boundary": "text=CC BY-NC-SA 3.0 US; code=MIT (separate)",
            "provenance": {
                "source": "automatetheboringstuff.com (official author site)",
                "source_url": cand["source_url"],
                "edition": "3rd Edition",
                "license_text": "CC BY-NC-SA 3.0 United States",
                "license_code": "MIT",
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