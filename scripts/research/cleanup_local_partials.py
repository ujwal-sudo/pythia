#!/usr/bin/env python3
"""
Clean up local partial GitHub clones that don't have a valid commit SHA directory.

This script identifies repositories in the local GitHub raw directory that are
incomplete (no SHA subdirectory) and optionally deletes them after confirmation.

Usage:
    python3 cleanup_local_partials.py [--yes] [--dry-run]
"""

import os
import sys
import shutil
from pathlib import Path

LOCAL_BASE = Path('/home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline/data/raw/github')
REPOS_DIR = Path('/home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline/data/raw/github/repositories')

def find_partial_repos():
    """Return list of (full_name, repo_dir) for repos without SHA subdirectory."""
    partial = []
    if not REPOS_DIR.exists():
        return partial
    for repo_dir in REPOS_DIR.iterdir():
        if not repo_dir.is_dir() or repo_dir.name.startswith('.'):
            continue
        parts = repo_dir.name.split('__', 1)
        if len(parts) != 2:
            continue
        owner, repo = parts
        full_name = f"{owner}/{repo}"
        # Check for SHA subdirectory
        sha_dirs = [d for d in repo_dir.iterdir() if d.is_dir() and len(d.name) == 40 and all(c in '0123456789abcdef' for c in d.name)]
        if not sha_dirs:
            partial.append((full_name, repo_dir))
    return partial

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Clean up local partial GitHub clones")
    parser.add_argument('--yes', action='store_true', help='Automatically confirm deletion')
    parser.add_argument('--dry-run', action='store_true', help='List what would be deleted without deleting')
    args = parser.parse_args()

    partial = find_partial_repos()
    if not partial:
        print("No partial repositories found.")
        return

    print(f"Found {len(partial)} partial repositories (no commit SHA directory):")
    for full_name, repo_dir in partial:
        print(f"  {full_name} -> {repo_dir}")

    if args.dry_run:
        print("Dry run: no files deleted.")
        return

    if not args.yes:
        confirm = input(f"Delete these {len(partial)} partial repositories? [y/N]: ").strip().lower()
        if confirm != 'y':
            print("Aborted.")
            return

    deleted = 0
    for full_name, repo_dir in partial:
        try:
            shutil.rmtree(repo_dir)
            print(f"Deleted {full_name}")
            deleted += 1
        except Exception as e:
            print(f"Failed to delete {full_name}: {e}")

    print(f"Deleted {deleted} partial repositories.")

if __name__ == "__main__":
    main()