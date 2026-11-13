#!/usr/bin/env python3
"""
Verify all ACQUIRED entries in the canonical GitHub manifest against the cloud filesystem.
Enforces the clean-snapshot invariant: NO .git/, NO .github/, NO .git* files anywhere.

Exit code: 0 if all ACQUIRED entries are verified clean, non-zero if any discrepancy found.
"""

import errno
import hashlib
import json
import os
import signal
import sys
import time
from pathlib import Path

# Paths
MANIFEST_PATH = Path("/mnt/pythia-cloud/PythiaDrive/raw/github/manifests/github_candidates_v1.jsonl")
CLOUD_BASE    = Path("/mnt/pythia-cloud/PythiaDrive/raw/github")

FILE_READ_TIMEOUT_SEC  = 30   # max seconds to read a single file
WALK_TIMEOUT_SEC       = 60   # max seconds for a full rglob walk of one snapshot

# Timeout helpers ───────────────────────────────────────────────────────────
class TimeoutError(Exception):
    pass

def _alarm_handler(signum, frame):
    raise TimeoutError("Operation timed out")

def _set_timeout(seconds):
    signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(seconds)

def _clear_timeout():
    signal.alarm(0)


# Retry helpers ───────────────────────────────────────────────────────────────
RETRY_BASE_DELAY_SEC = 1.0
RETRY_MAX_DELAY_SEC  = 15.0
MAX_IO_RETRIES       = 5

_TRANSIENT_ERRNOS = {
    errno.EIO, errno.EAGAIN, errno.EBUSY, errno.EINTR,
    errno.ETIMEDOUT, errno.ECONNRESET, errno.ENETRESET,
}

def _is_transient_oserror(e):
    if not isinstance(e, OSError):
        return False
    if getattr(e, 'errno', None) in _TRANSIENT_ERRNOS:
        return True
    msg = str(e)
    return "Input/output error" in msg or "[Errno 5]" in msg

def _retry(call, timeout_sec=None, description="I/O operation"):
    """
    Run call(), retrying transient FUSE I/O errors (e.g. [Errno 5]) with
    exponential backoff. If timeout_sec is given, each attempt is guarded by a
    SIGALRM timeout. Returns call()'s result; raises TimeoutError or the last
    OSError if all attempts fail.
    """
    last_exc = None
    for attempt in range(MAX_IO_RETRIES + 1):
        if timeout_sec is not None:
            _set_timeout(timeout_sec)
        try:
            return call()
        except TimeoutError:
            raise
        except OSError as e:
            if timeout_sec is not None:
                _clear_timeout()
            if not _is_transient_oserror(e) or attempt >= MAX_IO_RETRIES:
                raise
            last_exc = e
            delay = min(RETRY_BASE_DELAY_SEC * (2 ** attempt), RETRY_MAX_DELAY_SEC)
            print(f"    [retry {attempt + 1}/{MAX_IO_RETRIES}] {description}: {e}", flush=True)
            time.sleep(delay)
        finally:
            if timeout_sec is not None:
                _clear_timeout()
    raise last_exc


def load_manifest() -> list:
    """Load the canonical manifest."""
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"Manifest not found at {MANIFEST_PATH}")
    with open(MANIFEST_PATH, 'r') as f:
        return [json.loads(line) for line in f if line.strip()]


def has_forbidden_git_metadata(path: Path) -> list:
    """
    Check for forbidden Git metadata in the snapshot.
    Returns list of offending paths (relative to snapshot root).
    """
    forbidden = []
    try:
        for entry in path.rglob('*'):
            name = entry.name
            # Check for .git directory
            if name == '.git' and entry.is_dir():
                forbidden.append(str(entry.relative_to(path)))
            # Check for .github directory
            elif name == '.github' and entry.is_dir():
                forbidden.append(str(entry.relative_to(path)))
            # Check for any file/dir starting with .git
            elif name.startswith('.git'):
                forbidden.append(str(entry.relative_to(path)))
    except OSError as e:
        raise OSError(f"I/O error during git metadata walk: {e}") from e
    return forbidden


