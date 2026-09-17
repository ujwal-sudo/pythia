from pathlib import Path
import time
import json
import logging
import subprocess
import os
import sys
from datetime import datetime, timezone

import requests

# Ensure the project root (parent of scripts/) is on sys.path so we can import config
_proj_root = str(Path(__file__).resolve().parent.parent)
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

# Import Pythia configuration constants
from config import (
    GITHUB_RAW_DIR,
    GITHUB_MANIFEST_DIR,
    GITHUB_PILOT_SIZE,
    GITHUB_MIN_STARS,
    GITHUB_API_RATE_LIMIT_PER_MIN,
    GITHUB_API_BACKOFF_SECONDS,
    GITHUB_PAGINATION_PER_PAGE,
    GITHUB_PAGINATION_MAX_PAGES,
)

# Append project root again (redundant but safe) and import logger
sys.path.insert(0, _proj_root)
from scripts.logger import get_logger

logger = get_logger(__name__)

GITHUB_API_URL = "https://api.github.com/search/repositories"
GITHUB_REPO_URL = "https://api.github.com/repos/{owner}/{repo}"

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _rate_limit_sleep(page: int, per_page: int, max_pages: int) -> None:
    """Simple back‑off to stay under the unauthenticated GitHub rate limit."""
    # We approximate: 30 requests per minute → 2 s per request.
    # Additionally add a small jitter.
    delay = GITHUB_API_BACKOFF_SECONDS
    logger.debug("Sleeping %.1f s (rate‑limit) before page %d", delay, page)
    time.sleep(delay)


