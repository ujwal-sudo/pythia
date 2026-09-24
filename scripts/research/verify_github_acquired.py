#!/usr/bin/env python3
"""
Verify all ACQUIRED entries in the canonical GitHub manifest against the cloud filesystem.
Enforces the clean-snapshot invariant: NO .git/, NO .github/, NO .git* files anywhere.

Exit code: 0 if all ACQUIRED entries are verified clean, non-zero if any discrepancy found.
"""

import json
import sys
from pathlib import Path

# Paths
MANIFEST_PATH = Path("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl")
CLOUD_BASE = Path("/mnt/pythia-cloud/Pythia/raw/github")


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
    return forbidden


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
        import hashlib
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
    import hashlib
    computed_manifest_hash = hashlib.sha256(manifest_content.encode()).hexdigest()
    if computed_manifest_hash != manifest.get('manifest_hash'):
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

    for c in acquired:
        full_name = c['full_name']
        cloud_path = c.get('cloud_path', '')
        commit_sha = c.get('commit_sha', '')

        if not cloud_path:
            discrepancies.append(f"{full_name}: ACQUIRED but no cloud_path")
            invalid_data += 1
            continue

        path = Path(cloud_path)

        if not path.exists():
            discrepancies.append(f"{full_name}: cloud_path does not exist: {cloud_path}")
            invalid_data += 1
            continue

        if not path.is_dir():
            discrepancies.append(f"{full_name}: cloud_path is not a directory: {cloud_path}")
            invalid_data += 1
            continue

        # Check directory name matches commit SHA
        if path.name != commit_sha:
            discrepancies.append(f"{full_name}: directory name '{path.name}' != commit_sha '{commit_sha}'")
            invalid_data += 1
            continue

        # Check directory has files
        has_files = any(path.iterdir())
        if not has_files:
            discrepancies.append(f"{full_name}: directory exists but is empty")
            invalid_data += 1
            continue

        # Check total bytes > 1000 (sample first 100 files for speed)
        total_bytes = 0
        file_count = 0
        for entry in path.rglob('*'):
            if entry.is_file():
                try:
                    total_bytes += entry.stat().st_size
                    file_count += 1
                    if file_count >= 100:
                        break
                except OSError:
                    pass
        if total_bytes <= 1000:
            discrepancies.append(f"{full_name}: total bytes {total_bytes} <= 1000")
            invalid_data += 1
            continue

        # CRITICAL: Check for forbidden Git metadata
        forbidden = has_forbidden_git_metadata(path)
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