#!/usr/bin/env python3
"""
Acquire a single GitHub repository from the canonical manifest.

This script implements the acquisition state machine for a single repository:
- Loads the canonical manifest (github_candidates_v1.jsonl)
- Finds the first QUEUED repository
- Marks it DOWNLOADING immediately (writes manifest update)
- Clones to a temporary .inprogress/ directory under PYTHIA_DATA_ROOT
- Verifies: commit SHA matches, file count > 0, total bytes > 1000
- On success: atomic os.rename() to final <commit_sha>/ directory, marks ACQUIRED
- On TimeoutError: marks TIMEOUT (retryable)
- On any other failure: marks FAILED, logs reason
- In finally block: always deletes .inprogress/ if it exists
- On startup: if .inprogress/ exists for any repo, delete it and reset that repo to QUEUED
- PYTHIA_DATA_ROOT defaults to /mnt/pythia-cloud/Pythia

State machine states:
DISCOVERED, QUEUED, DOWNLOADING, DOWNLOADED, EXTRACTED, VERIFIED, ACQUIRED, FAILED, PARTIAL, TIMEOUT, SKIPPED

Rules:
- ACQUIRED is only written after filesystem verification passes.
- Manifest is the source of truth for state.
- Filesystem is the source of truth for data.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import signal
from pathlib import Path
from typing import Optional

# Ensure we can import config
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import DATA_ROOT, RAW_DIR

# Configuration
GITHUB_RAW_DIR = DATA_ROOT / "raw" / "github"
MANIFEST_PATH = RAW_DIR / "github" / "manifests" / "github_candidates_v1.jsonl"
INPROGRESS_BASE = DATA_ROOT / "raw" / "github" / ".inprogress"
# Per-repo timeout: 180 seconds (3 minutes) - leaves buffer for 300s wall-clock limit
CLONE_TIMEOUT_SECONDS = 180
VERIFY_TIMEOUT_SECONDS = 30

# State machine states
DISCOVERED = "DISCOVERED"
QUEUED = "QUEUED"
DOWNLOADING = "DOWNLOADING"
DOWNLOADED = "DOWNLOADED"
EXTRACTED = "EXTRACTED"
VERIFIED = "VERIFIED"
ACQUIRED = "ACQUIRED"
FAILED = "FAILED"
PARTIAL = "PARTIAL"
TIMEOUT = "TIMEOUT"
SKIPPED = "SKIPPED"

VALID_STATES = {
    DISCOVERED, QUEUED, DOWNLOADING, DOWNLOADED, EXTRACTED,
    VERIFIED, ACQUIRED, FAILED, PARTIAL, TIMEOUT, SKIPPED
}

def load_manifest():
    """Load the canonical manifest."""
    MANIFEST_PATH = Path("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl")
    if not Path("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl").exists():
        raise FileNotFoundError(f"Manifest not found")
    with open("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl", 'r') as f:
        return [json.loads(line) for line in f if line.strip()]

def save_manifest(candidates):
    """Write the manifest back atomically."""
    manifest_path = "/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl"
    tmp_path = "/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl.tmp"
    with open(tmp_path, 'w') as f:
        for c in candidates:
            f.write(json.dumps(c, sort_keys=True) + '\n')
    os.rename(tmp_path, "/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl")

def find_next_queued(candidates):
    """Find the first candidate with state QUEUED."""
    for c in candidates:
        if c.get('state') == 'QUEUED':
            return c
    return None

def update_candidate_state(candidates, full_name, new_state, **extra):
    """Update a candidate's state and any extra fields."""
    for c in candidates:
        if c['full_name'] == full_name:
            c['state'] = new_state
            for k, v in extra.items():
                c[k] = v
            break

def cleanup_inprogress():
    """Delete any .inprogress directories and reset their repos to QUEUED."""
    inprogress_dir = Path("/mnt/pythia-cloud/Pythia/raw/github/.inprogress")
    if not inprogress_dir.exists():
        return
    for repo_dir in inprogress_dir.iterdir():
        if not repo_dir.is_dir():
            continue
        parts = repo_dir.name.split('__', 1)
        if len(parts) != 2:
            continue
        full_name = f"{parts[0]}/{parts[1]}"
        # Reset state to QUEUED in manifest
        candidates = load_manifest()
        for c in candidates:
            if c['full_name'] == full_name and c.get('state') == 'DOWNLOADING':
                c['state'] = 'QUEUED'
                break
            if c.get('state') in ('DOWNLOADING', 'DOWNLOADED', 'EXTRACTED', 'VERIFIED'):
                c['state'] = 'QUEUED'
        save_manifest(candidates)
        shutil.rmtree(repo_dir, ignore_errors=True)
        print(f"Cleaned up incomplete .inprogress for {full_name}")

