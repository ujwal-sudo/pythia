"""Stream Hugging Face dataset shards into the archive.

The laptop has ~7 GB free; the datasets are 23–29 GB. So nothing is stored
locally for longer than one shard: download → verify sha256 → upload to the
store → delete. Several shards move at once to work around per-connection
throughput, with a disk guard so the staging area cannot fill the disk.

Resumable: a shard already in the store with the right size is skipped.

    python -m scripts.corpus.ingest --source stack_dedup_python --limit 2
    python -m scripts.corpus.ingest --source stack_dedup_python --workers 4
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from scripts.corpus.sources import load as load_sources
from scripts.storage import RootedStore, open_store

HF_API = "https://huggingface.co/api/datasets"
HF_RESOLVE = "https://huggingface.co/datasets"
MIN_FREE_BYTES = 2 * 1024**3
STAGING = Path(__file__).resolve().parents[2] / ".ingest"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_token() -> str | None:
    """HF token from the environment, else the repo's .env files."""
    token = os.environ.get("HF_TOKEN")
    if token:
        return token.strip()
    repo = Path(__file__).resolve().parents[2]
    for candidate in (repo / ".env", repo.parent / ".env"):
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("HF_TOKEN"):
                _, _, value = line.partition("=")
                return value.strip().strip("'\"")
    return None


@dataclass(frozen=True, slots=True)
class RemoteFile:
    path: str
    size: int
    sha256: str | None

    @property
    def filename(self) -> str:
        return self.path.rsplit("/", 1)[-1]


def list_files(dataset: str, subpath: str, token: str | None) -> list[RemoteFile]:
    url = f"{HF_API}/{dataset}/tree/main/{subpath}?recursive=true"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = requests.get(url, headers=headers, timeout=60)
    if response.status_code == 401:
        raise PermissionError(
            f"{dataset} is gated: accept the terms on the dataset page first"
        )
    response.raise_for_status()
    files: list[RemoteFile] = []
    for item in response.json():
        if item.get("type") != "file":
            continue
        lfs = item.get("lfs") or {}
        files.append(
            RemoteFile(
                path=item["path"],
                size=int(item.get("size") or lfs.get("size") or 0),
                sha256=lfs.get("oid"),
            )
        )
    return sorted(files, key=lambda f: f.path)


def _download(dataset: str, item: RemoteFile, token: str | None, dest: Path) -> str:
    """Download one shard, return its sha256."""
    url = f"{HF_RESOLVE}/{dataset}/resolve/main/{item.path}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    digest = hashlib.sha256()
    written = 0
    with requests.get(url, headers=headers, stream=True, timeout=300) as response:
        response.raise_for_status()
        with dest.open("wb") as handle:
            for chunk in response.iter_content(1 << 20):
                if not chunk:
                    continue
                handle.write(chunk)
                digest.update(chunk)
                written += len(chunk)
    if written != item.size:
        raise IOError(f"size mismatch for {item.path}: got {written}, expected {item.size}")
    return digest.hexdigest()


def _chunks(path: Path, chunk_size: int = 1 << 20):
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                return
            yield chunk


