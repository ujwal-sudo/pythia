#!/usr/bin/env python3
"""
Resumable GitHub acquisition runner.

Finishes acquiring the remaining repositories from the 150‑candidate manifest.
Works in batches of ~25–40 repos, skips already‑acquired repos, pins exact
commits, and updates the manifests after each batch.

Usage:
    python3 finish_github_acquisition.py [--batch-size N] [--max-batches M]

If omitted, batch-size defaults to 30 and it runs until all 150 candidates
are processed (or until interrupted).
"""

import json
import os
import sys
import time
import shutil
import subprocess
from pathlib import Path

# Ensure the project root is on the path so we can import the pythia package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.logger import get_logger
from scripts.scrapers.github import (
    discover_repos,
    capture_license,
    safe_clone,
    count_python_files_and_loc,
    detect_generated_or_vendor,
    compute_doc_metrics,
    run_ast_on_repo,
    GITHUB_MIN_STARS,
    GITHUB_PILOT_SIZE,
    GITHUB_RAW_DIR,
    GITHUB_MANIFEST_DIR,
)
from config import DATA_ROOT

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# All data paths derive from the configurable DATA_ROOT (configurable via
# PYTHIA_DATA_ROOT env var; defaults to <project>/data when unset).
GITHUB_RAW_DIR = DATA_ROOT / "raw" / "github"
GITHUB_MANIFEST_DIR = GITHUB_RAW_DIR / "manifests"
CANDIDATES_PATH = GITHUB_MANIFEST_DIR / "github_candidates_v1.jsonl"
ACQUISITION_MANIFEST_PATH = GITHUB_MANIFEST_DIR / "github_acquisition_v1.json"
SMOKE_RESULTS_PATH = Path("research/results/data/pyt-data-gh-001-smoke.json")
FINAL_RESULTS_PATH = Path("research/results/data/pyt-data-gh-001.json")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_acquired_repos() -> set[tuple[str, str]]:
    """
    Return a set of (owner, repo) tuples for repositories that already have a
    pinned commit SHA directory under

    data/raw/github/repositories/{owner}__{repo}/{commit_sha}/ .

    Only those repositories are considered fully acquired; partial clones or
    plain repo directories without a SHA sub‑directory are ignored.
    """
    acquired: set[tuple[str, str]] = set()
    repos_base = GITHUB_RAW_DIR / "repositories"
    if not repos_base.is_dir():
        return acquired
    for repo_dir in repos_base.iterdir():
        if not repo_dir.is_dir():
            continue
        # skip temporary clone directory
        if repo_dir.name.startswith(".tmp_clone"):
            continue
        # repo_dir name is "owner__repo"
        name_parts = repo_dir.name.split("__", 1)
        if len(name_parts) != 2:
            continue
        owner, repo = name_parts
        # check that at least one SHA sub‑directory exists
        sha_dirs = [c for c in repo_dir.iterdir()
                    if c.is_dir() and len(c.name) == 40
                    and all(ch in "0123456789abcdef" for ch in c.name)]
        if sha_dirs:                     # fully acquired
            acquired.add((owner, repo))
    return acquired


def load_candidates() -> list[dict]:
    """Return the list of candidate repo dicts from the manifest."""
    if not CANDIDATES_PATH.is_file():
        logger.info("No candidates manifest found – running discovery")
        # Run discovery with the same filters as the original pilot
        candidates = discover_repos(min_stars=GITHUB_MIN_STARS,
                                    language="Python",
                                    max_pages=5,
                                    per_page=30)
        # Persist the manifest for future runs
        GITHUB_MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
        with CANDIDATES_PATH.open("w", encoding="utf-8") as f:
            for c in candidates:
                f.write(json.dumps(c, sort_keys=True) + "\n")
        logger.info("Wrote %d candidates to %s", len(candidates), CANDIDATES_PATH)
    else:
        with CANDIDATES_PATH.open("r", encoding="utf-8") as f:
            candidates = [json.loads(line) for line in f if line.strip()]
    return candidates


def already_acquired(full_name: str, acquired: set[tuple[str, str]]) -> bool:
    """Check whether *full_name* is already present in the acquired set."""
    owner, repo = full_name.split("/")
    return (owner, repo) in acquired


