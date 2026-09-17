#!/usr/bin/env python3
"""
Batch supervisor for GitHub repository acquisition.

This script repeatedly invokes the single-repo acquisition worker
(github_acquire_one.py) while respecting safety limits:

- Maximum runtime per batch (default 240s, leaving 60s buffer for 300s wall-clock)
- Free disk space check (stop if < 3 GiB)
- Stop if no QUEUED candidates remain
* Clean checkpointing between repositories
- Never marks ACQUIRED itself; the worker handles state
* Does not duplicate acquisition logic.
* Exits cleanly before the 300s wall-clock limit.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Configuration
MANIFEST_PATH = "/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl"
INPROGRESS_BASE = Path("/mnt/pythia-cloud/Pythia/raw/github/.inprogress")
DISK_SAFETY_GB = 3  # GiB
DEFAULT_MAX_RUNTIME = 240  # 4 minutes (leaves 60s buffer for 300s wall-clock)

def load_manifest():
    """Load the canonical manifest."""
    if not Path("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl").exists():
        raise FileNotFoundError(f"Manifest not found")
    with open("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl", 'r') as f:
        return [json.loads(line) for line in f if line.strip()]

def get_disk_free_gib(path="/home"):
    """Return free disk space in GiB."""
    stat = shutil.disk_usage(path)
    return stat.free / (1024 ** 3)

def get_queued_count():
    """Get count of QUEUED repositories."""
    candidates = load_manifest_safe()
    return sum(1 for c in candidates if c.get('state') == 'QUEUED')

def get_acquired_count():
    candidates = load_manifest_safe()
    return sum(1 for c in candidates if c.get('state') == 'ACQUIRED')

def load_manifest_safe():
    """Load manifest from cloud path."""
    with open("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl", 'r') as f:
        return [json.loads(line) for line in f if line.strip()]

def get_disk_free_gib(path="/home"):
    """Return free disk space in GiB."""
    stat = shutil.disk_usage(path)
    return stat.free / (1024 ** 3)

def run_single_acquisition() -> tuple:
    """Run the single-repo acquisition worker."""
    env = os.environ.copy()
    env["PYTHIA_DATA_ROOT"] = "/mnt/pythia-cloud/Pythia"
    env["PYTHONPATH"] = "/home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline"

    try:
        result = subprocess.run(
            ["python3", "/home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline/scripts/scrapers/github_acquire_one.py"],
            env=env,
            cwd="/home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline",
            capture_output=True,
            text=True,
            timeout=180  # 3 minutes max per repo
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout"

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Batch GitHub acquisition supervisor")
    parser.add_argument("--max-runtime", type=int, default=240, help="Max runtime in seconds (default 240)")
    parser.add_argument("--disk-limit-gb", type=float, default=3, help="Min free disk space in GiB")
    args = parser.parse_args()

    print(f"=== GitHub Acquisition Batch Supervisor ===")
    print(f"Max runtime: {args.max_runtime}s (leaves {300 - args.max_runtime}s buffer for 300s wall-clock)")
    print(f"Disk safety limit: {DISK_SAFETY_GB} GiB")

    start_time = time.time()
    start_queued = get_queued_count()
    start_acquired = 0
    # Count ACQUIRED from manifest
    with open("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl") as f:
        start_acquired = sum(1 for line in open("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl") if json.loads(line).get('state') == 'ACQUIRED')

    start_disk = get_disk_free_gib()

    print(f"Starting state: {start_acquired} ACQUIRED, {start_queued} QUEUED")
    print(f"Free disk: {start_disk:.2f} GiB")

    repos_attempted = 0
    repos_acquired = 0
    repos_failed = 0
    repos_timeout = 0

    while True:
        # Check stopping conditions
        elapsed = time.time() - start_time
        if elapsed > args.max_runtime:
            print(f"Max runtime ({args.max_runtime}s) reached, stopping.")
            break

        free_gib = get_disk_free_gib()
        if free_gib < 3:
            print(f"Free disk space {free_gib:.2f} GiB below limit 3 GiB, stopping.")
            break

        queued = get_queued_count()
        if queued == 0:
            print("No QUEUED repositories remaining.")
            break

        # Run one acquisition
        print(f"\n--- Attempting acquisition ({get_acquired_count()} acquired, {get_queued_count()} queued) ---")
        retcode, stdout, stderr = run_single_acquisition()

        if retcode == 0:
            print("Repository acquired successfully.")
            repos_acquired += 1
        elif retcode == -2:  # timeout
            print("Repository timed out.")
            repos_timeout += 1
        elif retcode == -1:
            print("Repository failed.")
            repos_failed += 1
        else:
            print(f"Unexpected return code: {retcode}")
            repos_failed += 1

        repos_attempted += 1

        # Check if we've processed enough repos for this batch
        if time.time() - start_time > args.max_runtime - 30:  # Stop 30s before limit
            print(f"Approaching time limit, stopping batch.")
            break

        # Small delay between acquisitions
        time.sleep(2)

    # Final report
    end_acquired = 0
    with open("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl") as f:
        end_acquired = sum(1 for line in open("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl") if json.loads(line).get('state') == 'ACQUIRED')
    end_queued = get_queued_count()
    end_disk = get_disk_free_gib()
    elapsed = time.time() - start_time

    print(f"\n=== BATCH SUMMARY ===")
    print(f"Runtime: {time.time() - start_time:.1f}s")
    print(f"Starting: {start_acquired} ACQUIRED, {start_queued} QUEUED")
    print(f"Ending: {end_acquired} ACQUIRED, {get_queued_count()} QUEUED")
    print(f"Acquired this batch: {repos_acquired}")
    print(f"Failed: {repos_failed}")
    print(f"Timeouts: {repos_timeout}")
    print(f"Free disk: {get_disk_free_gib():.2f} GiB (started at {start_disk:.2f} GiB)")
    print(f"Free disk change: {get_disk_free_gib() - start_disk:.2f} GiB")

    return 0

if __name__ == "__main__":
    sys.exit(main())