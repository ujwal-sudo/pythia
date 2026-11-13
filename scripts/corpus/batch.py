"""Immutable, append-only corpus batches.

Collection happens in waves: today's sources are cleaned now, next month's
later. Each wave becomes one batch that never changes, and new batches
deduplicate against every earlier one. Training reads the union of batches in
registry order, so "start training" never waits for the last acquisition.

Layout on the archive:

    batches/REGISTRY.json              ordered list, the dataset version
    batches/batch-001/shard-0000.jsonl cleaned records: {"text", "meta"}
    batches/batch-001/hashes.txt       normalised hashes, for the next batch
    batches/batch-001/stats.json       counts, inputs, drops

    python -m scripts.corpus.batch status
    python -m scripts.corpus.batch adopt --snapshot corpus-v1-20261110
    python -m scripts.corpus.batch clean --stages 1,2,3
    python -m scripts.corpus.batch verify --id batch-001
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from scripts.corpus.build import select_files
from scripts.corpus.license import DEFAULT_POLICY
from scripts.corpus.pipeline import CurationRun, DedupIndex
from scripts.corpus.sync import _chunks, sha256_file
from scripts.storage import RootedStore, open_store

REGISTRY_REL = "batches/REGISTRY.json"
DEFAULT_SHARD_BYTES = 200 * 1024 * 1024


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ registry


def load_registry(store: RootedStore) -> dict:
    if not store.exists(REGISTRY_REL):
        return {"schema_version": 1, "updated_at": utc_now(), "batches": []}
    return json.loads(store.read_text(REGISTRY_REL))


def save_registry(store: RootedStore, registry: dict) -> None:
    registry["updated_at"] = utc_now()
    registry["totals"] = {
        "batches": len(registry["batches"]),
        "records": sum(b["records"] for b in registry["batches"]),
        "chars": sum(b["chars"] for b in registry["batches"]),
    }
    store.write_text(REGISTRY_REL, json.dumps(registry, indent=2) + "\n")


def next_batch_id(registry: dict) -> str:
    used = {b["id"] for b in registry["batches"]}
    index = 1
    while f"batch-{index:03d}" in used:
        index += 1
    return f"batch-{index:03d}"


def _input_rels(entry: dict) -> list[str]:
    return sorted(item["rel"] for item in entry.get("inputs", []))


def _refuse_repeated_inputs(registry: dict, files: list[str]) -> None:
    """Cleaning the same files twice would produce an all-duplicate batch."""
    wanted = sorted(files)
    for batch in registry["batches"]:
        if _input_rels(batch) == wanted:
            raise FileExistsError(
                f"inputs already cleaned as {batch['id']}; only new files can form a batch"
            )


def _require_absent(store: RootedStore, registry: dict, batch_id: str) -> None:
    if any(b["id"] == batch_id for b in registry["batches"]):
        raise FileExistsError(f"batch {batch_id} already registered")
    # Object stores keep empty directories after their files are deleted, so
    # "the prefix exists" is not the same as "a batch is here".
    prefix = f"batches/{batch_id}"
    if store.exists(prefix) and store.files(prefix):
        raise FileExistsError(f"batches/{batch_id} has data but is not registered")


# --------------------------------------------------------------- shard writer


@dataclass
class ShardWriter:
    """Buffer one shard locally, upload it, rotate. 200 MB by default."""

    store: RootedStore
    batch_id: str
    max_bytes: int = DEFAULT_SHARD_BYTES
    tmpdir: Path | None = None
    shards: list[dict] = field(default_factory=list)
    _handle: object = None
    _path: Path | None = None
    _size: int = 0
    _records: int = 0

    def __post_init__(self) -> None:
        self._tmpdir_ctx = tempfile.TemporaryDirectory(prefix="pythia-shard-")
        self.tmpdir = Path(self._tmpdir_ctx.name)

    def _open(self) -> None:
        self._path = self.tmpdir / f"shard-{len(self.shards):04d}.jsonl"
        self._handle = self._path.open("wb")
        self._size = 0
        self._records = 0

    def write(self, line: bytes) -> None:
        if self._handle is None:
            self._open()
        self._handle.write(line)  # type: ignore[union-attr]
        self._size += len(line)
        self._records += 1
        if self._size >= self.max_bytes:
            self._rotate()

    def _rotate(self) -> None:
        if self._handle is None:
            return
        self._handle.close()  # type: ignore[union-attr]
        self._handle = None
        if self._records == 0:
            self._path.unlink(missing_ok=True)  # type: ignore[union-attr]
            return
        assert self._path is not None
        digest, size = sha256_file(self._path)
        index = len(self.shards)
        rel = f"batches/{self.batch_id}/shard-{index:04d}.jsonl"
        self.store.write(rel, _chunks(self._path))
        self.shards.append({"rel": rel, "bytes": size, "records": self._records, "sha256": digest})
        self._path.unlink(missing_ok=True)

    def close(self) -> list[dict]:
        self._rotate()
        self._tmpdir_ctx.cleanup()
        return self.shards


# ------------------------------------------------------------------- helpers


def _write_hashes(store: RootedStore, batch_id: str, hashes: list[str]) -> dict:
    rel = f"batches/{batch_id}/hashes.txt"
    payload = ("\n".join(hashes) + "\n").encode("utf-8") if hashes else b""
    store.write(rel, [payload])
    return {
        "rel": rel,
        "lines": len(hashes),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _prior_hashes(store: RootedStore, registry: dict, exclude: str | None = None) -> list[str]:
    """Download the hash lists of every completed earlier batch."""
    collected: list[str] = []
    for batch in registry["batches"]:
        if batch["id"] == exclude or batch.get("status") != "complete":
            continue
        with store.open(batch["hashes"]["rel"]) as handle:
            for line in handle:
                value = line.strip().decode()
                if value:
                    collected.append(value)
    return collected


# --------------------------------------------------------------------- adopt


def adopt(
    store: RootedStore,
    snapshot_id: str,
    batch_id: str | None = None,
    shard_bytes: int = DEFAULT_SHARD_BYTES,
) -> dict:
    """Turn an already-built corpus into batch-001 without re-reading raw data."""
    manifest_rel = store.manifests(f"{snapshot_id}.json")
    if not store.exists(manifest_rel):
        raise FileNotFoundError(f"no manifest for snapshot {snapshot_id}")
    manifest = json.loads(store.read_text(manifest_rel))
    source_rel = manifest.get("output")
    if not source_rel:
        raise ValueError(f"snapshot {snapshot_id} has no output file")

    registry = load_registry(store)
    if any(b.get("source_snapshot") == snapshot_id for b in registry["batches"]):
        raise FileExistsError(f"snapshot {snapshot_id} was already adopted")
    batch_id = batch_id or next_batch_id(registry)
    _require_absent(store, registry, batch_id)

    writer = ShardWriter(store, batch_id, shard_bytes)
    hashes: list[str] = []
    seen: set[str] = set()
    by_source: Counter = Counter()
    records = chars = duplicates = invalid = 0

    for raw in store.iter_lines(source_rel):
        if not raw.strip():
            continue
        record = json.loads(raw)
        text = record.get("text")
        meta = record.get("meta") or {}
        digest = meta.get("normalized_sha256")
        if not isinstance(text, str) or not text or not isinstance(digest, str):
            invalid += 1
            continue
        if meta.get("license_decision") != "ALLOW":
            invalid += 1
            continue
        if digest in seen:
            duplicates += 1
            continue
        seen.add(digest)
        hashes.append(digest)
        by_source[meta.get("source", "unknown")] += 1
        records += 1
        chars += len(text)
        writer.write(raw + b"\n")

    shards = writer.close()
    hashes_meta = _write_hashes(store, batch_id, hashes)

    entry = {
        "id": batch_id,
        "kind": "adopted",
        "status": "complete",
        "created_at": utc_now(),
        "source_snapshot": snapshot_id,
        "records": records,
        "chars": chars,
        "duplicates_within": duplicates,
        "invalid": invalid,
        "by_source": dict(by_source.most_common()),
        "shards": shards,
        "hashes": hashes_meta,
    }
    stats = {**entry, "inputs": manifest.get("sources", []), "generator": "scripts.corpus.batch"}
    store.write_text(f"batches/{batch_id}/stats.json", json.dumps(stats, indent=2) + "\n")

    registry["batches"].append(entry)
    save_registry(store, registry)
    return entry


# --------------------------------------------------------------------- clean


def clean(
    store: RootedStore,
    *,
    files: list[str] | None = None,
    stages: tuple[int, ...] = (1, 2, 3),
    only: str | None = None,
    batch_id: str | None = None,
    shard_bytes: int = DEFAULT_SHARD_BYTES,
    policy=DEFAULT_POLICY,
) -> dict:
    """Clean newly acquired files into a new batch, deduped against all earlier ones."""
    registry = load_registry(store)
    batch_id = batch_id or next_batch_id(registry)
    _require_absent(store, registry, batch_id)
    files = files or select_files(store, stages=stages, only=only)
    if not files:
        raise ValueError("no input files selected")
    _refuse_repeated_inputs(registry, files)

    writer = ShardWriter(store, batch_id, shard_bytes)
    with tempfile.TemporaryDirectory(prefix="pythia-batch-") as tmp:
        with DedupIndex(Path(tmp) / "dedup.sqlite") as index:
            seeded = index.seed(_prior_hashes(store, registry), label="prior-batch")
            run = CurationRun(
                store=store,
                files=files,
                index=index,
                snapshot_id=batch_id,
                policy=policy,
            )
            for line in run.lines():
                writer.write(line)
            totals = run.finalise_totals()

    shards = writer.close()
    hashes_meta = _write_hashes(store, batch_id, run.new_hashes)

    entry = {
        "id": batch_id,
        "kind": "cleaned",
        "status": "complete",
        "created_at": utc_now(),
        "records": totals.get("kept", 0),
        "chars": totals.get("chars_kept", 0),
        "inputs": run.source_rows(),
        "kept_by_source": dict(Counter(r["source"] for r in run.source_rows()).most_common()),
        "dropped": {
            "duplicates": totals.get("duplicates", 0),
            "license_hold": totals.get("license_hold", 0),
            "license_deny": totals.get("license_deny", 0),
            "text_missing": totals.get("text_missing", 0),
            "parse_errors": totals.get("parse_errors", 0),
        },
        "dedup_seeded_from_prior_batches": seeded,
        "shards": shards,
        "hashes": hashes_meta,
        "policy": policy.describe(),
    }
    store.write_text(f"batches/{batch_id}/stats.json", json.dumps(entry, indent=2) + "\n")
    registry["batches"].append(entry)
    save_registry(store, registry)
    return entry


# -------------------------------------------------------------------- verify


def verify(store: RootedStore, batch_id: str, *, quick: bool = False) -> dict:
    registry = load_registry(store)
    entry = next((b for b in registry["batches"] if b["id"] == batch_id), None)
    if entry is None:
        raise KeyError(f"unknown batch {batch_id}")

    problems: list[str] = []
    checked_records = 0
    for shard in entry["shards"]:
        stat = store.stat(shard["rel"])
        if stat is None:
            problems.append(f"missing shard {shard['rel']}")
            continue
        if stat.size != shard["bytes"]:
            problems.append(f"size mismatch {shard['rel']}: {stat.size} != {shard['bytes']}")
            continue
        if quick:
            continue
        digest = hashlib.sha256()
        lines = 0
        with store.open(shard["rel"]) as handle:
            for line in handle:
                digest.update(line)
                if line.strip():
                    lines += 1
        if digest.hexdigest() != shard["sha256"]:
            problems.append(f"sha256 mismatch {shard['rel']}")
        if lines != shard["records"]:
            problems.append(f"record count {shard['rel']}: {lines} != {shard['records']}")
        checked_records += lines

    return {
        "batch": batch_id,
        "shards": len(entry["shards"]),
        "records_checked": checked_records,
        "ok": not problems,
        "problems": problems,
    }


# ----------------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Immutable corpus batches.")
    parser.add_argument("--store", default=None)
    parser.add_argument("--root", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="show the registry")

    adopt_cmd = sub.add_parser("adopt", help="turn an existing snapshot into a batch")
    adopt_cmd.add_argument("--snapshot", required=True)
    adopt_cmd.add_argument("--id", default=None)
    adopt_cmd.add_argument("--shard-bytes", type=int, default=DEFAULT_SHARD_BYTES)

    clean_cmd = sub.add_parser("clean", help="clean newly acquired files into a new batch")
    clean_cmd.add_argument("--stages", default="1,2,3")
    clean_cmd.add_argument("--only", default=None)
    clean_cmd.add_argument("--id", default=None)
    clean_cmd.add_argument("--shard-bytes", type=int, default=DEFAULT_SHARD_BYTES)

    verify_cmd = sub.add_parser("verify", help="check shard hashes and counts")
    verify_cmd.add_argument("--id", required=True)
    verify_cmd.add_argument("--quick", action="store_true")

    args = parser.parse_args(argv)
    store = open_store(args.store, args.root)

    if args.command == "status":
        registry = load_registry(store)
        print(json.dumps(registry.get("totals", {"batches": 0}), indent=2))
        for batch in registry["batches"]:
            print(
                f"  {batch['id']}  {batch['kind']:8} {batch['records']:>9,} records "
                f"{batch['chars']:>13,} chars  {len(batch['shards'])} shard(s)"
            )
        return 0
    if args.command == "adopt":
        entry = adopt(store, args.snapshot, args.id, args.shard_bytes)
        print(json.dumps(entry, indent=2))
        return 0
    if args.command == "clean":
        stages = tuple(int(p) for p in args.stages.split(",") if p.strip())
        entry = clean(store, stages=stages, only=args.only, batch_id=args.id, shard_bytes=args.shard_bytes)
        print(json.dumps(entry, indent=2))
        return 0
    if args.command == "verify":
        result = verify(store, args.id, quick=args.quick)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
