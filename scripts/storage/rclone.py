"""rclone-backed storage.

The archive lives on a Google Drive remote (``pythia:Pythia``). We deliberately
do not depend on a FUSE mount: a missing mount looked like an ordinary empty
directory and the previous pipeline wrote 900 MB onto the system disk while
reporting success.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from collections.abc import Iterable
from typing import BinaryIO

from scripts.storage.base import Entry, normalize_rel
from scripts.storage.errors import BackendUnavailable, NotFound, StoreError


class _PipeStream:
    """Read side of ``rclone cat``; surfaces failures instead of truncating."""

    def __init__(self, proc: subprocess.Popen, target: str) -> None:
        self._proc = proc
        self._target = target
        self._out = proc.stdout
        self._closed = False

    def read(self, size: int = -1) -> bytes:  # type: ignore[override]
        return self._out.read(size)

    def readinto(self, buffer) -> int:  # type: ignore[override]
        return self._out.readinto(buffer)

    def __iter__(self):
        return iter(self._out)

    def __enter__(self) -> "_PipeStream":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close(raise_on_error=exc_type is None)

    def close(self, *, raise_on_error: bool = True) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._out.close()
        finally:
            stderr = self._proc.stderr.read() if self._proc.stderr else b""
            code = self._proc.wait()
        if raise_on_error and code != 0 and code != -13:
            detail = stderr.decode("utf-8", "replace").strip()
            raise StoreError(f"rclone cat failed for {self._target}: {detail or code}")


class RcloneBackend:
    """Object store addressed as ``<remote>:<path>``."""

    scheme = "rclone"

    def __init__(self, remote: str, *, binary: str = "rclone") -> None:
        if ":" not in remote:
            raise BackendUnavailable(
                f"rclone root must look like 'remote:bucket', got {remote!r}"
            )
        self.remote = remote.rstrip("/")
        self.binary = binary

    # -- helpers ------------------------------------------------------
    def _target(self, rel: str) -> str:
        rel = normalize_rel(rel)
        return f"{self.remote}/{rel}" if rel else self.remote

    def _check_available(self) -> None:
        if shutil.which(self.binary) is None:
            raise BackendUnavailable(f"{self.binary!r} not found on PATH")

    def _run(
        self,
        args: list[str],
        *,
        stdin: bytes | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        self._check_available()
        env = dict(os.environ)
        env.setdefault("RCLONE_FAST_LIST", "true")
        proc = subprocess.run(
            [self.binary, *args],
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        if check and proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace").strip()
            raise StoreError(f"rclone {' '.join(args)} failed: {detail}")
        return proc

    def _lsjson(self, target: str, *, recursive: bool, files_only: bool) -> list[dict]:
        args = ["lsjson", target]
        if recursive:
            args.append("--recursive")
        if files_only:
            args.append("--files-only")
        proc = self._run(args, check=False)
        if proc.returncode != 0:
            return []
        raw = proc.stdout.decode("utf-8", "replace").strip()
        if not raw or raw == "null":
            return []
        return json.loads(raw)

    # -- protocol -----------------------------------------------------
    def list(self, rel: str, *, recursive: bool = False) -> list[Entry]:
        rel = normalize_rel(rel)
        payload = self._lsjson(
            self._target(rel), recursive=recursive, files_only=recursive
        )
        entries: list[Entry] = []
        for item in payload:
            is_dir = bool(item.get("IsDir"))
            # rclone reports Size=-1 for directories.
            size = 0 if is_dir else max(0, int(item.get("Size") or 0))
            mtime_raw = item.get("ModTime")
            mtime = None
            if mtime_raw:
                try:
                    from datetime import datetime

                    mtime = datetime.fromisoformat(
                        mtime_raw.replace("Z", "+00:00")
                    ).timestamp()
                except ValueError:
                    mtime = None
            child = item.get("Path", "")
            entries.append(
                Entry(
                    # lsjson reports Path relative to the listed prefix.
                    rel=f"{rel}/{child}" if rel else child,
                    size=size,
                    mtime=mtime,
                    is_dir=is_dir,
                )
            )
        return sorted(entries, key=lambda e: e.rel)

    def open(self, rel: str) -> BinaryIO:
        self._check_available()
        target = self._target(rel)
        proc = subprocess.Popen(
            [self.binary, "cat", target],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc.stdout is not None
        return _PipeStream(proc, target)  # type: ignore[return-value]

    def write(self, rel: str, chunks: Iterable[bytes]) -> None:
        """Stream to a sibling temp object, then move it into place.

        The move makes a half-written corpus impossible to mistake for a
        complete one.
        """
        self._check_available()
        rel = normalize_rel(rel)
        target = self._target(rel)
        temp = f"{target}.part-{uuid.uuid4().hex[:8]}"
        proc = subprocess.Popen(
            [self.binary, "rcat", temp],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc.stdin is not None
        try:
            for chunk in chunks:
                if chunk:
                    proc.stdin.write(chunk)
            proc.stdin.close()
        except BrokenPipeError as error:
            proc.wait()
            raise StoreError(f"rclone rcat closed early for {target}") from error
        stderr = proc.stderr.read() if proc.stderr else b""
        code = proc.wait()
        if code != 0:
            detail = stderr.decode("utf-8", "replace").strip()
            raise StoreError(f"rclone rcat failed for {target}: {detail}")
        self._run(["moveto", temp, target])

    def exists(self, rel: str) -> bool:
        return self.stat(rel) is not None

    def stat(self, rel: str) -> Entry | None:
        proc = self._run(["lsjson", "--stat", self._target(rel)], check=False)
        if proc.returncode != 0:
            return None
        raw = proc.stdout.decode("utf-8", "replace").strip()
        if not raw or raw == "null":
            return None
        item = json.loads(raw)
        is_dir = bool(item.get("IsDir"))
        return Entry(
            rel=normalize_rel(rel),
            size=0 if is_dir else max(0, int(item.get("Size") or 0)),
            is_dir=is_dir,
        )

    def delete(self, rel: str) -> None:
        if not self.exists(rel):
            raise NotFound(f"cannot delete missing object: {self._target(rel)}")
        self._run(["deletefile", self._target(rel)])

    def move(self, src: str, dst: str) -> None:
        if not self.exists(src):
            raise NotFound(f"cannot move missing object: {self._target(src)}")
        self._run(["moveto", self._target(src), self._target(dst)])

    def mkdir(self, rel: str) -> None:
        # Object stores create prefixes implicitly; kept for protocol parity.
        return None
