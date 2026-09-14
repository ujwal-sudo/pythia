"""Official Python documentation ingestion for Stage 1 training candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import statistics
import sys
import time
import tokenize
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Iterable

import pycodestyle
import requests
from bs4 import BeautifulSoup, Tag
from tqdm import tqdm

from config import (
    LOGS_DIR,
    MAX_TOKEN_LENGTH,
    MIN_COMMENT_RATIO,
    MIN_TOKEN_LENGTH,
    PEP8_MAX_VIOLATIONS,
    PYTHON_DOCS_DIR,
    STAGE1_DIR,
)
from scripts.logger import get_logger
from scripts.validators.ast_validator import validate_python


logger = get_logger(__name__)

SOURCE = "python_docs"
STAGE = 1
DEFAULT_DOWNLOAD_PAGE = "https://docs.python.org/3/download.html"
DEFAULT_OUTPUT_PATH = STAGE1_DIR / "python_docs.jsonl"
DEFAULT_MANIFEST_PATH = PYTHON_DOCS_DIR / "manifest.json"
DEFAULT_REPORT_PATH = LOGS_DIR / "python_docs_report.json"
TOKEN_COUNT_METHOD = "provisional_python_tokenize_significant_tokens_v1"
LICENSE = "Python Software Foundation License"
LICENSE_URL = "https://docs.python.org/3/license.html"
KG_PENDING = "pending"

_PYTHON_CLASS_MARKERS = {"python", "python3", "pycon", "python-console"}
_NON_PYTHON_CLASS_MARKERS = {
    "bash",
    "console",
    "doscon",
    "html",
    "javascript",
    "json",
    "none",
    "shell",
    "text",
    "xml",
}


@dataclass(frozen=True, slots=True)
class DownloadMetadata:
    source_url: str
    download_url: str
    documentation_version: str
    license: str
    license_url: str


@dataclass(frozen=True, slots=True)
class ExtractedBlock:
    code: str
    context: str
    section: str
    source_url: str
    detection_method: str


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_code(code: str) -> str:
    return code.replace("\r\n", "\n").replace("\r", "\n").strip()


def exact_hash(code: str) -> str:
    return hashlib.sha256(normalize_code(code).encode("utf-8")).hexdigest()


def provisional_token_count(code: str) -> int:
    ignored = {
        tokenize.COMMENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
        tokenize.ENDMARKER,
        tokenize.INDENT,
        tokenize.NEWLINE,
        tokenize.NL,
    }
    try:
        tokens = tokenize.generate_tokens(StringIO(code).readline)
        return sum(1 for token in tokens if token.type not in ignored)
    except tokenize.TokenError:
        return len(code.split())


def measure_pep8_violations(code: str) -> int:
    style = pycodestyle.StyleGuide(quiet=True)
    checker = pycodestyle.Checker(
        lines=code.splitlines(keepends=True),
        options=style.options,
    )
    return int(checker.check_all())


def discover_download_metadata(version: str | None = None, timeout: int = 30) -> DownloadMetadata:
    """Discover an official docs HTML archive without hard-coding a release."""
    response = requests.get(DEFAULT_DOWNLOAD_PAGE, timeout=timeout)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    archive_pattern = re.compile(r"python-([0-9][^/\"']*)-docs-html\.zip$")
    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        match = archive_pattern.search(href)
        if not match:
            continue
        docs_version = match.group(1)
        if version and docs_version != version:
            continue
        download_url = requests.compat.urljoin(DEFAULT_DOWNLOAD_PAGE, href)
        source_url = f"https://docs.python.org/{_major_minor(docs_version)}/"
        return DownloadMetadata(
            source_url=source_url,
            download_url=download_url,
            documentation_version=docs_version,
            license=LICENSE,
            license_url=LICENSE_URL,
        )

    requested = f" for version {version}" if version else ""
    raise RuntimeError(f"could not discover official Python docs archive{requested}")


def download_archive(
    destination: Path = PYTHON_DOCS_DIR,
    version: str | None = None,
    timeout: int = 30,
    retries: int = 3,
) -> Path:
    metadata = discover_download_metadata(version=version, timeout=timeout)
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination / Path(metadata.download_url).name
    retrieved_at = utc_now_iso()

    if archive_path.exists() and archive_path.stat().st_size > 0:
        logger.info("Reusing existing Python docs archive: %s", archive_path)
        write_manifest(
            DEFAULT_MANIFEST_PATH,
            metadata,
            retrieved_at,
            archive_path,
            sha256_file(archive_path),
            {},
        )
        return archive_path

    partial_path = archive_path.with_suffix(archive_path.suffix + ".part")
    for attempt in range(1, retries + 1):
        headers: dict[str, str] = {}
        existing_size = partial_path.stat().st_size if partial_path.exists() else 0
        if existing_size:
            headers["Range"] = f"bytes={existing_size}-"

        try:
            with requests.get(
                metadata.download_url,
                headers=headers,
                stream=True,
                timeout=timeout,
            ) as response:
                response.raise_for_status()
                total = _download_total(response, existing_size)
                _ensure_disk_space(destination, total)
                mode = "ab" if existing_size and response.status_code == 206 else "wb"
                logger.info("Downloading Python docs archive: %s", metadata.download_url)
                with partial_path.open(mode) as handle:
                    progress = tqdm(
                        total=total,
                        initial=existing_size if mode == "ab" else 0,
                        unit="B",
                        unit_scale=True,
                        desc="python-docs",
                    )
                    with progress:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                handle.write(chunk)
                                progress.update(len(chunk))
            partial_path.replace(archive_path)
            checksum = sha256_file(archive_path)
            write_manifest(
                DEFAULT_MANIFEST_PATH,
                metadata,
                retrieved_at,
                archive_path,
                checksum,
                {},
            )
            logger.info("Downloaded Python docs archive to %s", archive_path)
            return archive_path
        except requests.RequestException:
            if attempt == retries:
                raise
            sleep_seconds = 2 ** (attempt - 1)
            logger.warning("Download attempt %s failed; retrying in %ss", attempt, sleep_seconds)
            time.sleep(sleep_seconds)

    raise RuntimeError("unreachable download retry state")


def process_documentation(
    raw_path: Path,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    source_url: str | None = None,
    download_url: str | None = None,
    documentation_version: str | None = None,
    retrieved_at: str | None = None,
    min_tokens: int = MIN_TOKEN_LENGTH,
    max_tokens: int = MAX_TOKEN_LENGTH,
    min_comment_ratio: float = MIN_COMMENT_RATIO,
    pep8_max_violations: int = PEP8_MAX_VIOLATIONS,
) -> dict[str, object]:
    raw_path = raw_path.resolve()
    retrieved_at = retrieved_at or utc_now_iso()
    documentation_version = documentation_version or infer_documentation_version(raw_path)
    source_url = source_url or f"https://docs.python.org/{_major_minor(documentation_version)}/"
    download_url = download_url or _download_url_from_path(raw_path)
    metadata = DownloadMetadata(
        source_url=source_url,
        download_url=download_url,
        documentation_version=documentation_version,
        license=LICENSE,
        license_url=LICENSE_URL,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    stats: dict[str, int | float] = {
        "blocks_examined": 0,
        "python_candidates": 0,
        "syntax_valid": 0,
        "syntax_invalid": 0,
        "too_short": 0,
        "too_long": 0,
        "low_documentation": 0,
        "pep8_rejected": 0,
        "exact_duplicates": 0,
        "retained": 0,
    }
    retained_records: list[dict[str, object]] = []
    code_lengths: list[int] = []
    comment_ratios: list[float] = []
    pep8_counts: list[int] = []
    seen_hashes: set[str] = set()

    for block in iter_python_doc_blocks(raw_path, source_url):
        stats["blocks_examined"] += 1
        stats["python_candidates"] += 1
        code = normalize_code(block.code)
        if not code:
            stats["syntax_invalid"] += 1
            continue

        code_hash = exact_hash(code)
        if code_hash in seen_hashes:
            stats["exact_duplicates"] += 1
            continue
        seen_hashes.add(code_hash)

        validation = validate_python(code)
        if not validation.is_valid:
            stats["syntax_invalid"] += 1
            continue

        stats["syntax_valid"] += 1
        token_count = provisional_token_count(code)
        pep8_violations = measure_pep8_violations(code)
        code_lengths.append(len(code))
        comment_ratios.append(validation.comment_ratio)
        pep8_counts.append(pep8_violations)

        if token_count < min_tokens:
            stats["too_short"] += 1
            continue
        if token_count > max_tokens:
            stats["too_long"] += 1
            continue
        if validation.comment_ratio < min_comment_ratio:
            stats["low_documentation"] += 1
            continue
        if pep8_violations > pep8_max_violations:
            stats["pep8_rejected"] += 1
            continue

        record = {
            "id": f"python_docs:{documentation_version}:{code_hash[:16]}",
            "code": code,
            "context": block.context,
            "source": SOURCE,
            "stage": STAGE,
            "documentation_version": documentation_version,
            "section": block.section,
            "source_url": block.source_url,
            "license": LICENSE,
            "license_url": LICENSE_URL,
            "retrieved_at": retrieved_at,
            "provisional_token_count": token_count,
            "token_count_method": TOKEN_COUNT_METHOD,
            "comment_ratio": validation.comment_ratio,
            "comment_count": validation.comment_count,
            "docstring_count": validation.docstring_count,
            "pep8_violations": pep8_violations,
            "syntax_valid": True,
            "kg_validation_status": KG_PENDING,
            "exact_hash": code_hash,
            "detection_method": block.detection_method,
            "ast_metadata": {
                "node_count": validation.node_count,
                "function_count": validation.function_count,
                "class_count": validation.class_count,
                "import_count": validation.import_count,
                "loop_count": validation.loop_count,
                "conditional_count": validation.conditional_count,
                "return_count": validation.return_count,
            },
        }
        retained_records.append(record)
        stats["retained"] += 1

    write_jsonl(output_path, retained_records)
    summary = stats | {
        "average_code_length": _average(code_lengths),
        "median_code_length": _median(code_lengths),
        "average_comment_ratio": _average(comment_ratios),
        "average_pep8_violations": _average(pep8_counts),
        "output_path": str(output_path),
    }
    report_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checksum = sha256_file(raw_path) if raw_path.is_file() else None
    manifest = write_manifest(
        manifest_path,
        metadata,
        retrieved_at,
        raw_path,
        checksum,
        {
            "candidate_count": int(stats["python_candidates"]),
            "valid_python_count": int(stats["syntax_valid"]),
            "retained_count": int(stats["retained"]),
            "output_path": str(output_path),
            "report_path": str(report_path),
        },
    )
    logger.info(
        "Python docs processing complete: %s candidates, %s retained",
        stats["python_candidates"],
        stats["retained"],
    )
    return {"manifest": manifest, "stats": summary, "records": retained_records}


def iter_python_doc_blocks(raw_path: Path, source_url: str) -> Iterable[ExtractedBlock]:
    for relative_path, html in iter_html_documents(raw_path):
        soup = BeautifulSoup(html, "html.parser")
        page_url = requests.compat.urljoin(source_url, relative_path.as_posix())
        for block in soup.find_all("div", class_=lambda value: value and "highlight" in str(value)):
            if not isinstance(block, Tag):
                continue
            code_tag = block.find("pre")
            if not code_tag:
                continue
            raw_code = code_tag.get_text()
            detection = detect_python_block(block, raw_code)
            if detection is None:
                continue
            code = strip_doctest_prompts(raw_code) if detection == "doctest" else raw_code
            yield ExtractedBlock(
                code=code,
                context=nearest_context(block),
                section=nearest_section(block),
                source_url=page_url,
                detection_method=detection,
            )


def iter_html_documents(raw_path: Path) -> Iterable[tuple[Path, str]]:
    if raw_path.is_file() and zipfile.is_zipfile(raw_path):
        with zipfile.ZipFile(raw_path) as archive:
            names = [name for name in archive.namelist() if name.endswith(".html")]
            root = common_archive_root(names)
            for name in sorted(names):
                relative = Path(name)
                if root and name.startswith(root + "/"):
                    relative = Path(name[len(root) + 1 :])
                with archive.open(name) as handle:
                    yield relative, handle.read().decode("utf-8", errors="replace")
        return

    if raw_path.is_dir():
        for path in sorted(raw_path.rglob("*.html")):
            yield path.relative_to(raw_path), path.read_text(encoding="utf-8", errors="replace")
        return

    raise ValueError(f"raw path must be a Python docs HTML zip archive or directory: {raw_path}")


def common_archive_root(names: list[str]) -> str | None:
    roots = {name.split("/", 1)[0] for name in names if "/" in name}
    return roots.pop() if len(roots) == 1 else None


def detect_python_block(block: Tag, raw_code: str) -> str | None:
    classes = {
        str(class_name).removeprefix("highlight-").lower()
        for parent in [block, *block.parents]
        for class_name in getattr(parent, "get", lambda *_: [])("class", [])
    }
    if "pycon" in classes or looks_like_doctest(raw_code):
        return "doctest"
    if classes & _PYTHON_CLASS_MARKERS:
        return "explicit_python"
    if classes & _NON_PYTHON_CLASS_MARKERS:
        return None
    return None


def looks_like_doctest(raw_code: str) -> bool:
    return any(line.lstrip().startswith((">>> ", "... ")) for line in raw_code.splitlines())


def strip_doctest_prompts(raw_code: str) -> str:
    lines: list[str] = []
    for line in raw_code.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(">>> "):
            lines.append(stripped[4:])
        elif stripped == ">>>":
            lines.append("")
        elif stripped.startswith("... "):
            lines.append(stripped[4:])
        elif stripped == "...":
            lines.append("")
    return "\n".join(lines)


def nearest_section(block: Tag) -> str:
    for previous in block.find_all_previous(["h1", "h2", "h3"]):
        text = previous.get_text(" ", strip=True)
        if text:
            return text
    title = block.find_previous("title")
    return title.get_text(" ", strip=True) if title else ""


def nearest_context(block: Tag) -> str:
    texts: list[str] = []
    for previous in block.find_all_previous(["p", "h1", "h2", "h3"], limit=3):
        text = previous.get_text(" ", strip=True)
        if text:
            texts.append(text)
    return " ".join(reversed(texts))


def write_jsonl(path: Path, records: Iterable[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def write_manifest(
    path: Path,
    metadata: DownloadMetadata,
    retrieved_at: str,
    raw_path: Path,
    checksum: str | None,
    counts: dict[str, object],
) -> dict[str, object]:
    manifest = {
        "source": SOURCE,
        "source_url": metadata.source_url,
        "download_url": metadata.download_url,
        "documentation_version": metadata.documentation_version,
        "retrieved_at": retrieved_at,
        "license": metadata.license,
        "license_url": metadata.license_url,
        "sha256": checksum,
        "raw_path": str(raw_path),
        "candidate_count": 0,
        "valid_python_count": 0,
        "retained_count": 0,
    } | counts
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def infer_documentation_version(raw_path: Path) -> str:
    candidates = [raw_path.name, *raw_path.parts]
    pattern = re.compile(r"python-([0-9][A-Za-z0-9.]+)-docs")
    for candidate in candidates:
        match = pattern.search(candidate)
        if match:
            return match.group(1)
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest official Python documentation examples.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--download", action="store_true", help="download/reuse the docs archive")
    action.add_argument("--process", action="store_true", help="process a local docs archive/directory")
    action.add_argument("--all", action="store_true", help="download/reuse and process")
    parser.add_argument("--raw-path", type=Path, help="local docs HTML zip archive or directory")
    parser.add_argument("--version", help="specific documentation version to download")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--min-tokens", type=int, default=MIN_TOKEN_LENGTH)
    parser.add_argument("--max-tokens", type=int, default=MAX_TOKEN_LENGTH)
    parser.add_argument("--min-comment-ratio", type=float, default=MIN_COMMENT_RATIO)
    parser.add_argument("--pep8-max-violations", type=int, default=PEP8_MAX_VIOLATIONS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    raw_path = args.raw_path

    if args.download or args.all:
        raw_path = download_archive(version=args.version)

    if args.process or args.all:
        if raw_path is None:
            raise SystemExit("--raw-path is required with --process")
        result = process_documentation(
            raw_path=raw_path,
            output_path=args.output,
            manifest_path=args.manifest,
            report_path=args.report,
            min_tokens=args.min_tokens,
            max_tokens=args.max_tokens,
            min_comment_ratio=args.min_comment_ratio,
            pep8_max_violations=args.pep8_max_violations,
        )
        stats = result["stats"]
        print(
            f"python_docs: candidates={stats['python_candidates']} "
            f"retained={stats['retained']} output={args.output}"
        )
    return 0


def _major_minor(version: str) -> str:
    match = re.match(r"([0-9]+\.[0-9]+)", version)
    return match.group(1) if match else "3"


def _download_url_from_path(raw_path: Path) -> str:
    if raw_path.is_file():
        return f"https://docs.python.org/{_major_minor(infer_documentation_version(raw_path))}/archives/{raw_path.name}"
    return ""


def _download_total(response: requests.Response, existing_size: int) -> int | None:
    content_length = response.headers.get("content-length")
    if not content_length:
        return None
    total = int(content_length)
    return total + existing_size if response.status_code == 206 else total


def _ensure_disk_space(destination: Path, required_bytes: int | None) -> None:
    if required_bytes is None:
        return
    free = shutil.disk_usage(destination).free
    if free < required_bytes:
        raise OSError(f"not enough disk space for download: need {required_bytes}, free {free}")


def _average(values: list[int] | list[float]) -> float:
    return float(statistics.fmean(values)) if values else 0.0


def _median(values: list[int]) -> float:
    return float(statistics.median(values)) if values else 0.0


if __name__ == "__main__":
    raise SystemExit(main())
