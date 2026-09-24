#!/usr/bin/env python3
"""
Acquire a single GitHub repository as a CLEAN SOURCE SNAPSHOT at an exact commit.

This script implements the CORRECT acquisition architecture with RESUMABILITY:
1. Loads the canonical manifest (github_candidates_v1.jsonl)
2. Finds the first QUEUED repository (or resumable TIMEOUT_RETRYABLE)
3. Marks it FETCHING/RESUME_FETCHING immediately (writes manifest update)
4. Uses persistent local Git cache at data/raw/github/repositories/<owner>__<repo>/
5. Fetches/checks out the EXACT commit SHA from manifest (resuming if needed)
6. Verifies HEAD == expected SHA
7. Creates a CLEAN SOURCE SNAPSHOT incrementally (excludes .git/, .github/, .git* files)
8. Verifies: no forbidden Git metadata, commit SHA matches, file count > 0, total bytes > 1000
9. Creates deterministic manifest with file hashes (resuming if needed)
10. Atomically moves to final location: /mnt/pythia-cloud/Pythia/raw/github/<owner>__<repo>/<commit_sha>/
11. Verifies destination
12. ONLY THEN marks ACQUIRED in manifest

State machine states:
QUEUED, FETCHING, RESUME_FETCHING, CHECKOUT, SNAPSHOTTING, RESUME_SNAPSHOTTING, 
VERIFYING, PROMOTING, ACQUIRED, FAILED, TIMEOUT_RETRYABLE, TIMEOUT_PERMANENT, SKIPPED

Rules:
- ACQUIRED is only written after filesystem verification passes.
- Manifest is the source of truth for state.
- Filesystem is the source of truth for data.
- NEVER copy .git/ or any .git* metadata
- Exact commit SHA from manifest MUST be acquired
- Local Git cache and partial snapshots persist across invocations
- Time budget: 240s max per invocation (60s buffer for 300s wall-clock)
"""

import json
import os
import shutil
import subprocess
import sys
import time
import hashlib
import signal
from pathlib import Path
from typing import Optional, List, Dict, Any

# Ensure we can import config
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import DATA_ROOT, RAW_DIR

# Configuration
GITHUB_RAW_DIR = Path(os.environ.get("PYTHIA_DATA_ROOT", "/mnt/pythia-cloud/Pythia")) / "raw" / "github"
MANIFEST_PATH = Path("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl")
INPROGRESS_BASE = Path("/mnt/pythia-cloud/Pythia/raw/github/.inprogress")
SNAPSHOT_TEMP_BASE = Path("/mnt/pythia-cloud/Pythia/raw/github/.snapshots")
# Persistent local Git cache (survives timeouts)
LOCAL_GIT_CACHE_BASE = Path("/home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline/data/raw/github/repositories")
# Temporary local snapshot storage (for in-progress snapshots)
LOCAL_GIT_TEMP_BASE = Path("/home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline/data/raw/github/.snapshots_temp")
# Time budgets
MAX_INVOCATION_SECONDS = 240  # Hard limit per invocation (leaves 60s buffer)
FETCH_TIMEOUT_SECONDS = 120
SNAPSHOT_TIMEOUT_SECONDS = 60
VERIFY_TIMEOUT_SECONDS = 30
# Retry policy
# Increased to allow large snapshots to complete across multiple invocations
# At ~10-50 KB/s, an 11.6 MB snapshot needs ~4-5 invocations of 240s each
MAX_RETRIES = 20

# State machine states
QUEUED = "QUEUED"
FETCHING = "FETCHING"
RESUME_FETCHING = "RESUME_FETCHING"
CHECKOUT = "CHECKOUT"
SNAPSHOTTING = "SNAPSHOTTING"
RESUME_SNAPSHOTTING = "RESUME_SNAPSHOTTING"
VERIFYING = "VERIFYING"
PROMOTING = "PROMOTING"
ACQUIRED = "ACQUIRED"
FAILED = "FAILED"
TIMEOUT_RETRYABLE = "TIMEOUT_RETRYABLE"
TIMEOUT_PERMANENT = "TIMEOUT_PERMANENT"
SKIPPED = "SKIPPED"

VALID_STATES = {
    QUEUED, FETCHING, RESUME_FETCHING, CHECKOUT, 
    SNAPSHOTTING, RESUME_SNAPSHOTTING, VERIFYING, PROMOTING,
    ACQUIRED, FAILED, TIMEOUT_RETRYABLE, TIMEOUT_PERMANENT, SKIPPED
}

# Files/directories to EXCLUDE from clean snapshot
EXCLUDE_PATTERNS = {
    '.git', '.github', '.gitignore', '.gitattributes', 
    '.gitmodules', '.gitkeep', '.gitlab', '.gitlab-ci.yml',
}

EXCLUDE_PREFIXES = ['.git']

# Global invocation start time for time budget enforcement
INVOCATION_START_TIME = time.time()


