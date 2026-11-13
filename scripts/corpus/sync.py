"""Publish canonical local files to the archive.

The archive is authoritative (remote-only mode), but a few sources exist only
on this machine — `filtered/stage1` was never uploaded. `sync` compares the
frozen canonical list against the store and uploads what is missing, writing a
manifest with sha256 so a later reader can tell "uploaded once" from "uploaded
twice, differently".

    python -m scripts.corpus.sync --plan     # show what would change
    python -m scripts.corpus.sync --apply
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

from scripts.corpus.canonical import STAGE1_CANONICAL, CanonicalFile
from scripts.storage import RootedStore, open_store


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def _chunks(path: Path, chunk_size: int = 1 << 20):
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                return
            yield chunk


def plan(
    local_store: RootedStore,
    remote_store: RootedStore,
    files: tuple[CanonicalFile, ...] = STAGE1_CANONICAL,
) -> list[dict]:
    local_root = Path(local_store.backend.root)
    actions: list[dict] = []
    for entry in files:
        local_path = local_root / "filtered" / "stage1" / entry.filename
        rel = f"filtered/stage1/{entry.filename}"
        row = {"source": entry.source, "rel": rel, "local": str(local_path)}
        if not local_path.is_file():
            row.update(action="missing-local", remote_size=None, note=entry.note)
            actions.append(row)
            continue
        digest, size = sha256_file(local_path)
        remote = remote_store.stat(rel)
        row.update(local_size=size, sha256=digest, remote_size=remote.size if remote else None)
        if remote is None:
            row["action"] = "upload"
        elif remote.size != size:
            row["action"] = "replace-size-mismatch"
        else:
            row["action"] = "present"
        actions.append(row)
    return actions


def apply(
    local_store: RootedStore,
    remote_store: RootedStore,
    files: tuple[CanonicalFile, ...] = STAGE1_CANONICAL,
) -> dict:
    actions = plan(local_store, remote_store, files)
    uploaded: list[dict] = []
    for row in actions:
        if row["action"] not in ("upload", "replace-size-mismatch"):
            continue
        path = Path(row["local"])
        remote_store.write(row["rel"], _chunks(path))
        remote = remote_store.stat(row["rel"])
        row["after_size"] = remote.size if remote else None
        uploaded.append(row)

    manifest = {
        "synced_at": utc_now(),
        "destination": remote_store.describe(),
        "files": actions,
        "uploaded": len(uploaded),
    }
    if uploaded:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        remote_store.write_text(
            remote_store.manifests(f"stage1_sync_{stamp}.json"),
            json.dumps(manifest, indent=2) + "\n",
        )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish canonical stage1 files to the archive.")
    parser.add_argument("--local-root", default=None, help="local data root (default: ./data)")
    parser.add_argument("--store", default=None)
    parser.add_argument("--root", default=None)
    parser.add_argument("--apply", action="store_true", help="upload (default is plan only)")
    args = parser.parse_args(argv)

    local = open_store("file", args.local_root or str(Path.cwd() / "data"))
    remote = open_store(args.store, args.root)

    result = apply(local, remote) if args.apply else {
        "destination": remote.describe(),
        "files": plan(local, remote),
        "uploaded": 0,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
