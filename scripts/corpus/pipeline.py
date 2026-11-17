"""Shared curation core used by both the one-shot build and batch cleaning.

Extracted so the rules live in exactly one place: normalisation, license
gating, deduplication, record identity. `build` and `batch` differ only in
where the input list comes from and where the output goes.

Two input shapes are supported:

* `lines()` streams JSONL files from the store and parses them line by line;
* `consume(rel, records)` accepts already-parsed dicts (used for parquet).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from scripts.corpus.license import DEFAULT_POLICY, Decision, Policy, classify
from scripts.corpus.quality import reject_reason
from scripts.corpus.schema import CanonicalRecord, normalize_text, normalized_hash, spec_for
from scripts.storage import RootedStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS hashes (
    h TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    rel TEXT NOT NULL,
    line INTEGER NOT NULL
)
"""


class DedupIndex:
    """SQLite-backed set of normalised hashes with first-seen provenance."""

    def __init__(self, path: str | Path) -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.execute(SCHEMA)
        self._conn.commit()

    def origin(self, digest: str) -> tuple[str, str, int] | None:
        return self._conn.execute(
            "SELECT source, rel, line FROM hashes WHERE h = ?", (digest,)
        ).fetchone()

    def add(self, digest: str, source: str, rel: str, line: int) -> bool:
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO hashes (h, source, rel, line) VALUES (?, ?, ?, ?)",
            (digest, source, rel, line),
        )
        return cursor.rowcount > 0

    def seed(self, hashes: Iterable[str], label: str, rel: str = "") -> int:
        """Load hashes from an earlier batch so new data dedupes against it."""
        rows = ((h.strip(), label, rel, 0) for h in hashes if h.strip())
        before = self._conn.total_changes
        self._conn.executemany(
            "INSERT OR IGNORE INTO hashes (h, source, rel, line) VALUES (?,?,?,?)", rows
        )
        self._conn.commit()
        return self._conn.total_changes - before

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __len__(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM hashes").fetchone()[0])

    def __enter__(self) -> "DedupIndex":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


@dataclass(slots=True)
class CurationRun:
    """A streaming curation pass.

    Consume :meth:`lines` (store files) or :meth:`consume` (parsed records);
    statistics are filled in as it runs.
    """

    store: RootedStore
    files: list[str]
    index: DedupIndex
    snapshot_id: str
    policy: Policy = DEFAULT_POLICY
    sample: int | None = None
    limit: int | None = None
    per_file: dict[str, dict] = field(default_factory=dict)
    totals: Counter = field(default_factory=Counter)
    licenses: Counter = field(default_factory=Counter)
    holders: Counter = field(default_factory=Counter)
    dupe_examples: list[dict] = field(default_factory=list)
    cross_source: int = 0
    _new_hashes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for rel in self.files:
            self._ensure_file(rel)

    def _ensure_file(self, rel: str) -> dict:
        if rel not in self.per_file:
            self.per_file[rel] = {
                "rel": rel,
                "source": spec_for(rel).name,
                "records": 0,
                "kept": 0,
                "duplicates": 0,
                "license_hold": 0,
                "license_deny": 0,
                "quality_drop": 0,
                "text_missing": 0,
                "parse_errors": 0,
                "chars_kept": 0,
                "sha256": "",
                "bytes": 0,
            }
        return self.per_file[rel]

    @property
    def new_hashes(self) -> list[str]:
        return self._new_hashes

    def _consume_record(
        self, rel: str, line_number: int, record: dict
    ) -> bytes | None:
        """Apply every rule to one record. Returns the canonical line, or None."""
        spec = spec_for(rel)
        row = self._ensure_file(rel)
        row["records"] += 1

        text = spec.text(record)
        if not text:
            row["text_missing"] += 1
            self.totals["text_missing"] += 1
            return None

        verdict = classify(spec.license_value(record), spec.license_status(record))
        self.licenses[verdict.spdx] += 1
        if not self.policy.admits(verdict):
            if verdict.decision is Decision.DENY:
                row["license_deny"] += 1
                self.totals["license_deny"] += 1
            else:
                row["license_hold"] += 1
                self.totals["license_hold"] += 1
                self.holders[f"{verdict.spdx}: {verdict.reason}"] += 1
            return None

        extra = {key: spec.field(record, field_name) for key, field_name in spec.extra}
        reason = reject_reason(text, spec.family, extra.get("repo_path") or "")
        if reason is not None:
            row["quality_drop"] += 1
            self.totals[f"quality_{reason}"] += 1
            return None

        normalised = normalize_text(text)
        digest = normalized_hash(normalised)
        origin = self.index.origin(digest)
        if origin is not None:
            row["duplicates"] += 1
            self.totals["duplicates"] += 1
            if origin[1] != rel:
                self.cross_source += 1
                self.totals["cross_source_duplicates"] += 1
            if len(self.dupe_examples) < 10:
                self.dupe_examples.append(
                    {"rel": rel, "line": line_number, "duplicate_of": origin[1] or origin[0]}
                )
            return None

        self.index.add(digest, spec.name, rel, line_number)
        self._new_hashes.append(digest)
        record_id = spec.record_id(record) or f"sha256:{digest[:16]}"
        canonical = CanonicalRecord(
            text=normalised,
            source=spec.name,
            family=spec.family,
            license_spdx=verdict.spdx,
            license_decision=verdict.decision.value,
            record_id=record_id,
            normalized_sha256=digest,
            char_count=len(normalised),
            source_url=spec.url(record),
            source_revision=spec.revision(record),
            snapshot_id=self.snapshot_id,
            extra={k: v for k, v in extra.items() if v},
        )
        row["kept"] += 1
        row["chars_kept"] += len(normalised)
        self.totals["kept"] += 1
        self.totals["chars_kept"] += len(normalised)
        self.totals["tokens_kept_est"] += len(normalised.split())
        if verdict.attribution_required:
            self.totals["attribution_required"] += 1
        if self.totals["kept"] % 5000 == 0:
            self.index.commit()
        return (
            json.dumps(canonical.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")

    def _at_limit(self, rel: str) -> bool:
        if self.sample is not None and self.per_file[rel]["records"] >= self.sample:
            return True
        return self.limit is not None and self.totals["kept"] >= self.limit

    def lines(self) -> Iterator[bytes]:
        """Stream JSONL files from the store."""
        for rel in self.files:
            row = self._ensure_file(rel)
            hasher = hashlib.sha256()
            with self.store.open(rel) as handle:
                for line_number, raw in enumerate(handle, start=1):
                    hasher.update(raw)
                    row["bytes"] += len(raw)
                    if not raw.strip():
                        continue
                    try:
                        record = json.loads(raw)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        row["parse_errors"] += 1
                        self.totals["parse_errors"] += 1
                        continue
                    if not isinstance(record, dict):
                        row["parse_errors"] += 1
                        self.totals["parse_errors"] += 1
                        continue
                    if self._at_limit(rel):
                        break
                    emitted = self._consume_record(rel, line_number, record)
                    if emitted is not None:
                        yield emitted
                if self.limit is not None and self.totals["kept"] >= self.limit:
                    row["sha256"] = hasher.hexdigest()
                    self.index.commit()
                    return
            row["sha256"] = hasher.hexdigest()
            self.index.commit()

    def consume(self, rel: str, records: Iterable[dict]) -> Iterator[bytes]:
        """Stream already-parsed records (e.g. rows of a parquet shard)."""
        row = self._ensure_file(rel)
        for line_number, record in enumerate(records, start=1):
            if self._at_limit(rel):
                break
            if not isinstance(record, dict):
                row["parse_errors"] += 1
                self.totals["parse_errors"] += 1
                continue
            emitted = self._consume_record(rel, line_number, record)
            if emitted is not None:
                yield emitted
        self.index.commit()

    def source_rows(self) -> list[dict]:
        return [self.per_file[rel] for rel in self.files] if self.files else list(self.per_file.values())

    def finalise_totals(self) -> dict:
        self.totals["files"] = len(self.per_file)
        self.totals["records"] = sum(row["records"] for row in self.per_file.values())
        self.totals["bytes_in"] = sum(row["bytes"] for row in self.per_file.values())
        return dict(self.totals)
