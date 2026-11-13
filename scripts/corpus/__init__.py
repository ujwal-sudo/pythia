"""Corpus curation: schema adapters, license policy, inspection, build.

Modules are imported lazily by callers (`python -m scripts.corpus.doctor`) so
that running one command does not drag in every other one.
"""

__all__ = [
    "build",
    "canonical",
    "doctor",
    "license",
    "quarantine",
    "records",
    "schema",
    "sync",
]
