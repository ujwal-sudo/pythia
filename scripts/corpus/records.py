"""Streaming record iteration and per-file inspection.

Nothing here loads a corpus into memory: files are read line by line from the
store, hashed as they stream, and reduced to statistics.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field

from scripts.corpus.license import Decision, Verdict, classify
from scripts.corpus.schema import SourceSpec, normalized_hash, spec_for
from scripts.storage.base import RootedStore

MAX_KEYSET_SAMPLES = 8


@dataclass(slots=True)
class FileStats:
    rel: str
    source: str
    family: str
    byte_count: int = 0
    sha256: str = ""
    hashed_complete: bool = True
    records: int = 0
    parse_errors: int = 0
    text_missing: int = 0
    chars: int = 0
    tokens_est: int = 0
    license_counts: Counter = field(default_factory=Counter)
    decisions: Counter = field(default_factory=Counter)
    key_sets: Counter = field(default_factory=Counter)
    intra_file_dupes: int = 0
    sample: int | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "rel": self.rel,
            "source": self.source,
            "family": self.family,
            "bytes": self.byte_count,
            "sha256": self.sha256,
            "hashed_complete": self.hashed_complete,
            "records": self.records,
            "parse_errors": self.parse_errors,
            "text_missing": self.text_missing,
            "chars": self.chars,
            "tokens_est": self.tokens_est,
            "licenses": dict(self.license_counts.most_common()),
            "decisions": dict(self.decisions.most_common()),
            "distinct_key_sets": len(self.key_sets),
            "key_sets": [
                {"records": count, "fields": list(keys)}
                for keys, count in self.key_sets.most_common(MAX_KEYSET_SAMPLES)
            ],
            "intra_file_dupes": self.intra_file_dupes,
            "sample": self.sample,
            "error": self.error,
        }


def iter_raw_lines(store: RootedStore, rel: str) -> Iterator[bytes]:
    with store.open(rel) as handle:
        for line in handle:
            yield line.rstrip(b"\r\n")


def parse_records(lines: Iterator[bytes]) -> Iterator[tuple[int, dict | None, int]]:
    """Yield ``(line_number, record_or_None, byte_length)``."""
    for number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            yield number, None, len(raw)
            continue
        if not isinstance(value, dict):
            yield number, None, len(raw)
            continue
        yield number, value, len(raw)


def inspect_file(
    store: RootedStore,
    rel: str,
    *,
    spec: SourceSpec | None = None,
    sample: int | None = None,
    hash_bytes: bool = True,
) -> FileStats:
    """Read one JSONL file and return its statistics.

    ``sample`` limits how many records are examined; when set, the reported
    sha256 covers only the bytes read and ``hashed_complete`` is False.
    """
    spec = spec or spec_for(rel)
    stats = FileStats(rel=rel, source=spec.name, family=spec.family, sample=sample)
    hasher = hashlib.sha256()
    seen_hashes: set[str] = set()

    try:
        with store.open(rel) as handle:
            for line_number, raw in enumerate(handle, start=1):
                if hash_bytes:
                    hasher.update(raw)
                stats.byte_count += len(raw)
                if not raw.strip():
                    continue
                try:
                    value = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    stats.parse_errors += 1
                    continue
                if not isinstance(value, dict):
                    stats.parse_errors += 1
                    continue
                if sample is not None and stats.records >= sample:
                    stats.hashed_complete = False
                    break
                stats.records += 1
                stats.key_sets[tuple(sorted(value.keys()))] += 1

                text = spec.text(value)
                if not text:
                    stats.text_missing += 1
                else:
                    stats.chars += len(text)
                    stats.tokens_est += len(text.split())
                    digest = normalized_hash(text)
                    if digest in seen_hashes:
                        stats.intra_file_dupes += 1
                    else:
                        seen_hashes.add(digest)

                verdict = classify(spec.license_value(value), spec.license_status(value))
                stats.license_counts[verdict.spdx] += 1
                stats.decisions[verdict.decision.value] += 1
    except Exception as error:  # store/network/parsing failure for the whole file
        stats.error = f"{type(error).__name__}: {error}"

    stats.sha256 = hasher.hexdigest()
    if sample is None:
        stats.hashed_complete = True
    return stats


def summarize(stats: list[FileStats]) -> dict:
    totals = {
        "files": len(stats),
        "bytes": sum(s.byte_count for s in stats),
        "records": sum(s.records for s in stats),
        "parse_errors": sum(s.parse_errors for s in stats),
        "text_missing": sum(s.text_missing for s in stats),
        "chars": sum(s.chars for s in stats),
        "tokens_est": sum(s.tokens_est for s in stats),
        "intra_file_dupes": sum(s.intra_file_dupes for s in stats),
        "decisions": dict(sum((s.decisions for s in stats), Counter())),
        "licenses": dict(sum((s.license_counts for s in stats), Counter()).most_common()),
    }
    return totals
