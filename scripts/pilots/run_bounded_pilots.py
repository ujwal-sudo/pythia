from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.pilots.common import (
    PilotStats,
    archive_root,
    clean_code,
    copy_verified,
    dedup_hash,
    download,
    evaluate_code,
    extract_units,
    find_license,
    is_noncode_path,
    is_test_path,
    is_vendor_path,
    load_csn_hashes,
    make_record,
    process_code_file,
    safe_extract,
    sha256_file,
    utc_now_iso,
    write_json,
    write_jsonl,
)


DEFAULT_PILOT_ROOT = Path("/mnt/pythia-cloud/PythiaDrive/pilots/bounded_20261022T094227Z")
DEFAULT_LOCAL_ROOT = Path("/tmp/opencode/pilots_20261022T094227Z")
DEFAULT_CSN = Path("/mnt/pythia-cloud/PythiaDrive/filtered/stage2/codesearchnet_full-v3/codesearchnet_canonical_accepted.jsonl")

CPYTHON = {
    "repository": "python/cpython",
    "tag": "v3.15.1",
    "commit": "c37e74cb6bcdadcd5f46f289498f6b3298ddee61",
    "license_file": "LICENSE",
    "license_sha256": "b0e25a78cffb43f4d92de8b61ccfa1f1f98ecbc22330b54b5251e7b6ba010231",
    "license_spdx": "PSF-2.0",
    "url": "https://codeload.github.com/python/cpython/tar.gz/c37e74cb6bcdadcd5f46f289498f6b3298ddee61",
    "max_bytes": 300_000_000,
}

G01 = [
    {
        "repository": "numpy/numpy",
        "tag": "v2.5.4",
        "commit": "a3d0ef1df045b858e68115001fdabc930bb3b68c",
        "license_file": "LICENSE.txt",
        "license_sha256": "1be1df33863f97a7bc1c4d67980bd6c69c9a6fef0a5ee76e6ad6cb91e56e8491",
        "license_spdx": "BSD-3-Clause",
        "max_bytes": 600_000_000,
    },
    {
        "repository": "scipy/scipy",
        "tag": "v1.18.1",
        "commit": "e4e854eaa8f18d807cd3496028e257e36caa93cc",
        "license_file": "LICENSE.txt",
        "license_sha256": "221e59f5e910fd7f94e44f0dac77436a11338c285c6346232e4a850a50da0e94",
        "license_spdx": "BSD-3-Clause",
        "max_bytes": 600_000_000,
    },
    {
        "repository": "pandas-dev/pandas",
        "tag": "v3.0.6",
        "commit": "2905718b126579d2cf0fe5bae05bd75facb67d77",
        "license_file": "LICENSE",
        "license_sha256": "9850f6b5bdef7346503065807b878deb8058b976c5c329f4c4d23bf4796ce9ae",
        "license_spdx": "BSD-3-Clause",
        "max_bytes": 600_000_000,
    },
    {
        "repository": "sympy/sympy",
        "tag": "sympy-1.14.0",
        "commit": "16fa855354eb7bcabd3fe10993841e03b1382692",
        "license_file": "LICENSE",
        "license_sha256": "07a5e9819f727b4986ad2829c7a29a6320d42575f720eb24d71b7fef573a0286",
        "license_spdx": "BSD-3-Clause",
        "max_bytes": 600_000_000,
    },
    {
        "repository": "pytest-dev/pytest",
        "tag": "9.1.1",
        "commit": "cf470ec0bf7eb89cd97dd56df4859eae5db46447",
        "license_file": "LICENSE",
        "license_sha256": "ca836a5f9ecca3b2f350230faa20a48fb8b145653b5568d784862df864706b9b",
        "license_spdx": "MIT",
        "max_bytes": 300_000_000,
    },
    {
        "repository": "pydantic/pydantic",
        "tag": "v2.14.1",
        "commit": "b2212c787fb5c73386dc770681ec49cd09da8e73",
        "license_file": "LICENSE",
        "license_sha256": "a9e186f3ca16b5eef84318e7a701721351a00cb7b8ae3a4394b67b49e3529ef3",
        "license_spdx": "MIT",
        "max_bytes": 300_000_000,
    },
    {
        "repository": "sqlalchemy/sqlalchemy",
        "tag": "rel_2_1_6",
        "commit": "2f6968cc126d4da2d2eabc5a51285472bb9bfc9e",
        "license_file": "LICENSE",
        "license_sha256": "e862bb5b904fb5513c3e14288d7a25a12eb0ecc7847a0a965d310e9a955e7cb9",
        "license_spdx": "MIT",
        "max_bytes": 600_000_000,
    },
    {
        "repository": "python/mypy",
        "tag": "v2.4.0",
        "commit": "935ba8afba7ceacca0651579450c74339f343016",
        "license_file": "LICENSE",
        "license_sha256": "fdf1cd17f50e1305ed8cfd37467312d27a984648dba622cef70573b5512e4e1b",
        "license_spdx": "MIT",
        "max_bytes": 300_000_000,
    },
]

