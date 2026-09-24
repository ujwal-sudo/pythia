#!/usr/bin/env python3
"""
STEP 0: Reconcile manifest with actual filesystem state.
Fixes manifest to match reality.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

MANIFEST_PATH = Path("data/raw/github/manifests/github_candidates_v1.jsonl")
CLOUD_BASE = Path("/mnt/pythia-cloud/Pythia/raw/github")
LOCAL_REPO_BASE = Path("data/raw/github/repositories")
LOCAL_SNAPSHOT_TEMP = Path("data/raw/github/.snapshots_temp")

def load_manifest():
    with open(MANIFEST_PATH) as f:
        return [json.loads(line) for line in f]

def save_manifest(candidates):
    with open(MANIFEST_PATH, 'w') as f:
        for c in candidates:
            f.write(json.dumps(c, sort_keys=True) + '\n')

def has_valid_content(path):
    """Check if directory exists and has actual content (not just empty dir)."""
    if not Path(path).exists():
        return False
    try:
        items = list(Path(path).iterdir())
        return len(items) > 0
    except:
        return False

def get_cloud_repo_path(owner, repo):
    """Get the cloud directory path for a repo."""
    return CLOUD_BASE / f"{owner}__{repo}"

def has_valid_commit_dir(repo_path, expected_sha=None):
    """Check if the repo has a valid commit SHA directory."""
    repo_path = Path(repo_path)
    if not repo_path.exists():
        return False
    for item in repo_path.iterdir():
        if item.is_dir() and len(item.name) == 40 and all(c in '0123456789abcdef' for c in item.name):
            if expected_sha is None or item.name == expected_sha:
                # Check if it has content
                if any(item.iterdir()):
                    return True
    return False

def reconcile():
    candidates = []
    with open(MANIFEST_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                candidates.append(json.loads(line))

    print("=" * 60)
    print("STEP 0: RECONCILIATION")
    print("=" * 60)

    # Initial state summary
    states = {}
    for c in candidates:
        s = c.get('state', 'UNKNOWN')
        states[s] = states.get(s, 0) + 1
    print("\nInitial state:")
    for k, v in sorted(states.items()):
        print(f"  {k}: {states[k]}")
    print(f"  TOTAL: {len(candidates)}")

    # Track changes
    changes = {
        'acquired_to_queued': [],
        'acquired_to_failed': [],
        'queued_to_acquired': [],
        'downloading_to_queued': [],
        'partial_to_queued': [],
        'downloading_to_failed': [],
    }

    # Cloud base path
    cloud_base = Path("/mnt/pythia-cloud/Pythia/raw/github")

    for c in candidates:
        state = c.get('state', 'UNKNOWN')
        full_name = c.get('full_name', '')
        owner = c.get('owner', '')
        repo = c.get('repo', '')
        commit_sha = c.get('commit_sha', '')
        cloud_path = c.get('cloud_path', '')

        # Build expected paths
        cloud_repo_dir = Path("/mnt/pythia-cloud/Pythia/raw/github") / f"{owner}__{repo}"

        if state == 'ACQUIRED':
            # Check if cloud directory exists and has valid content
            if not cloud_base.exists() or not (cloud_base / f"{owner}__{repo}").exists():
                print(f"  ACQUIRED -> QUEUED (missing cloud dir): {full_name}")
                c['state'] = 'QUEUED'
                c.pop('acquired_at', None)
                c.pop('cloud_path', None)
                c.pop('commit_sha', None)
                changes['acquired_to_queued'].append(full_name)
            else:
                # Check if the SHA directory exists
                sha_dir = Path("/mnt/pythia-cloud/Pythia/raw/github") / f"{owner}__{repo}" / c.get('commit_sha', '')
                if not sha_dir.exists() or not has_valid_commit_dir(cloud_base / f"{owner}__{repo}", c.get('commit_sha', '')):
                    print(f"  ACQUIRED -> QUEUED (missing SHA dir): {full_name}")
                    c['state'] = 'QUEUED'
                    c.pop('acquired_at', None)
                    c.pop('cloud_path', None)
                    c.pop('commit_sha', None)
                    changes['acquired_to_queued'].append(full_name)
                else:
                    # Verify it's valid
                    sha_dir = Path("/mnt/pythia-cloud/Pythia/raw/github") / f"{owner}__{repo}" / c.get('commit_sha', '')
                    if sha_dir.exists() and any(sha_dir.iterdir()):
                        print(f"  VERIFIED ACQUIRED: {full_name}")
                    else:
                        print(f"  ACQUIRED -> QUEUED (empty SHA dir): {full_name}")
                        c['state'] = 'QUEUED'
                        c.pop('acquired_at', None)
                        c.pop('cloud_path', None)
                        c.pop('commit_sha', None)
                        changes['acquired_to_queued'].append(full_name)

        elif state in ('DOWNLOADING', 'PARTIAL'):
            # Interrupted runs - reset to QUEUED
            print(f"  {state} -> QUEUED (interrupted): {full_name}")
            c['state'] = 'QUEUED'
            c.pop('acquired_at', None)
            c.pop('cloud_path', None)
            c.pop('commit_sha', None)
            if 'download_started_at' in c:
                c.pop('download_started_at', None)
            if state == 'DOWNLOADING':
                changes['downloading_to_queued'].append(full_name)
            else:
                changes['partial_to_queued'].append(full_name)

        elif state == 'DOWNLOADING':
            # Should be handled above, but just in case
            print(f"  DOWNLOADING -> QUEUED: {full_name}")
            c['state'] = 'QUEUED'
            changes['downloading_to_queued'].append(full_name)

    # Clean up .inprogress directories
    inprogress_dir = Path("/mnt/pythia-cloud/Pythia/raw/github/.inprogress")
    if inprogress_dir.exists():
        for item in inprogress_dir.iterdir():
            if item.is_dir():
                print(f"  Removing .inprogress: {item.name}")
                subprocess.run(['rm', '-rf', str(item)], check=False)

    # Also clean local .inprogress
    local_repo_base = Path("data/raw/github/repositories")
    for item in local_repo_base.iterdir():
        if item.name.endswith('.inprogress') or item.name == '.inprogress':
            print(f"  Removing local .inprogress: {item.name}")
            subprocess.run(['rm', '-rf', str(item)], check=False)

    # Remove empty .snapshots_temp entries
    snapshots_temp = Path("data/raw/github/.snapshots_temp")
    if snapshots_temp.exists():
        for item in snapshots_temp.iterdir():
            if item.is_dir():
                try:
                    if not any(item.iterdir()):
                        print(f"  Removing empty snapshot temp: {item.name}")
                        subprocess.run(['rm', '-rf', str(item)], check=False)
                except:
                    pass

    # Save reconciled manifest
    save_manifest(candidates)

    # Print final state
    print("\n" + "=" * 60)
    print("RECONCILIATION COMPLETE")
    print("=" * 60)
    
    states = {}
    for c in candidates:
        s = c.get('state', 'UNKNOWN')
        states[s] = states.get(s, 0) + 1
    for k, v in sorted(states.items()):
        print(f"  {k}: {states[k]}")
    print(f"  TOTAL: {len(candidates)}")

    print("\nChanges made:")
    for k, v in changes.items():
        if v:
            print(f"  {k}: {len(v)} - {', '.join(v[:5])}{'...' if len(v) > 5 else ''}")

    return candidates

if __name__ == "__main__":
    reconcile()