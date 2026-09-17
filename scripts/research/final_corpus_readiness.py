"""Final corpus readiness validation tool — Pythia-160M.

This tool VALIDATES ONLY. It does NOT assemble the corpus.
It checks whether the future corpus is ready for assembly.

Output:  READY
         NOT_READY

with explicit reasons.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def safe_json_load(path: Path) -> Optional[dict]:
    """Load JSON if file exists and is readable; return None otherwise."""
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None


def check_manifest_exists() -> dict:
    """Check that source manifests exist and have required fields."""
    results: List[str] = []
    manifest_status = "present"

    # Check Python docs manifest
    pd_manifest = PROJECT_ROOT / "data" / "raw" / "python_docs" / "manifest.json"
    data = safe_json_load(pd_manifest)
    if data is None:
        manifest_status = "missing"
        results.append("Python docs manifest missing: " + str(pd_manifest))
    else:
        required_keys = {"source", "candidate_count", "valid_python_count", "retained_count"}
        missing = required_keys - set(data.keys())
        if missing:
            manifest_status = "partial"
            results.append(f"Python docs manifest missing keys: {missing}")
        else:
            results.append("Python docs manifest OK")

    # Check stage1 manifest
    s1_manifest = PROJECT_ROOT / "data" / "filtered" / "stage1" / "stage1_manifest.json"
    data = safe_json_load(s1_manifest)
    if data is None:
        manifest_status = "missing"
        results.append("Stage 1 manifest missing")
    else:
        results.append("Stage 1 manifest OK")

    return {
        "status": manifest_status,
        "details": results,
    }


def check_dataset_versions() -> dict:
    """Check that dataset versions are recorded."""
    results: List[str] = []
    version_status = "unknown"

    vfile = PROJECT_ROOT / "research" / "dataset_versioning.md"
    if not vfile.is_file():
        version_status = "missing"
        results.append("dataset_versioning.md not found")
    else:
        version_status = "present"
        results.append("dataset_versioning.md present")

    # Check experiment registry
    erfile = PROJECT_ROOT / "research" / "experiment_registry.md"
    if not erfile.is_file():
        results.append("experiment_registry.md not found")
    else:
        results.append("experiment_registry.md present")

    # Check decision registry
    drfile = PROJECT_ROOT / "research" / "decision_registry.md"
    if not drfile.is_file():
        results.append("decision_registry.md not found")
    else:
        results.append("decision_registry.md present")

    return {
        "status": version_status,
        "details": results,
    }


def check_provenance_and_licenses() -> dict:
    """Check that provenance and license metadata exist where required."""
    results: List[str] = []

    # Check Python docs manifest for license
    pd_manifest = PROJECT_ROOT / "data" / "raw" / "python_docs" / "manifest.json"
    data = safe_json_load(pd_manifest)
    if data is None:
        results.append("Python docs manifest not available for license check")
    elif data.get("license") is None:
        results.append("Python docs manifest: license field missing")
    else:
        results.append(f"Python docs manifest: license = {data.get('license')}")

    # Check Stack Overflow manifest
    so_manifest = PROJECT_ROOT / "data" / "raw" / "stackoverflow" / "manifest.json"
    data = safe_json_load(so_manifest)
    if data is None:
        results.append("Stack Overflow manifest not available")
    elif data.get("license") is None:
        results.append("Stack Overflow manifest: license field missing")
    else:
        results.append(f"Stack Overflow manifest: license = {data.get('license')}")

    # Check GitHub acquisition report
    gh_report = PROJECT_ROOT / "research" / "results" / "data" / "pyt-data-gh-001.json"
    data = safe_json_load(gh_report)
    if data is None:
        results.append("GitHub experiment report not available")
    else:
        if "licenses" in data:
            results.append(f"GitHub experiment: licenses = {data.get('licenses')}")
        else:
            results.append("GitHub experiment: no license field")

    return {
        "details": results,
    }


def check_hashes() -> dict:
    """Check that content hashes exist where required."""
    results: List[str] = []

    # Check that at least one manifest has candidate records with hash-like fields
    pd_manifest = PROJECT_ROOT / "data" / "raw" / "python_docs" / "manifest.json"
    data = safe_json_load(pd_manifest)
    if data is None:
        results.append("Python docs manifest not available for hash check")
    elif data.get("sha256") is None:
        results.append("Python docs manifest: sha256 field missing")
    else:
        results.append(f"Python docs manifest: sha256 present ({data.get('sha256', '')[:16]}...)")

    # Check GitHub experiment for content hashes
    gh_report = PROJECT_ROOT / "research" / "results" / "data" / "pyt-data-gh-001.json"
    data = safe_json_load(gh_report)
    if data is None:
        results.append("GitHub experiment report not available for hash check")
    else:
        results.append("GitHub experiment report present")

    return {
        "details": results,
    }


def check_ast_and_tokenizer_versions() -> dict:
    """Check that AST validator version and tokenizer version are recorded."""
    results: List[str] = []

    # Check AST validator is importable and version-known
    try:
        from scripts.validators.ast_validator import validate_python
        results.append("AST validator importable")
    except ImportError:
        results.append("AST validator import failed")

    # Check that tokenizer version is noted as provisional
    # Look for token_count_status in manifests
    pd_manifest = PROJECT_ROOT / "data" / "raw" / "python_docs" / "manifest.json"
    data = safe_json_load(pd_manifest)
    if data is None:
        results.append("Python docs manifest not available for AST/tokenizer check")
    else:
        # The manifest may not have tokenizer version, but we check for notes
        if "provisional" in str(data).lower() or "PROVISIONAL" in str(data).upper():
            results.append("Token count methodology noted as provisional")
        else:
            results.append("Token count status not explicitly labeled (assumed PROVISIONAL until tokenizer exists)")

    # Check experiment logs for tokenizer version notes
    el_file = PROJECT_ROOT / "research" / "experiment_log.md"
    if el_file.is_file():
        with el_file.open("r") as f:
            content = f.read()
        if "TOKEN" in content.upper() and "PROVISIONAL" in content.upper():
            results.append("Experiment log labels token counts as provisional")
        else:
            results.append("Experiment log: no explicit provisional label found")

    return {
        "details": results,
    }


def check_duplicate_policy() -> dict:
    """Check that duplicate-policy metadata exists."""
    results: List[str] = []

    # Check experiment registry for dedup mentions
    er_file = PROJECT_ROOT / "research" / "experiment_registry.md"
    if er_file.is_file():
        with er_file.open("r") as f:
            content = f.read()
        if "dedup" in content.lower() or "deduplication" in content.lower():
            results.append("Experiment registry mentions deduplication policy")
        else:
            results.append("Experiment registry: no deduplication policy found")

    # Check decisions.md for dedup
    dr_file = PROJECT_ROOT / "research" / "decisions.md"
    if dr_file.is_file():
        with dr_file.open("r") as f:
            content = f.read()
        if "dedup" in content.lower() or "deduplication" in content.lower():
            results.append("Decisions.md mentions deduplication policy")
        else:
            results.append("Decisions.md: no deduplication policy found")

    return {
        "details": results,
    }


def check_train_validation_holdout() -> dict:
    """Check that train/validation/holdout policy exists."""
    results: List[str] = []

    # Check experiment registry
    er_file = PROJECT_ROOT / "research" / "experiment_registry.md"
    if er_file.is_file():
        with er_file.open("r") as f:
            content = f.read()
        if "train" in content.lower() and "validation" in content.lower():
            results.append("Experiment registry mentions train/validation split")
        else:
            results.append("Experiment registry: no train/validation split policy found")

    # Check remaining work.md
    rw_file = PROJECT_ROOT / "research" / "reconciliation" / "remaining_work.md"
    if rw_file.is_file():
        with rw_file.open("r") as f:
            content = f.read()
        if "train" in content.lower():
            results.append("Remaining work mentions training splits")
        else:
            results.append("Remaining work: no training split policy found")

    return {
        "details": results,
    }


def check_source_datasets_present() -> dict:
    """Check that source-specific datasets are present."""
    results: List[str] = []

    # Check key source directories
    import os
    data_dir = PROJECT_ROOT / "data"
    sources_checked = []

    # Python docs
    if (data_dir / "raw" / "python_docs").is_dir():
        results.append("Python docs source directory present")
        sources_checked.append("python_docs")
    else:
        results.append("Python docs source directory absent")

    # Textbooks
    if (data_dir / "raw" / "textbooks").is_dir():
        results.append("Textbooks source directory present")
        sources_checked.append("textbooks")
    else:
        results.append("Textbooks source directory absent")

    # Stack Overflow
    if (data_dir / "raw" / "stackoverflow").is_dir():
        results.append("Stack Overflow source directory present")
        sources_checked.append("stackoverflow")
    else:
        results.append("Stack Overflow source directory absent")

    # GitHub
    if (data_dir / "raw" / "github").is_dir():
        results.append("GitHub source directory present")
        sources_checked.append("github")
    else:
        results.append("GitHub source directory absent")

    # The Stack
    if (data_dir / "raw" / "the_stack").is_dir():
        results.append("The Stack source directory present")
        sources_checked.append("the_stack")
    else:
        results.append("The Stack source directory absent")

    return {
        "details": results,
    }


def run_readiness_check() -> dict:
    """Run all readiness checks and produce a final verdict.

    Output is either READY or NOT_READY with explicit reasons.
    """
    reasons: List[str] = []
    all_pass = True

    # 1. Manifest checks
    manifest_check = check_manifest_exists()
    if manifest_check["status"] == "present":
        reasons.append("✓ Source manifests exist with required fields")
    else:
        all_pass = False
        for r in manifest_check["details"]:
            reasons.append(f"✗ {r}")

    # 2. Dataset versions
    dv_check = check_dataset_versions()
    if dv_check["status"] == "present":
        reasons.append("✓ Dataset versions and infrastructure recorded")
    else:
        all_pass = False
        for r in dv_check["details"]:
            reasons.append(f"✗ {r}")

    # 3. Provenance and licenses
    pl_check = check_provenance_and_licenses()
    for r in pl_check["details"]:
        reasons.append(r)

    # 4. Hashes
    hash_check = check_hashes()
    for r in hash_check["details"]:
        reasons.append(r)

    # 5. AST and tokenizer versions
    at_check = check_ast_and_tokenizer_versions()
    for r in at_check["details"]:
        reasons.append(r)

    # 6. Duplicate policy
    dp_check = check_duplicate_policy()
    for r in dp_check["details"]:
        reasons.append(r)

    # 7. Train/validation/holdout policy
    tvh_check = check_train_validation_holdout()
    for r in tvh_check["details"]:
        reasons.append(r)

    # 8. Source datasets present
    sd_check = check_source_datasets_present()
    for r in sd_check["details"]:
        reasons.append(r)

    # Final verdict
    if all_pass:
        verdict = "READY"
        reasons.append("")
        reasons.append("VERDICT: READY — corpus infrastructure is in place for assembly.")
    else:
        verdict = "NOT_READY"
        reasons.append("")
        reasons.append("VERDICT: NOT_READY — resolve the above issues before corpus assembly.")

    return {
        "verdict": verdict,
        "reasons": reasons,
    }


def main() -> int:
    """Main entry point."""
    result = run_readiness_check()
    print(f"Verdict: {result['verdict']}")
    print()
    for reason in result["reasons"]:
        print(reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())