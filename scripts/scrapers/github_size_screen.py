#!/usr/bin/env python3
"""
STEP 1: Size screening of all QUEUED repositories using GitHub API.
Adds repo_size_kb and size_category fields to manifest.
Resumable - saves after each repo.
"""

import json
import os
import sys
import time
import requests
from pathlib import Path

MANIFEST_PATH = Path("data/raw/github/manifests/github_candidates_v1.jsonl")

def load_manifest():
    with open(MANIFEST_PATH) as f:
        return [json.loads(line) for line in f]

def save_manifest(candidates):
    with open(MANIFEST_PATH, 'w') as f:
        for c in candidates:
            f.write(json.dumps(c, sort_keys=True) + '\n')

def get_repo_size(owner, repo, token=None, max_retries=3):
    """Fetch repo size from GitHub API. Returns size in KB or None on error."""
    url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {'Accept': 'application/vnd.github.v3+json'}
    if token:
        headers['Authorization'] = f'token {token}'
    
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return data.get('size', 0)  # size in KB
            elif resp.status_code == 404:
                print(f"  404 Not Found: {owner}/{repo}")
                return None
            elif resp.status_code == 403:
                # Rate limited
                reset = resp.headers.get('X-RateLimit-Reset')
                if reset:
                    wait = max(0, int(reset) - int(time.time()) + 5)
                    print(f"  Rate limited. Waiting {wait}s...")
                    time.sleep(wait)
                    continue
                else:
                    print(f"  403 Forbidden: {owner}/{repo}")
                    return None
            else:
                print(f"  API error {resp.status_code}: {owner}/{repo}")
                return None
        except requests.exceptions.ConnectionError as e:
            if "NameResolutionError" in str(e) or "Name or service not known" in str(e):
                print(f"  DNS error, waiting 10s...")
                time.sleep(10)
                continue
            else:
                print(f"  Connection error: {e}")
                return None
        except Exception as e:
            print(f"  Error fetching {owner}/{repo}: {e}")
            return None
    return None

def main():
    token = os.environ.get('GITHUB_TOKEN')
    if token:
        print("Using GitHub token for API calls")
    else:
        print("No GITHUB_TOKEN set - using unauthenticated API (60 req/hr limit)")

    # Load manifest
    with open(MANIFEST_PATH) as f:
        candidates = [json.loads(line) for line in f]

    # Filter QUEUED repos that don't have size_category yet
    queued = [c for c in candidates if c.get('state') == 'QUEUED' and not c.get('size_category')]
    print(f"\nScreening {len(queued)} QUEUED repositories (without size_category)...")

    SMALL_LIMIT = 51200      # 50 MB in KB
    MEDIUM_LIMIT = 204800    # 200 MB in KB

    stats = {'SMALL': 0, 'MEDIUM': 0, 'LARGE': 0, 'ERROR': 0, 'SKIPPED': 0}

    for i, c in enumerate(candidates):
        if c.get('state') != 'QUEUED' or c.get('size_category'):
            continue  # Already processed
            
        owner = c.get('owner')
        repo = c.get('repo')
        full_name = c.get('full_name')

        if not owner or not repo:
            print(f"  {c.get('full_name')}: Missing owner/repo, skipping")
            c['repo_size_kb'] = None
            c['size_category'] = 'ERROR'
            continue

        print(f"  {full_name}...", end=' ', flush=True)

        size_kb = get_repo_size(c['owner'], c['repo'])
        time.sleep(0.5)  # Rate limit courtesy

        if size_kb is None:
            c['repo_size_kb'] = None
            c['size_category'] = 'ERROR'
            print("ERROR")
            continue

        c['repo_size_kb'] = size_kb

        if size_kb <= 51200:  # <= 50 MB
            c['size_category'] = 'SMALL'
            print(f"SMALL ({size_kb} KB)")
        elif size_kb <= 204800:  # <= 200 MB
            c['size_category'] = 'MEDIUM'
            print(f"MEDIUM ({size_kb} KB)")
        else:
            c['size_category'] = 'LARGE'
            c['state'] = 'SKIPPED'
            c['skip_reason'] = 'repo_too_large_for_pipeline'
            print(f"LARGE ({size_kb} KB) -> SKIPPED")
        
        # Save after each repo
        save_manifest(candidates)
        time.sleep(0.5)

    # Final summary
    with open(MANIFEST_PATH) as f:
        candidates = [json.loads(line) for line in f]
    cats = Counter(c.get('size_category', 'NONE') for c in candidates)
    for k, v in sorted(Counter(c.get('size_category', 'NONE') for c in candidates).items()):
        print(f"  {k}: {v}")

if __name__ == "__main__":
    import os
    import time
    import requests
    from pathlib import Path
    from collections import Counter
    
    MANIFEST_PATH = Path("data/raw/github/manifests/github_candidates_v1.jsonl")
    main()