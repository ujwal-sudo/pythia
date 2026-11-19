"""Phase 2: tokenize the archive into uint16 shards (resumable, disk-guarded).

    python -m scripts.corpus.tokenize_corpus run [--limit-shards N] [--batches batch-002 ...]
    python -m scripts.corpus.tokenize_corpus finalize

Per input shard it writes, under ``tokenized/<tokenizer-name>/`` in the store
(name = $PYTHIA_TOKENIZER, default pythia-bpe-32k-v2):
    <batch>-<shard>.train.bin / .val.bin   raw little-endian uint16 token ids
    <batch>-<shard>.json                   counts + hashes (its presence == shard done)
Each document is its token ids followed by one <|endoftext|> (EOS).

Rules baked in:
  * Validation = documents whose *repo* (meta.source_url) hashes into the val
    bucket, so no repo is split across train/val. Fixed by VAL_PERMILLE.
  * Input shard bytes are sha256-checked against the registry before use.
  * Documents containing a literal special-token string are EXCLUDED from the
    output (they would be parsed as real specials) and listed in the shard json.
    Nothing is deleted from the archive.
  * Local scratch is cleaned per shard; aborts if free disk drops below the guard.
"""

from __future__ import annotations

import argparse
import hashlib
import sys as _sys
import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scripts.corpus.quality import QUALITY_VERSION, reject_reason
from scripts.corpus.tokenizer import SPECIAL_TOKENS, WORK

# Frozen tokenizer under tokenizer/<name>/; outputs never mix versions (separate OUT_ROOT).
TOKENIZER_NAME = os.environ.get("PYTHIA_TOKENIZER", "pythia-bpe-32k-v2")
TOK_DIR = Path(__file__).resolve().parents[2] / "tokenizer" / TOKENIZER_NAME
OUT_ROOT = f"tokenized/{TOKENIZER_NAME}"
SCRATCH = WORK / "phase2_tmp"
EOS = "<|endoftext|>"
VAL_PERMILLE = 2          # 0.2% of repos -> validation
MIN_FREE_BYTES = 1_500_000_000
ENCODE_BATCH = 512


def is_val(record: dict) -> bool:
    meta = record.get("meta") or {}
    key = meta.get("source_url") or meta.get("record_id") or ""
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % 1000 < VAL_PERMILLE


def has_special_string(text: str) -> bool:
    return "<|" in text and any(s in text for s in SPECIAL_TOKENS)


def encode_records(tokenizer, records: list[dict]):
    """Return (train_ids, val_ids, excluded_record_ids, doc_counts, quality_drops)."""
    from collections import Counter

    eos = tokenizer.token_to_id(EOS)
    kept, excluded, dropped = [], [], Counter()
    for record in records:
        text = record.get("text") or ""
        if not text:
            continue
        if has_special_string(text):
            excluded.append((record.get("meta") or {}).get("record_id", "?"))
            continue
        meta = record.get("meta") or {}
        reason = reject_reason(text, meta.get("source_family", ""), meta.get("repo_path") or "")
        if reason is not None:
            dropped[reason] += 1
            continue
        kept.append(record)
    from array import array

    train, val = array("H"), array("H")  # uint16; OverflowError if an id ever exceeds 65535
    docs = {"train": 0, "val": 0}
    for i in range(0, len(kept), ENCODE_BATCH):
        chunk = kept[i : i + ENCODE_BATCH]
        encoded = tokenizer.encode_batch([r["text"] for r in chunk], add_special_tokens=False)
        for record, enc in zip(chunk, encoded):
            side, split = (val, "val") if is_val(record) else (train, "train")
            side.extend(enc.ids)
            side.append(eos)
            docs[split] += 1
    return train, val, excluded, docs, dict(dropped)


def _to_bytes(ids) -> bytes:
    from array import array

    try:
        arr = ids if isinstance(ids, array) and ids.typecode == "H" else array("H", ids)
    except OverflowError as exc:
        raise ValueError("token id out of uint16 range") from exc
    if _sys.byteorder == "big":
        arr.byteswap()  # file format is little-endian
    return arr.tobytes()


def _read_shard(store, rel: str) -> tuple[bytes, str]:
    digest = hashlib.sha256()
    parts = []
    with store.open(rel) as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
            parts.append(block)
    return b"".join(parts), digest.hexdigest()


def _parse(raw: bytes) -> list[dict]:
    out = []
    for line in raw.splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _load_tokenizer():
    from tokenizers import Tokenizer

    manifest = json.loads((TOK_DIR / "MANIFEST.json").read_text())
    path = TOK_DIR / "tokenizer.json"
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if sha != manifest["tokenizer_json_sha256"]:
        raise RuntimeError("tokenizer.json does not match its MANIFEST hash")
    return Tokenizer.from_file(str(path)), sha


def _shard_stem(rel: str) -> str:
    parts = rel.split("/")  # batches/batch-002/shard-0000.jsonl
    return f"{parts[1]}-{Path(parts[2]).stem}"


