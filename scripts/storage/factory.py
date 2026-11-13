"""Construction of the active store from configuration.

Two knobs, both explicit:

    PYTHIA_STORE       "rclone" (default) or "file"
    PYTHIA_STORE_ROOT  "pythia:Pythia" or an absolute local directory

The default is the real archive. Tests pass a ``file`` root explicitly; they
never touch the network.
"""

from __future__ import annotations

import os
from pathlib import Path

from scripts.storage.base import RootedStore
from scripts.storage.errors import BackendUnavailable
from scripts.storage.local import LocalBackend
from scripts.storage.rclone import RcloneBackend

DEFAULT_RCLONE_ROOT = "pythia:Pythia"
DEFAULT_LOCAL_ROOT = str(Path(__file__).resolve().parents[2] / "data")


def open_store(
    kind: str | None = None,
    root: str | None = None,
) -> RootedStore:
    """Return the configured store.

    ``kind="file", root="..."`` is how tests build an isolated store.
    """
    kind = (kind or os.environ.get("PYTHIA_STORE") or "rclone").strip().lower()
    root = root or os.environ.get("PYTHIA_STORE_ROOT")

    if kind in ("file", "local"):
        return RootedStore(LocalBackend(root or DEFAULT_LOCAL_ROOT))
    if kind == "rclone":
        return RootedStore(RcloneBackend(root or DEFAULT_RCLONE_ROOT))
    raise BackendUnavailable(f"unknown store kind {kind!r}; use 'rclone' or 'file'")
