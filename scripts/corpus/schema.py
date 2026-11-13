"""Per-source record adapters.

The archive writes a different key-set for every source (six variants observed
in `filtered/stage1` alone). Rather than force one schema at write time, each
source declares where its text, license, identity and revision live, and the
curation layer normalises on read.

If a source is not in :data:`SOURCES`, :func:`spec_for` returns a conservative
fallback that tries the common field names and reports the source as unknown.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """Where the useful fields live inside this source's records."""

    name: str
    family: str
    stage: int
    text_fields: tuple[str, ...]
    license_fields: tuple[str, ...] = ("license_spdx", "license", "licence")
    id_fields: tuple[str, ...] = ("record_id", "id", "original_record_id")
    url_fields: tuple[str, ...] = ("source_url", "url", "document_url")
    revision_fields: tuple[str, ...] = (
        "source_revision",
        "commit_sha",
        "commit_id",
        "source_version",
        "version",
    )
    notes: str = ""
    required_text: bool = True
    extra: tuple[tuple[str, str], ...] = ()

    def text(self, record: dict) -> str | None:
        return _first_str(record, self.text_fields)

    def license_value(self, record: dict) -> str | None:
        return _first_str(record, self.license_fields)

    def license_status(self, record: dict) -> str | None:
        return _first_str(record, ("license_status", "license_decision_status"))

    def record_id(self, record: dict) -> str | None:
        return _first_str(record, self.id_fields)

    def url(self, record: dict) -> str | None:
        return _first_str(record, self.url_fields)

    def revision(self, record: dict) -> str | None:
        return _first_str(record, self.revision_fields)

    def field(self, record: dict, name: str) -> str | None:
        return _first_str(record, (name,))


