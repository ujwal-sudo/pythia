from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.pilots.common import (
    dedup_hash,
    evaluate_code,
    extract_units,
    is_noncode_path,
    is_test_path,
    is_vendor_path,
    load_csn_hashes,
    sha256_text,
    utc_now_iso,
    write_json,
)


DEFAULT_MANIFEST = Path("/mnt/pythia-cloud/PythiaDrive/raw/pypi/manifests/pypi_acquisition_v1.json")
DEFAULT_CSN = Path("/mnt/pythia-cloud/PythiaDrive/filtered/stage2/codesearchnet_full-v3/codesearchnet_canonical_accepted.jsonl")
DEFAULT_OUTPUT = Path("/mnt/pythia-cloud/PythiaDrive/processed/audits/pypi_scaleup_feasibility_20261022T094227Z/pypi_scaleup_audit.json")

PERMISSIVE_SIGNALS = (
    "mit license",
    "permission is hereby granted",
    "bsd 2-clause",
    "bsd 3-clause",
    "redistribution and use in source and binary forms",
    "apache license",
    "isc license",
    "python software foundation license",
    "mozilla public license",
)
COPYLEFT_SIGNALS = (
    "gnu general public license",
    "gnu lesser general public license",
    "gnu affero general public license",
    "creative commons attribution-sharealike",
    "european union public licence",
)
LICENSE_NAME_MARKERS = ("license", "licence", "copying", "notice")