def _request(url: str, headers: dict | None = None, retry: int = 3) -> dict:
    """Perform a GET request with simple retry & back‑off."""
    for attempt in range(retry + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (403, 429) and attempt < retry:
                # Simple exponential back‑off
                wait = (2 ** attempt) * GITHUB_API_BACKOFF_SECONDS
                logger.warning(
                    "GitHub returned %s, retrying in %.1f s (attempt %s/%s)",
                    resp.status_code,
                    wait,
                    attempt + 1,
                    retry,
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
        except requests.RequestException as exc:
            if attempt < retry:
                wait = (2 ** attempt) * GITHUB_API_BACKOFF_SECONDS
                logger.warning("Request error %s, retrying in %.1f s: %s", exc, wait, attempt + 1)
                time.sleep(wait)
                continue
            logger.error("Request failed after %s retries: %s", retry + 1, exc)
            raise
    raise RuntimeError("Max retries exceeded for GitHub request")


# ---------------------------------------------------------------------------
# Step 2 – Discovery
# ---------------------------------------------------------------------------

def discover_repos(
    min_stars: int = GITHUB_MIN_STARS,
    language: str = "Python",
    max_pages: int = GITHUB_PAGINATION_MAX_PAGES,
    per_page: int = GITHUB_PAGINATION_PER_PAGE,
) -> list[dict]:
    """
    Search GitHub for public Python repos with at least ``min_stars``.

    Returns a list of dictionaries containing the minimal metadata we need:
    full_name, owner, repo, stars, forks, language, license_key,
    default_branch, url, topics, archived, size, created_at, updated_at.
    """
    query = f"language:{language}+stars:>{min_stars}+is:public"
    candidates: list[dict] = []

    for page in range(1, max_pages + 1):
        _rate_limit_sleep(page, per_page, max_pages)
        url = f"{GITHUB_API_URL}?q={query}&per_page={per_page}&page={page}"
        logger.info("Fetching GitHub search page %d", page)
        data = _request(url)

        total = data.get("total_count", 0)
        logger.info("Page %d: total_count=%d", page, total)

        items = data.get("items", [])
        if not items:
            logger.warning("No items on page %d", page)
            break

        for item in items:
            meta = {
                "full_name": item.get("full_name"),
                "owner": item.get("owner", {}).get("login"),
                "repo": item.get("name"),
                "stars": item.get("stargazers_count", 0),
                "forks": item.get("forks_count", 0),
                "language": item.get("language"),
                "license_key": item.get("license", {}).get("key") if item.get("license") else None,
                "default_branch": item.get("default_branch", "main"),
                "url": item.get("html_url"),
                "topics": item.get("topics", []),
                "archived": item.get("archived", False),
                "size": item.get("size", 0),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            }
            candidates.append(meta)

        # Stop early if we already have enough for the pilot
        if len(candidates) >= GITHUB_PILOT_SIZE:
            logger.info("Reached pilot size %d, stopping discovery", GITHUB_PILOT_SIZE)
            break

    # Trim to exactly the pilot size (or fewer if not enough repos found)
    candidates = candidates[:GITHUB_PILOT_SIZE]
    logger.info("Discovery finished with %d candidates", len(candidates))
    return candidates


# ---------------------------------------------------------------------------
# Step 3 – License (metadata only)
# ---------------------------------------------------------------------------

def capture_license(full_name: str) -> dict:
    """
    Pull the SPDX license identifier for a repository.

    Returns a dict with keys:
    - identifier: the SPDX string (e.g. "MIT", "Apache-2.0") or None
    - url: license URL if present
    - raw: the license API payload for possible later parsing

    If the GitHub API returns a 403/429 rate‑limit error the function returns
    ``identifier = None`` so that the caller can treat the license as ``UNKNOWN``
    without aborting the repository acquisition.
    """
    owner, repo = full_name.split("/")
    url = GITHUB_REPO_URL.format(owner=owner, repo=repo)
    try:
        data = _request(url)
    except requests.HTTPError as exc:
        # 403/429 = rate limit; treat as unknown licence, not a fatal error
        if exc.response is not None and exc.response.status_code in (403, 429):
            logger.warning("GitHub license API %s for %s – marking licence UNKNOWN", exc.response.status_code, full_name)
            return {"identifier": None, "url": None, "raw": None}
        raise
    license_info = data.get("license", {})
    if not license_info:
        return {"identifier": None, "url": None, "raw": None}
    identifier = license_info.get("spdx_id")
    license_url = license_info.get("url")
    return {"identifier": identifier, "url": license_url, "raw": license_info}


# ---------------------------------------------------------------------------
# Step 4 – Exact commit / safe acquisition
# ---------------------------------------------------------------------------

def safe_clone(full_name: str, target_root: Path) -> Path:
    """
    Clone the repository into a deterministic directory:

    target_root/repositories/{owner}__{repo}/{commit_sha}/

    Returns the Path to the commit‑sha directory.
    Only ``git clone`` (depth 1) is used; no code is executed.
    """
    import shutil

    owner, repo = full_name.split("/")
    repo_key = f"{owner}__{repo}"
    tmp_dir = target_root / ".tmp_clone" / repo_key
    # Clean any previous temp clone
    if tmp_dir.is_dir():
        shutil.rmtree(tmp_dir)

    # Ensure the final storage layout exists
    final_dir = target_root / "repositories" / repo_key
    final_dir.mkdir(parents=True, exist_ok=True)

    clone_url = f"https://github.com/{full_name}.git"
    logger.info("Cloning %s into %s", clone_url, tmp_dir)
    subprocess.run(
        ["git", "clone", "--depth", "1", clone_url, str(tmp_dir)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Pin to the exact commit of the default branch (depth 1 gives HEAD)
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_dir,
        capture_output=True,
        text=True,
    )
    commit_sha = result.stdout.strip()
    logger.info("Pinned commit SHA: %s", commit_sha)

    sha_dir = final_dir / commit_sha
    sha_dir.mkdir(parents=True, exist_ok=True)

    # Move all files from the cloned repo into the sha directory
    for item in tmp_dir.iterdir():
        dest = sha_dir / item.name
        if item.is_dir():
            shutil.copytree(str(item), str(dest))
        else:
            shutil.copy2(str(item), str(dest))

    # Remove the temporary clone
    shutil.rmtree(tmp_dir)

    return sha_dir


# ---------------------------------------------------------------------------
# Step 6 – Static analysis (file counts, LOC, generated/vendor detection)
# ---------------------------------------------------------------------------

def count_python_files_and_loc(root_dir: Path) -> dict:
    """
    Walk the repository and count:
    - total files
    - Python files (extension .py)
    - total lines of code (approximate, ignoring empty/comment-only lines)
    - Python LOC
    """
    total_files = 0
    py_files = 0
    total_loc = 0
    py_loc = 0

    for dirpath, _dirnames, filenames in os.walk(root_dir):
        for fname in filenames:
            total_files += 1
            fpath = Path(dirpath) / fname
            if fpath.suffix == ".py":
                py_files += 1
                # Count lines, skipping blank & comment‑only lines
                try:
                    lines = fpath.read_text(errors="replace").splitlines()
                    loc = sum(1 for line in lines if line.strip() and not line.strip().startswith("#"))
                    py_loc += loc
                    total_loc += len(lines)
                except Exception as exc:
                    logger.warning("Could not read %s: %s", fpath, exc)
                    total_loc += 0

    return {
        "total_files": total_files,
        "python_files": py_files,
        "total_lines": total_loc,
        "python_lines": py_loc,
    }


def detect_generated_or_vendor(root_dir: Path) -> dict:
    """
    Flag files residing in or named with common generated/vendor directories,
    and files whose header contains "DO NOT EDIT", "GENERATED", or "AUTOGENERATED".

    Returns counts of files scanned, flagged, and retained (not flagged).
    """
    generated_dirs = {
        "vendor",
        "vendored",
        "third_party",
        "external",
        "node_modules",
        "dist",
        "build",
        "generated",
        "autogenerated",
    }
    flagged = 0
    scanned = 0

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Check if any component of the path is a generated/vendor dir
        parts = Path(dirpath).relative_to(root_dir).parts
        dirnames[:] = [d for d in dirnames if d not in generated_dirs]  # prune walk
        for d in dirnames:
            if d in generated_dirs:
                # entire subtree flagged
                for f in filenames:
                    scanned += 1
                    flagged += 1
        for fname in filenames:
            scanned += 1
            fpath = Path(dirpath) / fname
            # Header check (first 5 lines)
            try:
                header_lines = fpath.read_text(errors="replace").splitlines()[:5]
                header_text = "\n".join(header_lines)
                if any(marker in header_text for marker in ("DO NOT EDIT", "GENERATED", "AUTOGENERATED")):
                    flagged += 1
            except Exception:
                pass

    retained = scanned - flagged
    return {
        "scanned": scanned,
        "flagged": flagged,
        "retained": retained,
    }


# ---------------------------------------------------------------------------
# Step 9 – AST validation
# ---------------------------------------------------------------------------

from scripts.validators.ast_validator import validate_python  # type: ignore


def run_ast_on_repo(python_files: list[Path]) -> dict:
    """
    Run the AST validator on each supplied Python file.

    Returns a dict with counts of accepted, rejected, and analysis errors,
    plus a list of rejection reasons.
    """
    accepted = 0
    rejected = 0
    errors = 0
    rejection_reasons: list[str] = []

    for pfile in python_files:
        result = validate_python(pfile.read_text(errors="replace"))
        if result.is_valid:
            accepted += 1
        else:
            rejected += 1
            reason_parts = []
            if result.error_type:
                reason_parts.append(f"syntax/{result.error_type}")
            if result.error_message:
                reason_parts.append(result.error_message)
            # Record any analysis errors
            if result.analysis_error_type:
                errors += 1
                reason_parts.append(f"analysis/{result.analysis_error_type}")
            rejection_reasons.append(" | ".join(reason_parts) if reason_parts else "unknown")

    return {
        "accepted": accepted,
        "rejected": rejected,
        "analysis_errors": errors,
        "rejection_reasons": rejection_reasons,
    }


# ---------------------------------------------------------------------------
# Step 10 – Documentation metrics
# ---------------------------------------------------------------------------

def compute_doc_metrics(root_dir: Path) -> dict:
    """
    Very lightweight documentation metrics:
    - README presence
    - docs directory presence
    - Count of modules with docstrings (via simple heuristic: file has a docstring at top)
    - Function docstring ratio, class docstring ratio (placeholder counts)
    """
    readme_path = root_dir / "README.md"
    docs_dir = root_dir / "docs"

    readme_present = readme_path.is_file()
    docs_present = docs_dir.is_dir()

    # Count Python files and check for docstring at module level
    py_files = list(root_dir.rglob("*.py"))
    total_py = len(py_files)
    files_with_module_docstring = 0
    files_with_function_docstring = 0
    files_with_class_docstring = 0

    for pf in py_files:
        try:
            src = pf.read_text(errors="replace")
            # Very naive checks
            if '"""' in src.split("\n")[1:3] or "'''" in src.split("\n")[1:3]:
                files_with_module_docstring += 1
            # Count def and class lines with docstring following
            # (very rough)
            import re
            defs = re.findall(r"^(\"\"\"|''')", src, re.MULTILINE)
            # placeholder counts
        except Exception:
            pass

    # Return whatever we could compute; many fields will be zero/None for pilot.
    return {
        "readme_present": readme_present,
        "docs_directory_present": docs_present,
        "total_python_files": total_py,
        "files_with_module_docstring": files_with_module_docstring,
        "files_with_function_docstring": files_with_function_docstring,
        "files_with_class_docstring": files_with_class_docstring,
    }


# ---------------------------------------------------------------------------
# Step 12 – PyPI overlap (metadata only)
# ---------------------------------------------------------------------------

def capture_pypi_overlap(full_name: str) -> dict:
    """
    Very high‑level PyPI overlap check: does the repo name match a known
    PyPI package?  We only look at the repository name (last component) and
    attempt a simple presence check against a static list shipped with the
    pipeline (empty by default).  No file‑hash comparison is performed here.

    Returns a dict with potential_pypi_overlap flag.
    """
    repo_name = full_name.split("/")[-1]
    # Placeholder: load a list if available; otherwise treat as unknown.
    # In a real deployment this would be a json file of known PyPI package names.
    return {
        "potential_pypi_overlap": None,  # unknown until full cross‑source hash run
        "repo_name": repo_name,
    }


# ---------------------------------------------------------------------------
# Step 13 – Token estimation (provisional)
# ---------------------------------------------------------------------------

def provisional_token_estimate(py_loc: int) -> int:
    """
    Very rough conversion: 1 token ≈ 4 characters ≈ 2 words.
    Using a very rough factor of 4 chars per token.
    """
    # characters approximated as py_loc * avg_line_len (assume 60 chars per line)
    estimated_chars = py_loc * 60
    tokens = int(estimated_chars / 4)
    return tokens


# ---------------------------------------------------------------------------
# Manifest generation
# ---------------------------------------------------------------------------

def write_candidates_manifest(candidates: list[dict], path: Path) -> None:
    """Write one JSONL line per candidate repository."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(c, sort_keys=True) + "\n")
    logger.info("Wrote candidates manifest to %s", path)


def write_acquisition_manifest(acquisition_record: dict, path: Path) -> None:
    """Write a single‑line JSON summary of the acquisition run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(acquisition_record, sort_keys=True) + "\n")
    logger.info("Wrote acquisition manifest to %s", path)


# ---------------------------------------------------------------------------
# Main driver for the pilot
# ---------------------------------------------------------------------------

def run_pilot() -> dict:
    """
    Execute the full pilot workflow:
    1. Discover candidates
    2. For each: capture license, clone, static analysis, AST, docs, etc.
    3. Produce manifests and a result summary.

    Returns a summary dictionary with all measured metrics.
    """
    # ------------------------------------------------------------------
    # 1. Discovery
    # ------------------------------------------------------------------
    candidates = discover_repos()
    if not candidates:
        logger.error("No candidates discovered – aborting pilot")
        return {"error": "no_candidates"}

    # ------------------------------------------------------------------
    # 2. Prepare storage directories
    # ------------------------------------------------------------------
    GITHUB_RAW_DIR.mkdir(parents=True, exist_ok=True)
    GITHUB_MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 3. Process each candidate
    # ------------------------------------------------------------------
    summary = {
        "repositories_discovered": len(candidates),
        "repositories_acquired": 0,
        "licenses": {"CLEAR": 0, "UNKNOWN": 0, "RESTRICTED_OR_REVIEW": 0},
        "python_proportion": {"files": 0, "loc": 0},
        "total_py_files": 0,          # track total Python files across repos
        "generated_vendor": {"scanned": 0, "flagged": 0, "retained": 0},
        "ast": {"accepted": 0, "rejected": 0, "errors": 0},
        "documentation": {"readme": 0, "docs_dir": 0},
        "forks": {"primary": 0, "fork": 0},
        "pypi_overlap": {"potential": 0, "total": 0},
        "token_estimate": 0,
        "total_py_loc": 0,
        "total_files": 0,
    }

    for idx, cand in enumerate(candidates, start=1):
        full_name = cand["full_name"]
        logger.info("Processing %s (%d/%d)", full_name, idx, len(candidates))

        # --- License ---------------------------------------------------
        lic_info = capture_license(full_name)
        lic_id = lic_info["identifier"]
        # Classify simply for the pilot
        if lic_id in ("MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Unlicense"):
            lic_category = "CLEAR"
        elif lic_id is None:
            lic_category = "UNKNOWN"
        else:
            # Anything else (GPL, AGPL, MPL, etc.) we treat as RESTRICTED_OR_REVIEW
            lic_category = "RESTRICTED_OR_REVIEW"
        summary["licenses"][lic_category] += 1

        # --- Safe clone ------------------------------------------------
        sha_dir = safe_clone(full_name, GITHUB_RAW_DIR)
        summary["repositories_acquired"] += 1

        # --- Static analysis -----------------------------------------
        stats = count_python_files_and_loc(sha_dir)
        summary["total_files"] += stats["total_files"]
        summary["total_py_files"] += stats["python_files"]
        summary["total_py_loc"] += stats["python_lines"]

        # Generated/vendor detection
        gv = detect_generated_or_vendor(sha_dir)
        summary["generated_vendor"]["scanned"] += gv["scanned"]
        summary["generated_vendor"]["flagged"] += gv["flagged"]
        summary["generated_vendor"]["retained"] += gv["retained"]

        # --- Documentation metrics ------------------------------------
        doc = compute_doc_metrics(sha_dir)
        summary["documentation"]["readme"] += 1 if doc["readme_present"] else 0
        summary["documentation"]["docs_dir"] += 1 if doc["docs_directory_present"] else 0

        # --- AST validation on Python files ----------------------------
        py_files = list(sha_dir.rglob("*.py"))
        # Filter out files that live inside flagged vendor dirs (simple)
        # We'll just run AST on all python files found; the validator will reject generated.
        ast_results = run_ast_on_repo(py_files)
        summary["ast"]["accepted"] += ast_results["accepted"]
        summary["ast"]["rejected"] += ast_results["rejected"]
        summary["ast"]["errors"] += ast_results["analysis_errors"]

        # --- PyPI overlap (metadata only) ---------------------------
        pypi = capture_pypi_overlap(full_name)
        if pypi["potential_pypi_overlap"] is True:
            summary["pypi_overlap"]["potential"] += 1
        summary["pypi_overlap"]["total"] += 1

        # Estimate provisional tokens
        summary["token_estimate"] += provisional_token_estimate(stats["python_lines"])

        # ------------------------------------------------------------------
        # Record per‑repo metadata (could be appended to manifest later)
        # ------------------------------------------------------------------
        # (We skip writing individual records here; the candidate manifest already
        #  contains the base metadata.)

    # ------------------------------------------------------------------
    # 4. Write manifests
    # ------------------------------------------------------------------
    # Aggregate python proportion before writing
    summary["python_proportion"] = {
        "files": summary["total_py_files"],
        "loc": summary["total_py_loc"],
    }

    write_candidates_manifest(candidates, GITHUB_MANIFEST_DIR / "github_candidates_v1.jsonl")

    acquisition_summary = {
        "experiment_id": "PYT-DATA-GH-001",
        "pilot_size": GITHUB_PILOT_SIZE,
        "repositories_acquired": summary["repositories_acquired"],
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "license_distribution": summary["licenses"],
        "python_proportion_files": summary["python_proportion"]["files"]
        if False  # we have file counts separately
        else summary["total_files"],
        "python_loc": summary["total_py_loc"],
        "generated_vendor": summary["generated_vendor"],
        "ast": summary["ast"],
        "documentation": summary["documentation"],
        "forks": summary["forks"],
        "pypi_overlap": summary["pypi_overlap"],
        "provisional_token_estimate": summary["token_estimate"],
    }
    write_acquisition_manifest(acquisition_summary, GITHUB_MANIFEST_DIR / "github_acquisition_v1.json")

    # ------------------------------------------------------------------
    # 5. Return overall summary
    # ------------------------------------------------------------------
    return summary


# ---------------------------------------------------------------------------
# Allow running as a script
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    result = run_pilot()
    # Pretty‑print the most important bits
    import json as _json
    print(_json.dumps(result, indent=2, default=str))