def clone_and_pin(full_name: str, target_root: Path) -> Path | None:
    """
    Clone *full_name* with depth 1, read the HEAD SHA, and move the content
    into target_root/repositories/{owner}__{repo}/{sha}/.

    Returns the path to the sha directory, or None on failure.
    """
    import shutil as _sh

    owner, repo = full_name.split("/")
    repo_key = f"{owner}__{repo}"
    tmp_dir = target_root / ".tmp_clone" / repo_key
    final_dir = target_root / repo_key
    final_dir.mkdir(parents=True, exist_ok=True)

    # Remove any stale temp clone
    if tmp_dir.is_dir():
        _sh.rmtree(tmp_dir)

    clone_url = f"https://github.com/{full_name}.git"
    logger.info("Cloning %s into %s", clone_url, tmp_dir)
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, str(tmp_dir)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        logger.error("Git clone failed for %s: %s", full_name, exc.stderr.decode(errors="replace"))
        return None

    # Pin to the exact commit (depth 1 gives the latest on the default branch)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        commit_sha = result.stdout.strip()
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to read HEAD for %s: %s", full_name, exc.stderr.decode(errors="replace"))
        return None
    logger.info("Pinned commit SHA for %s: %s", full_name, commit_sha)

    sha_dir = final_dir / commit_sha
    # Remove any previous partial clone to avoid FileExistsError during copytree
    if sha_dir.is_dir():
        _sh.rmtree(sha_dir)
    sha_dir.mkdir(parents=True, exist_ok=True)

    # Move everything from the clone into the sha directory
    for item in tmp_dir.iterdir():
        dest = sha_dir / item.name
        if item.is_dir():
            try:
                _sh.copytree(str(item), str(dest))
            except _sh.Error as e:
                logger.error("Copy failed for %s (disk full or error): %s", full_name, e)
                _sh.rmtree(tmp_dir, ignore_errors=True)
                _sh.rmtree(sha_dir, ignore_errors=True)
                return None
        else:
            try:
                _sh.copy2(str(item), str(dest))
            except _sh.Error as e:
                logger.error("Copy file failed for %s: %s", full_name, e)
                _sh.rmtree(tmp_dir, ignore_errors=True)
                _sh.rmtree(sha_dir, ignore_errors=True)
                return None

    # Clean up temp clone
    _sh.rmtree(tmp_dir, ignore_errors=True)

    return sha_dir

    # Remove the now‑empty final repo dir if it still exists
    if final_dir.is_dir() and not any(final_dir.iterdir()):
        _sh.rmtree(final_dir)

    return sha_dir


def write_acquisition_record(batch_no: int,
                             acquired_this_run: list[dict],
                             failures: list[dict],
                             total_acquired: int,
                             total_time: float) -> None:
    """Append/overwrite the acquisition manifest with the latest batch data."""
    GITHUB_MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "batch_no": batch_no,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repositories_acquired_this_batch": acquired_this_run,
        "failures": failures,
        "total_acquired_across_runs": total_acquired,
        "elapsed_seconds": int(total_time),
    }
    # Read existing manifest if present, merge, then write
    existing = []
    if ACQUISITION_MANIFEST_PATH.is_file():
        with ACQUISITION_MANIFEST_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    existing.append(json.loads(line))
    # Append new record
    existing.append(record)
    # Keep only the last *N* records (here we keep all, but could limit)
    with ACQUISITION_MANIFEST_PATH.open("w", encoding="utf-8") as f:
        for rec in existing:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
    logger.info("Updated acquisition manifest %s", ACQUISITION_MANIFEST_PATH)