def _upload(store, stem, shard, sha, tok_sha, blobs, counts, excluded, dropped, encode_s) -> int:
    t0 = time.time()
    outputs = {}
    for split, blob in blobs.items():
        rel = f"{OUT_ROOT}/{stem}.{split}.bin"
        store.write(rel, [blob])
        stat = store.stat(rel)
        if stat is None or stat.size != len(blob):
            raise RuntimeError(f"upload size mismatch for {rel}")
        outputs[split] = {"rel": rel, "tokens": counts[split][0], "docs": counts[split][1],
                          "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()}
    info = {
        "input": shard["rel"], "input_sha256": sha, "tokenizer_sha256": tok_sha,
        "outputs": outputs, "excluded_special_string_docs": excluded,
        "quality_filter": QUALITY_VERSION, "quality_dropped_docs": dropped,
        "encode_seconds": encode_s, "upload_seconds": round(time.time() - t0, 1),
    }
    # The json is written last: its existence marks the shard complete.
    store.write(f"{OUT_ROOT}/{stem}.json", [json.dumps(info, indent=2).encode()])
    print(f"    uploaded {stem} in {info['upload_seconds']}s", flush=True)
    return counts["train"][0] + counts["val"][0]


def run(store, *, batches: list[str] | None = None, limit_shards: int | None = None) -> dict:
    from scripts.corpus.batch import load_registry

    tokenizer, tok_sha = _load_tokenizer()
    registry = load_registry(store)
    todo = [
        (b["id"], s)
        for b in registry["batches"]
        if not batches or b["id"] in batches
        for s in b["shards"]
    ]
    todo = [(bid, s) for bid, s in todo if not store.exists(f"{OUT_ROOT}/{_shard_stem(s['rel'])}.json")]
    if limit_shards:
        todo = todo[:limit_shards]
    SCRATCH.mkdir(parents=True, exist_ok=True)
    done_tokens = 0
    started = time.time()
    print(f"{len(todo)} shards to do", flush=True)
    if not todo:
        return {"shards_done": 0}

    uploading = None
    with ThreadPoolExecutor(max_workers=1) as pool, ThreadPoolExecutor(max_workers=1) as uploader:
        pending = pool.submit(_read_shard, store, todo[0][1]["rel"])
        for index, (bid, shard) in enumerate(todo):
            free = shutil.disk_usage(SCRATCH).free
            if free < MIN_FREE_BYTES:
                raise RuntimeError(f"disk guard: only {free / 1e9:.2f} GB free, stopping before {shard['rel']}")
            raw, sha = pending.result()
            if index + 1 < len(todo):
                pending = pool.submit(_read_shard, store, todo[index + 1][1]["rel"])
            if sha != shard["sha256"]:
                raise RuntimeError(f"input hash mismatch for {shard['rel']}: {sha} != {shard['sha256']}")
            t0 = time.time()
            train, val, excluded, docs, dropped = encode_records(tokenizer, _parse(raw))
            del raw
            encode_s = round(time.time() - t0, 1)
            stem = _shard_stem(shard["rel"])
            blobs = {"train": _to_bytes(train), "val": _to_bytes(val)}
            counts = {"train": (len(train), docs["train"]), "val": (len(val), docs["val"])}
            del train, val
            # At most one upload in flight: it overlaps the next download+encode.
            if uploading is not None:
                uploaded = uploading.result()
                done_tokens += uploaded
            uploading = uploader.submit(_upload, store, stem, shard, sha, tok_sha, blobs, counts, excluded, dropped, encode_s)
            print(f"[{index + 1}/{len(todo)}] {stem}: encoded {sum(c[0] for c in counts.values()):,} tok "
                  f"in {encode_s}s, excluded={len(excluded)}, quality_dropped={sum(dropped.values())}, elapsed {time.time() - started:.0f}s", flush=True)
        if uploading is not None:
            done_tokens += uploading.result()
    return {"shards_done": len(todo), "tokens": done_tokens, "seconds": round(time.time() - started, 1)}


def finalize(store) -> dict:
    from scripts.corpus.batch import load_registry

    tok_sha = _load_tokenizer()[1]
    registry = load_registry(store)
    shards, totals = [], {"train_tokens": 0, "val_tokens": 0, "train_docs": 0, "val_docs": 0, "excluded_docs": 0, "quality_dropped_docs": 0}
    missing = []
    for batch in registry["batches"]:
        for shard in batch["shards"]:
            rel = f"{OUT_ROOT}/{_shard_stem(shard['rel'])}.json"
            if not store.exists(rel):
                missing.append(shard["rel"])
                continue
            with store.open(rel) as handle:
                info = json.loads(handle.read())
            if info["tokenizer_sha256"] != tok_sha:
                raise RuntimeError(f"{rel} was made with a different tokenizer")
            if info.get("quality_filter") != QUALITY_VERSION:
                raise RuntimeError(f"{rel} predates quality filter {QUALITY_VERSION}; delete it and re-run")
            shards.append(info)
            totals["train_tokens"] += info["outputs"]["train"]["tokens"]
            totals["val_tokens"] += info["outputs"]["val"]["tokens"]
            totals["train_docs"] += info["outputs"]["train"]["docs"]
            totals["val_docs"] += info["outputs"]["val"]["docs"]
            totals["excluded_docs"] += len(info["excluded_special_string_docs"])
            totals["quality_dropped_docs"] += sum(info["quality_dropped_docs"].values())
    manifest = {
        "tokenizer": TOKENIZER_NAME, "tokenizer_sha256": tok_sha, "dtype": "uint16 little-endian",
        "doc_boundary": "each document followed by <|endoftext|> (id 2); no BOS in data",
        "val_rule": f"sha256(meta.source_url or record_id)[:8] % 1000 < {VAL_PERMILLE} (repo-level)",
        "complete": not missing, "missing_shards": missing, "totals": totals, "shards": shards,
    }
    store.write(f"{OUT_ROOT}/manifest.json", [json.dumps(manifest, indent=2).encode()])
    return {"complete": manifest["complete"], "missing": len(missing), **totals}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--store", default=None)
    parser.add_argument("--root", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("--batches", nargs="*", default=None)
    run_cmd.add_argument("--limit-shards", type=int, default=None)
    sub.add_parser("finalize")
    args = parser.parse_args(argv)
    from scripts.storage import open_store

    store = open_store(args.store, args.root)
    if args.command == "run":
        print(json.dumps(run(store, batches=args.batches, limit_shards=args.limit_shards), indent=2))
    else:
        print(json.dumps(finalize(store), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
