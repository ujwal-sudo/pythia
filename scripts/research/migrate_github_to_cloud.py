#!/usr/bin/env python3
"""
Migrate verified local GitHub repositories to the cloud-backed GitHub raw directory.

This script is resumable and does not delete any local data.
It uses the canonical candidate manifest (local) and migrates only the repositories
that are fully acquired locally (have a SHA directory).
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# Ensure we can import config
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import DATA_ROOT, RAW_DIR

# Cloud and local base directories
CLOUD_BASE = Path(DATA_ROOT) / "raw" / "github"
LOCAL_BASE = Path(__file__).resolve().parent.parent.parent / "data" / "raw" / "github"

# Paths
# Repositories are stored directly under LOCAL_BASE (data/raw/github) with SHA subdirectories
LOCAL_REPOS_DIR = LOCAL_BASE
# Cloud repositories are stored directly under CLOUD_BASE (not under a "repositories" subdirectory)
CLOUD_REPOS_DIR = CLOUD_BASE
CANONICAL_MANIFEST = Path(__file__).resolve().parent.parent.parent / "data" / "raw" / "github" / "manifests" / "github_candidates_v1.jsonl"
MIGRATION_MANIFEST = CLOUD_BASE / "manifests" / "migration_manifest.jsonl"
STATE_FILE = CLOUD_BASE / "manifests" / "migration_state.json"

# Migration states
MIGRATION_PENDING = "MIGRATION_PENDING"
MIGRATING = "MIGRATING"
CLOUD_VERIFIED = "CLOUD_VERIFIED"
MIGRATION_FAILED = "MIGRATION_FAILED"

def load_canonical_candidates() -> List[dict]:
    """Load the canonical 150-candidate manifest."""
    if not CANONICAL_MANIFEST.exists():
        raise FileNotFoundError(f"Canonical manifest not found at {CANONICAL_MANIFEST}")
    with open(CANONICAL_MANIFEST, 'r') as f:
        return [json.loads(line) for line in f if line.strip()]

def get_local_verified_repos(canonical_names: set) -> Dict[str, dict]:
    """
    Scan local repositories directory for fully acquired repos (with SHA directory).
    Returns dict: full_name -> {'sha': sha, 'path': Path}
    """
    verified = {}
    if not LOCAL_REPOS_DIR.exists():
        return verified
    for repo_dir in LOCAL_REPOS_DIR.iterdir():
        if not repo_dir.is_dir() or repo_dir.name.startswith('.') or repo_dir.name == 'manifests' or repo_dir.name == 'repositories':
            continue
        # repo_dir name format: owner__repo
        parts = repo_dir.name.split('__', 1)
        if len(parts) != 2:
            continue
        owner, repo = parts
        full_name = f"{owner}/{repo}"
        if full_name not in canonical_names:
            continue
        # Find SHA subdirectory
        sha_dirs = [d for d in repo_dir.iterdir() if d.is_dir() and len(d.name) == 40 and all(c in '0123456789abcdef' for c in d.name)]
        if sha_dirs:
            # Assume only one SHA dir per repo (the pinned commit)
            sha = sha_dirs[0].name
            verified[full_name] = {'sha': sha, 'path': sha_dirs[0]}
    return verified

def load_state() -> Dict[str, dict]:
    """Load migration state from JSON file."""
    print(f"DEBUG: STATE_FILE = {STATE_FILE}, exists={STATE_FILE.exists()}")
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_state(state: Dict[str, dict]):
    """Save migration state to JSON file."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def append_migration_record(record: dict):
    """Append a record to the migration manifest (JSONL)."""
    MIGRATION_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(MIGRATION_MANIFEST, 'a') as f:
        f.write(json.dumps(record, sort_keys=True) + '\n')

def compute_dir_size(path: Path) -> int:
    """Return total size of directory in bytes."""
    total = 0
    for entry in path.rglob('*'):
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except OSError:
                pass
    return total

def count_files(path: Path) -> int:
    """Count files in directory (recursive)."""
    count = 0
    for entry in path.rglob('*'):
        if entry.is_file():
            count += 1
    return count

def verify_copy(src: Path, dst: Path) -> bool:
    """
    Verify that destination is a faithful copy of source.
    Checks: same number of files, same total size, and no obvious truncation.
    """
    if not dst.exists():
        return False
    src_files = count_files(src)
    dst_files = count_files(dst)
    if src_files != dst_files:
        return False
    src_size = compute_dir_size(src)
    dst_size = compute_dir_size(dst)
    if src_size != dst_size:
        return False
    return True