def load_manifest(manifest_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load the canonical manifest."""
    if manifest_path is None:
        manifest_path = Path("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl")
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found at {manifest_path}")
    with open(manifest_path, 'r') as f:
        return [json.loads(line) for line in f if line.strip()]


def save_manifest(candidates: List[Dict[str, Any]], manifest_path: Optional[Path] = None) -> None:
    """Write the manifest back atomically."""
    if manifest_path is None:
        manifest_path = Path("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl")
    tmp_path = Path(str(manifest_path) + ".tmp")
    with open(tmp_path, 'w') as f:
        for c in candidates:
            f.write(json.dumps(c, sort_keys=True) + '\n')
    os.rename(tmp_path, manifest_path)


def find_next_candidate(candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Find the next candidate to process: TIMEOUT_RETRYABLE (with retries left) first, then QUEUED."""
    # First priority: TIMEOUT_RETRYABLE with retries remaining (resume interrupted work)
    for c in candidates:
        if c.get('state') == 'TIMEOUT_RETRYABLE':
            attempt = c.get('attempt_count', 0)
            if attempt < MAX_RETRIES:
                return c
    # Second priority: QUEUED (new work)
    for c in candidates:
        if c.get('state') == 'QUEUED':
            return c
    return None


def update_candidate_state(candidates: List[Dict[str, Any]], full_name: str, new_state: str, **extra) -> None:
    """Update a candidate's state and any extra fields."""
    for c in candidates:
        if c['full_name'] == full_name:
            c['state'] = new_state
            for k, v in extra.items():
                c[k] = v
            break


def check_time_budget(minimum_remaining: int = 30) -> bool:
    """Check if we have at least minimum_remaining seconds left in the invocation budget."""
    elapsed = time.time() - INVOCATION_START_TIME
    remaining = MAX_INVOCATION_SECONDS - elapsed
    if remaining < minimum_remaining:
        print(f"Time budget exceeded: {elapsed:.1f}s elapsed, {remaining:.1f}s remaining (need {minimum_remaining}s)")
        return False
    return True


def cleanup_inprogress(inprogress_base: Optional[Path] = None, manifest_path: Optional[Path] = None):
    """Delete any .inprogress directories and reset their repos to QUEUED."""
    if inprogress_base is None:
        inprogress_dir = Path("/mnt/pythia-cloud/Pythia/raw/github/.inprogress")
    else:
        inprogress_dir = inprogress_base
    
    if not inprogress_dir.exists():
        return
    
    if manifest_path is None:
        manifest_path = Path("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl")
    
    if not inprogress_dir.exists():
        return
    
    candidates = load_manifest()
    
    for repo_dir in inprogress_dir.iterdir():
        if not repo_dir.is_dir():
            continue
        parts = repo_dir.name.split('__', 1)
        if len(parts) != 2:
            continue
        full_name = f"{parts[0]}/{parts[1]}"
        # Reset state to QUEUED in manifest
        for c in candidates:
            if c['full_name'] == full_name and c.get('state') in ('FETCHING', 'RESUME_FETCHING', 'CHECKOUT', 'SNAPSHOTTING', 'RESUME_SNAPSHOTTING', 'VERIFYING', 'PROMOTING'):
                c['state'] = 'QUEUED'
                break
        save_manifest(candidates)
        # Delete the inprogress directory
        shutil.rmtree(repo_dir, ignore_errors=True)
        print(f"Cleaned up incomplete .inprogress for {full_name}")


def prune_local_cache(max_shas: int = 3, manifest_path: Optional[Path] = None, cache_base: Optional[Path] = None) -> int:
    """
    Prune local Git cache directories that are not referenced by active acquisition states.
    
    Preserves caches for repositories in active states:
    QUEUED, TIMEOUT_RETRYABLE, FETCHING, RESUME_FETCHING, CHECKOUT, 
    SNAPSHOTTING, RESUME_SNAPSHOTTING, VERIFYING, PROMOTING, DOWNLOADING
    
    Only prunes caches that are demonstrably safe (not referenced by active states).
    Respects max_shas limit to avoid aggressive pruning.
    
    Returns number of cache directories pruned.
    """
    if manifest_path is None:
        manifest_path = Path("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl")
    if cache_base is None:
        cache_base = LOCAL_GIT_CACHE_BASE
    
    if not cache_base.exists():
        return 0
    
    candidates = load_manifest(manifest_path)
    
    # Active states that require local Git cache
    active_states = {
        'QUEUED', 'TIMEOUT_RETRYABLE', 'FETCHING', 'RESUME_FETCHING', 
        'CHECKOUT', 'SNAPSHOTTING', 'RESUME_SNAPSHOTTING', 
        'VERIFYING', 'PROMOTING', 'DOWNLOADING'
    }
    
    # Collect active repositories
    active_repos = set()
    for c in candidates:
        if c.get('state') in active_states:
            active_repos.add(f"{c['owner']}__{c['repo']}")
    
    # Find prunable cache directories
    prunable = []
    for repo_dir in cache_base.iterdir():
        if not repo_dir.is_dir():
            continue
        if repo_dir.name.startswith('.'):
            continue
        if repo_dir.name not in active_repos:
            # Additional safety: check if it's a valid Git repo
            git_dir = repo_dir / '.git'
            if git_dir.exists():
                prunable.append(repo_dir)
    
    # Sort by modification time (oldest first) for predictable pruning
    prunable.sort(key=lambda p: p.stat().st_mtime)
    
    # Prune up to max_shas
    pruned = 0
    for repo_dir in prunable[:max_shas]:
        try:
            shutil.rmtree(repo_dir, ignore_errors=True)
            print(f"Pruned local cache: {repo_dir.name}")
            pruned += 1
        except Exception as e:
            print(f"Failed to prune {repo_dir.name}: {e}")
    
    return pruned


def clone_repo_init(full_name: str, dest_dir: Path, timeout_seconds: int) -> None:
    """Initialize empty repo and add remote. Idempotent - safe to call on existing repo."""
    clone_url = f"https://github.com/{full_name}.git"
    try:
        # Check if already initialized
        git_dir = dest_dir / ".git"
        if git_dir.exists():
            # Verify remote URL matches
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=dest_dir,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0 and result.stdout.strip() == clone_url:
                print(f"  Repo already initialized with correct remote")
                return
            # Remote mismatch - update it
            subprocess.run(
                ["git", "remote", "set-url", "origin", clone_url],
                cwd=dest_dir,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10
            )
            print(f"  Updated remote URL")
            return
        
        # Initialize empty repo
        subprocess.run(
            ["git", "init", str(dest_dir)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30
        )
        # Add remote
        subprocess.run(
            ["git", "remote", "add", "origin", clone_url],
            cwd=dest_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Git init/remote add timed out after {timeout_seconds} seconds")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Git init/remote failed: {e.stderr.decode(errors='replace')[:200]}")


def get_local_repo_state(dest_dir: Path) -> Dict[str, Any]:
    """Inspect local repo to determine what's already fetched."""
    state = {
        'is_git_repo': False,
        'remote_url': None,
        'has_fetch_head': False,
        'fetch_head_sha': None,
        'current_branch': None,
        'head_sha': None,
    }
    
    git_dir = dest_dir / ".git"
    if not git_dir.exists():
        return state
    
    state['is_git_repo'] = True
    
    try:
        # Get remote URL
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=dest_dir,
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            state['remote_url'] = result.stdout.strip()
    except Exception:
        pass
    
    try:
        # Check FETCH_HEAD
        fetch_head = dest_dir / ".git" / "FETCH_HEAD"
        if fetch_head.exists():
            state['has_fetch_head'] = True
            result = subprocess.run(
                ["git", "rev-parse", "FETCH_HEAD"],
                cwd=dest_dir,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                state['fetch_head_sha'] = result.stdout.strip()
    except Exception:
        pass
    
    try:
        # Get current HEAD
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=dest_dir,
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            state['head_sha'] = result.stdout.strip()
    except Exception:
        pass
    
    return state


def fetch_exact_sha(full_name: str, dest_dir: Path, commit_sha: str, timeout_seconds: int, resume: bool = False) -> None:
    """Fetch the exact commit SHA from remote. Supports resume."""
    if not check_time_budget(60):
        raise TimeoutError("Insufficient time budget for fetch")
    
    try:
        if resume:
            # Check if we already have this commit
            state = get_local_repo_state(dest_dir)
            if state['fetch_head_sha'] == commit_sha:
                print(f"  Commit {commit_sha[:12]} already fetched")
                return
            # Try to fetch with --deepen if we have a shallow repo
            # But for exact SHA, we just fetch it directly
            print(f"  Resuming fetch for {commit_sha[:12]}...")
        
        # Fetch the specific commit with depth 1
        subprocess.run(
            ["git", "fetch", "--depth", "1", "origin", commit_sha],
            cwd=dest_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Git fetch timed out after {timeout_seconds} seconds")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors='replace')[:500]
        # Check if it's a "not found" error (commit doesn't exist or not reachable with depth=1)
        if "couldn't find remote ref" in stderr or "not found" in stderr.lower():
            # Try fetching with more depth
            print(f"  Commit not found with depth=1, trying deeper fetch...")
            try:
                subprocess.run(
                    ["git", "fetch", "--depth", "50", "origin", commit_sha],
                    cwd=dest_dir,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=timeout_seconds
                )
            except subprocess.CalledProcessError as e2:
                raise RuntimeError(f"Git fetch failed: {e2.stderr.decode(errors='replace')[:500]}")
        else:
            raise RuntimeError(f"Git fetch failed: {stderr}")


def get_latest_commit_sha(dest_dir: Path, branch: str, timeout_seconds: int) -> str:
    """Fetch the latest commit SHA for a branch."""
    if not check_time_budget(60):
        raise TimeoutError("Insufficient time budget for fetch")
    
    try:
        # Check if we already have this branch fetched
        state = get_local_repo_state(dest_dir)
        if state['fetch_head_sha']:
            # Verify it's the right branch by checking remote branches
            try:
                result = subprocess.run(
                    ["git", "ls-remote", "origin", branch],
                    cwd=dest_dir,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0 and result.stdout.strip():
                    # Parse the SHA from ls-remote output
                    remote_sha = result.stdout.strip().split('\t')[0]
                    if state['fetch_head_sha'] == remote_sha:
                        print(f"  Branch {branch} already at latest: {remote_sha[:12]}")
                        return remote_sha
            except Exception:
                pass
        
        # Fetch the branch
        subprocess.run(
            ["git", "fetch", "--depth", "1", "origin", branch],
            cwd=dest_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds
        )
        # Get the commit SHA of FETCH_HEAD
        result = subprocess.run(
            ["git", "rev-parse", "FETCH_HEAD"],
            cwd=dest_dir,
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Git fetch branch timed out after {timeout_seconds} seconds")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Git fetch branch failed: {e.stderr.decode(errors='replace')[:500]}")


def verify_head_sha(dest_dir: Path, expected_sha: str) -> bool:
    """Verify that HEAD matches the expected commit SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=dest_dir,
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        actual_sha = result.stdout.strip()
        return actual_sha == expected_sha
    except subprocess.CalledProcessError:
        return False


def checkout_sha(dest_dir: Path, commit_sha: str) -> None:
    """Checkout the exact commit SHA in detached HEAD mode."""
    try:
        # Check if already at correct commit
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=dest_dir,
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0 and result.stdout.strip() == commit_sha:
            print(f"  Already at commit {commit_sha[:12]}")
            return
        
        subprocess.run(
            ["git", "checkout", "--detach", commit_sha],
            cwd=dest_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Git checkout failed: {e.stderr.decode(errors='replace')[:200]}")


def should_exclude(path_part: str) -> bool:
    """Check if a path part should be excluded."""
    if path_part in EXCLUDE_PATTERNS:
        return True
    for prefix in EXCLUDE_PREFIXES:
        if path_part.startswith(prefix):
            return True
    return False


SNAPSHOT_PROGRESS_FILE = "SNAPSHOT_PROGRESS.json"


def create_clean_snapshot(source_dir: Path, dest_dir: Path, progress: Optional[Dict] = None, time_budget: int = 60) -> Dict[str, Any]:
    """
    Create a CLEAN source snapshot excluding .git/ and all .git* files.
    Supports resumability via progress dict.
    Returns metadata about the snapshot.
    """
    start_time = time.time()
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    # Load progress if provided
    if progress is None:
        progress = {'completed_files': [], 'file_hashes': [], 'file_count': 0, 'total_bytes': 0}
    
    completed_files = set(progress.get('completed_files', []))
    file_hashes = progress.get('file_hashes', [])
    file_count = progress.get('file_count', 0)
    total_bytes = progress.get('total_bytes', 0)
    
    # Collect all files to process
    all_files = []
    for entry in Path(source_dir).rglob('*'):
        if entry.is_file():
            rel_path = entry.relative_to(source_dir)
            should_exclude = False
            for part in rel_path.parts:
                if part in EXCLUDE_PATTERNS or part.startswith('.git'):
                    should_exclude = True
                    break
            if not should_exclude:
                all_files.append((entry, str(rel_path)))
    
    # Sort for deterministic order
    all_files.sort(key=lambda x: x[1])
    
    # Process files, skipping already completed
    for entry, rel_path_str in all_files:
        if not check_time_budget(10):
            # Save progress and return partial
            progress['completed_files'] = list(completed_files)
            progress['file_hashes'] = file_hashes
            progress['file_count'] = file_count
            progress['total_bytes'] = total_bytes
            save_snapshot_progress(dest_dir, progress)
            return {
                'file_count': file_count,
                'total_bytes': total_bytes,
                'files': file_hashes,
                'partial': True,
                'progress': progress
            }
        
        if rel_path_str in completed_files:
            continue
        
        # Copy file
        dest_file = Path(dest_dir) / rel_path_str
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry, dest_file)
        
        # Compute hash for manifest
        file_hash = hashlib.sha256()
        with open(entry, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                file_hash.update(chunk)
        
        file_hashes.append({
            'path': rel_path_str,
            'sha256': file_hash.hexdigest(),
            'size': entry.stat().st_size
        })
        
        completed_files.add(rel_path_str)
        file_count += 1
        total_bytes += entry.stat().st_size
    
    # All done - clean up progress file
    progress_path = dest_dir / SNAPSHOT_PROGRESS_FILE
    if progress_path.exists():
        progress_path.unlink()
    
    return {
        'file_count': file_count,
        'total_bytes': total_bytes,
        'files': file_hashes,
        'partial': False
    }


def save_snapshot_progress(snapshot_dir: Path, progress: Dict) -> None:
    """Save snapshot progress to file."""
    progress_path = snapshot_dir / SNAPSHOT_PROGRESS_FILE
    with open(progress_path, 'w') as f:
        json.dump(progress, f, sort_keys=True)


def load_snapshot_progress(snapshot_dir: Path) -> Optional[Dict]:
    """Load snapshot progress from file."""
    progress_path = snapshot_dir / SNAPSHOT_PROGRESS_FILE
    if not progress_path.exists():
        return None
    try:
        with open(progress_path, 'r') as f:
            return json.load(f)
    except Exception:
        return None


def create_snapshot_manifest(snapshot_dir: Path, commit_sha: str, full_name: str) -> Dict[str, Any]:
    """Create a deterministic manifest for the snapshot. Uses cached hashes if available."""
    # Try to load hashes from progress file first
    progress = load_snapshot_progress(snapshot_dir)
    if progress and not progress.get('partial', False) and progress.get('file_hashes'):
        file_hashes = progress['file_hashes']
    else:
        # Fallback: compute all hashes
        file_hashes = []
        for entry in Path(snapshot_dir).rglob('*'):
            if entry.is_file() and entry.name != 'SNAPSHOT_MANIFEST.json' and entry.name != SNAPSHOT_PROGRESS_FILE:
                file_hash = hashlib.sha256()
                with open(entry, 'rb') as f:
                    for chunk in iter(lambda: f.read(8192), b''):
                        file_hash.update(chunk)
                
                rel_path = entry.relative_to(snapshot_dir)
                file_hashes.append({
                    'path': str(rel_path),
                    'sha256': file_hash.hexdigest(),
                    'size': entry.stat().st_size
                })
    
    # Sort by path for determinism
    file_hashes.sort(key=lambda x: x['path'])
    
    # Create manifest content for hash
    manifest_content = json.dumps({
        'commit_sha': commit_sha,
        'full_name': full_name,
        'files': file_hashes,
        'total_files': len(file_hashes),
        'total_bytes': sum(f['size'] for f in file_hashes),
    }, sort_keys=True)
    manifest_hash = hashlib.sha256(manifest_content.encode()).hexdigest()
    
    # Acquisition timestamp
    acquired_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    
    return {
        'commit_sha': commit_sha,
        'full_name': full_name,
        'file_count': len(file_hashes),
        'total_files': len(file_hashes),
        'total_bytes': sum(f['size'] for f in file_hashes),
        'manifest_hash': manifest_hash,
        'files': file_hashes,
        'acquired_at': acquired_at,
        'pipeline_version': '1.0',
    }


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


def has_forbidden_git_metadata(path: Path) -> list:
    """
    Check for forbidden Git metadata in the snapshot.
    Returns list of offending paths (relative to snapshot root).
    """
    forbidden = []
    for entry in path.rglob('*'):
        name = entry.name
        if name == '.git' and entry.is_dir():
            forbidden.append(str(entry.relative_to(path)))
        elif name == '.github' and entry.is_dir():
            forbidden.append(str(entry.relative_to(path)))
        elif name.startswith('.git'):
            forbidden.append(str(entry.relative_to(path)))
    return forbidden


def verify_snapshot(snapshot_dir: Path, expected_sha: str) -> tuple:
    """Verify snapshot against expected commit SHA and clean-snapshot invariant."""
    # Check directory exists
    if not snapshot_dir.exists() or not snapshot_dir.is_dir():
        return False, "Snapshot directory does not exist"
    
    # Check for .git directory (should NOT exist)
    git_dir = snapshot_dir / '.git'
    if git_dir.exists():
        return False, "Snapshot contains .git directory (should be excluded)"
    
    # Check for .github directory (should NOT exist)
    github_dir = snapshot_dir / '.github'
    if github_dir.exists():
        return False, "Snapshot contains .github directory (should be excluded)"
    
    # Check for .git* files
    for entry in Path(snapshot_dir).rglob('*'):
        if entry.is_file():
            name = entry.name
            if name.startswith('.git'):
                return False, f"Snapshot contains .git file: {name}"
    
    # Verify commit SHA matches directory name (additional check)
    if snapshot_dir.name != expected_sha:
        return False, f"Snapshot directory name '{snapshot_dir.name}' != expected SHA '{expected_sha}'"
    
    # Verify has files and size
    file_count = 0
    total_bytes = 0
    for entry in Path(snapshot_dir).rglob('*'):
        if entry.is_file():
            try:
                total_bytes += entry.stat().st_size
                file_count += 1
            except OSError:
                pass
    
    return file_count > 0 and total_bytes > 1000, "OK"


def verify_snapshot_manifest(snapshot_dir: Path, expected_sha: str) -> tuple:
    """
    Verify the SNAPSHOT_MANIFEST.json exists and is internally consistent.
    Returns (ok, message).
    """
    manifest_path = snapshot_dir / "SNAPSHOT_MANIFEST.json"
    if not manifest_path.exists():
        return False, "SNAPSHOT_MANIFEST.json not found"
    
    try:
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON in manifest: {e}"
    
    # Verify manifest contains expected fields
    required_fields = ['commit_sha', 'full_name', 'file_count', 'total_bytes', 'manifest_hash', 'files']
    for field in required_fields:
        if field not in manifest:
            return False, f"Manifest missing required field: {field}"
    
    # Verify commit SHA matches
    if manifest.get('commit_sha') != expected_sha:
        return False, f"Manifest commit_sha '{manifest.get('commit_sha')}' != expected '{expected_sha}'"
    
    # Verify file count matches
    actual_files = [f for f in snapshot_dir.rglob('*') if f.is_file() and f.name != 'SNAPSHOT_MANIFEST.json']
    if manifest.get('file_count') != len(actual_files):
        return False, f"Manifest file_count {manifest.get('file_count')} != actual {len(actual_files)}"
    
    # Verify total bytes
    actual_bytes = sum(f.stat().st_size for f in actual_files)
    if manifest.get('total_bytes') != actual_bytes:
        return False, f"Manifest total_bytes {manifest.get('total_bytes')} != actual {actual_bytes}"
    
    # Verify each file hash
    for file_entry in manifest.get('files', []):
        file_path = snapshot_dir / file_entry['path']
        if not file_path.exists():
            return False, f"Manifest references missing file: {file_entry['path']}"
        
        # Compute hash
        file_hash = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                file_hash.update(chunk)
        computed_hash = file_hash.hexdigest()
        
        if computed_hash != file_entry['sha256']:
            return False, f"Hash mismatch for {file_entry['path']}: expected {file_entry['sha256']}, got {computed_hash}"
        
        if file_entry['size'] != file_path.stat().st_size:
            return False, f"Size mismatch for {file_entry['path']}: expected {file_entry['size']}, got {file_path.stat().st_size}"
    
    # Verify manifest_hash determinism
    manifest_content = json.dumps({
        'commit_sha': manifest['commit_sha'],
        'full_name': manifest['full_name'],
        'files': manifest['files'],
        'total_files': manifest['total_files'],
        'total_bytes': manifest['total_bytes'],
    }, sort_keys=True)
    computed_manifest_hash = hashlib.sha256(manifest_content.encode()).hexdigest()
    if computed_manifest_hash != manifest.get('manifest_hash'):
        return False, f"Manifest hash mismatch: expected {manifest.get('manifest_hash')}, got {computed_manifest_hash}"
    
    return True, "OK"


def acquire_one() -> int:
    """
    Acquire a single repository with full resumability.
    Returns: 1 = success, 0 = no work, -1 = failure, -2 = timeout (retryable)
    
    Git operations use persistent local cache at LOCAL_GIT_CACHE_BASE.
    Snapshot creation is incremental with progress tracking.
    Time budget: 240s max per invocation.
    """
    # Clean up any leftover .inprogress directories (cloud only)
    cleanup_inprogress()

    # Load manifest
    candidates = load_manifest()
    candidate = find_next_candidate(candidates)
    if not candidate:
        print("No QUEUED or TIMEOUT_RETRYABLE repositories left.")
        return 0

    full_name = candidate['full_name']
    expected_sha = candidate.get('commit_sha')
    default_branch = candidate.get('default_branch', 'main')
    attempt_count = candidate.get('attempt_count', 0)
    is_resume = candidate.get('state') == 'TIMEOUT_RETRYABLE'
    
    print(f"Acquiring {full_name} (branch: {default_branch}, attempt: {attempt_count + 1}/{MAX_RETRIES}, resume: {is_resume})...")

    # Increment attempt count
    attempt_count += 1
    update_candidate_state(candidates, full_name, 'FETCHING' if not is_resume else 'RESUME_FETCHING', 
                           attempt_count=attempt_count, 
                           last_attempt_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    save_manifest(candidates)

    # Prepare paths - PERSISTENT local Git cache
    local_git_dir = LOCAL_GIT_CACHE_BASE / f"{candidate['owner']}__{candidate['repo']}"
    local_git_dir.mkdir(parents=True, exist_ok=True)
    
    # Cloud paths
    inprogress_dir = Path("/mnt/pythia-cloud/Pythia/raw/github/.inprogress") / f"{candidate['owner']}__{candidate['repo']}"
    inprogress_dir.mkdir(parents=True, exist_ok=True)
    final_repo_dir = Path("/mnt/pythia-cloud/Pythia/raw/github") / f"{candidate['owner']}__{candidate['repo']}"
    final_repo_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Initialize repo and add remote (LOCAL) - idempotent
        print(f"Initializing repo for {full_name} (local)...")
        update_candidate_state(candidates, full_name, 'FETCHING' if not is_resume else 'RESUME_FETCHING')
        save_manifest(candidates)
        clone_repo_init(full_name, local_git_dir, 30)

        # If manifest doesn't have commit_sha, fetch latest for default branch (LOCAL)
        if not expected_sha:
            if not check_time_budget(60):
                raise TimeoutError("Insufficient time budget for branch fetch")
            print(f"Fetching latest commit for branch {default_branch} (local)...")
            expected_sha = get_latest_commit_sha(local_git_dir, default_branch, FETCH_TIMEOUT_SECONDS)
            print(f"Latest commit SHA: {expected_sha}")
            # Update manifest with the fetched SHA
            update_candidate_state(candidates, full_name, 'FETCHING' if not is_resume else 'RESUME_FETCHING', commit_sha=expected_sha)
            save_manifest(candidates)

        # Fetch the EXACT commit SHA (LOCAL) - with resume support
        if not check_time_budget(60):
            raise TimeoutError("Insufficient time budget for SHA fetch")
        print(f"Fetching exact commit {expected_sha[:12]} (local)...")
        fetch_exact_sha(full_name, local_git_dir, expected_sha, FETCH_TIMEOUT_SECONDS, resume=is_resume)

        # Checkout the exact SHA (LOCAL)
        if not check_time_budget(30):
            raise TimeoutError("Insufficient time budget for checkout")
        print(f"Checking out {expected_sha[:12]} (local)...")
        update_candidate_state(candidates, full_name, 'CHECKOUT')
        save_manifest(candidates)
        checkout_sha(local_git_dir, expected_sha)

        # CRITICAL: Verify HEAD matches expected SHA (LOCAL)
        print(f"Verifying HEAD matches expected SHA (local)...")
        if not verify_head_sha(local_git_dir, expected_sha):
            raise RuntimeError(f"HEAD SHA mismatch: expected {expected_sha}, got different commit")
        print(f"HEAD verified: {expected_sha[:12]}")

        # Verify the cloned repo has content (LOCAL)
        if not verify_repo(local_git_dir):
            raise RuntimeError("Repository verification failed: no files or size <= 1000 bytes")

        # Create clean snapshot (LOCAL) - INCREMENTAL with progress tracking
        local_snapshot_dir = LOCAL_GIT_TEMP_BASE / expected_sha
        local_snapshot_dir.mkdir(parents=True, exist_ok=True)
        
        # Load existing snapshot progress if resuming
        snapshot_progress = None
        if is_resume:
            snapshot_progress = load_snapshot_progress(local_snapshot_dir)
            if snapshot_progress:
                print(f"  Resuming snapshot from {len(snapshot_progress.get('completed_files', []))} completed files")
        
        print("Creating clean snapshot (local)...")
        update_candidate_state(candidates, full_name, 'SNAPSHOTTING' if not is_resume else 'RESUME_SNAPSHOTTING')
        save_manifest(candidates)
        
        # Check time budget before snapshot
        if not check_time_budget(30):
            raise TimeoutError("Insufficient time budget for snapshot")
        
        snapshot_info = create_clean_snapshot(local_git_dir, local_snapshot_dir, snapshot_progress, time_budget=SNAPSHOT_TIMEOUT_SECONDS)
        
        if snapshot_info.get('partial'):
            # Snapshot incomplete - save state and return timeout
            print(f"Snapshot partial: {snapshot_info['file_count']} files, {snapshot_info['total_bytes']} bytes - will resume")
            update_candidate_state(candidates, full_name, 'TIMEOUT_RETRYABLE', 
                                   commit_sha=expected_sha,
                                   snapshot_progress=snapshot_info.get('progress'),
                                   last_stage='SNAPSHOTTING',
                                   error="Snapshot incomplete - time budget exceeded")
            save_manifest(candidates)
            return -2  # timeout, retryable

        print(f"Local snapshot created: {snapshot_info['file_count']} files, {snapshot_info['total_bytes']} bytes")

        # Verify snapshot for clean-snapshot invariant (LOCAL)
        print("Verifying clean snapshot (local)...")
        ok, msg = verify_snapshot(local_snapshot_dir, expected_sha)
        if not ok:
            raise RuntimeError(f"Clean snapshot verification failed: {msg}")
        print(f"Clean snapshot verified: {msg}")

        # Create snapshot manifest (LOCAL) - uses cached hashes
        print("Creating snapshot manifest (local)...")
        snapshot_manifest = create_snapshot_manifest(local_snapshot_dir, expected_sha, full_name)
        manifest_path = local_snapshot_dir / "SNAPSHOT_MANIFEST.json"
        with open(manifest_path, 'w') as f:
            json.dump(snapshot_manifest, f, indent=2, sort_keys=True)

        # Verify snapshot manifest (LOCAL)
        print("Verifying snapshot manifest (local)...")
        ok, msg = verify_snapshot_manifest(local_snapshot_dir, expected_sha)
        if not ok:
            raise RuntimeError(f"Snapshot manifest verification failed: {msg}")
        print(f"Snapshot manifest verified: {msg}")

        # Copy clean snapshot to cloud (.snapshots temp directory)
        if not check_time_budget(60):
            raise TimeoutError("Insufficient time budget for cloud copy")
        print("Copying clean snapshot to cloud...")
        cloud_snapshot_parent = Path("/mnt/pythia-cloud/Pythia/raw/github/.snapshots") / f"{candidate['owner']}__{candidate['repo']}"
        cloud_snapshot_dir = cloud_snapshot_parent / expected_sha
        if cloud_snapshot_dir.exists():
            shutil.rmtree(cloud_snapshot_dir)
        cloud_snapshot_parent.mkdir(parents=True, exist_ok=True)
        
        # Use incremental copy with time budget
        copy_snapshot_to_cloud(local_snapshot_dir, cloud_snapshot_dir, time_budget=60)
        print(f"Copied to cloud: {cloud_snapshot_dir}")

        # Verify again on cloud
        print("Verifying snapshot on cloud...")
        ok, msg = verify_snapshot(cloud_snapshot_dir, expected_sha)
        if not ok:
            raise RuntimeError(f"Cloud snapshot verification failed: {msg}")
        ok, msg = verify_snapshot_manifest(cloud_snapshot_dir, expected_sha)
        if not ok:
            raise RuntimeError(f"Cloud snapshot manifest verification failed: {msg}")
        print(f"Cloud verification passed: {msg}")

        # Prepare final destination on cloud
        if not check_time_budget(10):
            raise TimeoutError("Insufficient time budget for promotion")
        final_sha_dir = Path("/mnt/pythia-cloud/Pythia/raw/github") / f"{candidate['owner']}__{candidate['repo']}" / expected_sha
        if final_sha_dir.exists():
            shutil.rmtree(final_sha_dir)
        final_sha_dir.parent.mkdir(parents=True, exist_ok=True)

        # Atomic move on cloud
        print(f"Moving to final location on cloud...")
        update_candidate_state(candidates, full_name, 'PROMOTING')
        save_manifest(candidates)
        os.rename(cloud_snapshot_dir, final_sha_dir)
        print(f"Moved to final location: {final_sha_dir}")

        # Final verification on cloud
        print("Final filesystem verification on cloud...")
        ok, msg = verify_snapshot(final_sha_dir, expected_sha)
        if not ok:
            raise RuntimeError(f"Final verification failed: {msg}")
        ok, msg = verify_snapshot_manifest(final_sha_dir, expected_sha)
        if not ok:
            raise RuntimeError(f"Final manifest verification failed: {msg}")
        print(f"Final verification passed: {msg}")

        # Update manifest to ACQUIRED
        update_candidate_state(candidates, full_name, 'ACQUIRED',
                               commit_sha=expected_sha,
                               cloud_path=str(final_sha_dir),
                               acquired_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                               attempt_count=attempt_count)
        save_manifest(candidates)
        print(f"Successfully acquired {full_name} (SHA: {expected_sha})")
        return 1

    except TimeoutError as e:
        print(f"Timeout acquiring {full_name}: {e}")
        # Determine if retryable based on attempt count
        if attempt_count < MAX_RETRIES:
            update_candidate_state(candidates, full_name, 'TIMEOUT_RETRYABLE', 
                                   commit_sha=expected_sha,
                                   attempt_count=attempt_count,
                                   last_error=str(e),
                                   last_stage=candidate.get('state', 'UNKNOWN'))
        else:
            update_candidate_state(candidates, full_name, 'TIMEOUT_PERMANENT', 
                                   commit_sha=expected_sha,
                                   attempt_count=attempt_count,
                                   last_error=str(e),
                                   last_stage=candidate.get('state', 'UNKNOWN'))
        save_manifest(candidates)
        return -2
    except Exception as e:
        print(f"Failed to acquire {full_name}: {e}")
        update_candidate_state(candidates, full_name, 'FAILED', 
                               commit_sha=expected_sha,
                               attempt_count=attempt_count,
                               error=str(e))
        save_manifest(candidates)
        return -1
    finally:
        # IMPORTANT: Do NOT delete local Git cache - it's our resumable state!
        # Only clean up the cloud .inprogress and .snapshots temp dirs
        inprogress_dir = Path("/mnt/pythia-cloud/Pythia/raw/github/.inprogress") / f"{candidate['owner']}__{candidate['repo']}"
        if Path(inprogress_dir).exists():
            shutil.rmtree(inprogress_dir, ignore_errors=True)
        # Also clean up snapshot temp dir on cloud if it exists
        if expected_sha:
            cloud_snapshot_dir = Path("/mnt/pythia-cloud/Pythia/raw/github/.snapshots") / f"{candidate['owner']}__{candidate['repo']}" / expected_sha
            if cloud_snapshot_dir.exists():
                shutil.rmtree(cloud_snapshot_dir, ignore_errors=True)
        
        # Prune local cache (safe - only prunes unreferenced caches)
        try:
            pruned = prune_local_cache(max_shas=3)
            if pruned > 0:
                print(f"Pruned {pruned} local cache directories")
        except Exception as e:
            print(f"Cache pruning error (non-fatal): {e}")


def copy_snapshot_to_cloud(local_snapshot_dir: Path, cloud_snapshot_dir: Path, time_budget: int) -> None:
    """Copy snapshot to cloud using rclone for resumable chunked transfer.
    
    Uses rclone copy with --ignore-existing and --max-transfer for resumable chunked transfers.
    This bypasses the slow FUSE mount and uses rclone's native Google Drive API.
    Implements chunked transfer with --max-transfer to limit data per invocation,
    allowing large snapshots to complete across multiple invocations.
    Includes optimization to skip copy if remote is already complete.
    """
    if not check_time_budget(30):
        raise TimeoutError("Insufficient time budget for cloud copy preparation")
    
    # Ensure parent directory exists
    cloud_snapshot_dir.parent.mkdir(parents=True, exist_ok=True)
    
    # Check if rclone is available
    rclone_path = shutil.which("rclone")
    if not rclone_path:
        raise RuntimeError("rclone not found in PATH")
    
    # Build destination path for rclone remote
    try:
        rel_path = cloud_snapshot_dir.relative_to("/mnt/pythia-cloud")
    except ValueError:
        # Fallback if not under expected path
        rel_path = Path("Pythia/raw/github") / cloud_snapshot_dir.parent.name / cloud_snapshot_dir.name
    
    dest_remote = f"pythia:{rel_path}"
    
    # Check if remote already has all files (optimization to skip copy)
    print(f"  Checking remote snapshot state...")
    try:
        # Count files on remote (excluding manifest)
        remote_count_cmd = ["rclone", "ls", dest_remote]
        remote_count_result = subprocess.run(remote_count_cmd, capture_output=True, text=True, timeout=60)
        if remote_count_result.returncode == 0:
            remote_files = len([line for line in remote_count_result.stdout.strip().split('\n') if line.strip()])
            # Count local files (excluding manifest)
            local_files = len([f for f in local_snapshot_dir.rglob('*') if f.is_file() and f.name != 'SNAPSHOT_MANIFEST.json'])
            
            print(f"  Remote files: {remote_files}, Local files: {local_files}")
            
            if remote_files >= local_files:
                # Check manifest exists
                manifest_check = subprocess.run(["rclone", "lsf", f"{dest_remote}/SNAPSHOT_MANIFEST.json"], 
                                               capture_output=True, text=True, timeout=30)
                if manifest_check.returncode == 0:
                    print(f"  Remote snapshot already complete ({remote_files} files), skipping copy")
                    return
    except Exception as e:
        print(f"  Warning: Could not check remote state, proceeding with copy: {e}")
    
    print(f"  Copying snapshot to cloud via rclone...")
    print(f"  Source: {local_snapshot_dir}")
    print(f"  Destination: pythia:Pythia/raw/github/{cloud_snapshot_dir.parent.name}/{cloud_snapshot_dir.name}")
    
    # Build rclone command for resumable chunked copy
    # --ignore-existing: skip files that already exist on destination (resumable)
    # --checksum: verify checksums for integrity
    # --progress: show progress
    # --retries: retry on transient errors
    # --low-level-retries: retries for low-level operations
    # --transfers: number of parallel transfers
    # --drive-chunk-size: chunk size for Google Drive uploads
    # --fast-list: use recursive list for better performance
    # --max-transfer: limit data per invocation for chunked transfer
    # --ignore-existing: skip files that already exist (resumable)
    # --checksum: verify checksums for integrity
    
    # Calculate appropriate max-transfer size based on time budget
    # Estimate ~20 KB/s average transfer rate, so in 200s we can transfer ~4 MB
    # Use 4M as a safe chunk size that fits within the time budget
    max_transfer_size = "4M"
    
    # Build rclone command for chunked resumable copy
    cmd = [
        "rclone", "copy",
        str(local_snapshot_dir),
        dest_remote,
        "--ignore-existing",      # Skip files that already exist (resumable)
        "--checksum",             # Verify checksums
        "--progress",             # Show progress
        "--retries", "3",         # Retry on transient errors
        "--low-level-retries", "10",  # Low-level retries
        "--transfers", "4",       # Parallel transfers
        "--drive-chunk-size", "32M",  # Google Drive chunk size
        "--fast-list",            # Use fast listing
        "--stats", "10s",         # Progress update interval
        "--stats-one-line",       # Single line stats
        "--log-level", "INFO",    # Log level
        "--max-transfer", max_transfer_size,  # Limit data per invocation for chunked transfer
    ]
    
    print(f"  Running rclone copy (chunked transfer, max 4M per invocation)...")
    print(f"  Command: {' '.join(cmd)}")
    
    # Run rclone with time budget awareness
    # We'll run it and monitor time budget
    start_time = time.time()
    
    # Use subprocess with timeout
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line buffered
        )
        
        # Monitor output and time budget
        last_progress_time = time.time()
        while True:
            # Check time budget - be more generous for transfer phase
            # Allow up to 30 seconds for cleanup/verification
            if not check_time_budget(30):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise TimeoutError("Time budget exceeded during rclone transfer")
            
            # Read output line by line
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                line = line.strip()
                if line:
                    # Print progress lines (rclone progress output)
                    if "Transferred:" in line or "Checks:" in line or "Elapsed time:" in line:
                        print(f"  {line}")
                    last_progress_time = time.time()
            
            # Small sleep to prevent busy loop
            time.sleep(0.1)
        
        return_code = process.wait()
        
        if return_code != 0:
            raise RuntimeError(f"rclone copy failed with return code {return_code}")
        
        print(f"  rclone copy completed in {time.time() - start_time:.1f}s")
        
    except subprocess.TimeoutExpired:
        raise TimeoutError("rclone copy timed out")
    except FileNotFoundError:
        raise RuntimeError("rclone not found")
    
    # Verify the cloud snapshot directory exists on the remote (bypass FUSE cache)
    if not check_time_budget(10):
        raise TimeoutError("Insufficient time budget for cloud verification")
    
    # Verify using rclone (bypasses FUSE cache)
    verify_cmd = ["rclone", "lsd", dest_remote]
    verify_result = subprocess.run(verify_cmd, capture_output=True, text=True, timeout=30)
    if verify_result.returncode != 0:
        raise RuntimeError(f"Cloud snapshot directory not created on remote: {dest_remote}")
    
    # Verify manifest exists on remote
    manifest_remote = f"{dest_remote}/SNAPSHOT_MANIFEST.json"
    manifest_check = subprocess.run(["rclone", "lsf", manifest_remote], capture_output=True, text=True, timeout=30)
    if manifest_check.returncode != 0:
        raise RuntimeError(f"SNAPSHOT_MANIFEST.json missing after cloud copy on remote: {manifest_remote}")
    
    print(f"  Cloud copy verified on remote")


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