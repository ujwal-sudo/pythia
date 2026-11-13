"""Single source of truth for where Pythia data lives.

The project previously had three competing notions of "project root", which
produced a shadow data tree (`scripts/data/raw/`, 914 MB) and a fake cloud
mount. Everything new goes through this package instead:

    from scripts.storage import open_store
    store = open_store()
    for entry in store.list("filtered/stage1"):
        ...

Paths handed to a store are always *relative to the store root* and are
validated: absolute paths, `..`, and backslashes are rejected. The root is
configured once (``PYTHIA_STORE_ROOT``) and never inferred from ``__file__``.
"""

from scripts.storage.base import Backend, Entry, RootedStore, normalize_rel
from scripts.storage.errors import (
    BackendUnavailable,
    InvalidPath,
    NotFound,
    StoreError,
)
from scripts.storage.factory import open_store

__all__ = [
    "Backend",
    "BackendUnavailable",
    "Entry",
    "InvalidPath",
    "NotFound",
    "RootedStore",
    "StoreError",
    "normalize_rel",
    "open_store",
]
