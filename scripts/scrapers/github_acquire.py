#!/usr/bin/env python3
"""
GitHub Repository Acquisition Script

Acquires repositories using shallow clone (depth=1) with resumable rclone transfer.
Writes all artifacts to Google Drive mount at /mnt/pythia-cloud/Pythia.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

MANIFEST_PATH = Path("data/raw/github/manifests/github_candidates_v1.jsonl")
CLOUD_BASE = Path("/mnt/pythia-cloud/Pythia/raw/github")
LOCAL_REPO_BASE = Path("data/raw/github/repositories")
LOCAL_SNAPSHOT_TEMP = Path("data/raw/github/.snapshots_temp")
LOCAL_GIT_CACHE = Path("data/raw/github/repositories")
LOCAL_GIT_TEMP_BASE = Path("data/raw/github/.git_temp")

MAX_INVOCATION_SECONDS = 240
REPO_TIMEOUT = 180
SNAPSHOT_TIMEOUT = 60
VERIFY_TIMEOUT = 30
FETCH_TIMEOUT_SECONDS = 120
MAX_RETRIES = 20  # Increased to allow large snapshots to complete across invocations

QUEUE = "QUEUED"
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
LEGACY_ACQUIRED_UNVERIFIED = "LEGACY_ACQUIRED_UNVERIFIED"

VALID_STATES = {
    QUEUE, FETCHING, RESUME_FETCHING, CHECKOUT, SNAPSHOTTING, RESUME_SNAPSHOTTING,
    VERIFYING, PROMOTING, ACQUIRED, FAILED, TIMEOUT_RETRYABLE, TIMEOUT_PERMANENT,
    SKIPPED, LEGACY_ACQUIRED_UNVERIFIED
}

EXCLUDE_PATTERNS = {
    '.git', '.github', '.gitignore', '.gitattributes',
    '.gitmodules', '.gitkeep', '.gitlab', '.gitlab-ci.yml',
}

EXCLUDE_PREFIXES = ['.git']


def check_drive_mounted():
    """Verify Google Drive access. The pipeline transfers via rclone directly to
    the 'pythia:' remote, so we verify rclone connectivity rather than the FUSE
    mount (which may be stale/disconnected even when the remote is fine)."""
    try:
        result = subprocess.run(
            ["rclone", "lsd", "pythia:Pythia/"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print("Drive verified via rclone remote: pythia:Pythia")
            return
    except Exception as e:
        print(f"WARNING: rclone remote check failed: {e}")
    print("ERROR: rclone remote 'pythia:Pythia' not reachable")
    sys.exit(1)


EXCLUDE_PATTERNS = {
    '.git', '.github', '.gitignore', '.gitattributes',
    '.gitmodules', '.gitkeep', '.gitlab', '.gitlab-ci.yml',
}

EXCLUDE_PREFIXES = ['.git']

INVOCATION_START_TIME = time.time()
MAX_INVOCATION_SECONDS = 240


def check_time_budget(minimum_remaining: int = 30) -> bool:
    """Check if we have at least minimum_remaining seconds left."""
    elapsed = time.time() - INVOCATION_START_TIME
    remaining = MAX_INVOCATION_SECONDS - elapsed
    if remaining < minimum_remaining:
        print(f"Time budget exceeded: {elapsed:.1f}s elapsed, {remaining:.1f}s remaining (need {minimum_remaining}s)")
        return False
    return True


def load_manifest():
    with open(MANIFEST_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]


def save_manifest(candidates):
    # Atomic write: write to a temp file then rename, so a killed process can
    # never truncate/corrupt the authoritative manifest.
    tmp_path = Path(str(MANIFEST_PATH) + ".tmp")
    with open(tmp_path, 'w') as f:
        for c in candidates:
            f.write(json.dumps(c, sort_keys=True) + '\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, MANIFEST_PATH)


def find_next_candidate(candidates):
    """Select the next repository to process.

    Prefer TIMEOUT_RETRYABLE (in-progress, partially transferred) so that once a
    repository is started it is driven to completion before new work begins.
    Within each group prefer SMALL repos, then ascending size. The frozen
    manifest order is preserved; this only affects selection order.
    """
    def size_key(c):
        cat_order = {'SMALL': 0, 'MEDIUM': 1, 'ERROR': 2}.get(c.get('size_category', ''), 3)
        size = c.get('repo_size_kb') or 0
        return (cat_order, size)

    retryable = [
        c for c in candidates
        if c.get('state') == 'TIMEOUT_RETRYABLE' and c.get('attempt_count', 0) < MAX_RETRIES
    ]
    if retryable:
        return min(retryable, key=size_key)

    queued = [c for c in candidates if c.get('state') == 'QUEUED']
    if queued:
        return min(queued, key=size_key)

    return None


def update_state(candidates, full_name, new_state, **extra):
    for c in candidates:
        if c['full_name'] == full_name:
            c['state'] = new_state
            for k, v in extra.items():
                c[k] = v
            break
    save_manifest(candidates)


def cleanup_inprogress():
    """Clean up any stale .inprogress directories on cloud and local."""
    # Cloud .inprogress
    inprogress_dir = Path("/mnt/pythia-cloud/Pythia/raw/github/.inprogress")
    if inprogress_dir.exists():
        for item in inprogress_dir.iterdir():
            if item.is_dir():
                print(f"  Cleaning .inprogress: {item.name}")
                subprocess.run(['rm', '-rf', str(item)], check=False)

    # Local .inprogress
    local_repo_base = Path("data/raw/github/repositories")
    for item in local_repo_base.iterdir():
        if item.name == '.inprogress' or item.name.endswith('.inprogress'):
            print(f"  Cleaning local .inprogress: {item.name}")
            subprocess.run(['rm', '-rf', str(item)], check=False)


def clone_repo_init(full_name: str, dest_dir: Path, timeout: int = 30) -> None:
    """Initialize empty repo and add remote. Idempotent - safe to call on existing repo."""
    clone_url = f"https://github.com/{full_name}.git"
    try:
        # Check if already initialized
        git_dir = dest_dir / ".git"
        if git_dir.exists():
            # Verify remote URL matches
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=dest_dir, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip() == clone_url:
                print(f"  Repo already initialized with correct remote")
                return
            # Remote mismatch - update it
            subprocess.run(
                ["git", "remote", "set-url", "origin", clone_url],
                cwd=dest_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10
            )
            print(f"  Updated remote URL")
            return
        
        # Initialize empty repo
        subprocess.run(
            ["git", "init", str(dest_dir)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
        )
        # Add remote
        subprocess.run(
            ["git", "remote", "add", "origin", clone_url],
            cwd=dest_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Git init/remote add timed out after {timeout} seconds")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Git init/remote failed: {e.stderr.decode(errors='replace')[:200]}")


def get_local_repo_state(dest_dir: Path) -> dict:
    """Inspect local repo to determine what's already fetched."""
    state = {
        'is_git_repo': False,
        'remote_url': None,
        'has_fetch_head': False,
        'fetch_head_sha': None,
        'head_sha': None,
    }
    
    git_dir = dest_dir / ".git"
    if not git_dir.exists():
        return state
    
    state['is_git_repo'] = True
    
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=dest_dir, capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            state['remote_url'] = result.stdout.strip()
    except Exception:
        pass
    
    try:
        fetch_head = dest_dir / ".git" / "FETCH_HEAD"
        if fetch_head.exists():
            state['has_fetch_head'] = True
            result = subprocess.run(
                ["git", "rev-parse", "FETCH_HEAD"],
                cwd=dest_dir, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                state['fetch_head_sha'] = result.stdout.strip()
    except Exception:
        pass
    
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=dest_dir, capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            state['head_sha'] = result.stdout.strip()
    except Exception:
        pass
    
    return state


def get_latest_commit_sha(dest_dir: Path, branch: str, timeout: int = 120) -> str:
    """Fetch the latest commit SHA for a branch."""
    _clear_stale_git_locks(dest_dir)
    try:
        # Check if we already have this branch fetched
        state = get_local_repo_state(dest_dir)
        if state['has_fetch_head'] and state['fetch_head_sha']:
            # Verify it's the right branch by checking remote
            try:
                result = subprocess.run(
                    ["git", "ls-remote", "origin", branch],
                    cwd=dest_dir, capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0 and result.stdout.strip():
                    remote_sha = result.stdout.strip().split('\t')[0]
                    if state['fetch_head_sha'] == remote_sha:
                        print(f"  Branch {branch} already at latest: {remote_sha[:12]}")
                        return remote_sha
            except Exception:
                pass
        
        # Fetch the branch
        subprocess.run(
            ["git", "fetch", "--depth", "1", "origin", branch],
            cwd=dest_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
        )
        # Get the commit SHA of FETCH_HEAD
        result = subprocess.run(
            ["git", "rev-parse", "FETCH_HEAD"],
            cwd=dest_dir, capture_output=True, text=True, check=True, timeout=10
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Git fetch branch timed out after {timeout} seconds")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Git fetch branch failed: {e.stderr.decode(errors='replace')[:500]}")


def _clear_stale_git_locks(dest_dir: Path) -> None:
    """Remove stale git lock files left by a killed process, which would otherwise
    make subsequent git operations fail with 'File exists'."""
    git_dir = dest_dir / ".git"
    if not git_dir.exists():
        return
    for name in ("shallow.lock", "index.lock", "HEAD.lock"):
        lock = git_dir / name
        if lock.exists():
            try:
                lock.unlink()
            except OSError:
                pass


def fetch_exact_sha(full_name: str, dest_dir: Path, commit_sha: str, timeout: int = 120, resume: bool = False) -> None:
    """Fetch the exact commit SHA from remote. Supports resuming."""
    _clear_stale_git_locks(dest_dir)
    try:
        # Check if we already have this commit
        result = subprocess.run(
            ["git", "rev-parse", "FETCH_HEAD"],
            cwd=dest_dir, capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip() == commit_sha:
            print(f"  Commit {commit_sha[:12]} already fetched")
            return
        
        if resume:
            # Check if we already have this commit
            result = subprocess.run(
                ["git", "rev-parse", "FETCH_HEAD"],
                cwd=dest_dir, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip() == commit_sha:
                print(f"  Commit {commit_sha[:12]} already fetched")
                return
            # Try to fetch with --deepen if we have a shallow repo
            print(f"  Resuming fetch for {commit_sha[:12]}...")
        
        subprocess.run(
            ["git", "fetch", "--depth", "1", "origin", commit_sha],
            cwd=dest_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Git fetch timed out after {timeout} seconds")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors='replace')[:500]
        # If depth=1 failed, try deeper fetch
        if "couldn't find remote ref" in stderr or "not found" in stderr.lower():
            print(f"  Commit not found with depth=1, trying deeper fetch...")
            try:
                subprocess.run(
                    ["git", "fetch", "--depth", "50", "origin", commit_sha],
                    cwd=dest_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
                )
            except subprocess.CalledProcessError as e2:
                raise RuntimeError(f"Git fetch failed: {e2.stderr.decode(errors='replace')[:500]}")
        else:
            raise RuntimeError(f"Git fetch failed: {stderr[:500]}")


def checkout_sha(dest_dir: Path, commit_sha: str) -> None:
    """Checkout the exact commit SHA in detached HEAD mode."""
    try:
        # Check if already at correct commit
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=dest_dir, capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip() == commit_sha:
            print(f"  Already at commit {commit_sha[:12]}")
            return
        
        # Remove stale untracked files that would block a clean detached checkout,
        # then force the checkout. This is safe: the working tree is rebuilt from
        # the pinned commit immediately afterward.
        subprocess.run(
            ["git", "clean", "-fd"],
            cwd=dest_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60
        )
        subprocess.run(
            ["git", "checkout", "--detach", "-f", commit_sha],
            cwd=dest_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Git checkout failed: {e.stderr.decode(errors='replace')[:200]}")


def verify_head_sha(dest_dir: Path, expected_sha: str) -> bool:
    """Verify that HEAD matches the expected commit SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=dest_dir, capture_output=True, text=True, timeout=10
        )
        actual_sha = result.stdout.strip()
        return actual_sha == expected_sha
    except subprocess.CalledProcessError:
        return False


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


def should_exclude(path_part: str) -> bool:
    """Check if a path part should be excluded."""
    if path_part in EXCLUDE_PATTERNS:
        return True
    for prefix in EXCLUDE_PREFIXES:
        if path_part.startswith(prefix):
            return True
    return False


def load_snapshot_progress(snapshot_dir: Path) -> dict:
    """Load incremental snapshot progress from SNAPSHOT_PROGRESS.json if present.

    Returns the progress dict, or None if no usable progress exists.
    """
    progress_path = snapshot_dir / "SNAPSHOT_PROGRESS.json"
    if not progress_path.exists():
        return None
    try:
        with open(progress_path) as f:
            progress = json.load(f)
        if isinstance(progress, dict) and 'completed_files' in progress:
            return progress
    except Exception:
        pass
    return None


def create_clean_snapshot(source_dir: Path, dest_dir: Path, progress: dict = None) -> dict:
    """
    Create a CLEAN source snapshot excluding .git/ and all .git* files.
    Supports resumable copy via progress dict.
    Returns metadata about the snapshot.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    if progress is None:
        progress = {'completed_files': [], 'file_hashes': [], 'file_count': 0, 'total_bytes': 0}
    
    completed_files = set(progress.get('completed_files', []))
    file_hashes = progress.get('file_hashes', [])
    file_count = progress.get('file_count', 0)
    total_bytes = progress.get('total_bytes', 0)
    
    for entry in Path(source_dir).rglob('*'):
        if entry.is_file():
            rel_path = entry.relative_to(source_dir)
            should_exclude = False
            for part in rel_path.parts:
                if part in EXCLUDE_PATTERNS or part.startswith('.git'):
                    should_exclude = True
                    break
            if should_exclude:
                continue
            
            rel_path_str = str(rel_path)
            if rel_path_str in completed_files:
                continue
            
            # Copy file
            dest_file = Path(dest_dir) / rel_path_str
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry, dest_file)
            
            # Compute hash
            file_hash = hashlib.sha256()
            with open(entry, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    file_hash.update(chunk)
            
            rel_path_str = str(entry.relative_to(source_dir))
            file_hashes.append({
                'path': str(entry.relative_to(source_dir)),
                'sha256': file_hash.hexdigest(),
                'size': entry.stat().st_size
            })
            
            completed_files.add(rel_path_str)
            file_count += 1
            total_bytes += entry.stat().st_size
    
    return {
        'file_count': file_count,
        'total_bytes': total_bytes,
        'files': file_hashes,
        'partial': False,
        'progress': {
            'completed_files': list(completed_files),
            'file_hashes': file_hashes,
            'file_count': file_count,
            'total_bytes': total_bytes
        }
    }


def create_snapshot_manifest(snapshot_dir: Path, commit_sha: str, full_name: str) -> dict:
    """Create a deterministic manifest for the snapshot."""
    file_hashes = []
    total_bytes = 0
    
    for entry in Path(snapshot_dir).rglob('*'):
        if entry.is_file() and entry.name != 'SNAPSHOT_MANIFEST.json':
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
    
    file_hashes.sort(key=lambda x: x['path'])
    
    manifest_content = json.dumps({
        'commit_sha': commit_sha,
        'full_name': full_name,
        'files': file_hashes,
        'file_count': len(file_hashes),
        'total_bytes': sum(f['size'] for f in file_hashes),
    }, sort_keys=True)
    manifest_hash = hashlib.sha256(manifest_content.encode()).hexdigest()
    
    acquired_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    
    return {
        'commit_sha': commit_sha,
        'full_name': full_name,
        'file_count': len(file_hashes),
        'total_bytes': sum(f['size'] for f in file_hashes),
        'manifest_hash': manifest_hash,
        'files': file_hashes,
        'acquired_at': acquired_at,
        'pipeline_version': '1.0',
    }


def verify_snapshot(snapshot_dir: Path, expected_sha: str) -> tuple:
    """Verify snapshot against expected commit SHA and clean-snapshot invariant."""
    if not snapshot_dir.exists() or not snapshot_dir.is_dir():
        return False, "Snapshot directory does not exist"
    
    # Check for .git directory
    git_dir = snapshot_dir / '.git'
    if git_dir.exists():
        return False, "Snapshot contains .git directory (should be excluded)"
    
    # Check for .github directory
    github_dir = snapshot_dir / '.github'
    if github_dir.exists():
        return False, "Snapshot contains .github directory (should be excluded)"
    
    # Check for .git* files
    for entry in Path(snapshot_dir).rglob('*'):
        if entry.is_file():
            name = entry.name
            if name.startswith('.git'):
                return False, f"Snapshot contains .git file: {name}"
    
    # Verify commit SHA matches directory name
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
    
    if file_count == 0 or total_bytes <= 1000:
        return False, f"Snapshot has no files or size <= 1000 bytes"
    
    return True, "OK"


def verify_snapshot_manifest(snapshot_dir: Path, expected_sha: str) -> tuple:
    """Verify the SNAPSHOT_MANIFEST.json exists and is internally consistent."""
    manifest_path = snapshot_dir / "SNAPSHOT_MANIFEST.json"
    if not manifest_path.exists():
        return False, "SNAPSHOT_MANIFEST.json not found"
    
    try:
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON in manifest: {e}"
    
    required_fields = ['commit_sha', 'full_name', 'file_count', 'total_bytes', 'manifest_hash', 'files']
    for field in required_fields:
        if field not in manifest:
            return False, f"Manifest missing required field: {field}"
    
    if manifest.get('commit_sha') != expected_sha:
        return False, f"Manifest commit_sha '{manifest.get('commit_sha')}' != expected '{expected_sha}'"
    
    # Verify file count (manifest uses 'file_count' key)
    actual_files = [f for f in Path(snapshot_dir).rglob('*') if f.is_file() and f.name != 'SNAPSHOT_MANIFEST.json']
    if manifest.get('file_count') != len(actual_files):
        return False, f"Manifest file_count {manifest.get('file_count')} != actual {len(actual_files)}"
    
    # Verify total bytes
    actual_bytes = sum(f.stat().st_size for f in Path(snapshot_dir).rglob('*') if f.is_file() and f.name != 'SNAPSHOT_MANIFEST.json')
    if manifest.get('total_bytes') != actual_bytes:
        return False, f"Manifest total_bytes {manifest.get('total_bytes')} != actual {actual_bytes}"
    
    # Verify each file hash
    for file_entry in manifest.get('files', []):
        file_path = snapshot_dir / file_entry['path']
        if not file_path.exists():
            return False, f"Manifest references missing file: {file_entry['path']}"
        
        file_hash = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                file_hash.update(chunk)
        computed_hash = file_hash.hexdigest()
        
        if computed_hash != file_entry['sha256']:
            return False, f"Hash mismatch for {file_entry['path']}: expected {file_entry['sha256']}, got {computed_hash}"
        
        if file_entry['size'] != file_path.stat().st_size:
            return False, f"Size mismatch for {file_entry['path']}: expected {file_entry['size']}, got {file_path.stat().st_size}"
    
    # Verify manifest hash determinism
    manifest_content = json.dumps({
        'commit_sha': manifest['commit_sha'],
        'full_name': manifest['full_name'],
        'files': manifest['files'],
        'file_count': manifest['file_count'],
        'total_bytes': manifest['total_bytes'],
    }, sort_keys=True)
    computed_hash = hashlib.sha256(manifest_content.encode()).hexdigest()
    if computed_hash != manifest.get('manifest_hash'):
        return False, f"Manifest hash mismatch: expected {manifest.get('manifest_hash')}, got {computed_hash}"
    
    return True, "OK"


def copy_snapshot_to_cloud(local_snapshot_dir: Path, cloud_snapshot_dir: Path, time_budget: int) -> None:
    """Copy snapshot to cloud using rclone for resumable transfer.

    Uploads to the .snapshots staging area on the remote. Uses --ignore-existing
    so that already-uploaded files are skipped, making the transfer resumable
    across invocations. rclone uploads each file atomically, so an existing file
    on the destination is always complete.
    """
    if not check_time_budget(30):
        raise TimeoutError("Insufficient time budget for cloud copy preparation")
    
    # Check if rclone is available
    rclone_path = shutil.which("rclone")
    if not rclone_path:
        raise RuntimeError("rclone not found in PATH")
    
    # Build the rclone remote destination path.
    # cloud_snapshot_dir is an absolute FUSE path like:
    #   /mnt/pythia-cloud/Pythia/raw/github/.snapshots/<owner>__<repo>/<sha>
    # The rclone remote 'pythia:' maps to /mnt/pythia-cloud, so the relative
    # path preserves the .snapshots staging directory.
    try:
        rel_path = cloud_snapshot_dir.relative_to("/mnt/pythia-cloud")
    except ValueError:
        rel_path = Path("Pythia/raw/github/.snapshots") / cloud_snapshot_dir.parent.name / cloud_snapshot_dir.name
    
    dest_remote = f"pythia:{rel_path}"
    
    # Count local files (excluding the manifest, which is created by the caller)
    local_files = [f for f in Path(local_snapshot_dir).rglob('*')
                   if f.is_file() and f.name != 'SNAPSHOT_MANIFEST.json']
    
    # Check if remote already has all files
    print(f"  Checking remote snapshot state...")
    try:
        remote_count_result = subprocess.run(
            ["rclone", "ls", dest_remote],
            capture_output=True, text=True, timeout=60
        )
        if remote_count_result.returncode == 0:
            remote_files = len([line for line in remote_count_result.stdout.strip().split('\n') if line.strip()])
            print(f"  Remote files: {remote_files}, Local files: {len(local_files)}")
            if remote_files >= len(local_files):
                manifest_check = subprocess.run(
                    ["rclone", "lsf", f"{dest_remote}/SNAPSHOT_MANIFEST.json"],
                    capture_output=True, text=True, timeout=30
                )
                if manifest_check.returncode == 0:
                    print(f"  Remote snapshot already complete ({remote_files} files), skipping copy")
                    return
    except Exception as e:
        print(f"  Warning: Could not check remote state, proceeding with copy: {e}")
    
    print(f"  Copying snapshot to cloud via rclone...")
    print(f"  Source: {local_snapshot_dir}")
    print(f"  Destination: {dest_remote}")
    
    # Use --ignore-existing for speed and reliable resumption: rclone uploads each
    # file atomically, so an existing destination file is complete. Stale files
    # (from an earlier, different local snapshot) are reconciled later by a
    # targeted --checksum re-sync in verify_and_reconcile() only if verification
    # detects a count/byte mismatch.
    cmd = [
        "rclone", "copy",
        str(local_snapshot_dir),
        dest_remote,
        "--ignore-existing",
        "--checksum",
        "--progress",
        "--retries", "3",
        "--low-level-retries", "10",
        "--transfers", "4",
        "--drive-chunk-size", "32M",
        "--fast-list",
        "--stats", "10s",
        "--stats-one-line",
        "--log-level", "INFO",
    ]
    
    print(f"  Running rclone copy (resumable, interrupted by time budget)...")
    print(f"  Command: {' '.join(cmd)}")
    
    start_time = time.time()
    
    # Compute a hard timeout from the remaining invocation budget, leaving a small
    # buffer for verification/cleanup. subprocess.run kills rclone on timeout,
    # which is safe because --ignore-existing makes the transfer resumable.
    remaining = MAX_INVOCATION_SECONDS - (time.time() - INVOCATION_START_TIME)
    rclone_timeout = max(30, remaining - 30)
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=rclone_timeout,
        )
        # Echo the tail of rclone output for the logs
        for line in (result.stdout or "").splitlines()[-8:]:
            print(f"  {line}")
    except subprocess.TimeoutExpired:
        raise TimeoutError("Time budget exceeded during rclone transfer")
    except FileNotFoundError:
        raise RuntimeError("rclone not found")
    
    return_code = result.returncode
    
    # Exit code 0 = success. Exit code 8 = max-transfer reached.
    if return_code not in (0, 8):
        # Capture the rclone error detail for diagnosis before raising.
        err_detail = (result.stderr or "").strip() or (result.stdout or "").strip()
        raise RuntimeError(f"rclone copy failed with return code {return_code}: {err_detail[:300]}")
    
    print(f"  rclone copy finished in {time.time() - start_time:.1f}s")
    
    # Ensure the remote carries the authoritative, current SNAPSHOT_MANIFEST.json.
    # --ignore-existing skips an existing stale manifest, which could otherwise
    # differ in bytes from the local one and fail remote byte verification.
    local_manifest_file = Path(local_snapshot_dir) / "SNAPSHOT_MANIFEST.json"
    if local_manifest_file.exists():
        manifest_up = subprocess.run(
            ["rclone", "copyto", str(local_manifest_file), f"{dest_remote}/SNAPSHOT_MANIFEST.json",
             "--retries", "3", "--low-level-retries", "10", "--log-level", "ERROR"],
            capture_output=True, text=True, timeout=60
        )
        if manifest_up.returncode != 0:
            raise RuntimeError(f"rclone copyto manifest failed: {manifest_up.stderr[:200]}")
        print(f"  Manifest synchronized to remote")
    
    if not check_time_budget(10):
        raise TimeoutError("Insufficient time budget for cloud verification")
    
    # Verify the snapshot is complete on the remote using rclone (bypasses FUSE cache).
    # The caller performs the authoritative SNAPSHOT_MANIFEST verification via the
    # FUSE mount after this function returns.
    remote_verify = subprocess.run(
        ["rclone", "ls", dest_remote],
        capture_output=True, text=True, timeout=60
    )
    if remote_verify.returncode != 0:
        raise RuntimeError(f"Cloud snapshot directory not created on remote: {dest_remote}")
    
    remote_file_count = len([line for line in remote_verify.stdout.strip().split('\n') if line.strip()])
    if remote_file_count < len(local_files):
        raise RuntimeError(
            f"Cloud snapshot incomplete: {remote_file_count} files on remote, "
            f"{len(local_files)} expected"
        )
    
    print(f"  Cloud copy verified on remote ({remote_file_count} files)")


def _fuse_to_remote(path: Path) -> str:
    """Convert a FUSE mount path to an rclone remote path (pythia:...)."""
    try:
        rel = path.relative_to("/mnt/pythia-cloud")
    except ValueError:
        rel = Path(str(path).lstrip("/"))
    return f"pythia:{rel}"


def reconcile_remote_extras(remote: str, local_snapshot_dir: Path) -> int:
    """Delete remote files that do not exist in the local snapshot. This is much
    faster than 'rclone sync' on a slow remote because it only lists files once
    and deletes the specific extra paths. Returns number of files deleted."""
    # List remote files
    ls = subprocess.run(
        ["rclone", "lsf", "--files-only", "-R", remote],
        capture_output=True, text=True, timeout=600
    )
    if ls.returncode != 0:
        print(f"    reconcile: could not list remote: {ls.stderr[:150]}")
        return 0
    remote_paths = set(p for p in ls.stdout.split('\n') if p.strip())
    if not remote_paths:
        return 0
    # List local content files (exclude manifest)
    local_paths = set()
    for f in local_snapshot_dir.rglob('*'):
        if f.is_file() and f.name != 'SNAPSHOT_MANIFEST.json':
            local_paths.add(str(f.relative_to(local_snapshot_dir)))
    extras = sorted(remote_paths - local_paths)
    if not extras:
        return 0
    print(f"    reconcile: deleting {len(extras)} stale remote file(s)...")
    deleted = 0
    for rel in extras:
        d = subprocess.run(
            ["rclone", "deletefile", f"{remote}/{rel}"],
            capture_output=True, text=True, timeout=120
        )
        if d.returncode == 0:
            deleted += 1
        else:
            print(f"    reconcile: failed to delete {rel}: {d.stderr[:120]}")
    return deleted


def verify_remote_snapshot(cloud_snapshot_dir: Path, local_snapshot_dir: Path) -> tuple:
    """Verify a staged remote snapshot via rclone against the local snapshot.

    Checks:
      - remote file count (excluding manifest) matches local
      - remote total bytes match local
      - remote manifest exists and its manifest_hash matches local
    Returns (ok, message).
    """
    remote = _fuse_to_remote(cloud_snapshot_dir)
    
    # Remote size (count + bytes)
    size_res = subprocess.run(
        ["rclone", "size", "--json", remote],
        capture_output=True, text=True, timeout=120
    )
    if size_res.returncode != 0:
        return False, f"rclone size failed: {size_res.stderr[:200]}"
    try:
        size_data = json.loads(size_res.stdout)
    except json.JSONDecodeError:
        return False, "rclone size returned invalid JSON"
    
    remote_count = size_data.get('count', 0)
    remote_bytes = size_data.get('bytes', 0)
    
    # Local counts (exclude manifest from file count; it is included in bytes below)
    local_files = [f for f in local_snapshot_dir.rglob('*')
                   if f.is_file() and f.name != 'SNAPSHOT_MANIFEST.json']
    local_count = len(local_files)
    local_bytes = sum(f.stat().st_size for f in local_files)
    
    # rclone size includes the manifest; account for it
    local_manifest_path = local_snapshot_dir / "SNAPSHOT_MANIFEST.json"
    manifest_bytes = local_manifest_path.stat().st_size if local_manifest_path.exists() else 0
    expected_count = local_count + (1 if manifest_bytes else 0)
    expected_bytes = local_bytes + manifest_bytes
    
    if remote_count != expected_count or remote_bytes != expected_bytes:
        time.sleep(3)  # settle for Drive eventual consistency
        size_res = subprocess.run(["rclone", "size", "--json", remote], capture_output=True, text=True, timeout=120)
        try:
            size_data = json.loads(size_res.stdout)
            remote_count = size_data.get('count', 0)
            remote_bytes = size_data.get('bytes', 0)
        except Exception:
            pass
    
    if remote_count != expected_count:
        # Attempt reconciliation: a stale file may exist (from an earlier snapshot
        # rebuild) or a file may be missing. Delete stale extra remote files
        # (fast targeted deletes) and re-verify once.
        print(f"  Count mismatch ({remote_count} != {expected_count}), reconciling (delete stale extras)...")
        reconcile_remote_extras(remote, local_snapshot_dir)
        size_res = subprocess.run(["rclone", "size", "--json", remote], capture_output=True, text=True, timeout=120)
        try:
            size_data = json.loads(size_res.stdout)
        except Exception:
            return False, "rclone size returned invalid JSON after reconcile"
        remote_count = size_data.get('count', 0)
        remote_bytes = size_data.get('bytes', 0)
    
    if remote_count != expected_count:
        return False, f"Remote file count {remote_count} != expected {expected_count}"
    if remote_bytes != expected_bytes:
        # Stale content file: delete stale extras and re-sync differing bytes
        # with a plain --checksum copy (faster than full sync).
        print(f"  Byte mismatch ({remote_bytes} != {expected_bytes}), reconciling (delete extras + checksum copy)...")
        reconcile_remote_extras(remote, local_snapshot_dir)
        reconcile = subprocess.run(
            ["rclone", "copy", str(local_snapshot_dir), remote,
             "--checksum", "--retries", "3", "--low-level-retries", "10",
             "--drive-chunk-size", "32M", "--log-level", "ERROR"],
            capture_output=True, text=True, timeout=600
        )
        if reconcile.returncode != 0:
            return False, f"Reconciliation failed: {reconcile.stderr[:200]}"
        size_res = subprocess.run(["rclone", "size", "--json", remote], capture_output=True, text=True, timeout=120)
        try:
            size_data = json.loads(size_res.stdout)
        except Exception:
            return False, "rclone size returned invalid JSON after reconcile"
        remote_count = size_data.get('count', 0)
        remote_bytes = size_data.get('bytes', 0)
    
    if remote_count != expected_count:
        return False, f"Remote file count {remote_count} != expected {expected_count}"
    if remote_bytes != expected_bytes:
        return False, f"Remote bytes {remote_bytes} != expected {expected_bytes}"
    
    # Fetch remote manifest and compare manifest_hash
    cat_res = subprocess.run(
        ["rclone", "cat", f"{remote}/SNAPSHOT_MANIFEST.json"],
        capture_output=True, text=True, timeout=120
    )
    if cat_res.returncode != 0:
        return False, "Could not fetch remote SNAPSHOT_MANIFEST.json"
    try:
        remote_manifest = json.loads(cat_res.stdout)
    except json.JSONDecodeError:
        return False, "Remote SNAPSHOT_MANIFEST.json is invalid JSON"
    
    if not local_manifest_path.exists():
        return False, "Local SNAPSHOT_MANIFEST.json missing"
    with open(local_manifest_path) as f:
        local_manifest = json.load(f)
    
    if remote_manifest.get('manifest_hash') != local_manifest.get('manifest_hash'):
        return False, "Remote manifest_hash does not match local manifest_hash"
    
    return True, f"OK ({remote_count} files, {remote_bytes} bytes)"


def promote_remote_snapshot(cloud_snapshot_dir: Path, final_sha_dir: Path) -> None:
    """Promote a staged remote snapshot to the final location via server-side rclone move."""
    staging_remote = _fuse_to_remote(cloud_snapshot_dir)
    final_remote = _fuse_to_remote(final_sha_dir)
    
    # Remove any pre-existing final directory (should not normally exist)
    subprocess.run(["rclone", "purge", final_remote], capture_output=True, text=True, timeout=120)
    
    result = subprocess.run(
        ["rclone", "moveto", staging_remote, final_remote,
         "--retries", "3", "--low-level-retries", "10",
         "--drive-chunk-size", "32M", "--log-level", "ERROR"],
        capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0:
        raise RuntimeError(f"rclone moveto failed: {result.stderr[:300]}")


def acquire_one(candidates) -> int:
    """Acquire a single repository. Returns 1=success, 0=no work, -1=failure, -2=timeout."""
    cleanup_inprogress()
    
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
    
    print(f"Acquiring {full_name} (branch: {default_branch}, attempt: {attempt_count + 1}/20, resume: {is_resume})...")
    
    attempt_count += 1
    update_state(candidates, full_name, 'FETCHING' if not is_resume else 'RESUME_FETCHING', 
                 attempt_count=attempt_count, last_attempt_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    
    local_git_dir = LOCAL_GIT_CACHE / f"{candidate['owner']}__{candidate['repo']}"
    local_git_dir.mkdir(parents=True, exist_ok=True)
    
    inprogress_dir = Path("/mnt/pythia-cloud/Pythia/raw/github/.inprogress") / f"{candidate['owner']}__{candidate['repo']}"
    inprogress_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        clone_repo_init(candidate['full_name'], local_git_dir, 30)
        
        if not expected_sha:
            if not check_time_budget(60):
                raise TimeoutError("Insufficient time budget for branch fetch")
            print(f"Fetching latest commit for branch {default_branch} (local)...")
            expected_sha = get_latest_commit_sha(local_git_dir, default_branch, FETCH_TIMEOUT_SECONDS)
            print(f"Latest commit SHA: {expected_sha}")
            update_state(candidates, full_name, 'FETCHING', commit_sha=expected_sha)
            save_manifest(candidates)
        
        if not check_time_budget(60):
            raise TimeoutError("Insufficient time budget for SHA fetch")
        print(f"Fetching exact commit {expected_sha[:12]} (local)...")
        fetch_exact_sha(candidate['full_name'], local_git_dir, expected_sha, FETCH_TIMEOUT_SECONDS, resume=True)
        
        if not check_time_budget(30):
            raise TimeoutError("Insufficient time budget for checkout")
        print(f"Checking out {expected_sha[:12]} (local)...")
        update_state(candidates, full_name, 'CHECKOUT')
        save_manifest(candidates)
        checkout_sha(local_git_dir, expected_sha)
        
        print(f"Verifying HEAD matches expected SHA (local)...")
        if not verify_head_sha(local_git_dir, expected_sha):
            raise RuntimeError(f"HEAD SHA mismatch: expected {expected_sha}, got different commit")
        print(f"HEAD verified: {expected_sha[:12]}")
        
        if not verify_repo(local_git_dir):
            raise RuntimeError("Repository verification failed: no files or size <= 1000 bytes")
        
        local_snapshot_dir = LOCAL_GIT_TEMP_BASE / expected_sha
        local_snapshot_dir.mkdir(parents=True, exist_ok=True)
        
        manifest_path = local_snapshot_dir / "SNAPSHOT_MANIFEST.json"
        # Marker stored outside the snapshot tree so it is never uploaded to cloud.
        verified_marker = LOCAL_GIT_TEMP_BASE / f"{expected_sha}.verified"
        
        # Optimization: the marker is written only after a full local verification
        # (all hashes + manifest). If it exists alongside the manifest, trust it and
        # skip the expensive re-copy/re-hash work so the time budget goes to transfer.
        snapshot_ready = verified_marker.exists() and manifest_path.exists()
        
        if snapshot_ready:
            print("  Local snapshot already verified, skipping snapshot creation/verification")
            update_state(candidates, full_name, 'SNAPSHOTTING' if not is_resume else 'RESUME_SNAPSHOTTING')
            save_manifest(candidates)
            existing_files = [f for f in local_snapshot_dir.rglob('*')
                              if f.is_file() and f.name not in ('SNAPSHOT_MANIFEST.json', '.snapshot_verified')]
            snapshot_info = {
                'file_count': len(existing_files),
                'total_bytes': sum(f.stat().st_size for f in existing_files),
                'files': [],
                'partial': False,
            }
        else:
            # Remove any stale marker before rebuilding
            if verified_marker.exists():
                verified_marker.unlink()
            
            snapshot_progress = None
            if is_resume:
                snapshot_progress = load_snapshot_progress(local_snapshot_dir)
                if snapshot_progress:
                    print(f"  Resuming snapshot from {len(snapshot_progress.get('completed_files', []))} completed files")
            
            print("Creating clean snapshot (local)...")
            update_state(candidates, full_name, 'SNAPSHOTTING' if not is_resume else 'RESUME_SNAPSHOTTING')
            save_manifest(candidates)
            
            if not check_time_budget(30):
                raise TimeoutError("Insufficient time budget for snapshot")
            
            snapshot_info = create_clean_snapshot(local_git_dir, local_snapshot_dir, snapshot_progress)
        
        if snapshot_info.get('partial'):
            print(f"Snapshot partial: {snapshot_info['file_count']} files, {snapshot_info['total_bytes']} bytes - will resume")
            update_state(candidates, full_name, 'TIMEOUT_RETRYABLE', 
                         commit_sha=expected_sha,
                         snapshot_progress=snapshot_info.get('progress'),
                         last_stage='SNAPSHOTTING',
                         error="Snapshot incomplete - time budget exceeded")
            save_manifest(candidates)
            return -2
        
        if not snapshot_ready:
            print(f"Local snapshot created: {snapshot_info['file_count']} files, {snapshot_info['total_bytes']} bytes")
            
            print("Verifying clean snapshot (local)...")
            ok, msg = verify_snapshot(local_snapshot_dir, expected_sha)
            if not ok:
                raise RuntimeError(f"Clean snapshot verification failed: {msg}")
            print(f"Clean snapshot verified: {msg}")
            
            print("Creating snapshot manifest (local)...")
            snapshot_manifest = create_snapshot_manifest(local_snapshot_dir, expected_sha, full_name)
            with open(manifest_path, 'w') as f:
                json.dump(snapshot_manifest, f, indent=2, sort_keys=True)
            
            print("Verifying snapshot manifest (local)...")
            ok, msg = verify_snapshot_manifest(local_snapshot_dir, expected_sha)
            if not ok:
                raise RuntimeError(f"Snapshot manifest verification failed: {msg}")
            print(f"Snapshot manifest verified: {msg}")
            
            # Mark the local snapshot as fully verified so later invocations can skip
            # the expensive re-verification and spend the budget on transfer.
            with open(verified_marker, 'w') as f:
                f.write(time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
            print("  Local snapshot marked verified")
        else:
            print(f"Local snapshot ready: {snapshot_info['file_count']} files, {snapshot_info['total_bytes']} bytes")
        
        if not check_time_budget(60):
            raise TimeoutError("Insufficient time budget for cloud copy")
        print("Copying clean snapshot to cloud...")
        cloud_snapshot_parent = Path("/mnt/pythia-cloud/Pythia/raw/github/.snapshots") / f"{candidate['owner']}__{candidate['repo']}"
        cloud_snapshot_dir = cloud_snapshot_parent / expected_sha
        
        copy_snapshot_to_cloud(local_snapshot_dir, cloud_snapshot_dir, time_budget=120)
        print(f"Copied to cloud: {cloud_snapshot_dir}")
        
        print("Verifying snapshot on cloud (remote)...")
        ok, msg = verify_remote_snapshot(cloud_snapshot_dir, local_snapshot_dir)
        if not ok:
            raise RuntimeError(f"Cloud snapshot verification failed: {msg}")
        print(f"Cloud verification passed: {msg}")
        
        final_sha_dir = Path("/mnt/pythia-cloud/Pythia/raw/github") / f"{candidate['owner']}__{candidate['repo']}" / expected_sha
        
        print(f"Promoting to final location on cloud (server-side move)...")
        update_state(candidates, full_name, 'PROMOTING')
        save_manifest(candidates)
        promote_remote_snapshot(cloud_snapshot_dir, final_sha_dir)
        print(f"Promoted to final location: {final_sha_dir}")
        
        print("Final filesystem verification on cloud (remote)...")
        ok, msg = verify_remote_snapshot(final_sha_dir, local_snapshot_dir)
        if not ok:
            raise RuntimeError(f"Final verification failed: {msg}")
        print(f"Final verification passed: {msg}")
        
        update_state(candidates, full_name, 'ACQUIRED',
                     commit_sha=expected_sha,
                     cloud_path=str(final_sha_dir),
                     acquired_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                     attempt_count=attempt_count)
        save_manifest(candidates)
        print(f"Successfully acquired {full_name} (SHA: {expected_sha})")
        return 1
    
    except TimeoutError as e:
        print(f"Timeout acquiring {full_name}: {e}")
        if attempt_count < 120:
            update_state(candidates, full_name, 'TIMEOUT_RETRYABLE', 
                         commit_sha=expected_sha,
                         attempt_count=attempt_count,
                         last_error=str(e),
                         last_stage=candidate.get('state', 'UNKNOWN'))
        else:
            update_state(candidates, full_name, 'TIMEOUT_PERMANENT', 
                         commit_sha=expected_sha,
                         attempt_count=attempt_count,
                         last_error=str(e),
                         last_stage=candidate.get('state', 'UNKNOWN'))
        save_manifest(candidates)
        return -2
    except Exception as e:
        print(f"Failed to acquire {full_name}: {e}")
        update_state(candidates, full_name, 'FAILED', 
                     commit_sha=expected_sha,
                     attempt_count=attempt_count,
                     error=str(e))
        save_manifest(candidates)
        return -1
    finally:
        # Only the local .inprogress marker is transient. The local snapshot
        # (.git_temp/<sha>) and the remote staging directory (.snapshots/...) are
        # deliberately PRESERVED on timeout so the next invocation can resume
        # rather than restart the transfer from zero.
        inprogress_dir = Path("/mnt/pythia-cloud/Pythia/raw/github/.inprogress") / f"{candidate['owner']}__{candidate['repo']}"
        if Path(inprogress_dir).exists():
            shutil.rmtree(inprogress_dir, ignore_errors=True)


def prune_acquired_local_state(min_free_gb: float = 2.0) -> int:
    """Prune local temp snapshots and git caches for already-ACQUIRED repos when
    the local root filesystem is low on space. The authoritative verified copy
    lives on the remote/cloud, so these local artifacts are safe to remove.
    Returns number of items removed."""
    try:
        free_gb = shutil.disk_usage("/").free / (1024 ** 3)
        if free_gb >= min_free_gb:
            return 0
    except Exception:
        return 0

    try:
        candidates = load_manifest()
    except Exception:
        return 0
    acquired_shas = set()
    acquired_names = set()
    for c in candidates:
        if c.get('state') == 'ACQUIRED':
            if c.get('commit_sha'):
                acquired_shas.add(c['commit_sha'])
            acquired_names.add(f"{c.get('owner')}__{c.get('repo')}")

    removed = 0
    # Prune local snapshot dirs in .git_temp for acquired SHAs
    temp = Path("data/raw/github/.git_temp")
    if temp.is_dir():
        for d in list(temp.iterdir()):
            base = d.name[:-9] if d.name.endswith('.verified') else d.name
            if base in acquired_shas:
                if d.is_dir():
                    shutil.rmtree(d, ignore_errors=True)
                else:
                    try:
                        d.unlink()
                    except OSError:
                        pass
                removed += 1
    # Prune git caches in repositories for acquired repos
    repo_base = Path("data/raw/github/repositories")
    if repo_base.is_dir():
        for d in list(repo_base.iterdir()):
            if d.is_dir() and d.name in acquired_names:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
    if removed:
        print(f"  [disk-safety] pruned {removed} local items for acquired repos "
              f"(free: {shutil.disk_usage('/').free/(1024**3):.1f} GiB)")
    return removed


def reset_stale_inprogress() -> None:
    """Reset manifest states that were left mid-operation by a killed process.
    Called once at the start of a new acquisition process. Only transient states
    are reset to QUEUED; ACQUIRED/FAILED/QUEUED/TIMEOUT_* are preserved."""
    stale = {'FETCHING', 'RESUME_FETCHING', 'CHECKOUT', 'SNAPSHOTTING',
             'RESUME_SNAPSHOTTING', 'VERIFYING', 'PROMOTING', 'DOWNLOADING', 'PARTIAL',
             'TIMEOUT_PERMANENT'}
    try:
        candidates = load_manifest()
    except Exception:
        return
    changed = 0
    for c in candidates:
        if c.get('state') in stale:
            c['state'] = 'QUEUED'
            c['attempt_count'] = 0
            for k in ('error', 'last_error', 'last_attempt_at', 'last_stage', 'failed_at',
                      'snapshot_progress', 'download_started_at'):
                c.pop(k, None)
            changed += 1
    if changed:
        save_manifest(candidates)
        print(f"  Reset {changed} stale in-progress states to QUEUED")


def run_batch(max_runtime_seconds: int = 240) -> dict:
    """Run batch acquisition within time budget."""
    # Reset any states left mid-operation by a previously killed process.
    reset_stale_inprogress()
    print(f"=== GitHub Acquisition Batch ===")
    print(f"Max runtime: {max_runtime_seconds}s")
    
    start_time = time.time()
    candidates = load_manifest()
    
    start_queued = sum(1 for c in candidates if c.get('state') == 'QUEUED')
    start_acquired = sum(1 for c in candidates if c.get('state') == 'ACQUIRED')
    try:
        start_disk = shutil.disk_usage("/mnt/pythia-cloud").free / (1024 ** 3)
    except OSError:
        start_disk = 0.0
    
    print(f"Starting state: {start_acquired} ACQUIRED, {start_queued} QUEUED")
    print(f"Free disk: {start_disk:.2f} GiB")
    
    repos_attempted = 0
    repos_acquired = 0
    repos_failed = 0
    repos_timeout = 0
    
    while True:
        # Respect the invocation budget (shared across the whole process).
        remaining = MAX_INVOCATION_SECONDS - (time.time() - INVOCATION_START_TIME)
        if remaining < 30:
            print(f"Invocation budget nearly exhausted ({remaining:.0f}s left), stopping.")
            break
        
        # Local disk safety: prune acquired-repo local state if the root FS is low.
        # (No cloud-disk check here: transfers go directly via rclone to the
        # pythia: remote, which has ample space, and the FUSE mount may be down.)
        local_free_gb = shutil.disk_usage("/").free / (1024 ** 3)
        if local_free_gb < 2.0:
            print(f"  Local disk low ({local_free_gb:.1f} GiB), pruning acquired local state...")
            prune_acquired_local_state(min_free_gb=2.0)
        
        current = load_manifest()
        queued = sum(1 for c in current if c.get('state') == 'QUEUED')
        timeout_retryable = sum(1 for c in current if c.get('state') == 'TIMEOUT_RETRYABLE')
        acquired = sum(1 for c in current if c.get('state') == 'ACQUIRED')
        if queued == 0 and timeout_retryable == 0:
            print("No QUEUED or TIMEOUT_RETRYABLE repositories remaining.")
            break
        
        print(f"\n--- Attempting acquisition ({acquired} acquired, {queued} queued, "
              f"{timeout_retryable} retryable, {remaining:.0f}s left) ---")
        result = acquire_one(current)
        
        if result == 1:
            print("Repository acquired successfully.")
            repos_acquired += 1
        elif result == -2:
            print("Repository timed out.")
            repos_timeout += 1
        elif result == -1:
            print("Repository failed.")
            repos_failed += 1
        else:
            print(f"Unexpected result: {result}")
            repos_failed += 1
        
        repos_attempted += 1
        
        if repos_attempted >= 5:
            print(f"Reached max repos per batch (5), stopping.")
            break
        
        time.sleep(2)
    
    end_acquired = sum(1 for c in load_manifest() if c.get('state') == 'ACQUIRED')
    end_queued = sum(1 for c in load_manifest() if c.get('state') == 'QUEUED')
    try:
        end_disk = shutil.disk_usage("/mnt/pythia-cloud").free / (1024 ** 3)
    except OSError:
        end_disk = 0.0
    elapsed = time.time() - start_time
    
    print(f"\n=== BATCH SUMMARY ===")
    print(f"Runtime: {elapsed:.1f}s")
    print(f"Starting: {start_acquired} ACQUIRED, {start_queued} QUEUED")
    print(f"Ending: {end_acquired} ACQUIRED, {end_queued} QUEUED")
    print(f"Acquired this batch: {repos_acquired}")
    print(f"Failed: {repos_failed}")
    print(f"Timeouts: {repos_timeout}")
    print(f"Free disk: {end_disk:.2f} GiB (started at {start_disk:.2f} GiB)")
    print(f"Disk change: {end_disk - start_disk:+.2f} GiB")
    
    return {
        'acquired': repos_acquired,
        'failed': repos_failed,
        'timeout': repos_timeout,
        'elapsed': elapsed
    }


def main():
    print("Starting GitHub acquisition batch...")
    check_drive_mounted()
    run_batch(max_runtime_seconds=240)
    print("Batch complete.")


if __name__ == "__main__":
    import shutil
    import hashlib
    main()