SCIKIT_DOCS = {
    "repository": "scikit-learn/scikit-learn.github.io",
    "docs_version": "1.9.1",
    "docs_commit": "e468fb97b23eb68411e4f3c1c3ba1244f92aa399",
    "source_commit": "866c0f51e7560ef0303cbcc5f159df5382ea9e3f",
    "url": "https://github.com/scikit-learn/scikit-learn.github.io/raw/e468fb97b23eb68411e4f3c1c3ba1244f92aa399/1.9/_downloads/scikit-learn-docs.zip",
    "expected_size": 99_790_745,
    "license_url": "https://raw.githubusercontent.com/scikit-learn/scikit-learn/866c0f51e7560ef0303cbcc5f159df5382ea9e3f/COPYING",
    "license_sha256": "50d6a9d340f19ab355609917993114daf5f47e3161067bcf34955bbd05cd9cb0",
    "license_spdx": "BSD-3-Clause",
    "max_bytes": 150_000_000,
    "max_records": 700,
    "max_context_tokens": 10_000_000,
    "max_blocks_examined": 20_000,
}


def _raw_file(root: Path, category: str, name: str) -> Path:
    return root / "raw" / category / name


def _report_path(root: Path, pilot: str) -> Path:
    return root / "reports" / f"{pilot}.json"


def _output_path(root: Path, pilot: str, filename: str) -> Path:
    return root / "filtered" / pilot / filename


def _repo_url(repository: str, commit: str, path: str) -> str:
    return f"https://github.com/{repository}/blob/{commit}/{path}"


def _ensure_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "raw").mkdir(exist_ok=True)
    (root / "filtered").mkdir(exist_ok=True)
    (root / "reports").mkdir(exist_ok=True)
    (root / "licenses").mkdir(exist_ok=True)


def _attach(csn_hashes: set[str], seen_hashes: set[str], records: list[dict[str, Any]], report: dict[str, Any]) -> None:
    report["outputs"] = {
        "records": len(records),
        "tokens": sum(int(record["provisional_token_count"]) for record in records),
        "chars": sum(int(record["char_count"]) for record in records),
    }


def run_c01(root: Path, local: Path, csn_hashes: set[str], seen_hashes: set[str]) -> dict[str, Any]:
    pilot = "c01_cpython"
    source = CPYTHON
    raw_dir = _raw_file(root, "cpython", "")
    raw_dir.mkdir(parents=True, exist_ok=True)
    local_dir = local / pilot
    local_dir.mkdir(parents=True, exist_ok=True)
    archive_path = local_dir / "cpython-v3.15.1.tar.gz"
    acquisition = download(source["url"], archive_path, max_bytes=source["max_bytes"])
    copy_verified(archive_path, _raw_file(root, "cpython", archive_path.name))
    extracted = local_dir / "extracted"
    safe_extract(archive_path, extracted)
    repository_root = archive_root(extracted)
    if source["commit"] not in repository_root.name:
        raise RuntimeError(f"unexpected cpython archive root: {repository_root.name}")
    license_source = find_license(repository_root, source["license_file"])
    license_record = copy_verified(
        license_source,
        root / "licenses" / pilot / source["license_file"],
        source["license_sha256"],
    )
    output_path = _output_path(root, pilot, "cpython_lib_code.jsonl")
    records: list[dict[str, Any]] = []
    stats = PilotStats()
    acquired_at = utc_now_iso()
    skipped = 0
    for path in sorted((repository_root / "Lib").rglob("*.py")):
        relative = path.relative_to(repository_root)
        relative_to_lib = path.relative_to(repository_root / "Lib")
        if relative_to_lib.parts and relative_to_lib.parts[0] in {"test", "idlelib"}:
            if "test" in relative_to_lib.parts or "idle_test" in relative_to_lib.parts:
                skipped += 1
                continue
        if relative_to_lib.parts and relative_to_lib.parts[0] in {"ensurepip", "tomllib", "site-packages"}:
            skipped += 1
            continue
        if is_vendor_path(relative) or is_test_path(relative):
            skipped += 1
            continue
        process_code_file(
            source_path=path,
            relative_path=relative,
            source="cpython",
            source_dataset="cpython_lib",
            repository=source["repository"],
            revision=source["commit"],
            source_url=_repo_url(source["repository"], source["commit"], relative.as_posix()),
            license_spdx=source["license_spdx"],
            license_path=license_record["path"],
            acquired_at=acquired_at,
            csn_hashes=csn_hashes,
            seen_hashes=seen_hashes,
            stats=stats,
            records=records,
            partition="code",
        )
    stats.increment("files_skipped_scope", skipped)
    write_jsonl(output_path, records)
    report = {
        "pilot": pilot,
        "status": "COMPLETED",
        "source": source,
        "acquisition": acquisition,
        "license": license_record,
        "scope": "Lib/**/*.py excluding tests, idle tests, ensurepip, tomllib, site-packages, vendor",
        "stats": stats.as_dict(),
        "output_path": str(output_path),
        "output_sha256": sha256_file(output_path),
        "outputs": {"records": len(records), "tokens": sum(int(item["provisional_token_count"]) for item in records), "chars": sum(int(item["char_count"]) for item in records)},
        "caps": {"archive_bytes": source["max_bytes"], "records": None, "tokens": None},
        "completed_at": utc_now_iso(),
    }
    write_json(_report_path(root, pilot), report)
    return report


