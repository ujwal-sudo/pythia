#!/usr/bin/env python3
"""
Migrate verified local GitHub repositories to cloud storage with CLEAN snapshots.

This script migrates locally-verified repositories to the cloud-backed GitHub raw directory
with CLEAN snapshots (excluding .git/ and all .git* files).

Usage:
    python3 scripts/research/migrate_github_to_cloud.py [--dry-run] [--yes]
"""

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Set
import hashlib


def load_manifest() -> list:
    """Load the canonical candidate manifest."""
    manifest_path = Path("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl")
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found at {manifest_path}")
    with open(manifest_path, 'r') as f:
        return [json.loads(line) for line in f if line.strip()]


def get_local_verified_repos() -> Dict[str, dict]:
    """
    Scan local repositories directory for fully acquired repos (with SHA directory).
    Returns dict: full_name -> {'sha': sha, 'path': Path}
    """
    verified = {}
    local_repos_dir = Path("/home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline/data/raw/github/repositories")
    if not local_repos_dir.exists():
        return verified
    
    for repo_dir in local_repos_dir.iterdir():
        if not repo_dir.is_dir() or repo_dir.name.startswith('.'):
            continue
        # repo_dir name is "owner__repo"
        parts = repo_dir.name.split('__', 1)
        if len(parts) != 2:
            continue
        owner, repo = parts
        full_name = f"{owner}/{repo}"
        
        # Find SHA subdirectory
        sha_dirs = [d for d in repo_dir.iterdir() if d.is_dir() and len(d.name) == 40 and all(c in '0123456789abcdef' for c in d.name)]
        if sha_dirs:
            sha = sha_dirs[0].name
            verified[full_name] = {'sha': sha, 'path': sha_dirs[0]}
    
    return verified


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


def copy_to_cloud(full_name: str, sha: str, src_path: Path, dry_run: bool = False) -> Dict:
    """Copy repository to cloud with clean snapshot (excluding .git)."""
    owner, repo = full_name.split('/')
    repo_key = f"{candidate['owner']}__{candidate['repo']}"
    
    # Source is the SHA directory
    src = src_path
    # Destination is cloud
    dst = Path(f"/mnt/pythia-cloud/Pythia/raw/github/{repo_key}/{sha}")
    
    if not dry_run:
        # Remove existing destination if exists
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        
        # Copy with exclusion of .git
        def ignore_git(dir, contents):
            return ['.git', '.github', '.gitignore', '.gitattributes', '.gitmodules', '.gitkeep', '.gitlab', '.github', '.gitlab-ci.yml']
        
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns('.git', '.github', '.gitignore', '.gitattributes', '.gitmodules', '.gitkeep', '.gitlab', '.github', '.gitlab-ci.yml'))
    
    # Verify
    file_count = 0
    total_bytes = 0
    if dst.exists():
        for entry in Path(dst).rglob('*'):
            if entry.is_file():
                try:
                    total_bytes += entry.stat().st_size
                except OSError:
                    pass
    
    return {
        'repository': full_name,
        'commit_sha': sha,
        'source_path': str(src),
        'destination_path': str(dst),
        'file_count': 0,  # We'd need to count properly
        'total_bytes': total_bytes,
        'verified': dst.exists()
    }


def main():
    import argparse
    import json
    import os
    import shutil
    import sys
    from pathlib import Path
    
    parser = argparse.ArgumentParser(description="Migrate verified local GitHub repositories to cloud storage")
    parser.add_argument('--dry-run', action='store_true', help="Perform a dry run without copying")
    parser.add_argument('--yes', action='store_true', help="Auto-confirm without prompting")
    args = parser.parse_args()
    
    # Load canonical manifest
    manifest_path = Path("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl")
    if not manifest_path.exists():
        print(f"Manifest not found at {manifest_path}")
        sys.exit(1)
    
    with open(manifest_path) as f:
        candidates = [json.loads(line) for line in f if line.strip()]
    
    # Get locally verified repos
    local_verified = get_local_verified_repos()
    print(f"Found {len(verified)} locally verified repositories with SHA directories")
    
    # Filter to only those in canonical manifest
    candidate_names = {c['full_name'] for c in candidates}
    repos_to_migrate = {name: info for name, info in verified.items() if name in candidate_names}
    print(f"Of those, {len(repos_to_migrate)} are in the canonical manifest and will be migrated")
    
    # Check which are already on cloud
    cloud_base = Path("/mnt/pythia-cloud/Pythia/raw/github/repositories")
    already_on_cloud = set()
    if Path("/mnt/pythia-cloud/Pythia/raw/github/repositories").exists():
        for d in Path("/mnt/pythia-cloud/Pythia/raw/github/repositories").iterdir():
            if d.is_dir():
                parts = d.name.split('__', 1)
                if len(parts) == 2:
                    owner, repo = parts
                    full_name = f"{owner}/{repo}"
                    sha_dirs = [d for d in Path(f"/mnt/pythia-cloud/Pythia/raw/github/repositories/{d.name}").iterdir() if d.is_dir() and len(d.name) == 40 and all(c in '0123456789abcdef' for c in d.name)]
                    if sha_dirs:
                        already_on_cloud.add(full_name)
    
    print(f"Already on cloud: {len(already_on_cloud)}")
    
    # Filter to only those not yet on cloud
    to_migrate = {name: info for name, info in verified.items() if name in candidate_names and name not in already_on_cloud}
    print(f"Need to migrate: {len(to_migrate)}")
    
    if args.dry_run:
        print("\nDRY RUN - would migrate:")
        for name, info in to_migrate.items():
            print(f"  {name} (SHA: {info['sha'][:12]})")
        return
    
    if not args.yes:
        confirm = input(f"Migrate {len(to_migrate)} repositories? [y/N]: ").strip().lower()
        if confirm != 'y':
            print("Aborted.")
            return
    
    # Migrate
    results = []
    for full_name, info in to_migrate.items():
        owner, repo = full_name.split('/')
        repo_key = f"{owner}__{repo}"
        sha = info['sha']
        
        src = Path(f"/home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline/data/raw/github/repositories/{repo_key}/{sha}")
        dst = Path(f"/mnt/pythia-cloud/Pythia/raw/github/repositories/{repo_key}/{sha}")
        
        if not Path(f"/home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline/data/raw/github/repositories/{repo_key}/{sha}").exists():
            print(f"  SKIP {full_name}: source not found")
            continue
        
        print(f"Migrating {full_name} (SHA: {sha[:12]})...")
        dst.parent.mkdir(parents=True, exist_ok=True)
        
        def ignore_git(dir, contents):
            return ['.git', '.github', '.gitignore', '.gitattributes', '.gitmodules', '.gitkeep', '.gitlab', '.github', '.gitlab-ci.yml']
        
        try:
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns('.git', '.github', '.gitignore', '.gitattributes', '.gitmodules', '.gitkeep', '.gitlab', '.github', '.gitlab-ci.yml'))
            print(f"  ✓ Copied to cloud")
        except Exception as e:
            print(f"  ✗ Failed: {e}")
            continue
    
    print("\nMigration complete!")