def migrate_repo(full_name: str, sha: str, src_path: Path, dry_run: bool = False) -> dict:
    """
    Migrate a single repository from local to cloud.
    Returns a record dict with migration result.
    """
    owner, repo = full_name.split('/')
    repo_key = f"{owner}__{repo}"
    dst_repo_dir = CLOUD_REPOS_DIR / repo_key
    dst_sha_dir = dst_repo_dir / sha

    record = {
        'repository': full_name,
        'commit_sha': sha,
        'source_path': str(src_path),
        'destination_path': str(dst_sha_dir),
        'source_size_bytes': 0,
        'destination_size_bytes': 0,
        'verification_result': 'FAILED',
        'failure_reason': '',
        'timestamp_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }

    if dry_run:
        record['verification_result'] = 'DRY_RUN'
        return record

    # Ensure destination repo directory exists
    dst_repo_dir.mkdir(parents=True, exist_ok=True)

    # Remove any existing incomplete copy at the SHA directory
    if dst_sha_dir.exists():
        shutil.rmtree(dst_sha_dir)

    # Copy the entire source SHA directory to the destination
    try:
        shutil.copytree(str(src_path), str(dst_sha_dir))
    except Exception as e:
        record['failure_reason'] = f"Copy failed: {e}"
        return record

    # Verify copy
    if not verify_copy(src_path, dst_sha_dir):
        record['failure_reason'] = "Verification failed: file count or size mismatch"
        # Clean up failed copy
        if dst_sha_dir.exists():
            shutil.rmtree(dst_sha_dir, ignore_errors=True)
        return record

    # Record sizes
    record['source_size_bytes'] = compute_dir_size(src_path)
    record['destination_size_bytes'] = compute_dir_size(dst_sha_dir)
    record['verification_result'] = 'CLOUD_VERIFIED'
    record['failure_reason'] = ''
    return record

def main(dry_run: bool = False):
    # Load canonical candidates
    candidates = load_canonical_candidates()
    candidate_names = {c['full_name'] for c in candidates}

    # Get locally verified repos
    local_verified = get_local_verified_repos(candidate_names)

    # Filter to only those in canonical manifest (should be all)
    repos_to_migrate = {name: info for name, info in local_verified.items() if name in candidate_names}

    print(f"Found {len(local_verified)} locally verified repositories.")
    print(f"Of those, {len(repos_to_migrate)} are in the canonical manifest and will be migrated.")

    # Load migration state
    state = load_state()

    migrated_count = 0
    verified_count = 0
    failed_count = 0

    for full_name, info in sorted(repos_to_migrate.items()):
        sha = info['sha']
        src_path = info['path']

        # Check current state
        repo_state = state.get(full_name, {}).get('status', MIGRATION_PENDING)

        if repo_state == CLOUD_VERIFIED:
            print(f"  {full_name} already verified on cloud, skipping.")
            continue

        if repo_state == MIGRATING:
            # Previous migration was interrupted; we'll retry
            pass

        # Update state to MIGRATING
        state[full_name] = {'status': MIGRATING, 'sha': sha, 'started_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        save_state(state)

        print(f"Migrating {full_name} (SHA: {sha})...")
        record = migrate_repo(full_name, info['sha'], info['path'])

        # Update state and manifest
        if record['verification_result'] == 'CLOUD_VERIFIED':
            state[full_name] = {'status': CLOUD_VERIFIED, 'sha': sha, 'completed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
            verified_count += 1
        else:
            state[full_name] = {'status': MIGRATION_FAILED, 'sha': sha, 'error': record['failure_reason'], 'failed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
            failed_count += 1

        save_state(state)
        append_migration_record(record)

        if record['verification_result'] == 'CLOUD_VERIFIED':
            migrated_count += 1
            print(f"  ✓ {full_name} migrated and verified.")
        else:
            print(f"  ✗ {full_name} failed: {record['failure_reason']}")

    # Summary
    print("\n=== MIGRATION SUMMARY ===")
    print(f"Total repositories to migrate: {len(repos_to_migrate)}")
    print(f"Successfully migrated and verified: {verified_count}")
    print(f"Failed: {failed_count}")
    print(f"Skipped (already verified): {len(repos_to_migrate) - verified_count - failed_count}")

    # Final verification: count cloud verified
    cloud_verified = sum(1 for v in state.values() if v.get('status') == CLOUD_VERIFIED)
    print(f"\nCloud verified total: {cloud_verified}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Migrate verified local GitHub repos to cloud.")
    parser.add_argument('--dry-run', action='store_true', help="Perform a dry run without copying")
    args = parser.parse_args()
    main(dry_run=args.dry_run)