"""Build a batch directly from Hugging Face shards, without a second download.

Downloading 28 GB into the archive and then downloading it again to clean would
cost ~115 GB of transfer for one batch. Instead a small prefetch pool keeps at
most a few shards on local disk while a single consumer cleans them and writes
batch shards straight to the archive.

The run stops on a character budget, so one night buys exactly the tokens we
need rather than all 20 B available in The Stack.

    python -m scripts.corpus.hf_batch --source stack_dedup_python \
        --max-chars 13e9 --shards 30 --workers 4
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import datetime as dt
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pyarrow.parquet as pq

from scripts.corpus.batch import (
    ShardWriter,
    _prior_hashes,
    _require_absent,
    _write_hashes,
    load_registry,
    next_batch_id,
    save_registry,
    utc_now,
)
from scripts.corpus.ingest import HF_RESOLVE, load_token, list_files
from scripts.corpus.pipeline import CurationRun, DedupIndex
from scripts.corpus.sources import load as load_sources
from scripts.storage import RootedStore, open_store

STAGING = Path(__file__).resolve().parents[2] / ".ingest"
PREFETCH = 3
MIN_FREE_BYTES = 2 * 1024**3


def _download_one(dataset: str, item, token: str | None, dest: Path, attempts: int = 6) -> None:
    """Download with Range-resume; the link here drops for minutes at a time."""
    import hashlib
    import time

    import requests

    url = f"{HF_RESOLVE}/{dataset}/resolve/main/{item.path}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        have = dest.stat().st_size if dest.exists() else 0
        if have == item.size:
            break
        request_headers = dict(headers)
        if have:
            request_headers["Range"] = f"bytes={have}-"
        try:
            with requests.get(url, headers=request_headers, stream=True, timeout=(30, 120)) as response:
                if response.status_code == 416 and have == item.size:
                    break
                response.raise_for_status()
                mode = "ab" if have and response.status_code == 206 else "wb"
                with dest.open(mode) as handle:
                    for chunk in response.iter_content(1 << 20):
                        if chunk:
                            handle.write(chunk)
            if dest.stat().st_size == item.size:
                break
            last_error = IOError(f"short read: {dest.stat().st_size}/{item.size}")
        except Exception as error:  # noqa: BLE001 - network layer, retried below
            last_error = error
        time.sleep(min(2 ** attempt, 30))
    else:
        raise IOError(f"download failed after {attempts} attempts: {last_error}")

    digest = hashlib.sha256()
    with dest.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    if item.sha256 and digest.hexdigest() != item.sha256:
        raise IOError(f"sha256 mismatch for {item.path}")


def build(
    store: RootedStore,
    source_id: str,
    *,
    max_chars: int,
    shards: int | None = None,
    offset: int = 0,
    workers: int = 4,
    batch_id: str | None = None,
    shard_bytes: int = 200 * 1024 * 1024,
) -> dict:
    registry = load_registry(store)
    batch_id = batch_id or next_batch_id(registry)
    _require_absent(store, registry, batch_id)

    source = next(s for s in load_sources()["sources"] if s["id"] == source_id)
    access = source["access"]
    token = load_token()
    files = list_files(access["dataset"], access.get("path", ""), token)
    if offset:
        files = files[offset:]
    if shards:
        files = files[:shards]
    if not files:
        raise RuntimeError("no shards selected")

    STAGING.mkdir(parents=True, exist_ok=True)
    started = time.time()

    with tempfile.TemporaryDirectory(prefix="pythia-hf-") as tmp:
        with DedupIndex(Path(tmp) / "dedup.sqlite") as index:
            seeded = index.seed(_prior_hashes(store, registry), label="prior-batch")
            run = CurationRun(
                store=store,
                files=[],
                index=index,
                snapshot_id=batch_id,
            )
            writer = ShardWriter(store, batch_id, shard_bytes)
            processed: list[dict] = []
            failures: list[dict] = []

            pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers))
            pending: collections.deque = collections.deque()
            try:
                for item in files[:PREFETCH]:
                    free = shutil.disk_usage(STAGING).free
                    if free < MIN_FREE_BYTES + item.size:
                        raise IOError(
                            f"disk guard: {free / 1e9:.1f} GB free, next shard {item.size / 1e9:.1f} GB"
                        )
                    local = STAGING / f"{time.time_ns()}-{item.filename}"
                    pending.append((item, local, pool.submit(_download_one, access["dataset"], item, token, local)))
                upcoming = iter(files[PREFETCH:])

                while pending:
                    item, local, future = pending.popleft()
                    try:
                        future.result()
                    except Exception as error:  # one bad shard must not kill the run
                        local.unlink(missing_ok=True)
                        failures.append({"path": item.path, "error": f"{type(error).__name__}: {error}"})
                        print(f"SKIP {item.path}: {error}", flush=True)
                        nxt = next(upcoming, None)
                        if nxt is not None:
                            local_next = STAGING / f"{time.time_ns()}-{nxt.filename}"
                            pending.append((nxt, local_next, pool.submit(_download_one, access["dataset"], nxt, token, local_next)))
                        continue
                    rel = f"raw/hf/{access['dataset'].replace('/', '__')}/{item.path}"
                    rows = (
                        record
                        for batch in pq.ParquetFile(local).iter_batches(batch_size=2000)
                        for record in batch.to_pylist()
                    )
                    for line in run.consume(rel, rows):
                        writer.write(line)
                    local.unlink(missing_ok=True)
                    processed.append({"path": item.path, "bytes": item.size})
                    print(
                        f"[{len(processed)}] {item.path} kept={run.totals['kept']:,} "
                        f"chars={run.totals['chars_kept'] / 1e9:.2f}B {time.time() - started:.0f}s",
                        flush=True,
                    )
                    if run.totals["chars_kept"] >= max_chars:
                        break
                    nxt = next(upcoming, None)
                    if nxt is not None:
                        local_next = STAGING / f"{time.time_ns()}-{nxt.filename}"
                        pending.append((nxt, local_next, pool.submit(_download_one, access["dataset"], nxt, token, local_next)))
            except Exception as error:
                failures.append({"path": "run", "error": f"{type(error).__name__}: {error}"})
                print(f"FAILED: {error}", flush=True)
            finally:
                pool.shutdown(wait=True, cancel_futures=True)

            shard_rows = writer.close()
            totals = run.finalise_totals()

    hashes_meta = _write_hashes(store, batch_id, run.new_hashes)
    entry = {
        "id": batch_id,
        "kind": "hf_cleaned",
        "status": "complete" if not failures else "partial",
        "failures": failures,
        "created_at": utc_now(),
        "source": source_id,
        "dataset": access["dataset"],
        "subpath": access.get("path", ""),
        "records": totals.get("kept", 0),
        "chars": totals.get("chars_kept", 0),
        "shards_processed": len(processed),
        "inputs": processed,
        "dropped": {
            "duplicates": totals.get("duplicates", 0),
            "license_hold": totals.get("license_hold", 0),
            "license_deny": totals.get("license_deny", 0),
            "text_missing": totals.get("text_missing", 0),
            "parse_errors": totals.get("parse_errors", 0),
        },
        "dedup_seeded_from_prior_batches": seeded,
        "shards": shard_rows,
        "hashes": hashes_meta,
        "policy": "DEFAULT",
        "elapsed_seconds": round(time.time() - started, 1),
    }
    store.write_text(f"batches/{batch_id}/stats.json", json.dumps(entry, indent=2) + "\n")
    registry["batches"].append(entry)
    save_registry(store, registry)
    return entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean HF shards straight into a batch.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--max-chars", type=float, required=True, help="stop after this many characters, e.g. 13e9")
    parser.add_argument("--shards", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--id", default=None)
    parser.add_argument("--store", default=None)
    parser.add_argument("--root", default=None)
    args = parser.parse_args(argv)

    store = open_store(args.store, args.root)
    entry = build(
        store,
        args.source,
        max_chars=int(args.max_chars),
        shards=args.shards,
        offset=args.offset,
        workers=args.workers,
        batch_id=args.id,
    )
    print(json.dumps({k: v for k, v in entry.items() if k != "inputs"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