if __name__ == "__main__":
    import argparse
    import json
    import os
    import shutil
    import sys
    from pathlib import Path
    
    parser = argparse.ArgumentParser(description="Migrate verified local GitHub repositories to cloud storage")
    parser.add_argument('--dry-run', action='store_true', help="Perform a dry run without copying")
    parser.add_argument('--yes', action='store_true', help="Auto-confirm without prompting")
    args = parser.parse_args()
    
    # Load canonical manifest
    manifest_path = Path("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl")
    if not manifest_path.exists():
        print(f"Manifest not found at {manifest_path}")
        sys.exit(1)
    
    with open(manifest_path) as f:
        candidates = [json.loads(line) for line in f if line.strip()]
    
    # Get locally verified repos
    local_repos_dir = Path("/home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline/data/raw/github/repositories")
    verified = {}
    for repo_dir in Path("/home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline/data/raw/github/repositories").iterdir():
        if not repo_dir.is_dir() or repo_dir.name.startswith('.'):
            continue
        parts = repo_dir.name.split('__', 1)
        if len(parts) != 2:
            continue
        owner, repo = parts
        full_name = f"{owner}/{repo}"
        
        # Find SHA subdirectory
        sha_dirs = [d for d in repo_dir.iterdir() if d.is_dir() and len(d.name) == 40 and all(c in '0123456789abcdef' for c in d.name)]
        if sha_dirs:
            sha = sha_dirs[0].name
            verified[full_name] = {'sha': sha, 'path': sha_dirs[0]}
    
    print(f"Found {len(verified)} locally verified repositories with SHA directories.")
    
    # Filter to only those in canonical manifest
    candidate_names = {c['full_name'] for c in candidates}
    repos_to_migrate = {name: info for name, info in verified.items() if name in candidate_names}
    print(f"Of those, {len(repos_to_migrate)} are in the canonical manifest and will be migrated")
    
    # Check which are already on cloud
    cloud_repos_dir = Path("/mnt/pythia-cloud/Pythia/raw/github/repositories")
    already_on_cloud = set()
    if cloud_repos_dir.exists():
        for d in cloud_repos_dir.iterdir():
            if d.is_dir():
                parts = d.name.split('__', 1)
                if len(parts) == 2:
                    owner, repo = parts
                    full_name = f"{owner}/{repo}"
                    sha_dirs = [d for d in d.iterdir() if d.is_dir() and len(d.name) == 40 and all(c in '0123456789abcdef' for c in d.name)]
                    if sha_dirs:
                        already_on_cloud.add(full_name)
    
    print(f"Already on cloud: {len(already_on_cloud)}")
    
    # Filter to only those not yet on cloud
    to_migrate = {name: info for name, info in verified.items() if name in candidate_names and name not in already_on_cloud}
    print(f"Need to migrate: {len(to_migrate)}")
    
    if not to_migrate:
        print("Nothing to migrate!")
        sys.exit(0)
    
    if not args.yes:
        confirm = input(f"Migrate {len(to_migrate)} repositories? [y/N]: ").strip().lower()
        if confirm != 'y':
            print("Aborted.")
            sys.exit(0)
    
    # Migrate
    results = []
    for full_name, info in to_migrate.items():
        owner, repo = full_name.split('/')
        repo_key = f"{owner}__{repo}"
        sha = info['sha']
        
        src = Path(f"/home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline/data/raw/github/repositories/{repo_key}/{sha}")
        dst = Path(f"/mnt/pythia-cloud/Pythia/raw/github/repositories/{repo_key}/{sha}")
        
        if not src.exists():
            print(f"  SKIP {full_name}: source not found")
            continue
        
        print(f"Migrating {full_name} (SHA: {sha[:12]})...")
        dst.parent.mkdir(parents=True, exist_ok=True)
        
        def ignore_git(dir, contents):
            return ['.git', '.github', '.gitignore', '.gitattributes', '.gitmodules', '.gitkeep', '.gitlab', '.github', '.gitlab-ci.yml']
        
        try:
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns('.git', '.github', '.gitignore', '.gitattributes', '.gitmodules', '.gitkeep', '.gitlab', '.github', '.gitlab-ci.yml'))
            print(f"  ✓ Copied to cloud")
        except Exception as e:
            print(f"  ✗ Failed: {e}")
            continue
    
    print("\nMigration complete!")


if __name__ == "__main__":
    main()