def run_g01(root: Path, local: Path, csn_hashes: set[str], seen_hashes: set[str]) -> dict[str, Any]:
    pilot = "g01_github_eight"
    raw_dir = _raw_file(root, "github", "")
    raw_dir.mkdir(parents=True, exist_ok=True)
    local_dir = local / pilot
    local_dir.mkdir(parents=True, exist_ok=True)
    code_records: list[dict[str, Any]] = []
    test_records: list[dict[str, Any]] = []
    stats = PilotStats()
    repo_reports: list[dict[str, Any]] = []
    acquired_at = utc_now_iso()
    for source in G01:
        repository = source["repository"]
        safe_name = repository.replace("/", "__")
        repo_dir = local_dir / safe_name
        repo_dir.mkdir(parents=True, exist_ok=True)
        archive_path = repo_dir / f"{safe_name}-{source['tag']}.tar.gz"
        url = f"https://codeload.github.com/{repository}/tar.gz/{source['commit']}"
        acquisition = download(url, archive_path, max_bytes=source["max_bytes"])
        copy_verified(archive_path, _raw_file(root, "github", archive_path.name))
        extracted = repo_dir / "extracted"
        safe_extract(archive_path, extracted)
        repository_root = archive_root(extracted)
        if source["commit"] not in repository_root.name:
            raise RuntimeError(f"unexpected archive root for {repository}: {repository_root.name}")
        license_source = find_license(repository_root, source["license_file"])
        license_record = copy_verified(
            license_source,
            root / "licenses" / pilot / safe_name / source["license_file"],
            source["license_sha256"],
        )
        repo_stats = PilotStats()
        skipped_vendor = 0
        skipped_docs = 0
        for path in sorted(repository_root.rglob("*.py")):
            relative = path.relative_to(repository_root)
            if is_vendor_path(relative):
                skipped_vendor += 1
                continue
            if is_noncode_path(relative):
                skipped_docs += 1
                continue
            partition = "tests" if is_test_path(relative) else "code"
            records = test_records if partition == "tests" else code_records
            process_code_file(
                source_path=path,
                relative_path=relative,
                source="github",
                source_dataset="g01_github_eight",
                repository=repository,
                revision=source["commit"],
                source_url=_repo_url(repository, source["commit"], relative.as_posix()),
                license_spdx=source["license_spdx"],
                license_path=license_record["path"],
                acquired_at=acquired_at,
                csn_hashes=csn_hashes,
                seen_hashes=seen_hashes,
                stats=stats,
                records=records,
                partition=partition,
            )
        repo_stats.increment("files_skipped_vendor", skipped_vendor)
        repo_stats.increment("files_skipped_noncode", skipped_docs)
        repo_reports.append(
            {
                "repository": repository,
                "tag": source["tag"],
                "commit": source["commit"],
                "acquisition": acquisition,
                "license": license_record,
                "counts": {
                    "code_records": sum(1 for item in code_records if item["repository_name"] == repository),
                    "test_records": sum(1 for item in test_records if item["repository_name"] == repository),
                    "skipped_vendor": skipped_vendor,
                    "skipped_noncode": skipped_docs,
                },
                "stats": repo_stats.as_dict(),
            }
        )
    code_path = _output_path(root, pilot, "github_code.jsonl")
    tests_path = _output_path(root, pilot, "github_tests.jsonl")
    write_jsonl(code_path, code_records)
    write_jsonl(tests_path, test_records)
    report = {
        "pilot": pilot,
        "status": "COMPLETED",
        "sources": G01,
        "repositories": repo_reports,
        "scope": "all .py; tests in separate partition; vendor/third-party and docs/examples/benchmarks excluded",
        "stats": stats.as_dict(),
        "output_paths": {"code": str(code_path), "tests": str(tests_path)},
        "output_sha256": {"code": sha256_file(code_path), "tests": sha256_file(tests_path)},
        "outputs": {
            "code_records": len(code_records),
            "test_records": len(test_records),
            "code_tokens": sum(int(item["provisional_token_count"]) for item in code_records),
            "test_tokens": sum(int(item["provisional_token_count"]) for item in test_records),
            "tokens": sum(int(item["provisional_token_count"]) for item in code_records + test_records),
        },
        "caps": {"archive_bytes_per_repo": sorted({item["max_bytes"] for item in G01}), "records": None, "tokens": None},
        "completed_at": utc_now_iso(),
    }
    write_json(_report_path(root, pilot), report)
    return report