def verify_snapshot_manifest(snapshot_dir: Path, expected_sha: str) -> tuple:
    """
    Verify the SNAPSHOT_MANIFEST.json exists and is internally consistent.
    Returns (ok, message).
    """
    manifest_path = snapshot_dir / "SNAPSHOT_MANIFEST.json"
    try:
        manifest_exists = _retry(
            manifest_path.exists,
            description="checking SNAPSHOT_MANIFEST.json",
        )
    except OSError as e:
        return False, f"I/O error checking SNAPSHOT_MANIFEST.json: {e}"
    if not manifest_exists:
        return False, "SNAPSHOT_MANIFEST.json not found"

    def _read_snapshot_manifest():
        with open(manifest_path, 'r') as f:
            return json.load(f)

    try:
        manifest = _retry(
            _read_snapshot_manifest,
            timeout_sec=FILE_READ_TIMEOUT_SEC,
            description="reading SNAPSHOT_MANIFEST.json",
        )
    except TimeoutError:
        return False, "Timed out reading SNAPSHOT_MANIFEST.json"
    except OSError as e:
        return False, f"I/O error reading SNAPSHOT_MANIFEST.json: {e}"
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON in manifest: {e}"
    
    # Verify manifest contains expected fields
    # Older snapshots use 'file_count'; newer ones use 'total_files' — accept either
    file_count_field = 'total_files' if 'total_files' in manifest else 'file_count'
    required_fields = ['commit_sha', 'full_name', file_count_field, 'total_bytes', 'manifest_hash', 'files']
    for field in required_fields:
        if field not in manifest:
            return False, f"Manifest missing required field: {field}"
    
    # Verify commit SHA matches
    if manifest.get('commit_sha') != expected_sha:
        return False, f"Manifest commit_sha '{manifest.get('commit_sha')}' != expected '{expected_sha}'"
    
    # Verify file count matches
    def _walk_files():
        return [f for f in snapshot_dir.rglob('*')
                if f.is_file() and f.name != 'SNAPSHOT_MANIFEST.json']

    try:
        actual_files = _retry(
            _walk_files,
            timeout_sec=WALK_TIMEOUT_SEC,
            description="walking snapshot directory for file count",
        )
    except TimeoutError:
        return False, "Timed out walking snapshot directory for file count"
    except OSError as e:
        return False, f"I/O error walking snapshot directory: {e}"
    expected_count = manifest[file_count_field]
    if expected_count != len(actual_files):
        return False, f"Manifest {file_count_field} {expected_count} != actual {len(actual_files)}"
    
    # Verify total bytes
    try:
        actual_bytes = _retry(
            lambda: sum(f.stat().st_size for f in actual_files),
            description="computing total_bytes",
        )
    except OSError as e:
        return False, f"I/O error computing total_bytes: {e}"
    if manifest.get('total_bytes') != actual_bytes:
        return False, f"Manifest total_bytes {manifest.get('total_bytes')} != actual {actual_bytes}"
    
    # Verify each file hash
    for file_entry in manifest.get('files', []):
        file_path = snapshot_dir / file_entry['path']
        try:
            exists = _retry(
                file_path.exists,
                description=f"checking file {file_entry['path']}",
            )
        except OSError as e:
            return False, f"I/O error checking file {file_entry['path']}: {e}"
        if not exists:
            return False, f"Manifest references missing file: {file_entry['path']}"
        
        # Compute hash
        import hashlib
        def _hash_file():
            h = hashlib.sha256()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    h.update(chunk)
            return h.hexdigest()

        try:
            computed_hash = _retry(
                _hash_file,
                timeout_sec=FILE_READ_TIMEOUT_SEC,
                description=f"reading file {file_entry['path']}",
            )
        except TimeoutError:
            return False, f"Timed out reading file: {file_entry['path']}"
        except OSError as e:
            return False, f"Could not read file {file_entry['path']}: {e}"
        
        if computed_hash != file_entry['sha256']:
            return False, f"Hash mismatch for {file_entry['path']}: expected {file_entry['sha256']}, got {computed_hash}"
        
        # Check size
        try:
            actual_size = _retry(
                lambda: file_path.stat().st_size,
                description=f"reading size for {file_entry['path']}",
            )
        except OSError as e:
            return False, f"I/O error reading size for {file_entry['path']}: {e}"
        if file_entry['size'] != actual_size:
            return False, f"Size mismatch for {file_entry['path']}: expected {file_entry['size']}, got {actual_size}"
    
    # Verify manifest_hash determinism. Snapshots were generated at different
    # times and hash the file count under different names ('file_count' vs
    # 'total_files'), so recompute using the field name actually present.
    base_fields = {
        'commit_sha': manifest['commit_sha'],
        'full_name': manifest['full_name'],
        'files': manifest['files'],
        'total_bytes': manifest['total_bytes'],
    }
    count_keys = [k for k in ('total_files', 'file_count') if k in manifest]
    computed_manifest_hash = None
    for count_key in count_keys:
        payload = dict(base_fields)
        payload[count_key] = manifest[count_key]
        candidate_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        if candidate_hash == manifest.get('manifest_hash'):
            computed_manifest_hash = candidate_hash
            break
    if computed_manifest_hash is None:
        preferred = count_keys[0] if count_keys else 'file_count'
        payload = dict(base_fields)
        payload[preferred] = manifest.get(preferred)
        computed_manifest_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return False, f"Manifest hash mismatch: expected {manifest.get('manifest_hash')}, got {computed_manifest_hash}"
    
    return True, "OK"