def _stable_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sample(packages: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    return sorted(packages, key=lambda item: _stable_key(item["package"]))[:count]


def _status(package: dict[str, Any]) -> str:
    return str(package.get("analysis", {}).get("license_status", "UNKNOWN"))


def _aggregate(packages: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for status in ("CLEAR", "UNKNOWN", "REVIEW_REQUIRED"):
        group = [item for item in packages if _status(item) == status]
        python_group = [item for item in group if int(item.get("analysis", {}).get("python_files", 0)) > 0]
        result[status] = {
            "packages": len(group),
            "packages_with_python": len(python_group),
            "archive_bytes": sum(int(item.get("archive_size", 0)) for item in group),
            "archive_bytes_with_python": sum(int(item.get("archive_size", 0)) for item in python_group),
            "python_files": sum(int(item.get("analysis", {}).get("python_files", 0)) for item in group),
            "python_loc": sum(int(item.get("analysis", {}).get("python_loc", 0)) for item in group),
            "ast_valid": sum(int(item.get("analysis", {}).get("ast_valid", 0)) for item in group),
            "ast_invalid": sum(int(item.get("analysis", {}).get("ast_invalid", 0)) for item in group),
        }
    result["TOTAL"] = {
        "packages": len(packages),
        "archive_bytes": sum(int(item.get("archive_size", 0)) for item in packages),
        "python_files": sum(int(item.get("analysis", {}).get("python_files", 0)) for item in packages),
        "python_loc": sum(int(item.get("analysis", {}).get("python_loc", 0)) for item in packages),
        "ast_valid": sum(int(item.get("analysis", {}).get("ast_valid", 0)) for item in packages),
        "ast_invalid": sum(int(item.get("analysis", {}).get("ast_invalid", 0)) for item in packages),
    }
    return result


def _members(archive_path: Path) -> Iterator[tuple[str, bytes]]:
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                if info.filename.endswith(".py") or any(marker in info.filename.lower() for marker in LICENSE_NAME_MARKERS):
                    if info.file_size > 2_000_000 and info.filename.endswith(".py"):
                        continue
                    yield info.filename, archive.read(info.filename)[:120_000]
        return
    with tarfile.open(archive_path, "r:*") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            if member.name.endswith(".py") or any(marker in member.name.lower() for marker in LICENSE_NAME_MARKERS):
                if member.size > 2_000_000 and member.name.endswith(".py"):
                    continue
                handle = archive.extractfile(member)
                if handle is not None:
                    yield member.name, handle.read(120_000)



def _python_names(archive_path: Path) -> list[str]:
    names: list[str] = []
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                if not info.is_dir() and info.filename.endswith(".py") and info.file_size <= 2_000_000:
                    names.append(info.filename)
        return sorted(names)
    with tarfile.open(archive_path, "r:*") as archive:
        for member in archive.getmembers():
            if member.isfile() and member.name.endswith(".py") and member.size <= 2_000_000:
                names.append(member.name)
    return sorted(names)


def _core_names(names: list[str]) -> list[str]:
    return [
        name
        for name in names
        if not is_test_path(Path(name)) and not is_vendor_path(Path(name)) and not is_noncode_path(Path(name))
    ]


def _even_sample(names: list[str], limit: int) -> list[str]:
    if not names:
        return []
    step = max(1, len(names) // limit)
    return names[::step][:limit]


def _read_python_names(archive_path: Path, names: list[str], byte_limit: int) -> Iterator[tuple[str, str]]:
    used = 0
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            for name in names:
                data = archive.read(name)
                if used + len(data) > byte_limit:
                    continue
                used += len(data)
                yield name, data.decode("utf-8", errors="replace")
        return
    with tarfile.open(archive_path, "r:*") as archive:
        members = {member.name: member for member in archive.getmembers()}
        for name in names:
            member = members.get(name)
            if member is None:
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            data = handle.read()
            if used + len(data) > byte_limit:
                continue
            used += len(data)
            yield name, data.decode("utf-8", errors="replace")

def _license_signal(text: str) -> str:
    lowered = text.lower()
    has_permissive = any(signal in lowered for signal in PERMISSIVE_SIGNALS)
    has_copyleft = any(signal in lowered for signal in COPYLEFT_SIGNALS)
    if has_permissive and has_copyleft:
        return "multi_signal"
    if has_copyleft:
        return "copyleft_signal"
    if has_permissive:
        return "permissive_signal"
    return "no_signal"


def _license_audit(package: dict[str, Any]) -> dict[str, Any]:
    archive_path = Path(package["archive_path"])
    names: list[str] = []
    chunks: list[str] = []
    try:
        if zipfile.is_zipfile(archive_path):
            with zipfile.ZipFile(archive_path) as archive:
                names = [info.filename for info in archive.infolist() if not info.is_dir() and any(marker in info.filename.lower() for marker in LICENSE_NAME_MARKERS)]
                for name in names[:3]:
                    chunks.append(archive.read(name)[:120_000].decode("utf-8", errors="replace"))
        else:
            with tarfile.open(archive_path, "r:*") as archive:
                members = [member for member in archive.getmembers() if member.isfile() and any(marker in member.name.lower() for marker in LICENSE_NAME_MARKERS)]
                names = [member.name for member in members]
                for member in members[:3]:
                    handle = archive.extractfile(member)
                    if handle is not None:
                        chunks.append(handle.read(120_000).decode("utf-8", errors="replace"))
    except Exception as error:
        return {"package": package["package"], "metadata_status": _status(package), "archive_read_error": str(error), "license_files": [], "license_signal": "archive_error"}
    text = "\n".join(chunks)
    signal = _license_signal(text)
    return {
        "package": package["package"],
        "version": package.get("version"),
        "metadata_status": _status(package),
        "archive_size": int(package.get("archive_size", 0)),
        "python_files": int(package.get("analysis", {}).get("python_files", 0)),
        "license_files": names[:10],
        "license_signal": signal,
        "has_license_file": bool(names),
    }


def _token_sample(package: dict[str, Any], csn_hashes: set[str], seen_hashes: set[str]) -> dict[str, Any]:
    archive_path = Path(package["archive_path"])
    result = {
        "package": package["package"],
        "version": package.get("version"),
        "metadata_status": _status(package),
        "archive_size": int(package.get("archive_size", 0)),
        "files_examined": 0,
        "bytes_examined": 0,
        "py_files": 0,
        "py_loc": 0,
        "raw_chars": 0,
        "raw_tokens_char4": 0,
        "ast_valid_files": 0,
        "ast_invalid_files": 0,
        "core_units_seen": 0,
        "core_units_accepted": 0,
        "accepted_chars": 0,
        "accepted_tokens": 0,
        "archive_py_files": 0,
        "archive_core_files": 0,
        "core_file_fraction": 0.0,
        "duplicate_csn_units": 0,
        "duplicate_sample_units": 0,
        "rejection_reasons": Counter(),
        "archive_error": None,
    }
    try:
        names = _python_names(archive_path)
        core_names = _core_names(names)
        selected = _even_sample(core_names, 60)
        result["archive_py_files"] = len(names)
        result["archive_core_files"] = len(core_names)
        result["core_file_fraction"] = round(len(core_names) / len(names), 6) if names else 0.0
        for name, text in _read_python_names(archive_path, selected, 6_000_000):
            result["files_examined"] += 1
            result["bytes_examined"] += len(text)
            result["py_files"] += 1
            result["py_loc"] += sum(1 for line in text.splitlines() if line.strip())
            result["raw_chars"] += len(text)
            result["raw_tokens_char4"] += len(text) // 4
            units, error = extract_units(text, Path(name))
            if error is not None:
                result["ast_invalid_files"] += 1
                continue
            result["ast_valid_files"] += 1
            result["core_units_seen"] += len(units)
            if result["core_units_seen"] >= 2500:
                break
            for unit in units:
                quality = evaluate_code(unit["code"], include_pep8=False)
                if not quality["accepted"]:
                    result["rejection_reasons"][str(quality["reason"])] += 1
                    continue
                digest = unit["content_hash"]
                if digest in csn_hashes:
                    result["duplicate_csn_units"] += 1
                    continue
                if digest in seen_hashes:
                    result["duplicate_sample_units"] += 1
                    continue
                seen_hashes.add(digest)
                result["core_units_accepted"] += 1
                result["accepted_chars"] += quality["chars"]
                result["accepted_tokens"] += quality["tokens"]
    except Exception as error:
        result["archive_error"] = str(error)
    result["rejection_reasons"] = dict(sorted(result["rejection_reasons"].items()))
    return result


def _projection(aggregate: dict[str, Any], sample: dict[str, Any]) -> dict[str, Any]:
    sample_files = int(sample["py_files"])
    sample_loc = int(sample["py_loc"])
    sample_chars = int(sample["raw_chars"])
    sample_tokens = int(sample["raw_tokens_char4"])
    accepted_tokens = int(sample["accepted_tokens"])
    total_files = int(aggregate["python_files"])
    total_loc = int(aggregate["python_loc"])
    core_fraction = sample.get("core_file_fraction", 0.0)
    total_core_files = total_files * core_fraction
    acceptance = accepted_tokens / sample_tokens if sample_tokens else 0
    projected_raw_files = sample_tokens * (total_core_files / sample_files) if sample_files else 0
    projected_raw_loc = (sample_chars / sample_loc * total_loc * core_fraction / 4) if sample_loc else 0
    return {
        "sample_files": sample_files,
        "sample_loc": sample_loc,
        "sample_raw_tokens_char4": sample_tokens,
        "sample_accepted_tokens": accepted_tokens,
        "sample_core_file_fraction": core_fraction,
        "sample_acceptance_ratio": round(acceptance, 6),
        "projected_core_files": int(total_core_files),
        "projected_raw_tokens_by_files": int(projected_raw_files),
        "projected_raw_tokens_by_loc": int(projected_raw_loc),
        "projected_accepted_tokens_by_files": int(projected_raw_files * acceptance),
        "projected_accepted_tokens_by_loc": int(projected_raw_loc * acceptance),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--csn", type=Path, default=DEFAULT_CSN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--license-sample", type=int, default=80)
    parser.add_argument("--token-sample", type=int, default=50)
    arguments = parser.parse_args()
    manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
    packages = manifest["packages"]
    aggregate = _aggregate(packages)

    license_pool = [item for item in packages if int(item.get("archive_size", 0)) <= 120_000_000]
    license_sample = _sample(license_pool, arguments.license_sample)
    license_results = []
    for item in license_sample:
        print(f"license: {item['package']}", file=sys.stderr, flush=True)
        license_results.append(_license_audit(item))

    token_pool = [
        item
        for item in packages
        if int(item.get("archive_size", 0)) <= 45_000_000 and int(item.get("analysis", {}).get("python_files", 0)) >= 5
    ]
    token_packages = _sample(token_pool, arguments.token_sample)
    csn_hashes = load_csn_hashes(arguments.csn)
    seen_hashes: set[str] = set()
    token_results = []
    for item in token_packages:
        print(f"tokens: {item['package']}", file=sys.stderr, flush=True)
        token_results.append(_token_sample(item, csn_hashes, seen_hashes))

    totals = Counter()
    for item in token_results:
        totals["files_examined"] += item["files_examined"]
        totals["bytes_examined"] += item["bytes_examined"]
        totals["py_files"] += item["py_files"]
        totals["py_loc"] += item["py_loc"]
        totals["raw_chars"] += item["raw_chars"]
        totals["raw_tokens_char4"] += item["raw_tokens_char4"]
        totals["ast_valid_files"] += item["ast_valid_files"]
        totals["ast_invalid_files"] += item["ast_invalid_files"]
        totals["core_units_seen"] += item["core_units_seen"]
        totals["core_units_accepted"] += item["core_units_accepted"]
        totals["accepted_chars"] += item["accepted_chars"]
        totals["accepted_tokens"] += item["accepted_tokens"]
        totals["duplicate_csn_units"] += item["duplicate_csn_units"]
        totals["duplicate_sample_units"] += item["duplicate_sample_units"]
        totals["archive_py_files"] += item["archive_py_files"]
        totals["archive_core_files"] += item["archive_core_files"]
    combined = dict(totals)
    combined["core_file_fraction"] = round(combined["archive_core_files"] / combined["archive_py_files"], 6) if combined["archive_py_files"] else 0.0
    combined["py_files"] = max(1, combined["py_files"])
    combined["py_loc"] = max(1, combined["py_loc"])
    projection = _projection(aggregate["TOTAL"], combined)

    license_cross = Counter()
    for item in license_results:
        license_cross[(item["metadata_status"], item["license_signal"], item["has_license_file"])] += 1
    license_summary = {
        "sample_packages": len(license_results),
        "metadata_status_counts": dict(Counter(item["metadata_status"] for item in license_results)),
        "license_signal_counts": dict(Counter(item["license_signal"] for item in license_results)),
        "has_license_file_counts": dict(Counter(bool(item["has_license_file"]) for item in license_results)),
        "cross_tab": {f"{status}|{signal}|{has_file}": count for (status, signal, has_file), count in sorted(license_cross.items())},
        "unknown_with_permissive_signal": sum(1 for item in license_results if item["metadata_status"] == "UNKNOWN" and item["license_signal"] == "permissive_signal"),
        "clear_without_license_file": sum(1 for item in license_results if item["metadata_status"] == "CLEAR" and not item["has_license_file"]),
        "review_required_with_copyleft_signal": sum(1 for item in license_results if item["metadata_status"] == "REVIEW_REQUIRED" and item["license_signal"] == "copyleft_signal"),
        "results": license_results,
    }
    report = {
        "report": "pypi_scaleup_feasibility_and_licensing",
        "generated_at": utc_now_iso(),
        "manifest": str(arguments.manifest),
        "manifest_sha256": sha256_text(arguments.manifest.read_text(encoding="utf-8")),
        "csn": str(arguments.csn),
        "scope": "Read-only stratified archive sampling; no package code executed and no corpus written.",
        "aggregate": aggregate,
        "license_audit": license_summary,
        "token_sample": {
            "sample_packages": len(token_results),
            "sampling_rule": "archive_size <= 45MB, manifest python_files >= 5, up to 50 packages and 60 evenly spaced core Python files per package; deterministic package-name hash order",
            "totals": combined,
            "projection": projection,
            "results": token_results,
        },
        "limitations": [
            "License classification is metadata-first; archive sampling is a lower-bound audit, not a per-file legal review.",
            "Token projection is char/4 based and scaled from a bounded sample; it is not a processed-corpus measurement.",
            "The manifest contains binary wheels; python_files and python_loc are only available for archives with inspectable Python sources.",
            "Exact dedup sampling uses normalized content hashes; near dedup is not evaluated.",
            "The PyPI token sample omits the PEP8 screen for speed; pilot results show PEP8 rejects a small fraction, so the acceptance estimate is an upper bound.",
        ],
    }
    write_json(arguments.output, report)
    print(json.dumps({"output": str(arguments.output), "aggregate": aggregate, "license_audit": {k: v for k, v in license_summary.items() if k != "results"}, "projection": projection, "sample_totals": combined}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
