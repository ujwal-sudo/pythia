"""The frozen selection of canonical corpus files.

`filtered/stage1` held four near-identical prose runs plus two license-gated
revisions, and any `glob("stage1/*.jsonl")` would ingest all of them. This
module is the single, auditable answer to "which files are the corpus".

Changing the corpus means editing this file and recording why — not adding a
fifth run to the same directory.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CanonicalFile:
    source: str
    filename: str
    note: str


STAGE1_CANONICAL: tuple[CanonicalFile, ...] = (
    CanonicalFile(
        "peps",
        "prose_docs_prose-license-gated-v2_peps.jsonl",
        "Latest prose run (2026-10-23); supersedes the four 2026-10-22 runs and v1.",
    ),
    CanonicalFile(
        "devguide",
        "prose_docs_prose-license-gated-v2_cpython_devguide.jsonl",
        "Same run as the PEP file; kept separate because acquisition was separate.",
    ),
    CanonicalFile(
        "python_docs",
        "python_docs_filtered_v3.jsonl",
        "v3 is the only revision present; the 317-vs-96 count conflict is documented.",
    ),
    CanonicalFile(
        "scientific_docs",
        "scientific_docs_scidocs-20261022T053610Z-ea912df1_numpy_docs.jsonl",
        "NumPy 2.5, BSD-3-Clause, pinned archive.",
    ),
    CanonicalFile(
        "scientific_docs",
        "scientific_docs_scidocs-20261022T063330Z-29c8f7b5_scipy_docs.jsonl",
        "SciPy 1.18.0, BSD-3-Clause, pinned archive.",
    ),
    CanonicalFile(
        "scientific_docs",
        "scientific_docs_scidocs-20261022T064353Z-91b4855a_pandas_docs.jsonl",
        "pandas 2.3.3, BSD-3-Clause, pinned archive.",
    ),
)


@dataclass(frozen=True, slots=True)
class ExcludedFile:
    source: str
    filename: str
    reason: str


# Deliberately not in the corpus. Kept in the archive for provenance, but the
# license policy denies them, so keeping them in stage1 only invited mistakes.
STAGE1_EXCLUDED: tuple[ExcludedFile, ...] = (
    ExcludedFile("thinkpython", "thinkpython_filtered_v3.jsonl", "CC-BY-NC-SA: non-commercial"),
    ExcludedFile("atbs", "atbs_filtered_v3.jsonl", "CC-BY-NC: non-commercial"),
)


def stage1_filenames() -> list[str]:
    return [entry.filename for entry in STAGE1_CANONICAL]