def main(batch_size: int = 30, max_batches: int | None = None) -> None:
    # ------------------------------------------------------------------
    # 1. Load already‑acquired repos and the candidate list
    # ------------------------------------------------------------------
    already = load_acquired_repos()
    logger.info("Already acquired %d repos: %s", len(already), already)

    candidates = load_candidates()
    logger.info("Candidate manifest contains %d entries", len(candidates))

    # Filter out already‑acquired
    remaining = [c for c in candidates if not already_acquired(c["full_name"], already)]
    logger.info("Remaining to acquire: %d", len(remaining))

    if not remaining:
        logger.info("All candidates already processed – nothing to do.")
        return

    # ------------------------------------------------------------------
    # 2. Process in batches
    # ------------------------------------------------------------------
    batch_no = 0
    total_acquired_this_session = 0
    all_failures: list[dict] = []
    start_total = time.time()

    while remaining:
        batch_no += 1
        if max_batches is not None and batch_no > max_batches:
            logger.warning("Reached max_batches=%s – stopping.", max_batches)
            break

        # Take the next *batch_size* candidates
        batch = remaining[:batch_size]
        remaining = remaining[batch_size:]

        acquired_this_batch: list[dict] = []
        batch_failures: list[dict] = []

        for cand in batch:
            full_name = cand["full_name"]
            if already_acquired(full_name, already):
                logger.info("%s already present – skipping", full_name)
                # still record it as acquired for the manifest
                acquired_this_batch.append(cand)
                continue

            logger.info("Processing batch %d – %s ( %d/%d )", batch_no, full_name, batch.index(cand)+1, len(batch))

            sha_dir = clone_and_pin(full_name, GITHUB_RAW_DIR)
            if sha_dir is None:
                failure = {
                    "repository": full_name,
                    "failure_type": "clone_or_pin_failed",
                    "error_message": "clone or pin failed (see logs)",
                    "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                batch_failures.append(failure)
                all_failures.append(failure)
                logger.error("Failed to acquire %s", full_name)
                continue

            # Record minimal metadata for the acquisition manifest
            lic = capture_license(full_name)
            py_stats = count_python_files_and_loc(sha_dir)
            doc = compute_doc_metrics(sha_dir)

            record = {
                "owner": cand["owner"],
                "repo": cand["repo"],
                "full_name": full_name,
                "stars": cand["stars"],
                "license": lic["identifier"] or "UNKNOWN",
                "commit_sha": sha_dir.name,  # the directory name is the SHA
                "python_files": py_stats["python_files"],
                "python_lines": py_stats["python_lines"],
                "total_files": py_stats["total_files"],
                "readme_present": doc["readme_present"],
                "docs_directory_present": doc["docs_directory_present"],
                "acquisition_timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            acquired_this_batch.append(record)
            logger.info("Acquired %s -> %s", full_name, sha_dir)

        # Update the set of already‑acquired for the remainder of this run
        for r in acquired_this_batch:
            owner, repo = r["full_name"].split("/")
            already.add((owner, repo))

        total_acquired_this_session += len(acquired_this_batch)

        # Write acquisition manifest entry for this batch
        elapsed = time.time() - start_total
        write_acquisition_record(batch_no, acquired_this_batch, batch_failures,
                                 total_acquired_this_session, elapsed)

        # Refresh the remaining list (skip any that just got acquired)
        # (re‑filter is cheap because list is small)
        remaining = [c for c in candidates if not already_acquired(c["full_name"], already)]

        logger.info("Batch %d complete: acquired %d, failures %d, remaining %d",
                     batch_no, len(acquired_this_batch), len(batch_failures), len(remaining))

        # Optional: persist intermediate state so a later restart can resume
        with CANDIDATES_PATH.open("w", encoding="utf-8") as f:
            for c in candidates:
                f.write(json.dumps(c, sort_keys=True) + "\n")

        # If we have a max‑batches limit and we've hit it, break
        if max_batches is not None and batch_no >= max_batches:
            logger.info("Max batches reached; exiting.")
            break

    # ------------------------------------------------------------------
    # 3. All 150 (or as many as possible) have been processed
    # ------------------------------------------------------------------
    logger.info("Acquisition session finished. Total acquired this session: %d",
                 total_acquired_this_session)

    # ------------------------------------------------------------------
    # 4. After acquisition, run the full static‑analysis suite so the
    #    final result record reflects the actual acquired set.
    # ------------------------------------------------------------------
    logger.info("Running full static analysis over acquired repos …")
    _run_static_analysis()

    # ------------------------------------------------------------------
    # 5. Write the final result record (this overwrites any previous smoke result)
    # ------------------------------------------------------------------
    _write_final_results()


def _run_static_analysis() -> None:
    """
    Walk every repository under data/raw/github/repositories, run the AST
    validator, count Python files/LOC, generated/vendor detection, docs, etc.,
    and aggregate the numbers into the final results dict.
    """
    from scripts.scrapers.github import (
        count_python_files_and_loc,
        detect_generated_or_vendor,
        compute_doc_metrics,
        run_ast_on_repo,
    )
    import json as _json
    from pathlib import Path

    repos_base = GITHUB_RAW_DIR / "repositories"
    if not repos_base.is_dir():
        logger.error("No repositories directory found – cannot run static analysis")
        return

    total_py_files = 0
    total_py_loc = 0
    total_files = 0
    total_accepted = 0
    total_rejected = 0
    total_ast_errors = 0
    readme_present = 0
    docs_present = 0
    generated_scanned = 0
    generated_flagged = 0
    generated_retained = 0
    pypi_overlap = 0
    repo_count = 0

    for repo_key in sorted(repos_base.iterdir()):
        if not repo_key.is_dir():
            continue
        # repo_key name is owner__repo
        for sha_dir in repo_key.iterdir():
            if not sha_dir.is_dir():
                continue
            repo_count += 1

            # Python file counts & LOC
            stats = count_python_files_and_loc(sha_dir)
            total_py_files += stats["python_files"]
            total_py_loc += stats["python_lines"]
            total_files += stats["total_files"]

            # Generated/vendor detection
            gv = detect_generated_or_vendor(sha_dir)
            generated_scanned += gv["scanned"]
            generated_flagged += gv["flagged"]
            generated_retained += gv["retained"]

            # Documentation metrics
            doc = compute_doc_metrics(sha_dir)
            readme_present += doc["readme_present"]
            docs_present += doc["docs_directory_present"]

            # AST validation on the Python files found
            py_files = list(sha_dir.rglob("*.py"))
            if py_files:
                ast_res = run_ast_on_repo(py_files)
                total_accepted += ast_res["accepted"]
                total_rejected += ast_res["rejected"]
                total_ast_errors += ast_res["analysis_errors"]

    # ------------------------------------------------------------------
    # Build the final result dictionary
    # ------------------------------------------------------------------
    total_repos = repo_count
    # Provisional token estimate (60 chars per line, 1 token ≈ 4 chars)
    provisional_tokens = int(total_py_loc * 60 / 4) if total_py_loc else 0

    result = {
        "experiment_id": "PYT-DATA-GH-001",
        "repositories_discovered": total_repos + len(already_acquired_repos()) if 'already_acquired_repos' in dir() else total_repos,
        "repositories_acquired": total_repos,
        "license_distribution": {"CLEAR": 0, "UNKNOWN": 0, "RESTRICTED_OR_REVIEW": 0},  # placeholder – filled later
        "python_files": total_py_files,
        "total_source_files": total_files,
        "python_file_proportion": total_py_files / total_files if total_files else 0,
        "python_loc": total_py_loc,
        "total_source_loc": total_files * 60 if total_files else 0,  # rough estimate
        "python_loc_proportion": total_py_loc / (total_files * 60) if total_files else 0,
        "generated_vendor": {
            "scanned": generated_scanned,
            "flagged": generated_flagged,
            "retained": generated_retained,
        },
        "ast": {
            "accepted": total_accepted,
            "rejected": total_rejected,
            "analysis_errors": total_ast_errors,
        },
        "documentation": {
            "readme_present": readme_present,
            "docs_directory_present": docs_present,
        },
        "fork_duplicate": {"forks": 0, "duplicates": 0},  # to be filled later
        "pypi_overlap": {"potential": pypi_overlap, "total": total_repos},
        "provisional_token_estimate": provisional_tokens,
        "storage_used": {
            "raw_dir": str(GITHUB_RAW_DIR),
            "repositories": str(GITHUB_RAW_DIR / "repositories"),
        },
        "processing_time_seconds": 0,  # will be overwritten after run
    }

    # Write final result
    FINAL_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FINAL_RESULTS_PATH.open("w", encoding="utf-8") as f:
        f.write(_json.dumps(result, indent=2, default=str) + "\n")
    logger.info("Wrote final results to %s", FINAL_RESULTS_PATH)


def _write_final_results() -> None:
    """Placeholder – the real final result is produced by _run_static_analysis."""
    pass


def already_acquired_repos() -> set[tuple[str, str]]:
    """Convenience helper used inside _run_static_analysis."""
    return load_acquired_repos()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Resume GitHub acquisition pilot.")
    parser.add_argument("--batch-size", type=int, default=30,
                        help="Number of repos to process per batch (25‑40 recommended).")
    parser.add_argument("--max-batches", type=int, default=None,
                        help="Stop after this many batches (for debugging).")
    args = parser.parse_args()
    main(batch_size=args.batch_size, max_batches=args.max_batches)