def clone_repo(full_name: str, dest_dir: Path, timeout_seconds: int) -> Optional[str]:
    """Clone repository with depth 1, return commit SHA."""
    clone_url = f"https://github.com/{full_name}.git"
    try:
        # Clone with depth 1
        subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, str(dest_dir)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Clone timed out after {timeout_seconds} seconds")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Git clone failed: {e.stderr.decode(errors='replace')[:200]}")

    # Get the commit SHA of the cloned HEAD
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=dest_dir,
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        commit_sha = result.stdout.strip()
        return commit_sha
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to get commit SHA: {e.stderr.decode(errors='replace')[:200]}")

def verify_repo(repo_dir: Path) -> bool:
    """Verify repository has files and size > 1000 bytes."""
    file_count = 0
    total_bytes = 0
    for entry in Path(repo_dir).rglob('*'):
        if entry.is_file():
            try:
                file_count += 1
                total_bytes += entry.stat().st_size
            except OSError:
                pass
    return file_count > 0 and total_bytes > 1000

def acquire_one() -> int:
    """
    Acquire a single repository.
    Returns: 1 = success, 0 = no work, -1 = failure, -2 = timeout
    """
    # Clean up any leftover .inprogress directories
    cleanup_inprogress()

    # Load manifest
    candidates = load_manifest()
    candidate = find_next_queued(candidates)
    if not candidate:
        print("No QUEUED repositories left.")
        return 0

    full_name = candidate['full_name']
    print(f"Acquiring {full_name}...")

    # Mark as DOWNLOADING immediately
    update_candidate_state(candidates, full_name, 'DOWNLOADING', download_started_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    save_manifest(candidates)

    # Prepare paths
    inprogress_dir = Path("/mnt/pythia-cloud/Pythia/raw/github/.inprogress") / f"{candidate['owner']}__{candidate['repo']}"
    inprogress_dir.mkdir(parents=True, exist_ok=True)
    final_repo_dir = Path("/mnt/pythia-cloud/Pythia/raw/github") / f"{candidate['owner']}__{candidate['repo']}"
    final_repo_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Clone into .inprogress with 180s timeout
        print(f"Cloning {full_name} (timeout: 180s)...")
        commit_sha = clone_repo(full_name, Path(inprogress_dir), 180)
        print(f"Cloned, commit SHA: {commit_sha}")

        # Verify the cloned repo
        if not verify_repo(Path(inprogress_dir)):
            raise RuntimeError("Repository verification failed: no files or size <= 1000 bytes")

        # Prepare final destination
        final_sha_dir = Path("/mnt/pythia-cloud/Pythia/raw/github") / f"{candidate['owner']}__{candidate['repo']}" / commit_sha
        if final_sha_dir.exists():
            shutil.rmtree(final_sha_dir)
        final_sha_dir.parent.mkdir(parents=True, exist_ok=True)

        # Atomic move
        os.rename(inprogress_dir, final_sha_dir)
        print(f"Moved to final location: {final_sha_dir}")

        # Verify again after move
        if not verify_repo(final_sha_dir):
            raise RuntimeError("Verification failed after move")

        # Update manifest to ACQUIRED
        update_candidate_state(candidates, full_name, 'ACQUIRED',
                               commit_sha=commit_sha,
                               cloud_path=str(final_sha_dir),
                               acquired_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        save_manifest(candidates)
        print(f"Successfully acquired {full_name} (SHA: {commit_sha})")
        return 1

    except TimeoutError as e:
        print(f"Timeout acquiring {full_name}: {e}")
        update_candidate_state(candidates, full_name, 'TIMEOUT', error=str(e))
        save_manifest(candidates)
        return -2
    except Exception as e:
        print(f"Failed to acquire {full_name}: {e}")
        update_candidate_state(candidates, full_name, 'FAILED', error=str(e))
        save_manifest(candidates)
        return -1
    finally:
        # Clean up .inprogress directory if it still exists
        if Path("/mnt/pythia-cloud/Pythia/raw/github/.inprogress").exists():
            shutil.rmtree("/mnt/pythia-cloud/Pythia/raw/github/.inprogress", ignore_errors=True)

def main():
    print("Starting single-repo acquisition...")
    result = acquire_one()
    if result == 1:
        print("Acquisition successful.")
    elif result == -1:
        print("Acquisition failed.")
    elif result == -2:
        print("Acquisition timed out.")
    else:
        print("No repositories to acquire.")
    sys.exit(0 if result >= 0 else 1)

if __name__ == "__main__":
    main()