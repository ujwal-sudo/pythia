#!/usr/bin/env python3
"""PEP corpus acquisition (Session 2, Pythia-160M).

Acquires the authoritative python/peps corpus into the dedicated PEP namespace
(pythia:Pythia/raw/peps/). Fully isolated from the PyPI namespace.

Authoritative source: github.com/python/peps @ pinned commit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REMOTE_PEP_ROOT = "pythia:Pythia/raw/peps"
ARCHIVES = f"{REMOTE_PEP_ROOT}/archives"
METADATA = f"{REMOTE_PEP_ROOT}/metadata"
MANIFESTS = f"{REMOTE_PEP_ROOT}/manifests"
STATE_PATH = f"{METADATA}/pep_acquisition_state_v1.json"
REPORT_PATH = f"{METADATA}/pep_acquisition_report_v1.json"


def rclone_lsf(path):
    p = subprocess.run(["rclone", "lsf", path], capture_output=True)
    return p.stdout.decode("utf-8", "replace").splitlines()


def rclone_cat(path):
    p = subprocess.run(["rclone", "cat", path], capture_output=True)
    return p.stdout


def rclone_write_bytes(path, data):
    with open("/tmp/opencode/_pep_tmp", "wb") as f:
        f.write(data)
    subprocess.run(["rclone", "copyto", "/tmp/opencode/_pep_tmp", path], check=True)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def utc_now():
    return datetime.now(UTC).replace(microsecond=0).isoformat()


HEADER_FIELDS = {
    "pep": "pep", "title": "title", "author": "authors", "status": "status",
    "type": "type", "topic": "topic", "requires": "requires", "replaces": "replaces",
    "superseded-by": "superseded_by", "created": "created", "python-version": "python_version",
    "post-history": "post_history", "resolution": "resolution", "discussions-to": "discussions_to",
    "content-type": "content_type", "bdc": "bdc", "bdde": "bdde", "sphere": "sphere",
}


def parse_pep_header(text):
    """Parse the RST header block (fields before the first blank line / title)."""
    meta = {}
    for line in text.splitlines():
        if not line.strip():
            break
        if ": " in line:
            key, _, val = line.partition(": ")
            key = key.strip().lstrip(":")
            if key.lower() in HEADER_FIELDS:
                meta[HEADER_FIELDS[key.lower()]] = val.strip()
    return meta


def load_manifest():
    raw = rclone_cat(f"{MANIFESTS}/pep_candidates_v1.json")
    return json.loads(raw.decode("utf-8"))


def acquire_one(cand, state):
    num = cand["pep_number"]
    kind = cand["kind"]
    rec_id = f"pep:{num}" if kind == "pep" else f"pep:{num}:{cand['source_path'].split('/')[-1]}"
    if rec_id in state["records"]:
        return None  # already processed (skip)
    rec = {
        "record_id": rec_id, "pep_number": num, "kind": kind,
        "source_path": cand["source_path"], "source_url": cand["source_url"],
        "acquisition_timestamp": utc_now(), "acquisition_status": "PENDING",
    }
    try:
        import requests
        r = requests.get(cand["source_url"], timeout=30)
        if r.status_code != 200:
            rec["acquisition_status"] = "FAILED"
            rec["failure_type"] = "permanent_source" if r.status_code >= 400 else "transient"
            rec["error"] = f"http_{r.status_code}"
            rec["retryable"] = r.status_code >= 500
            return rec
        content = r.content
        if len(content) == 0:
            rec["acquisition_status"] = "INVALID"
            rec["failure_type"] = "empty_document"
            rec["error"] = "zero-length document"
            return rec
        text = content.decode("utf-8", errors="replace")
        if "\x00" in text:
            rec["acquisition_status"] = "INVALID"
            rec["failure_type"] = "malformed"
            rec["error"] = "nul byte in content"
            return rec
        csha = sha256_bytes(content)
        # duplicate detection by content hash
        for existing in state["records"].values():
            if existing.get("content_hash") == csha and existing.get("acquisition_status") == "ACQUIRED":
                rec["acquisition_status"] = "DUPLICATE"
                rec["duplicate_of"] = existing["record_id"]
                rec["content_hash"] = csha
                return rec
        meta = parse_pep_header(text)
        # Write archive to PEP namespace
        ext = ".rst" if cand["format"] == "rst" else ".txt"
        if kind == "pep":
            arch_path = f"{ARCHIVES}/pep-{num}{ext}"
        else:
            arch_path = f"{ARCHIVES}/pep-{num}/{cand['source_path'].split('/')[-1]}"
        rclone_write_bytes(arch_path, content)
        rec.update({
            "acquisition_status": "ACQUIRED", "content_hash": csha,
            "archive_path": arch_path, "bytes": len(content),
            "content_length": len(content),
            **{k: v for k, v in meta.items() if v},
            "provenance": {
                "source": "python/peps", "source_url": cand["source_url"],
                "source_commit": cand.get("source_commit"),
                "acquisition_date": utc_now(),
            },
        })
        # clear failure fields
        rec.pop("failure_type", None); rec.pop("error", None)
        return rec
    except Exception as exc:
        rec["acquisition_status"] = "FAILED"
        rec["failure_type"] = "transient"
        rec["error"] = f"{type(exc).__name__}:{str(exc)[:120]}"
        rec["retryable"] = True
        return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch-size", type=int, default=100)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    manifest = load_manifest()
    candidates = manifest["candidates"]
    src_commit = manifest.get("source_commit")
    for c in candidates:
        c["source_commit"] = src_commit

    # Load state
    state = {"records": {}}
    if args.resume and rclone_lsf(METADATA):
        try:
            state = json.loads(rclone_cat(STATE_PATH).decode("utf-8"))
        except Exception:
            state = {"records": {}}

    target = candidates
    if args.limit:
        target = candidates[: args.limit]

    processed = 0
    for cand in target:
        rec = acquire_one(cand, state)
        if rec is None:
            continue
        state["records"][rec["record_id"]] = rec
        processed += 1
        if processed % 20 == 0:
            rclone_write_bytes(STATE_PATH, json.dumps(state, indent=2).encode())
            print(f"  processed {processed}...", flush=True)

    rclone_write_bytes(STATE_PATH, json.dumps(state, indent=2).encode())
    from collections import Counter
    counts = Counter(r["acquisition_status"] for r in state["records"].values())
    print(f"Total records in state: {len(state['records'])}")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    print(f"State: {STATE_PATH}")


if __name__ == "__main__":
    main()