def _first_str(record: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item.strip()
    return None


SOURCES: dict[str, SourceSpec] = {
    "codesearchnet": SourceSpec(
        name="codesearchnet",
        family="code",
        stage=2,
        text_fields=("code", "original_string"),
        license_fields=("license", "license_spdx"),
        id_fields=("record_id", "original_record_id"),
        url_fields=("source_url",),
        revision_fields=("commit_sha", "source_version"),
    ),
    "the_stack_dedup": SourceSpec(
        name="the_stack_dedup",
        family="code",
        stage=2,
        text_fields=("content",),
        license_fields=("max_stars_repo_licenses", "max_issues_repo_licenses", "max_forks_repo_licenses"),
        id_fields=("hexsha",),
        url_fields=("max_stars_repo_name",),
        revision_fields=("max_stars_repo_head_hexsha", "hexsha"),
        extra=(("repo_path", "max_stars_repo_path"), ("ext", "ext")),
        notes="The Stack dedup parquet: whole files with per-repo licence list.",
    ),
    "the_stack": SourceSpec(
        name="the_stack",
        family="code",
        stage=2,
        text_fields=("code", "content"),
    ),
    "pypi": SourceSpec(
        name="pypi",
        family="code",
        stage=2,
        text_fields=("content", "code", "source_text"),
        license_fields=("license_spdx", "license", "licence_status"),
    ),
    "peps": SourceSpec(
        name="peps",
        family="prose_docs",
        stage=1,
        text_fields=("content", "prose"),
        license_fields=("license_spdx", "license"),
        id_fields=("id", "record_id", "document_id"),
        url_fields=("document_url", "source_url"),
        revision_fields=("source_revision", "commit_id"),
    ),
    "devguide": SourceSpec(
        name="devguide",
        family="prose_docs",
        stage=1,
        text_fields=("content", "prose"),
        license_fields=("license_spdx", "license"),
        id_fields=("id", "record_id", "document_id"),
        url_fields=("document_url", "source_url"),
        revision_fields=("source_revision", "commit_id"),
    ),
    "prose_docs": SourceSpec(
        name="prose_docs",
        family="prose_docs",
        stage=1,
        text_fields=("content", "prose"),
    ),
    "python_docs": SourceSpec(
        name="python_docs",
        family="official_documentation",
        stage=1,
        text_fields=("code", "content", "text"),
        license_fields=("license_spdx", "license", "license_status"),
        id_fields=("record_id", "id", "document_id"),
    ),
    "scientific_docs": SourceSpec(
        name="scientific_docs",
        family="official_documentation",
        stage=1,
        text_fields=("code", "content", "text"),
        license_fields=("license_spdx", "license", "license_status"),
        id_fields=("record_id", "id", "document_id"),
    ),
    "thinkpython": SourceSpec(
        name="thinkpython",
        family="textbook",
        stage=1,
        text_fields=("code", "content", "text"),
    ),
    "atbs": SourceSpec(
        name="atbs",
        family="textbook",
        stage=1,
        text_fields=("code", "content", "text"),
    ),
    "jupyter": SourceSpec(
        name="jupyter",
        family="notebook",
        stage=3,
        # Observed stage3 records carry 50 metadata keys and no code payload.
        text_fields=("code", "content", "text", "source"),
        license_fields=("license_spdx", "license"),
        id_fields=("record_id",),
        url_fields=("source_url",),
        revision_fields=("source_revision", "commit_sha"),
        notes="stage3 records observed without a text field; doctor flags them.",
    ),
    "stackoverflow": SourceSpec(
        name="stackoverflow",
        family="qa",
        stage=2,
        text_fields=("answer", "question_instruction", "answer_text", "content"),
        license_fields=("license_spdx", "license"),
        id_fields=("record_id", "answer_id", "question_id"),
        url_fields=("source_url",),
    ),
}

# Filename stems that appear in the archive and map onto the specs above.
_ALIASES = {
    "cpython_devguide": "devguide",
    "python_docs": "python_docs",
    "scidocs": "scientific_docs",
    "numpy_docs": "scientific_docs",
    "scipy_docs": "scientific_docs",
    "pandas_docs": "scientific_docs",
    "stackoverflow": "stackoverflow",
    "codesearchnet": "codesearchnet",
    "the_stack": "the_stack",
    "the-stack-dedup": "the_stack_dedup",
    "jupyter": "jupyter",
    "peps": "peps",
    "pypi": "pypi",
    "atbs": "atbs",
    "think_python": "thinkpython",
    "thinkpython": "thinkpython",
    "prose": "prose_docs",
}

_FALLBACK = SourceSpec(
    name="unknown",
    family="unknown",
    stage=0,
    text_fields=("content", "code", "text", "prose", "source"),
)


def spec_for(rel: str) -> SourceSpec:
    """Guess the source spec from a store-relative path."""
    lowered = rel.lower()
    for alias, name in _ALIASES.items():
        if alias in lowered:
            return SOURCES[name]
    return _FALLBACK


def normalize_text(text: str) -> str:
    """Canonical form used for hashing and deduplication.

    Contract (matches the dead `global_dedup` scaffold, now actually used):
    normalise newlines, strip trailing whitespace per line, collapse runs of
    blank lines to one, strip leading/trailing blank lines.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    out: list[str] = []
    previous_blank = False
    for line in lines:
        blank = line == ""
        if blank and previous_blank:
            continue
        out.append(line)
        previous_blank = blank
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def normalized_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class CanonicalRecord:
    """What the curated corpus emits: text plus a thin provenance envelope."""

    text: str
    source: str
    family: str
    license_spdx: str
    license_decision: str
    record_id: str
    normalized_sha256: str
    char_count: int
    source_url: str | None = None
    source_revision: str | None = None
    snapshot_id: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        meta = {
            "record_id": self.record_id,
            "source": self.source,
            "source_family": self.family,
            "license_spdx": self.license_spdx,
            "license_decision": self.license_decision,
            "normalized_sha256": self.normalized_sha256,
            "char_count": self.char_count,
            "snapshot_id": self.snapshot_id,
        }
        if self.source_url:
            meta["source_url"] = self.source_url
        if self.source_revision:
            meta["source_revision"] = self.source_revision
        for key, value in self.extra.items():
            if value:
                meta[key] = value
        return {"text": self.text, "meta": meta}
