"""Read-only dataset inventory tool — Pythia-160M.

This tool ONLY inspects metadata/manifests/files. It does NOT:
- download data
- modify source data
- deduplicate
- rewrite manifests
- alter active workstreams
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def sha256_file(path: Path) -> str:
    """Compute SHA-256 of a file."""
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_json_load(path: Path) -> Optional[dict]:
    """Load JSON if file exists and is readable; return None otherwise."""
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None


def infer_source_type(filename: str) -> str:
    """Guess source_type from filename patterns."""
    name = filename.lower()
    if "python_docs" in name or "python-docs" in name:
        return "python_docs"
    if "thinkpython" in name or "atbs" in name or "textbook" in name:
        return "textbooks"
    if "stackoverflow" in name:
        return "stackoverflow"
    if "pypi" in name:
        return "pypi"
    if "github" in name:
        return "github"
    if "the_stack" in name:
        return "the_stack"
    if "codesearchnet" in name:
        return "codesearchnet"
    if "jupyter" in name:
        return "jupyter"
    if "reasoning" in name:
        return "reasoning"
    if "reddit" in name:
        return "reddit"
    return "unknown"


def inventory_source_directory(source_dir: Path) -> Optional[Dict[str, Any]]:
    """Inventory a single source directory. Read-only; does not modify anything."""
    if not source_dir.exists():
        return None

    results: List[Dict[str, Any]] = []

    for root, _dirs, files in os.walk(source_dir):
        root_path = Path(root)
        for fname in files:
            fpath = root_path / fname
            record: Dict[str, Any] = {
                "path": str(fpath),
                "filename": fname,
                "relative_path": str(fpath.relative_to(source_dir)),
            }

            # Try to read JSON manifests/reports
            if fname.endswith(".json"):
                data = safe_json_load(fpath)
                if data is not None:
                    record["type"] = "manifest"
                    # Preserve whatever fields exist; do not interpret or transform
                    record["content"] = {k: v for k, v in data.items() if not k.startswith("_")}
                else:
                    record["type"] = "json_invalid"
            elif fname.endswith(".jsonl"):
                record["type"] = "jsonl"
                # Count lines
                try:
                    with fpath.open("r", encoding="utf-8", errors="replace") as f:
                        line_count = sum(1 for _ in f)
                    record["line_count"] = line_count
                except OSError:
                    record["line_count"] = "unknown"
            elif fname.endswith(".zip"):
                record["type"] = "zip"
                try:
                    record["size_bytes"] = fpath.stat().st_size
                except OSError:
                    record["size_bytes"] = "unknown"
            else:
                # Text/binary file — report size only
                try:
                    record["size_bytes"] = fpath.stat().st_size
                    record["type"] = "file"
                except OSError:
                    record["type"] = "file"
                    record["size_bytes"] = "unknown"

            results.append(record)

    if not results:
        return None

    # Aggregate summary
    total_files = len(results)
    total_bytes = sum(
        r.get("size_bytes", 0) if isinstance(r.get("size_bytes"), (int, float)) else 0
        for r in results
        if isinstance(r.get("size_bytes"), (int, float))
    )

    summary: Dict[str, Any] = {
        "source_dir": str(source_dir),
        "total_files": total_files,
        "total_bytes": total_bytes,
        "records": results,
    }

    # Try to read a top-level manifest/report
    for item in source_dir.iterdir():
        if item.is_file():
            data = safe_json_load(item)
            if data is not None:
                # Check if this looks like a manifest/report by key fields
                keys = set(data.keys())
                if "candidate_count" in keys or "retained_count" in keys or "source" in keys:
                    summary["manifest"] = {
                        "path": str(item),
                        "keys": sorted(keys),
                    }
                elif "experiment_id" in keys or "repositories_discovered" in keys:
                    summary["experiment_report"] = {
                        "path": str(item),
                        "keys": sorted(keys),
                    }
                break

    return summary


def inventory_all_sources() -> Dict[str, Any]:
    """Inventory all known source directories under data/.

    Returns a master inventory dict keyed by source name.
    Read-only: does not modify any source data.
    """
    base = PROJECT_ROOT / "data"
    if not base.exists():
        return {"error": "data/ directory not found"}

    master: Dict[str, Any] = {
        "inventory_date": datetime.now(timezone.utc).isoformat(),
        "sources": {},
    }

    # Define known source directories (read-only mapping)
    source_dirs: list[tuple[str, Path]] = [
        ("python_docs", base / "raw" / "python_docs"),
        ("textbooks", base / "raw" / "textbooks"),
        ("stackoverflow", base / "raw" / "stackoverflow"),
        ("jupyter", base / "raw" / "jupyter"),
        ("peps", base / "raw" / "peps"),
        ("codesearchnet", base / "raw" / "codesearchnet"),
        ("the_stack", base / "raw" / "the_stack"),
    ]

    for source_name, source_dir in source_dirs:
        summary = inventory_source_directory(source_dir)
        if summary is not None:
            master["sources"][source_name] = summary
        else:
            # Source directory doesn't exist or is empty — record as NOT_AVAILABLE
            master["sources"][source_name] = {
                "status": "NOT_AVAILABLE",
                "note": f"Directory {source_dir} does not exist or is empty",
            }

    # Also check any additional directories found under data/raw/
    if base / "raw" / "stackoverflow":
        # Already included above, skip duplicate
        pass

    # Report on filtered directories
    filtered = base / "filtered"
    if filtered.exists():
        summary_parts: list[Dict[str, Any]] = []
        for subdir in sorted(filtered.iterdir()):
            if subdir.is_dir():
                sub_summary = inventory_source_directory(subdir)
                if sub_summary is not None:
                    # Rename key to avoid clash with source dict
                    sub_summary["dir_name"] = subdir.name
                    summary_parts.append(sub_summary)
        if summary_parts:
            master["filtered"] = summary_parts

    # Report on final corpus
    final_dir = base / "final"
    if final_dir.exists():
        final_summary = inventory_source_directory(final_dir)
        if final_summary is not None:
            master["final"] = final_summary

    return master


def format_inventory(inventory: Dict[str, Any]) -> str:
    """Format the inventory as human-readable text."""
    lines: list[str] = []
    lines.append(f"Pythia-160M Dataset Inventory")
    lines.append(f"Generated: {inventory.get('inventory_date', 'unknown')}")
    lines.append("")

    sources = inventory.get("sources", {})
    if not sources:
        lines.append("No source directories found.")
        return "\n".join(lines)

    for source_name, summary in sorted(sources.items()):
        lines.append(f"Source: {source_name}")
        if summary.get("status") == "NOT_AVAILABLE":
            lines.append(f"  Status: {summary['status']}")
            lines.append(f"  Note: {summary['note']}")
        else:
            if "total_files" in summary:
                lines.append(f"  Total files: {summary['total_files']}")
            if "total_bytes" in summary and summary["total_bytes"] != 0:
                lines.append(f"  Total size: {summary['total_bytes']} bytes")
            if "manifest" in summary:
                lines.append(f"  Manifest: {summary['manifest']['path']} (keys: {', '.join(summary['manifest']['keys'])})")
            if "experiment_report" in summary:
                lines.append(f"  Experiment report: {summary['experiment_report']['path']}")
            if "records" in summary and isinstance(summary["records"], list):
                lines.append(f"  Records: {len(summary['records'])} individual files")
                for rec in summary["records"][:5]:  # Show first 5
                    rtype = rec.get("type", "unknown")
                    label = rec.get("filename", rec.get("relative_path", "unknown"))
                    size = rec.get("size_bytes", "unknown")
                    lines.append(f"    - {rtype}: {label} (size: {size})")
                if len(summary["records"]) > 5:
                    lines.append(f"    ... and {len(summary['records']) - 5} more")
            if "filtered" in summary:
                for f in summary["filtered"]:
                    fd = f.get("dir_name", "?")
                    fc = f.get("total_files", "?")
                    lines.append("  Filtered [" + fd + "]:")
                    lines.append("    total_files=" + str(fc))
            if "final" in summary:
                final_f = summary["final"]
                fc = final_f.get("total_files", "?")
                lines.append("  Final corpus:")
                lines.append("    total_files=" + str(fc))
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    """Main entry point."""
    inventory = inventory_all_sources()
    print(format_inventory(inventory))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())