def run_d01(root: Path, local: Path, csn_hashes: set[str], seen_hashes: set[str]) -> dict[str, Any]:
    from scripts.scrapers.scientific_docs import iter_python_blocks

    pilot = "d01_scikit_docs"
    source = SCIKIT_DOCS
    raw_dir = _raw_file(root, "scikit_docs", "")
    raw_dir.mkdir(parents=True, exist_ok=True)
    local_dir = local / pilot
    local_dir.mkdir(parents=True, exist_ok=True)
    archive_path = local_dir / "scikit-learn-docs-1.9.1.zip"
    acquisition = download(source["url"], archive_path, max_bytes=source["max_bytes"])
    if acquisition["size"] != source["expected_size"]:
        raise RuntimeError(f"unexpected scikit docs size: {acquisition['size']}")
    copy_verified(archive_path, _raw_file(root, "scikit_docs", archive_path.name))
    license_local = local_dir / "COPYING"
    download(source["license_url"], license_local, expected_sha256=source["license_sha256"])
    license_record = copy_verified(
        license_local,
        root / "licenses" / pilot / "COPYING",
        source["license_sha256"],
    )
    records: list[dict[str, Any]] = []
    stats = PilotStats()
    acquired_at = utc_now_iso()
    context_tokens = 0
    blocks_examined = 0
    by_detection: dict[str, int] = {}
    for block in iter_python_blocks(archive_path, "https://scikit-learn.org/stable/"):
        if blocks_examined >= source["max_blocks_examined"]:
            stats.increment("block_scan_cap_reached")
            break
        if len(records) >= source["max_records"] or context_tokens >= source["max_context_tokens"]:
            stats.increment("record_or_context_cap_reached")
            break
        blocks_examined += 1
        by_detection[block.detection_method] = by_detection.get(block.detection_method, 0) + 1
        code = clean_code(block.code)
        quality = evaluate_code(code)
        if not quality["accepted"]:
            stats.reject(str(quality["reason"]))
            continue
        digest = dedup_hash(code)
        if digest in csn_hashes:
            stats.reject("duplicate_csn")
            continue
        if digest in seen_hashes:
            stats.reject("duplicate_pilot")
            continue
        seen_hashes.add(digest)
        context = " ".join(block.context.split())
        context_chars = len(context)
        context_token_count = context_chars // 4
        context_tokens += context_token_count
        stats.increment("units_accepted")
        stats.increment("accepted_chars", quality["chars"])
        stats.increment("accepted_tokens", quality["tokens"])
        stats.increment("context_chars", context_chars)
        stats.increment("context_tokens", context_token_count)
        records.append(
            make_record(
                source="scikit_docs",
                source_dataset="d01_scikit_docs",
                source_family="docs",
                source_url=block.source_url,
                repository=source["repository"],
                revision=source["docs_commit"],
                file_path=block.source_url,
                unit={
                    "code": code,
                    "content_hash": digest,
                    "kind": "documentation_example",
                    "qualified_name": block.section or "documentation",
                    "line_start": 1,
                    "line_end": len(code.splitlines()),
                },
                quality=quality,
                license_spdx=source["license_spdx"],
                license_path=license_record["path"],
                acquired_at=acquired_at,
                extra={
                    "documentation_version": source["docs_version"],
                    "source_release_commit": source["source_commit"],
                    "section": block.section,
                    "context": context,
                    "context_char_count": context_chars,
                    "context_token_count": context_token_count,
                    "context_token_count_status": "PROVISIONAL_CHAR4",
                    "detection_method": block.detection_method,
                    "partition": "docs_code",
                },
            )
        )
    stats.increment("blocks_examined", blocks_examined)
    output_path = _output_path(root, pilot, "scikit_docs_code.jsonl")
    write_jsonl(output_path, records)
    report = {
        "pilot": pilot,
        "status": "COMPLETED",
        "source": source,
        "acquisition": acquisition,
        "license": license_record,
        "scope": "Sphinx code/doctest blocks; prose retained only as context for accepted code examples",
        "stats": stats.as_dict(),
        "detection_methods": by_detection,
        "output_path": str(output_path),
        "output_sha256": sha256_file(output_path),
        "outputs": {
            "records": len(records),
            "code_tokens": sum(int(item["provisional_token_count"]) for item in records),
            "code_chars": sum(int(item["char_count"]) for item in records),
            "context_tokens": context_tokens,
        },
        "caps": {"archive_bytes": source["max_bytes"], "records": source["max_records"], "context_tokens": source["max_context_tokens"], "blocks_examined": source["max_blocks_examined"]},
        "completed_at": utc_now_iso(),
    }
    write_json(_report_path(root, pilot), report)
    return report


