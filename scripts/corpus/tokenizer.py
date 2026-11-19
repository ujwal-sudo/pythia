"""Tokenizer training, evaluation and (later) corpus tokenisation.

The corpus has 13.17 B characters, and every "token" number so far has been an
estimate. This module replaces the estimate with a measurement.

Three steps:

    python -m scripts.corpus.tokenizer sample --target-mb 600
    python -m scripts.corpus.tokenizer train --vocab 32000
    python -m scripts.corpus.tokenizer evaluate

The sample is stratified by source (file-level code, function-level code,
prose) so the merges are not dominated by one slice. Training on the full
13 GB is not worth it: BPE merge statistics stabilise well before that, and
this machine has 6.5 GB free.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import sys
import time
from pathlib import Path

WORK = Path(__file__).resolve().parents[2] / ".tokenizer"

# Byte-level BPE never needs <unk>; ids are fixed so they survive re-training.
NAMED_SPECIALS = [
    "<|pad|>",          # 0
    "<|bos|>",          # 1
    "<|endoftext|>",    # 2  (EOS / document separator)
    "<|fim_prefix|>",   # 3
    "<|fim_middle|>",   # 4
    "<|fim_suffix|>",   # 5
]
# 6 named + 122 reserved = 128 slots at the front of the vocab. Reserved ids
# are unused in v1 and let later ablations (INDENT/DEDENT, markers) land
# without resizing the embedding matrix. Total vocab stays 32,000 (= 250 * 128).
N_SPECIAL_SLOTS = 128
SPECIAL_TOKENS = NAMED_SPECIALS + [
    f"<|reserved_{i:03d}|>" for i in range(N_SPECIAL_SLOTS - len(NAMED_SPECIALS))
]

# v2 pre-tokenizer: GPT-2's regex with two changes, chosen by the 2026-11-18 audit
# (data/tokenizer-candidates/) and an LM pilot (runs/tok, equal bits/byte to v1):
#   * digits one at a time, keeping their leading space (" 2", "0", "2", "4"),
#     so every number splits the same way;
#   * underscores join the letters after them (" _init", "_user"); bare runs
#     ("_", "__") get their own rule instead of gluing onto punctuation.
PRETOKENIZER_REGEX = (
    r"""'s|'t|'re|'ve|'m|'ll|'d| ?_*\p{L}+| ?\p{N}| ?_+| ?[^\s\p{L}\p{N}_]+|\s+(?!\S)|\s+"""
)


def pre_tokenizer():
    from tokenizers import Regex
    from tokenizers.pre_tokenizers import ByteLevel, Sequence, Split

    # use_regex=False: the Split above replaces ByteLevel's built-in GPT-2 regex.
    return Sequence([Split(Regex(PRETOKENIZER_REGEX), behavior="isolated"),
                     ByteLevel(add_prefix_space=False, use_regex=False)])


def _doc_chunks(path: Path, size: int = 1 << 20):
    """Yield ~1 MB pieces cut at document boundaries ("\n\n", as `sample` writes them).

    tokenizer.train(files) feeds the trainer one *line* at a time, so a newline
    never sits next to the indentation after it and v1 learned 0 newline merges.
    """
    buf = ""
    with path.open(encoding="utf-8") as handle:
        while block := handle.read(size):
            buf += block
            cut = buf.rfind("\n\n")
            if cut > 0:  # shortcut: a single document > 1 MB is held whole in memory; fine for sampled text
                yield buf[:cut]
                buf = buf[cut + 2:]
    if buf:
        yield buf


# Share of the sample by source family. Prose gets more than its corpus share
# on purpose: it is under-represented, and the tokenizer must handle it well.
SAMPLE_QUOTAS = {
    "the_stack_dedup": 0.65,
    "codesearchnet": 0.22,
    "prose": 0.13,
}

PROSE_SOURCES = {"peps", "devguide", "python_docs", "scientific_docs"}


def _family(source: str) -> str:
    if source in PROSE_SOURCES:
        return "prose"
    if source == "the_stack_dedup":
        return "the_stack_dedup"
    if source == "codesearchnet":
        return "codesearchnet"
    return "other"


