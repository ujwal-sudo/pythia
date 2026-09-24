#!/usr/bin/env python3
"""
GitHub Acquisition Progress Reporter

Prints a comprehensive status report of the GitHub acquisition pipeline.
"""

import json
import os
import shutil
from pathlib import Path
from collections import Counter

MANIFEST_PATH = Path("data/raw/github/manifests/github_candidates_v1.jsonl")
CLOUD_BASE = Path("/mnt/pythia-cloud/Pythia/raw/github")


def load_manifest():
    with open(MANIFEST_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]


def get_drive_usage():
    """Get drive usage for the Pythia cloud mount."""
    try:
        usage = shutil.disk_usage("/mnt/pythia-cloud")
        total_gb = usage.total / (1024 ** 3)
        used_gb = usage.used / (1024 ** 3)
        free_gb = usage.free / (1024 ** 3)
        return total_gb, used_gb, free_gb
    except Exception:
        return None, None, None


def count_local_repos():
    """Count local repository caches."""
    base = Path("data/raw/github/repositories")
    if not base.exists():
        return 0
    return sum(1 for d in base.iterdir() if d.is_dir() and not d.name.startswith('.'))


def estimate_tokens(candidates):
    """Rough token estimate from acquired repos."""
    total_bytes = 0
    for c in candidates:
        if c.get('state') == 'ACQUIRED':
            size_kb = c.get('repo_size_kb', 0)
            total_bytes += size_kb * 1024
    # Rough estimate: 1 token ≈ 4 bytes for code
    return total_bytes // 4 if total_bytes > 0 else 0


def print_failed_repos(candidates):
    """List failed repositories with reasons."""
    failed = [c for c in candidates if c.get('state') == 'FAILED']
    if failed:
        print("\n  FAILED REPOSITORIES:")
        for c in failed:
            reason = c.get('error', 'Unknown error')
            print(f"  - {c['full_name']}: {reason[:80]}")
    else:
        print("\n  No failed repositories.")


def print_timeout_repos(candidates):
    """List timeout repositories."""
    timeout = [c for c in candidates if c.get('state') == 'TIMEOUT_PERMANENT']
    retryable = [c for c in candidates if c.get('state') == 'TIMEOUT_RETRYABLE']
    
    if timeout:
        print("\n  TIMEOUT_PERMANENT (exhausted retries):")
        for c in timeout:
            size = c.get('repo_size_kb', 0)
            attempts = c.get('attempt_count', 0)
            error = c.get('last_error', 'Unknown')[:60]
            print(f"  - {c['full_name']}: {size}KB, attempts={attempts}, error={error}")
    
    if retryable:
        print("\n  TIMEOUT_RETRYABLE (will retry):")
        for c in retryable:
            size = c.get('repo_size_kb', 0)
            attempts = c.get('attempt_count', 0)
            print(f"  - {c['full_name']}: {size}KB, attempts={c.get('attempt_count', 0)}")


def print_skipped_repos(candidates):
    """List skipped repositories."""
    skipped = [c for c in candidates if c.get('state') == 'SKIPPED']
    if skipped:
        print("\n  SKIPPED (too large):")
        for c in skipped:
            size = c.get('repo_size_kb', 0)
            reason = c.get('skip_reason', 'N/A')
            print(f"  - {c['full_name']}: {size}KB ({reason})")


def print_legacy(candidates):
    """List legacy acquired repos."""
    legacy = [c for c in candidates if c.get('state') == 'LEGACY_ACQUIRED_UNVERIFIED']
    if legacy:
        print("\n  LEGACY_ACQUIRED_UNVERIFIED (historical, unverified):")
        for c in legacy:
            size = c.get('repo_size_kb', 0)
            print(f"  - {c['full_name']}: {size}KB")


def print_acquired(candidates):
    """List acquired repositories."""
    acquired = [c for c in candidates if c.get('state') == 'ACQUIRED']
    if acquired:
        print("\n  ACQUIRED REPOSITORIES:")
        for c in acquired:
            size = c.get('repo_size_kb', 0)
            sha = c.get('commit_sha', 'N/A')[:12]
            print(f"  - {c['full_name']}: {size}KB, sha={sha}")


def main():
    candidates = []
    with open("data/raw/github/manifests/github_candidates_v1.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                candidates.append(json.loads(line))

    total = len(candidates)
    
    # Count states
    state_counts = Counter(c.get('state', 'UNKNOWN') for c in candidates)
    size_counts = Counter(c.get('size_category', 'NONE') for c in candidates)
    
    acquired = sum(1 for c in candidates if c.get('state') == 'ACQUIRED')
    queued = sum(1 for c in candidates if c.get('state') == 'QUEUED')
    skipped = sum(1 for c in candidates if c.get('state') == 'SKIPPED')
    failed = sum(1 for c in candidates if c.get('state') == 'FAILED')
    timeout = sum(1 for c in candidates if c.get('state') == 'TIMEOUT_PERMANENT')
    timeout_retry = sum(1 for c in candidates if c.get('state') == 'TIMEOUT_RETRYABLE')
    legacy = sum(1 for c in candidates if c.get('state') == 'LEGACY_ACQUIRED_UNVERIFIED')
    
    # Drive usage
    total_gb, used_gb, free_gb = get_drive_usage()
    
    # Token estimate
    est_tokens = estimate_tokens([c for c in candidates if c.get('state') == 'ACQUIRED'])
    
    # Local cache count
    local_repos = count_local_repos()
    
    # Print report
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║          PYTHIA GITHUB ACQUISITION PROGRESS                  ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print(f"║  ACQUIRED   : {acquired:>3} / {total:>3}  ({acquired*100//total if total else 0:>2}%)        ║")
    print(f"║  QUEUED     : {queued:>3}                                 ║")
    print(f"║  SKIPPED    : {skipped:>3}  (too large)                    ║")
    print(f"║  FAILED     : {failed:>3}                                 ║")
    print(f"║  TIMEOUT    : {timeout:>3}                                 ║")
    print(f"║  RETRYABLE  : {timeout_retry:>3}                              ║")
    print(f"║  LEGACY     : {legacy:>3}  (unverified)                  ║")
    print("╠═════════════════════════════════════════════════════════════╣")
    if total_gb:
        print(f"║  Drive total: {total_gb:.1f} GB  used: {used_gb:.1f} GB  free: {free_gb:.1f} GB  ║")
    print(f"║  Local cache: {local_repos} repo caches                   ║")
    print(f"║  Est. tokens: {est_tokens:>10,}                          ║")
    print("╚═════════════════════════════════════════════════════════════╝")
    
    # Detailed breakdown
    print_acquired(candidates)
    print_legacy(candidates)
    print_failed_repos(candidates)
    print_timeout_repos(candidates)
    print_skipped_repos(candidates)
    
    # Size distribution
    print("\n  SIZE DISTRIBUTION:")
    for cat in ['SMALL', 'MEDIUM', 'LARGE']:
        count = sum(1 for c in candidates if c.get('size_category') == cat)
        if count:
            print(f"  {cat}: {count}")


if __name__ == "__main__":
    main()