def write_summary(root: Path) -> dict[str, Any]:
    reports = {}
    for pilot in ("c01_cpython", "g01_github_eight", "d01_scikit_docs"):
        path = _report_path(root, pilot)
        reports[pilot] = json.loads(path.read_text(encoding="utf-8"))
    summary = {
        "pilot_root": str(root),
        "status": "COMPLETED",
        "pilot_count": len(reports),
        "pilots": reports,
        "totals": {
            "records": sum(item["outputs"].get("records", item["outputs"].get("code_records", 0) + item["outputs"].get("test_records", 0)) for item in reports.values()),
            "tokens": sum(item["outputs"].get("tokens", item["outputs"].get("code_tokens", 0) + item["outputs"].get("test_tokens", 0)) for item in reports.values()),
            "context_tokens": sum(item["outputs"].get("context_tokens", 0) for item in reports.values()),
        },
        "completed_at": utc_now_iso(),
    }
    write_json(root / "reports" / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("c01", "g01", "d01", "all", "summary"))
    parser.add_argument("--pilot-root", type=Path, default=DEFAULT_PILOT_ROOT)
    parser.add_argument("--local-root", type=Path, default=DEFAULT_LOCAL_ROOT)
    parser.add_argument("--csn", type=Path, default=DEFAULT_CSN)
    arguments = parser.parse_args()
    _ensure_root(arguments.pilot_root)
    if arguments.phase == "summary":
        print(json.dumps(write_summary(arguments.pilot_root), indent=2))
        return 0
    seen_hashes: set[str] = set()
    csn_hashes: set[str] = set()
    if arguments.phase in {"c01", "g01", "d01", "all"}:
        csn_hashes = load_csn_hashes(arguments.csn)
    if arguments.phase == "c01":
        report = run_c01(arguments.pilot_root, arguments.local_root, csn_hashes, seen_hashes)
    elif arguments.phase == "g01":
        report = run_g01(arguments.pilot_root, arguments.local_root, csn_hashes, seen_hashes)
    elif arguments.phase == "d01":
        report = run_d01(arguments.pilot_root, arguments.local_root, csn_hashes, seen_hashes)
    else:
        run_c01(arguments.pilot_root, arguments.local_root, csn_hashes, seen_hashes)
        run_g01(arguments.pilot_root, arguments.local_root, csn_hashes, seen_hashes)
        report = run_d01(arguments.pilot_root, arguments.local_root, csn_hashes, seen_hashes)
    print(json.dumps({"pilot": report["pilot"], "status": report["status"], "outputs": report["outputs"], "output_sha256": report.get("output_sha256", report.get("output_paths"))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
