"""Mount validation helper — Pythia-160M.

This tool verifies the configured DATA_ROOT path and reports whether it is
local or cloud-backed. It does NOT create large files, upload datasets, or
perform any global deduplication.

Usage:
    python3 scripts/research/check_data_root.py

Output:
    READINESS REPORT
    ==============

    Verdict :  READY / NOT_READY
    Message : <explicit reasons>

    Path    : <absolute path>
    Type    :  local / cloud
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the project scripts package is importable
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config import DATA_ROOT  # noqa: F401,F811


def _is_readable(path: Path) -> bool:
    """Return True if path exists and is readable."""
    return path.is_dir() and os.access(path, os.R_OK)


def _is_writable(path: Path) -> bool:
    """Return True if path exists and is writable."""
    return path.is_dir() and os.access(path, os.W_OK)


def _dirs_at(path: Path, names: list[str]) -> dict[str, bool]:
    """Check which of the given directory names exist under *path*."""
    result: dict[str, bool] = {}
    for name in names:
        d = path / name
        result[name] = d.is_dir()
    return result


def validate() -> dict[str, any]:
    """Run all checks and return a verdict dict."""
    reasons: list[str] = []

    # --- 1. configured DATA_ROOT exists ---
    path_type: str | None = None
    if _is_readable(DATA_ROOT):
        reasons.append("✓ DATA_ROOT exists and is a directory")
        path_type = "cloud" if str(DATA_ROOT).startswith("/mnt/") else "local"
        reasons.append(f"✓ Path type: {path_type}")
    else:
        reasons.append("✗ DATA_ROOT does not exist or is not a directory")
        # Fall back to local data dir for backward compatibility
        fallback = Path(__file__).resolve().parent.parent / "data"
        if _is_readable(fallback):
            reasons.append(f"✓ Fallback local data dir is available: {fallback}")
            effective_path = str(fallback)
            effective_type = "local (fallback)"
        else:
            effective_path = str(DATA_ROOT)
            effective_type = "unknown (path does not exist)"

    # --- 2. it is readable ---
    if _is_readable(DATA_ROOT):
        reasons.append("✓ DATA_ROOT is readable")
    else:
        reasons.append("✗ DATA_ROOT is not readable")

    # --- 3. it is writable ---
    if _is_writable(DATA_ROOT):
        reasons.append("✓ DATA_ROOT is writable")
    else:
        reasons.append("✗ DATA_ROOT is not writable")

    # --- 4. expected directories exist or can be created ---
    expected_dirs = ["raw", "filtered", "final", "manifests", "snapshots"]
    dirs = _dirs_at(DATA_ROOT, expected_dirs)
    missing: list[str] = [n for n, e in dirs.items() if not e]
    if not missing:
        reasons.append("✓ All expected directories exist")
    else:
        for name in missing:
            reasons.append(f"  note: {name} directory missing (can be created)")
        # Attempt to create missing dirs — do not fail if permissions denied
        for name in missing:
            d = DATA_ROOT / name
            try:
                d.mkdir(parents=True, exist_ok=True)
                reasons.append(f"  note: created {name} directory")
            except OSError:
                reasons.append(f"  warning: could not create {name} directory")

    # --- 5. report local/cloud path clearly ---
    path_str = str(DATA_ROOT)
    if path_str.startswith("/mnt/"):
        path_type_final = "cloud (Google Drive)"
    else:
        path_type_final = "local repository"
    reasons.append(f"✓ Reported path type: {path_type_final}")
    reasons.append(f"  Resolved path: {path_str}")

    verdict = "READY" if _is_readable(DATA_ROOT) and _is_writable(DATA_ROOT) else "NOT_READY"

    return {
        "verdict": verdict,
        "reasons": reasons,
        "path": path_str,
        "type": "cloud" if path_str.startswith("/mnt/") else "local",
    }


def main() -> int:
    """Main entry point."""
    result = validate()
    lines: list[str] = []
    lines.append("READINESS REPORT")
    lines.append("=" * len("READINESS REPORT"))
    lines.append(f"Verdict: {result['verdict']}")
    lines.append("")
    for reason in result["reasons"]:
        lines.append(reason)
    lines.append("")
    lines.append(f"Path: {result['path']}")
    lines.append(f"Type: {result['type']}")
    lines.append("")
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())