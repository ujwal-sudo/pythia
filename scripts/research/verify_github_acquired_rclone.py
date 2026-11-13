#!/usr/bin/env python3
"""
Verify all ACQUIRED snapshots by staging each one out of the Google Drive remote
(via rclone native transfer) to local disk, verifying the local copy, then
deleting it. This bypasses the FUSE mount entirely, avoiding the transient
[Errno 5] Input/output error rate-limit failures that plague in-place
verification.

One snapshot is staged at a time, so local disk only needs room for the single
largest snapshot (~215 MB), not the whole ~5 GB corpus.

Usage:
    python3 scripts/research/verify_github_acquired_rclone.py [--limit N] [--tmp-dir DIR] [--keep] [--dry-run]

Exit code: 0 if every checked snapshot verifies clean, non-zero otherwise.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_github_acquired import (
    has_forbidden_git_metadata,
    load_manifest,
    verify_snapshot_manifest,
)

# The FUSE mount maps to this rclone remote root:
#   /mnt/pythia-cloud/PythiaDrive  <->  pythia:Pythia
FUSE_ROOT = "/mnt/pythia-cloud/PythiaDrive"
REMOTE_ROOT = "pythia:Pythia"
RAW_GITHUB_RELPATH = "raw/github"

# Copy retry behaviour for transient network / Drive errors
MAX_COPY_RETRIES        = 6
COPY_RETRY_BASE_DELAY   = 5.0    # seconds
COPY_RETRY_MAX_DELAY    = 120.0  # seconds
MAX_CONSECUTIVE_NETWORK_FAILURES = 6

# Substrings (lower-cased) that mark a transient, retryable rclone failure
_RCLONE_TRANSIENT_MARKERS = (
    "server misbehaving",
    "dial tcp",
    "no such host",
    "temporary failure in name resolution",
    "connection refused",
    "connection reset",
    "i/o timeout",
    "tls handshake timeout",
    "couldn't find root directory id",
    "rate limit",
    "ratelimitexceeded",
    "quota",
    "googleapi: error 429",
    "googleapi: error 500",
    "googleapi: error 502",
    "googleapi: error 503",
    "googleapi: error 504",
    "input/output error",
)


def _is_transient_rclone_error(msg: str) -> bool:
    m = (msg or "").lower()
    return any(marker in m for marker in _RCLONE_TRANSIENT_MARKERS)


def build_rclone_cmd(remote_src: str, local_dst: str) -> list:
    """Construct the rclone copy command with conservative pacing + retries."""
    return [
        "rclone", "copy",
        remote_src, local_dst,
        "--transfers", "4",
        "--checkers", "8",
        "--retries", "5",
        "--low-level-retries", "10",
        "--drive-pacer-min-sleep", "100ms",
        "--drive-pacer-burst", "100",
        "--stats", "0",
        "--log-level", "ERROR",
    ]


def remote_path_for(entry: dict):
    """Derive the rclone remote path for a manifest entry."""
    owner = entry.get("owner")
    repo = entry.get("repo")
    sha = entry.get("commit_sha")
    if owner and repo and sha:
        return f"{REMOTE_ROOT}/{RAW_GITHUB_RELPATH}/{owner}__{repo}/{sha}"

    # Fall back to cloud_path (correcting the stale Pythia -> PythiaDrive root)
    cloud_path = entry.get("cloud_path", "")
    if not cloud_path:
        return None
    corrected = cloud_path.replace("/mnt/pythia-cloud/Pythia/", "/mnt/pythia-cloud/PythiaDrive/")
    if corrected.startswith(FUSE_ROOT):
        rel = corrected[len(FUSE_ROOT):].lstrip("/")
        return f"{REMOTE_ROOT}/{rel}"
    return None


def _run_rclone_with_retry(cmd: list, timeout_sec: int, description: str) -> tuple:
    """
    Run an rclone command, retrying transient network / Drive errors with
    exponential backoff.

    Returns (ok, stdout, message, transient).
    """
    last_detail = ""
    transient = False
    for attempt in range(MAX_COPY_RETRIES + 1):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            last_detail = f"{description} timed out"
            transient = True
        else:
            if proc.returncode == 0:
                return True, proc.stdout, "", False
            err = (proc.stderr or proc.stdout or "").strip().splitlines()
            last_detail = err[-1] if err else f"exit code {proc.returncode}"
            transient = _is_transient_rclone_error(last_detail)

        if not transient or attempt >= MAX_COPY_RETRIES:
            return False, "", f"{description} failed: {last_detail}", transient

        delay = min(COPY_RETRY_BASE_DELAY * (2 ** attempt), COPY_RETRY_MAX_DELAY)
        print(f"    [{description} retry {attempt + 1}/{MAX_COPY_RETRIES}] transient error, "
              f"sleeping {delay:.0f}s: {last_detail[:140]}", flush=True)
        time.sleep(delay)

    return False, "", f"{description} failed: {last_detail}", transient


def list_remote_entries(remote_src: str, dry_run: bool = False) -> tuple:
    """
    Recursively list all remote paths (files and directories) without
    downloading content. Returns (ok, entries, message, transient).
    """
    cmd = ["rclone", "lsf", "-R", remote_src]
    if dry_run:
        print("    [dry-run] " + " ".join(cmd))
        return True, [], "dry-run", False
    ok, stdout, msg, transient = _run_rclone_with_retry(cmd, timeout_sec=600, description="rclone lsf")
    if not ok:
        return False, [], msg, transient
    entries = list(dict.fromkeys(line.strip() for line in stdout.splitlines() if line.strip()))
    return True, entries, "", False


def _load_verified(progress_path: Path) -> set:
    try:
        return set(json.loads(progress_path.read_text()))
    except Exception:
        return set()


def _save_verified(progress_path: Path, verified_names: set) -> None:
    try:
        tmp = progress_path.with_suffix(progress_path.suffix + ".tmp")
        tmp.write_text(json.dumps(sorted(verified_names)))
        os.replace(tmp, progress_path)
    except Exception as e:
        print(f"    [warn] could not save progress: {e}", flush=True)


def forbidden_from_entries(entries: list) -> list:
    """
    Mirror has_forbidden_git_metadata() semantics on a flat remote listing:
    flag any entry whose basename starts with '.git' (.git, .github,
    .gitignore, .gitattributes, ...). Only the offending path itself is
    reported, not the files inside it — matching the local directory walk.
    """
    forbidden = []
    for entry in entries:
        cleaned = entry.rstrip("/")
        if not cleaned:
            continue
        basename = cleaned.rsplit("/", 1)[-1]
        if basename.startswith(".git"):
            forbidden.append(cleaned)
    return forbidden


def stage_snapshot(remote_src: str, local_dst: Path, dry_run: bool = False) -> tuple:
    """
    Copy a snapshot from the remote to local_dst.

    Returns (ok, message, transient).
    """
    cmd = build_rclone_cmd(remote_src, str(local_dst))
    if dry_run:
        print("    [dry-run] " + " ".join(cmd))
        return True, "dry-run", False
    ok, _, msg, transient = _run_rclone_with_retry(cmd, timeout_sec=1800, description="rclone copy")
    return ok, ("copied" if ok else msg), transient


def verify_acquired(args) -> bool:
    candidates = load_manifest()
    acquired = [c for c in candidates if c.get("state") == "ACQUIRED"]

    print(f"ACQUIRED in manifest: {len(acquired)}")
    print(f"Remote: {REMOTE_ROOT}  |  tmp dir: {args.tmp_dir}\n")

    verified = 0
    clean_listing = 0
    invalid_data = 0
    discrepancies = []

    tmp_root = Path(args.tmp_dir)
    tmp_root.mkdir(parents=True, exist_ok=True)

    progress_path = Path(args.progress_file) if args.progress_file else (tmp_root / "pythia_verify_progress.json")
    done_verified = set() if args.no_resume else _load_verified(progress_path)
    skipped_verified = 0
    if done_verified and not args.list_only:
        print(f"Resume: {len(done_verified)} snapshot(s) already fully verified\n")

    total = min(args.limit, len(acquired)) if args.limit else len(acquired)

    consecutive_transient = 0

    for i, c in enumerate(acquired[:total], 1):
        full_name = c["full_name"]
        commit_sha = c.get("commit_sha", "")
        size_kb = c.get("repo_size_kb", "?")

        print(f"[{i}/{total}] {full_name} ...", flush=True)

        if full_name in done_verified:
            print("    already fully verified (resume) — skipping", flush=True)
            skipped_verified += 1
            continue

        remote_src = remote_path_for(c)
        if remote_src is None:
            msg = "ACQUIRED but no resolvable cloud path"
            print(f"    FAIL — {msg}")
            discrepancies.append(f"{full_name}: {msg}")
            invalid_data += 1
            continue

        work_dir = None

        try:
            # Fast, download-free clean-snapshot invariant check via remote listing
            print("    listing remote (clean-snapshot check) ...", flush=True)
            ok, entries, msg, transient = list_remote_entries(remote_src, dry_run=args.dry_run)
            if args.dry_run:
                continue
            if not ok:
                print(f"    FAIL — {msg}")
                discrepancies.append(f"{full_name}: {msg}")
                invalid_data += 1
                if transient:
                    consecutive_transient += 1
                    if consecutive_transient >= MAX_CONSECUTIVE_NETWORK_FAILURES:
                        print(f"\nAborting: {consecutive_transient} consecutive network failures. "
                              f"Google Drive appears unreachable — rerun when connectivity recovers.",
                              flush=True)
                        break
                else:
                    consecutive_transient = 0
                continue

            consecutive_transient = 0

            forbidden = forbidden_from_entries(entries)
            if forbidden:
                msg = f"FORBIDDEN Git metadata found: {forbidden}"
                print(f"    FAIL — {msg}")
                discrepancies.append(f"{full_name}: {msg}")
                invalid_data += 1
                continue

            if args.list_only:
                print("    CLEAN (listing only)")
                clean_listing += 1
                continue

            work_dir = Path(tempfile.mkdtemp(prefix="pythia_verify_", dir=str(tmp_root)))
            snapshot_dir = work_dir / "snapshot"

            print(f"    staging {remote_src} ...", flush=True)
            ok, msg, transient = stage_snapshot(remote_src, snapshot_dir, dry_run=False)
            if not ok:
                print(f"    FAIL — {msg}")
                discrepancies.append(f"{full_name}: {msg}")
                invalid_data += 1
                if transient:
                    consecutive_transient += 1
                    if consecutive_transient >= MAX_CONSECUTIVE_NETWORK_FAILURES:
                        print(f"\nAborting: {consecutive_transient} consecutive network failures. "
                              f"Google Drive appears unreachable — rerun when connectivity recovers.",
                              flush=True)
                        break
                else:
                    consecutive_transient = 0
                continue

            consecutive_transient = 0

            # Defense in depth: re-check the staged copy before hashing
            forbidden = has_forbidden_git_metadata(snapshot_dir)
            if forbidden:
                msg = f"FORBIDDEN Git metadata found: {forbidden}"
                print(f"    FAIL — {msg}")
                discrepancies.append(f"{full_name}: {msg}")
                invalid_data += 1
                continue

            # Full manifest + per-file hash verification on the local copy
            ok, msg = verify_snapshot_manifest(snapshot_dir, commit_sha)
            if not ok:
                print(f"    FAIL — {msg}")
                discrepancies.append(f"{full_name}: snapshot manifest verification failed: {msg}")
                invalid_data += 1
                continue

            print("    OK")
            verified += 1
            done_verified.add(full_name)
            _save_verified(progress_path, done_verified)
        finally:
            if work_dir is not None and not args.keep:
                shutil.rmtree(work_dir, ignore_errors=True)

    print(f"\nVerification Results:")
    print(f"  ACQUIRED checked      : {total}")
    if args.list_only:
        print(f"  Clean (listing only)  : {clean_listing}")
    else:
        print(f"  Fully verified        : {verified}")
    if skipped_verified:
        print(f"  Skipped (resume)      : {skipped_verified}")
    print(f"  Failed / invalid      : {invalid_data}")

    if discrepancies:
        print("\nDiscrepancies:")
        for d in discrepancies:
            print(f"  - {d}")

    return len(discrepancies) == 0


def main():
    parser = argparse.ArgumentParser(description="Verify ACQUIRED snapshots via rclone staging (bypasses FUSE)")
    parser.add_argument("--limit", type=int, default=None, help="Only check the first N snapshots")
    parser.add_argument("--tmp-dir", type=str, default=tempfile.gettempdir(),
                        help="Local directory used for staging (default: system temp)")
    parser.add_argument("--keep", action="store_true", help="Keep staged copies after verification")
    parser.add_argument("--list-only", action="store_true",
                        help="Only run the download-free clean-snapshot listing check (no hashing)")
    parser.add_argument("--progress-file", type=str, default=None,
                        help="JSON file tracking fully-verified snapshots (default: <tmp-dir>/pythia_verify_progress.json)")
    parser.add_argument("--no-resume", action="store_true",
                        help="Ignore saved progress and re-verify everything")
    parser.add_argument("--dry-run", action="store_true", help="Print rclone commands without executing")
    args = parser.parse_args()

    ok = verify_acquired(args)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
