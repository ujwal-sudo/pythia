"""Backend protocol and the rooted store that all data access goes through."""

from __future__ import annotations

import posixpath
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import BinaryIO, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Entry:
    """One file in the store, addressed relative to the store root."""

    rel: str
    size: int
    mtime: float | None = None
    is_dir: bool = False

    def __post_init__(self) -> None:
        if self.size < 0:
            raise ValueError(f"negative size for {self.rel!r}")


@runtime_checkable
class Backend(Protocol):
    """Minimal object-store surface: list, stream read, stream write."""

    scheme: str

    def list(self, rel: str, *, recursive: bool = False) -> list[Entry]:
        ...

    def open(self, rel: str) -> BinaryIO:
        ...

    def write(self, rel: str, chunks: Iterable[bytes]) -> None:
        ...

    def exists(self, rel: str) -> bool:
        ...

    def stat(self, rel: str) -> Entry | None:
        ...

    def delete(self, rel: str) -> None:
        ...

    def move(self, src: str, dst: str) -> None:
        ...

    def mkdir(self, rel: str) -> None:
        ...


def normalize_rel(rel: str) -> str:
    """Validate a store-relative path.

    Rejects absolute paths, `..` traversal, backslashes, empty segments and
    trailing slashes. The empty string is allowed and means "the root".
    """
    if not isinstance(rel, str):
        raise ValueError(f"path must be a string, got {type(rel).__name__}")
    if "\\" in rel:
        raise ValueError(f"path must use forward slashes: {rel!r}")
    if rel.startswith("/"):
        raise ValueError(f"path must be relative to the store root: {rel!r}")
    if rel in ("", "."):
        return ""
    cleaned = rel.rstrip("/")
    parts = cleaned.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            raise ValueError(f"invalid path segment {part!r} in {rel!r}")
    return posixpath.join(*parts)


class RootedStore:
    """A backend plus one root directory.

    Every method takes a path relative to that root. Canonical locations are
    exposed as named accessors so callers never assemble paths by hand; when a
    layout change is needed, it happens here.
    """

    def __init__(self, backend: Backend, root: str = "") -> None:
        self._backend = backend
        self.root = root.rstrip("/")

    # -- identity -----------------------------------------------------
    @property
    def scheme(self) -> str:
        return self._backend.scheme

    @property
    def backend(self) -> Backend:
        return self._backend

    def describe(self) -> str:
        return f"{self.scheme}://{self.root}" if self.root else f"{self.scheme}://"

    def __repr__(self) -> str:
        return f"RootedStore({self.describe()})"

    # -- canonical layout --------------------------------------------
    def raw(self, source: str) -> str:
        return normalize_rel(f"raw/{source}")

    def filtered(self, stage: int | str) -> str:
        return normalize_rel(f"filtered/stage{stage}")

    def final(self, name: str) -> str:
        return normalize_rel(f"final/{name}")

    def manifests(self, name: str) -> str:
        return normalize_rel(f"manifests/{name}")

    def snapshots(self, name: str) -> str:
        return normalize_rel(f"snapshots/{name}")

    def reports(self, name: str) -> str:
        return normalize_rel(f"reports/{name}")

    # -- pass-through operations -------------------------------------
    def list(self, rel: str = "", *, recursive: bool = False) -> list[Entry]:
        return self._backend.list(normalize_rel(rel), recursive=recursive)

    def files(self, rel: str = "", *, recursive: bool = True) -> list[Entry]:
        return [e for e in self.list(rel, recursive=recursive) if not e.is_dir]

    def open(self, rel: str) -> BinaryIO:
        """Open for reading. A missing object raises ``NotFound``.

        Existence is not probed first: an extra round trip per file is slow on
        object storage, and the backend already reports the failure.
        """
        return self._backend.open(normalize_rel(rel))

    def write(self, rel: str, chunks: Iterable[bytes]) -> None:
        self._backend.write(normalize_rel(rel), chunks)

    def write_text(self, rel: str, text: str) -> None:
        self.write(rel, [text.encode("utf-8")])

    def read_text(self, rel: str) -> str:
        with self.open(rel) as handle:
            return handle.read().decode("utf-8")

    def exists(self, rel: str) -> bool:
        return self._backend.exists(normalize_rel(rel))

    def stat(self, rel: str) -> Entry | None:
        return self._backend.stat(normalize_rel(rel))

    def delete(self, rel: str) -> None:
        self._backend.delete(normalize_rel(rel))

    def move(self, src: str, dst: str) -> None:
        self._backend.move(normalize_rel(src), normalize_rel(dst))

    def mkdir(self, rel: str) -> None:
        self._backend.mkdir(normalize_rel(rel))

    # -- bounded iteration -------------------------------------------
    def iter_lines(self, rel: str) -> Iterator[bytes]:
        """Yield raw lines (without trailing newline) from a text object."""
        with self.open(rel) as handle:
            for line in handle:
                yield line.rstrip(b"\r\n")