def sample(
    store,
    *,
    total_mb: int = 600,
    stack_mb: int = 500,
    mixed_mb: int = 100,
    out: Path | None = None,
) -> dict:
    """Take contiguous chunks from several shards, not a stride over 13 GB.

    Reading the whole corpus to stride-sample would cost 13 GB of transfer for
    600 MB of text. Four Stack shards from different batches plus the head of
    batch-001 covers file-level code, function-level code and prose for ~400 MB
    of download.
    """
    from scripts.corpus.batch import load_registry

    out = out or WORK / "sample.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    registry = load_registry(store)
    hf_batches = [b for b in registry["batches"] if b["kind"] == "hf_cleaned"]
    mixed = [b for b in registry["batches"] if b["kind"] == "adopted"]

    written = collections.Counter()
    started = time.time()
    per_stack_shard = stack_mb * 1024 * 1024 // max(1, len(hf_batches[:4]))

    def collect(shard_rel: str, budget: int, keep=None):
        got = 0
        with store.open(shard_rel) as stream:
            for raw in stream:
                if got >= budget:
                    break
                if not raw.strip():
                    continue
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                text = record.get("text") or ""
                if not text:
                    continue
                family = _family((record.get("meta") or {}).get("source", ""))
                if keep and family not in keep:
                    continue
                handle.write(text)
                handle.write("\n\n")
                got += len(text)
                written[family] += len(text)
        return got

    with out.open("w", encoding="utf-8") as handle:
        for batch in hf_batches[:4]:
            collect(batch["shards"][0]["rel"], per_stack_shard)
            print(f"{sum(written.values()) / 1e6:.0f} MB ({time.time() - started:.0f}s)", flush=True)
        for batch in mixed:
            collect(batch["shards"][0]["rel"], mixed_mb * 1024 * 1024, keep={"prose", "codesearchnet", "other"})
            break

    stats = {
        "file": str(out),
        "bytes": out.stat().st_size,
        "chars_by_family": dict(written),
        "seconds": round(time.time() - started, 1),
    }
    (WORK / "sample_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    return stats


def train(
    *,
    vocab_size: int = 32000,
    sample_path: Path | None = None,
    extra_files: tuple[Path, ...] = (),
    extra_repeat: int = 1,
    out_dir: Path | None = None,
) -> dict:
    from tokenizers import Tokenizer
    from tokenizers.models import BPE
    from tokenizers.pre_tokenizers import ByteLevel
    from tokenizers.decoders import ByteLevel as ByteLevelDecoder
    from tokenizers.trainers import BpeTrainer

    sample_path = sample_path or WORK / "sample.txt"
    if not sample_path.is_file():
        raise FileNotFoundError(f"no sample at {sample_path}; run `sample` first")
    out_dir = out_dir or WORK / f"pythia-bpe-{vocab_size // 1000}k"
    out_dir.mkdir(parents=True, exist_ok=True)

    tokenizer = Tokenizer(BPE(unk_token=None))
    tokenizer.pre_tokenizer = pre_tokenizer()
    tokenizer.decoder = ByteLevelDecoder()
    trainer = BpeTrainer(
        vocab_size=vocab_size,
        special_tokens=SPECIAL_TOKENS,
        # Without this the trainer only learns bytes it happened to see, so
        # rare characters could not be encoded (the first tokenizer lacked 28).
        initial_alphabet=ByteLevel.alphabet(),
        min_frequency=2,
        show_progress=True,
    )

    files = [str(sample_path)]
    for extra in extra_files:
        if extra.is_file():
            files.extend([str(extra)] * max(1, extra_repeat))

    started = time.time()
    tokenizer.train_from_iterator((c for f in files for c in _doc_chunks(Path(f))), trainer)
    elapsed = time.time() - started
    tokenizer.save(str(out_dir / "tokenizer.json"))

    info = {
        "vocab_size": tokenizer.get_vocab_size(),
        "sample_bytes": sample_path.stat().st_size,
        "seconds": round(elapsed, 1),
        "specials": SPECIAL_TOKENS,
        "algorithm": "byte-level BPE, no normaliser, PRETOKENIZER_REGEX split, trained on document chunks",
        "pretokenizer_regex": PRETOKENIZER_REGEX,
        "files": files,
        "path": str(out_dir / "tokenizer.json"),
        "sha256": _sha256(out_dir / "tokenizer.json"),
        "tokenizers_version": __import__("tokenizers").__version__,
    }
    (out_dir / "train_report.json").write_text(json.dumps(info, indent=2) + "\n")
    return info


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def holdout(store, *, mb_per_shard: int = 4, out: Path | None = None) -> dict:
    """Write a JSONL held-out set from the LAST shard of every batch.

    `sample` only reads shard 0 of each batch, so these shards are disjoint
    from the tokenizer training text (asserted below).
    """
    from scripts.corpus.batch import load_registry

    out = out or WORK / "holdout.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    batches = load_registry(store)["batches"]
    used = {b["shards"][0]["rel"] for b in batches}
    budget = mb_per_shard * 1024 * 1024
    counts: dict[str, dict] = {}
    with out.open("w", encoding="utf-8") as handle:
        for batch in batches:
            rel = batch["shards"][-1]["rel"]
            assert rel not in used, f"{rel} overlaps the training sample"
            got = records = 0
            with store.open(rel) as stream:
                for raw in stream:
                    if got >= budget:
                        break
                    try:
                        record = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    text = record.get("text") or ""
                    if not text:
                        continue
                    source = (record.get("meta") or {}).get("source", "unknown")
                    handle.write(json.dumps({"text": text, "source": source, "shard": rel}, ensure_ascii=False) + "\n")
                    got += len(text.encode("utf-8"))
                    records += 1
            counts[rel] = {"records": records, "bytes": got}
    stats = {"file": str(out), "bytes": out.stat().st_size, "shards": counts, "sha256": _sha256(out)}
    (WORK / "holdout_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    return stats


def evaluate(
    *,
    tokenizer_path: Path | None = None,
    store=None,
    shards: int = 2,
    file: Path | None = None,
) -> dict:
    """Measure chars/token on held-out records and extrapolate corpus tokens."""
    from tokenizers import Tokenizer

    tokenizer_path = tokenizer_path or WORK / "pythia-bpe-32k" / "tokenizer.json"
    tokenizer = Tokenizer.from_file(str(tokenizer_path))

    chars = tokens = records = 0
    per_source = collections.defaultdict(lambda: [0, 0])  # chars, tokens
    if file is not None and file.suffix == ".jsonl":
        stream = (
            {"text": r["text"], "meta": {"source": r.get("source", "holdout")}}
            for r in map(json.loads, file.open(encoding="utf-8"))
        )
    elif file is not None:
        stream = ({"text": part, "meta": {"source": "holdout"}} for part in _split_docs(file))
    else:
        stream = _iter_held_out(store, shards)
    roundtrip_failures: list[str] = []
    special_string_records = 0
    for record in stream:
        text = record.get("text") or ""
        if not text:
            continue
        encoded = tokenizer.encode(text)
        # skip_special_tokens=False so literal "<|endoftext|>" in text survives.
        if tokenizer.decode(encoded.ids, skip_special_tokens=False) != text:
            roundtrip_failures.append(text[:80])
        if any(t in text for t in SPECIAL_TOKENS[:N_SPECIAL_SLOTS]):
            special_string_records += 1
        chars += len(text)
        tokens += len(encoded.ids)
        records += 1
        source = (record.get("meta") or {}).get("source", "unknown")
        per_source[source][0] += len(text)
        per_source[source][1] += len(encoded.ids)

    ratio = chars / tokens if tokens else 0.0
    report = {
        "sha256": _sha256(tokenizer_path),
        "vocab_size": tokenizer.get_vocab_size(),
        "records": records,
        "roundtrip_failures": len(roundtrip_failures),
        "roundtrip_failure_examples": roundtrip_failures[:3],
        "records_containing_special_strings": special_string_records,
        "chars": chars,
        "tokens": tokens,
        "chars_per_token": round(ratio, 3),
        "tokens_per_char": round(tokens / chars, 4) if chars else None,
        "by_source": {
            source: {"chars": c, "tokens": t, "chars_per_token": round(c / t, 3) if t else None}
            for source, (c, t) in per_source.items()
        },
    }
    return report


def _split_docs(path: Path, chunk_chars: int = 4000):
    """Chunk a plain-text holdout file into pseudo-documents."""
    buffer: list[str] = []
    size = 0
    with path.open(encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            buffer.append(line)
            size += len(line)
            if size >= chunk_chars:
                yield "".join(buffer)
                buffer, size = [], 0
    if buffer:
        yield "".join(buffer)


def _iter_held_out(store, shards: int):
    """Stream the last shards of the newest batches (not in any sample)."""
    from scripts.corpus.batch import load_registry

    registry = load_registry(store)
    candidates = [s for b in registry["batches"][-2:] for s in b["shards"]]
    for shard in candidates[-shards:]:
        with store.open(shard["rel"]) as stream:
            for raw in stream:
                if raw.strip():
                    try:
                        yield json.loads(raw)
                    except json.JSONDecodeError:
                        continue


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train and evaluate the Pythia tokenizer.")
    parser.add_argument("--store", default=None)
    parser.add_argument("--root", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    sample_cmd = sub.add_parser("sample")
    sample_cmd.add_argument("--total-mb", type=int, default=600)
    sample_cmd.add_argument("--stack-mb", type=int, default=500)
    sample_cmd.add_argument("--mixed-mb", type=int, default=100)

    hold_cmd = sub.add_parser("holdout")
    hold_cmd.add_argument("--mb-per-shard", type=int, default=4)

    train_cmd = sub.add_parser("train")
    train_cmd.add_argument("--vocab", type=int, default=32000)
    train_cmd.add_argument("--sample", default=None)
    train_cmd.add_argument("--prose", default=None)
    train_cmd.add_argument("--prose-repeat", type=int, default=1)

    eval_cmd = sub.add_parser("evaluate")
    eval_cmd.add_argument("--tokenizer", default=None)
    eval_cmd.add_argument("--shards", type=int, default=2)
    eval_cmd.add_argument("--file", default=None)

    args = parser.parse_args(argv)
    from scripts.storage import open_store

    store = open_store(args.store, args.root)
    if args.command == "sample":
        print(json.dumps(sample(store, total_mb=args.total_mb, stack_mb=args.stack_mb, mixed_mb=args.mixed_mb), indent=2))
    elif args.command == "holdout":
        print(json.dumps(holdout(store, mb_per_shard=args.mb_per_shard), indent=2))
    elif args.command == "train":
        print(json.dumps(train(
            vocab_size=args.vocab,
            sample_path=Path(args.sample) if args.sample else None,
            extra_files=(Path(args.prose),) if args.prose else (),
            extra_repeat=args.prose_repeat,
        ), indent=2))
    else:
        path = Path(args.tokenizer) if args.tokenizer else None
        print(json.dumps(evaluate(
            tokenizer_path=path, store=store, shards=args.shards,
            file=Path(args.file) if args.file else None,
        ), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
