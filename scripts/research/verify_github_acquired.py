#!/usr/bin/env python3
"""
Verify all ACQUIRED entries in the canonical GitHub manifest against the cloud filesystem.

Exit code: 0 if all ACQUIRED entries are verified, non-zero if any discrepancy found.
"""

import json
import sys
from pathlib import Path

# Ensure we can import config
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import DATA_ROOT, RAW_DIR

# Paths
MANIFEST_PATH = RAW_DIR / "github" / "manifests" / "github_candidates_v1.jsonl"
CLOUD_BASE = Path("/mnt/pythia-cloud/Pythia/raw/github")

def load_manifest():
    """Load the canonical manifest."""
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"Manifest not found at {MANIFEST_PATH}")
    with open(MANIFEST_PATH, 'r') as f:
        return [json.loads(line) for line in f if line.strip()]

def verify_acquired():
    """Verify all ACQUIRED entries against filesystem."""
    candidates = []
    with open(MANIFEST_PATH, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                candidates.append(json.loads(line))

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

        from pathlib import Path
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

        # Check directory has files (non-recursive check for speed)
        has_files = any(path.iterdir())
        if not has_files:
            discrepancies.append(f"{full_name}: directory exists but appears empty")
            invalid_data += 1
            continue

        # Check total bytes > 1000 (sample a few files)
        total_bytes = 0
        file_count = 0
        for entry in path.rglob('*'):
            if entry.is_file():
                try:
                    total_bytes += entry.stat().st_size
                    file_count += 1
                    if file_count >= 100:  # Sample first 100 files for speed
                        break
                except OSError:
                    pass
        if total_bytes <= 1000:
            discrepancies.append(f"{full_name}: total bytes {total_bytes} <= 1000")
            invalid_data += 1
            continue

        verified += 1

    print(f"\nVerification Results:")
    print(f"  ACQUIRED in manifest: {len(acquired)}")
    print(f"  Filesystem verified: {verified}")
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