def verify_acquired() -> bool:
    """Verify all ACQUIRED entries against filesystem with clean-snapshot invariant."""
    candidates = load_manifest()

    acquired = [c for c in candidates if c.get('state') == 'ACQUIRED']
    queued = [c for c in candidates if c.get('state') == 'QUEUED']
    failed = [c for c in candidates if c.get('state') == 'FAILED']
    timeout = [c for c in candidates if c.get('state') == 'TIMEOUT']
    other = [c for c in candidates if c.get('state') not in ('ACQUIRED', 'QUEUED', 'FAILED', 'TIMEOUT')]

    print(f"Manifest state counts:")
    print(f"  ACQUIRED: {len(acquired)}")
    print(f"  QUEUED: {len(queued)}")
    print(f"  FAILED: {len(failed)}")
    print(f"  TIMEOUT: {len(timeout)}")
    print(f"  Other: {len(other)}")
    print(f"  Total: {len(candidates)}")

    verified = 0
    missing_data = 0
    invalid_data = 0
    discrepancies = []

    for i, c in enumerate(acquired, 1):
        full_name  = c['full_name']
        cloud_path = c.get('cloud_path', '')
        commit_sha = c.get('commit_sha', '')

        print(f"[{i}/{len(acquired)}] {full_name} ...", flush=True)

        if not cloud_path:
            discrepancies.append(f"{full_name}: ACQUIRED but no cloud_path")
            invalid_data += 1
            continue

        # Rewrite stale root if present
        corrected = cloud_path.replace(
            "/mnt/pythia-cloud/Pythia/",
            "/mnt/pythia-cloud/PythiaDrive/"
        )
        if corrected != cloud_path:
            print(f"(path corrected) ", end='', flush=True)
        path = Path(corrected)

        try:
            exists = _retry(path.exists, description=f"checking {full_name} exists")
        except OSError as e:
            discrepancies.append(f"{full_name}: I/O error checking cloud_path exists: {e}")
            invalid_data += 1
            continue
        if not exists:
            discrepancies.append(f"{full_name}: cloud_path does not exist: {cloud_path}")
            invalid_data += 1
            continue

        try:
            is_d = _retry(path.is_dir, description=f"checking {full_name} is_dir")
        except OSError as e:
            discrepancies.append(f"{full_name}: I/O error checking cloud_path is_dir: {e}")
            invalid_data += 1
            continue
        if not is_d:
            discrepancies.append(f"{full_name}: cloud_path is not a directory: {cloud_path}")
            invalid_data += 1
            continue

        # Check directory name matches commit SHA
        try:
            dir_name = path.name
        except OSError as e:
            discrepancies.append(f"{full_name}: I/O error getting path name: {e}")
            invalid_data += 1
            continue
        if dir_name != commit_sha:
            discrepancies.append(f"{full_name}: directory name '{dir_name}' != commit_sha '{commit_sha}'")
            invalid_data += 1
            continue

        # Check directory has files
        try:
            has_files = _retry(
                lambda: any(path.iterdir()),
                description=f"listing {full_name} directory",
            )
        except OSError as e:
            discrepancies.append(f"{full_name}: I/O error listing directory: {e}")
            invalid_data += 1
            continue

        # Check total bytes > 1000 (sample first 100 files for speed)
        def _sample_size():
            tb = 0
            fc = 0
            for entry in path.rglob('*'):
                if entry.is_file():
                    tb += entry.stat().st_size
                    fc += 1
                    if fc >= 100:
                        break
            return tb

        try:
            total_bytes = _retry(
                _sample_size,
                description=f"sampling size for {full_name}",
            )
        except OSError as e:
            discrepancies.append(f"{full_name}: I/O error reading file stat: {e}")
            invalid_data += 1
            continue
        if total_bytes <= 1000:
            discrepancies.append(f"{full_name}: total bytes {total_bytes} <= 1000")
            invalid_data += 1
            continue

        # CRITICAL: Check for forbidden Git metadata
        try:
            forbidden = _retry(
                lambda: has_forbidden_git_metadata(path),
                timeout_sec=WALK_TIMEOUT_SEC,
                description=f"git metadata walk for {full_name}",
            )
        except TimeoutError:
            msg = "Timed out checking for forbidden Git metadata"
            print(f"FAIL — {msg}")
            discrepancies.append(f"{full_name}: {msg}")
            invalid_data += 1
            continue
        except OSError as e:
            msg = f"I/O error during git metadata check: {e}"
            print(f"FAIL — {msg}")
            discrepancies.append(f"{full_name}: {msg}")
            invalid_data += 1
            continue
        if forbidden:
            discrepancies.append(f"{full_name}: FORBIDDEN Git metadata found: {forbidden}")
            invalid_data += 1
            continue

        # Verify snapshot manifest
        ok, msg = verify_snapshot_manifest(path, commit_sha)
        if not ok:
            discrepancies.append(f"{full_name}: snapshot manifest verification failed: {msg}")
            invalid_data += 1
            continue

        verified += 1

    print(f"\nVerification Results:")
    print(f"  ACQUIRED in manifest: {len(acquired)}")
    print(f"  Clean-snapshot verified: {verified}")
    print(f"  Missing data: {missing_data}")
    print(f"  Invalid data: {invalid_data}")

    if discrepancies:
        print("\nDiscrepancies:")
        for d in discrepancies:
            print(f"  - {d}")

    return len(discrepancies) == 0


if __name__ == "__main__":
    ok = verify_acquired()
    sys.exit(0 if ok else 1)