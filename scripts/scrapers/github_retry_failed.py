#!/usr/bin/env python3
"""
GitHub Failed/Timeout Retry Script

Resets failed and timeout states to QUEUED for retry.
"""

import json
import os
from pathlib import Path

MANIFEST_PATH = Path("data/raw/github/manifests/github_candidates_v1.jsonl")


def load_manifest():
    with open(MANIFEST_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]


def save_manifest(candidates):
    with open(MANIFEST_PATH, 'w') as f:
        for c in candidates:
            f.write(json.dumps(c, sort_keys=True) + '\n')


def main():
    candidates = load_manifest()
    
    reset_count = 0
    
    for c in candidates:
        state = c.get('state', 'UNKNOWN')
        
        if state == 'TIMEOUT_PERMANENT':
            # Reset timeout to retryable
            c['state'] = 'TIMEOUT_RETRYABLE'
            print(f"Reset TIMEOUT_PERMANENT -> TIMEOUT_RETRYABLE: {c['full_name']}")
            c['attempt_count'] = 0
            c.pop('error', None)
            c.pop('last_error', None)
            c.pop('last_attempt_at', None)
            c.pop('last_stage', None)
            c.pop('failed_at', None)
            c.pop('snapshot_progress', None)
            reset_count += 1
            
        elif state == 'FAILED':
            error = c.get('error', '').lower()
            # Only retry network/timeout failures, not permanent errors
            retryable_errors = [
                'timeout', 'network', 'connection', 'dns', 'dns',
                'temporary', 'rate limit', 'rate limited',
                'unable to write', 'input/output', 'io error',
                'connection refused', 'connection reset', 'broken pipe'
            ]
            
            error = str(c.get('error', '')).lower()
            if any(e in error for e in retryable_errors):
                c['state'] = 'QUEUED'
                c['attempt_count'] = 0
                c.pop('error', None)
                c.pop('last_error', None)
                c.pop('last_attempt_at', None)
                c.pop('last_stage', None)
                c.pop('failed_at', None)
                print(f"Reset FAILED (retryable) -> QUEUED: {c['full_name']} ({error[:60]})")
                reset_count += 1
            else:
                print(f"Kept as FAILED (non-retryable): {c['full_name']} ({error[:60]})")
    
    if reset_count > 0:
        print(f"\nReset {reset_count} repositories to retryable states.")
        # Save
        with open(MANIFEST_PATH, 'w') as f:
            for c in candidates:
                f.write(json.dumps(c, sort_keys=True) + '\n')
    else:
        print("No repositories reset.")

    # Summary
    with open(MANIFEST_PATH) as f:
        candidates = [json.loads(line) for line in f]
    
    states = {}
    for c in candidates:
        s = c.get('state', 'UNKNOWN')
        states[s] = states.get(s, 0) + 1
    
    print("\nCurrent state after reset:")
    for k, v in sorted(states.items()):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    import json
    from pathlib import Path
    from collections import Counter
    
    main()