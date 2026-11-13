"""Filesystem backend. Used for tests and for temporary staging areas."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import BinaryIO

from scripts.storage.base import Entry, normalize_rel
from scripts.storage.errors import InvalidPath, NotFound


class LocalBackend:
    """A directory tree on the local filesystem."""

    scheme = "file"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    # -- helpers ------------------------------------------------------
    def _abs(self, rel: str) -> Path:
        rel = normalize_rel(rel)
        candidate = (self.root / rel).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise InvalidPath(f"path escapes local root: {rel!r}")
        return candidate

    # -- protocol -----------------------------------------------------
    def list(self, rel: str, *, recursive: bool = False) -> list[Entry]:
        base = self._abs(rel)
        if not base.exists():
            return []
        if base.is_file():
            stat = base.stat()
            return [Entry(rel=normalize_rel(rel), size=stat.st_size, mtime=stat.st_mtime)]
        entries: list[Entry] = []
        walker = base.rglob("*") if recursive else base.glob("*")
        for path in sorted(walker):
            stat = path.stat()
            entries.append(
                Entry(
                    rel=path.relative_to(self.root).as_posix(),
                    size=0 if path.is_dir() else stat.st_size,
                    mtime=stat.st_mtime,
                    is_dir=path.is_dir(),
                )
            )
        return entries

    def open(self, rel: str) -> BinaryIO:
        path = self._abs(rel)
        if not path.is_file():
            raise NotFound(f"file not found: {path}")
        return path.open("rb")

    def write(self, rel: str, chunks: Iterable[bytes]) -> None:
        target = self._abs(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".part",
            delete=False,
        )
        tmp = Path(handle.name)
        try:
            with handle:
                for chunk in chunks:
                    if chunk:
                        handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def exists(self, rel: str) -> bool:
        return self._abs(rel).exists()

    def stat(self, rel: str) -> Entry | None:
        path = self._abs(rel)
        if not path.exists():
            return None
        stat = path.stat()
        return Entry(
            rel=normalize_rel(rel),
            size=0 if path.is_dir() else stat.st_size,
            mtime=stat.st_mtime,
            is_dir=path.is_dir(),
        )

    def delete(self, rel: str) -> None:
        path = self._abs(rel)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    def move(self, src: str, dst: str) -> None:
        source = self._abs(src)
        target = self._abs(dst)
        if not source.exists():
            raise NotFound(f"cannot move missing path: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)

    def mkdir(self, rel: str) -> None:
        self._abs(rel).mkdir(parents=True, exist_ok=True)