def ingest(
    store: RootedStore,
    source_id: str,
    *,
    workers: int = 4,
    limit: int | None = None,
    keep_local: bool = False,
    max_bytes: int | None = None,
) -> dict:
    registry = load_sources()
    source = next((s for s in registry["sources"] if s["id"] == source_id), None)
    if source is None:
        raise KeyError(f"unknown source {source_id!r}")
    access = source["access"]
    if access["type"] != "huggingface":
        raise ValueError(f"{source_id} is not a Hugging Face source")

    token = load_token()
    files = list_files(access["dataset"], access.get("path", ""), token)
    if limit:
        files = files[:limit]
    if max_bytes:
        selected, total = [], 0
        for item in files:
            if total + item.size > max_bytes:
                break
            selected.append(item)
            total += item.size
        files = selected

    prefix = f"raw/hf/{access['dataset'].replace('/', '__')}/{access.get('path', '')}".rstrip("/")
    STAGING.mkdir(parents=True, exist_ok=True)

    plan: list[tuple[RemoteFile, str, bool]] = []
    for item in files:
        dest_rel = f"{prefix}/{item.path[len(access.get('path', '')):].lstrip('/')}"
        existing = store.stat(dest_rel)
        plan.append((item, dest_rel, existing is not None and existing.size == item.size))

    todo = [p for p in plan if not p[2]]
    print(f"{len(plan)} shards, {len(plan) - len(todo)} already present, {len(todo)} to fetch")

    results: list[dict] = []
    lock = __import__("threading").Lock()
    started = time.time()

    def work(item: RemoteFile, dest_rel: str) -> dict:
        free = shutil.disk_usage(STAGING).free
        if free < MIN_FREE_BYTES + item.size:
            raise IOError(f"disk guard: {free / 1e9:.1f} GB free, shard needs {item.size / 1e9:.1f} GB")
        local = STAGING / f"{time.time_ns()}-{item.filename}"
        began = time.time()
        try:
            digest = _download(access["dataset"], item, token, local)
            if item.sha256 and digest != item.sha256:
                raise IOError(f"sha256 mismatch for {item.path}")
            store.write(dest_rel, _chunks(local))
            remote = store.stat(dest_rel)
            if remote is None or remote.size != item.size:
                raise IOError(f"upload verification failed for {dest_rel}")
            return {
                "path": item.path,
                "rel": dest_rel,
                "bytes": item.size,
                "sha256": digest,
                "seconds": round(time.time() - began, 1),
                "status": "ok",
            }
        finally:
            if not keep_local:
                local.unlink(missing_ok=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(work, item, rel): item for item, rel, skip in plan if not skip}
        for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            item = futures[future]
            try:
                record = future.result()
            except Exception as error:  # one bad shard must not kill the run
                record = {"path": item.path, "status": "error", "error": f"{type(error).__name__}: {error}"}
            with lock:
                results.append(record)
            done = sum(r["bytes"] for r in results if r["status"] == "ok")
            print(
                f"[{index}/{len(todo)}] {record['status']:5} {item.path} "
                f"({done / 1e9:.1f} GB done, {time.time() - started:.0f}s)",
                flush=True,
            )

    for item, rel, skipped in plan:
        if skipped:
            results.append({"path": item.path, "rel": rel, "bytes": item.size, "status": "skipped"})

    ok = [r for r in results if r["status"] == "ok"]
    failed = [r for r in results if r["status"] == "error"]
    manifest = {
        "source": source_id,
        "dataset": access["dataset"],
        "subpath": access.get("path", ""),
        "prefix": prefix,
        "ingested_at": utc_now(),
        "shards_total": len(plan),
        "shards_fetched": len(ok),
        "shards_skipped": len(results) - len(ok) - len(failed),
        "shards_failed": len(failed),
        "bytes_fetched": sum(r["bytes"] for r in ok),
        "files": results,
        "failures": failed,
    }
    if ok or failed:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        store.write_text(
            store.manifests(f"ingest_{source_id}_{stamp}.json"),
            json.dumps(manifest, indent=2) + "\n",
        )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stream HF shards into the archive.")
    parser.add_argument("--source", required=True, help="id from scripts/corpus/sources.json")
    parser.add_argument("--store", default=None)
    parser.add_argument("--root", default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=None, help="first N shards only")
    parser.add_argument("--max-bytes", type=int, default=None, help="stop before this many bytes")
    parser.add_argument("--keep-local", action="store_true", help="keep downloaded shards in .ingest/")
    args = parser.parse_args(argv)

    store = open_store(args.store, args.root)
    manifest = ingest(
        store,
        args.source,
        workers=args.workers,
        limit=args.limit,
        keep_local=args.keep_local,
        max_bytes=args.max_bytes,
    )
    print(json.dumps({k: v for k, v in manifest.items() if k not in ("files", "failures")}, indent=2))
    return 0 if manifest["shards_failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
