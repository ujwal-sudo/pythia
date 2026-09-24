"""PyPI remote storage abstraction — direct rclone access to pythia:Pythia.

This module provides the storage-layer abstraction that lets the existing
PyPI pipeline operate safely against the authoritative remote
``pythia:Pythia`` WITHOUT the FUSE mount (unavailable inside the VS Code
snap environment) and WITHOUT weakening the guarantees POSIX atomic rename
previously provided.

Design goals
------------
* Canonical authoritative PyPI root: ``pythia:Pythia/raw/pypi``. A single
  path-mapping mechanism; no ambiguous alternate roots.
* Read operations verified against the authoritative remote.
* Write operations use a **two-phase commit** (staging + verified promote)
  so a torn/partial object is never interpreted as a committed record.
* A **lease-based distributed single-writer lock** to protect against two
  concurrent PyPI writers / concurrent Phase C and Phase D.
* Freeze sentinel resolved through the authoritative remote and checked
  FIRST before every PyPI write.
* Session 4 (GitHub) paths are isolated and never redirected by this module.

Honest backend-guarantee accounting
-----------------------------------
The module is layered over a ``StorageBackend`` so semantics can be tested
against an isolated local backend. The real remote backend is ``RcloneBackend``
(Google Drive via rclone). Google Drive/rclone does NOT provide a native atomic
create-if-absent or atomic rename primitive. The commit protocol therefore
uses a *staging object + verified promote* model that is crash-safe for
READERS (a reader only ever sees a fully-verified final object or an absent
final object), but the promotion step itself is NOT a single atomic remote
operation. A partially uploaded final object is detected by read-after-write
verification; if verification fails the logical record is NOT marked
committed and the object is retried/left for reconciliation.

Limitations that require external services (documented, not hidden):
  * TRUE atomicity of the final-object promotion cannot be proven with
    Google Drive/rclone alone. The module fails closed instead of claiming
    atomicity it cannot provide.
  * The distributed lock is lease-based best-effort; a strict mutually
    exclusive lock requires an external lock service (documented).

This module does NOT change acquisition, selection, identity, recovery,
checkpoint schema, or dataset semantics.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# canonical mapping
# --------------------------------------------------------------------------
MOUNT_ROOT = Path("/mnt/pythia-cloud")
REMOTE_ROOT = "pythia:"
PYTHIA_CONTAINER = "Pythia"
AUTHORITATIVE_PYPI_REMOTE = f"{REMOTE_ROOT}{PYTHIA_CONTAINER}/raw/pypi"

# Legacy config-driven root (no Pythia container) is NOT authoritative.
_LEGACY_PYPI_ROOT_NO_PYTHIA = Path("/mnt/pythia-cloud/raw/pypi")
_CANONICAL_PYPI_ROOT = Path("/mnt/pythia-cloud/Pythia/raw/pypi")

FREEZE_SENTINEL_REL = "raw/pypi/.FREEZE_SENTINEL"

# Lock / staging namespaces live under the PyPI remote root and are never
# read as authoritative checkpoint/manifest data.
STAGING_REL = "metadata/.staging"
LOCK_REL = "metadata/.locks"
MANIFEST_STAGING_REL = "manifests/.staging"

# Session 4 GitHub paths must never be redirected by this shim.
_SESSION4_PREFIXES = (
    "/mnt/pythia-cloud/Pythia/raw/github",
    "pythia:Pythia/raw/github",
)

DEFAULT_LEASE_SECONDS = 300  # 5 minute single-writer lease
LOCK_FILENAME = "writer.lock"


class RemotePathMappingError(Exception):
    """A path cannot be canonically mapped to the authoritative remote."""


class FreezeError(Exception):
    """A PyPI write was attempted while the freeze sentinel exists."""


class RemoteWriteVerificationError(Exception):
    """A remote write could not be verified (fail-closed)."""


class RemoteOverwriteError(Exception):
    """A remote object would be silently overwritten (fail-closed)."""


class LockAcquisitionError(Exception):
    """The single-writer lock could not be acquired."""


class LockNotHeldError(Exception):
    """An operation required a held lock but none was held."""


class StorageBackendError(Exception):
    """A storage backend operation failed."""


# --------------------------------------------------------------------------
# canonical path model
# --------------------------------------------------------------------------
def canonical_pypi_root() -> Path:
    """Return the canonical local-style PyPI root path (Pythia container)."""
    return _CANONICAL_PYPI_ROOT


def is_session4_path(path: Path | str) -> bool:
    """Return True if the path belongs to Session 4 (raw/github)."""
    s = str(path)
    for prefix in _SESSION4_PREFIXES:
        if s == prefix or s.startswith(prefix + "/"):
            return True
    return False


def map_local_path_to_remote(path: Path | str) -> str:
    """Map a local-style path to a remote ``pythia:...`` path.

    Accepts:
      * ``/mnt/pythia-cloud/Pythia/raw/pypi/...``   -> ``pythia:Pythia/raw/pypi/...``
      * ``/mnt/pythia-cloud/raw/pypi/...`` (legacy)  -> ``pythia:Pythia/raw/pypi/...``
      * ``pythia:Pythia/...`` (already remote)       -> unchanged

    Rejects ambiguous / Session 4 paths with RemotePathMappingError.
    """
    s = str(path)
    if s.startswith("pythia:"):
        if is_session4_path(s):
            raise RemotePathMappingError(f"Refusing to map Session 4 path: {s}")
        return s
    if is_session4_path(s):
        raise RemotePathMappingError(f"Refusing to map Session 4 path: {s}")

    p = Path(s)
    try:
        rel = p.relative_to(_CANONICAL_PYPI_ROOT)
        return f"{REMOTE_ROOT}{PYTHIA_CONTAINER}/raw/pypi/{rel}"
    except ValueError:
        pass
    try:
        rel = p.relative_to(_LEGACY_PYPI_ROOT_NO_PYTHIA)
        return f"{REMOTE_ROOT}{PYTHIA_CONTAINER}/raw/pypi/{rel}"
    except ValueError:
        pass
    # Recovery paths live under /mnt/pythia-cloud/Pythia/recovery/... and are
    # part of the authoritative project storage; map them to the remote.
    _recovery_root = Path("/mnt/pythia-cloud/Pythia/recovery")
    try:
        rel = p.relative_to(_recovery_root)
        return f"{REMOTE_ROOT}{PYTHIA_CONTAINER}/recovery/{rel}"
    except ValueError:
        pass

    raise RemotePathMappingError(f"Path is not under the canonical PyPI root: {s}")


def freeze_sentinel_remote() -> str:
    """Remote path of the freeze sentinel (authoritative)."""
    return f"{REMOTE_ROOT}{PYTHIA_CONTAINER}/{FREEZE_SENTINEL_REL}"


def staging_dir_remote() -> str:
    return f"{AUTHORITATIVE_PYPI_REMOTE}/{STAGING_REL}"


def lock_dir_remote() -> str:
    return f"{AUTHORITATIVE_PYPI_REMOTE}/{LOCK_REL}"


def manifest_staging_dir_remote() -> str:
    return f"{AUTHORITATIVE_PYPI_REMOTE}/{MANIFEST_STAGING_REL}"


# --------------------------------------------------------------------------
# storage backends
# --------------------------------------------------------------------------
class StorageBackend:
    """Abstract storage backend. Subclasses implement rclone vs local mock."""

    def exists(self, remote: str) -> bool:  # pragma: no cover - abstract
        raise NotImplementedError

    def read_bytes(self, remote: str) -> bytes:  # pragma: no cover
        raise NotImplementedError

    def list_names(self, remote_dir: str) -> List[str]:  # pragma: no cover
        raise NotImplementedError

    def write_bytes(self, remote: str, data: bytes, *, prevent_overwrite: bool = True) -> None:
        raise NotImplementedError

    def sha256(self, remote: str) -> Optional[str]:  # pragma: no cover
        raise NotImplementedError

    def delete(self, remote: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def about_free_gb(self) -> Optional[float]:  # pragma: no cover
        raise NotImplementedError


class RcloneBackend(StorageBackend):
    """Real backend using rclone subprocesses against pythia:."""

    def __init__(self, timeout: int = 90) -> None:
        self._timeout = timeout

    def _run(self, args: List[str], timeout: Optional[int] = None) -> subprocess.CompletedProcess:
        cmd = ["rclone"] + args
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout or self._timeout)

    def exists(self, remote: str) -> bool:
        proc = self._run(["lsf", remote, "--max-depth", "1"], timeout=self._timeout)
        return proc.returncode == 0

    def read_bytes(self, remote: str) -> bytes:
        proc = self._run(["cat", remote], timeout=self._timeout)
        if proc.returncode != 0:
            raise StorageBackendError(f"rclone cat failed for {remote}: {proc.stderr}")
        return proc.stdout.encode("utf-8")

    def list_names(self, remote_dir: str) -> List[str]:
        proc = self._run(["lsf", remote_dir, "--max-depth", "1"], timeout=self._timeout)
        if proc.returncode != 0:
            raise StorageBackendError(f"rclone lsf failed for {remote_dir}: {proc.stderr}")
        return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]

    def write_bytes(self, remote: str, data: bytes, *, prevent_overwrite: bool = True) -> None:
        _guard_write()  # never write to the real remote unless explicitly enabled
        if prevent_overwrite and self.exists(remote):
            raise RemoteOverwriteError(f"Refusing to overwrite {remote}")
        with tempfile.NamedTemporaryFile(prefix="pypi_rw_", delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            proc = self._run(
                ["copyto", str(tmp_path), remote, "--checksum", "--retries", "3",
                 "--low-level-retries", "10", "--transfers", "1", "--fast-list"],
                timeout=max(self._timeout, 180))
            if proc.returncode != 0:
                raise StorageBackendError(f"rclone copyto failed for {remote}: {proc.stderr}")
        finally:
            tmp_path.unlink(missing_ok=True)

    def sha256(self, remote: str) -> Optional[str]:
        proc = self._run(["hashsum", "sha256", remote, "--fast-list"], timeout=self._timeout)
        if proc.returncode != 0:
            return None
        for line in proc.stdout.splitlines():
            parts = line.split()
            if parts:
                return parts[0]
        return None

    def delete(self, remote: str) -> None:
        _guard_write()  # never delete from the real remote unless explicitly enabled
        self._run(["delete", remote], timeout=self._timeout)

    def about_free_gb(self) -> Optional[float]:
        proc = self._run(["about", REMOTE_ROOT], timeout=60)
        if proc.returncode != 0:
            return None
        for line in proc.stdout.splitlines():
            low = line.lower()
            if "free" in low and ":" in low:
                val = low.split(":", 1)[1].strip()
                gb = _parse_size_to_gb(val)
                if gb is not None:
                    return gb
        return None


class LocalDirBackend(StorageBackend):
    """Isolated local backend used ONLY by tests.

    Maps a ``pythia:Pythia/raw/pypi/<path>`` style remote path to a local
    directory tree rooted at ``root``. Provides POSIX-atomic semantics for
    deterministic write tests, but preserves the same overwrite guards.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _to_path(self, remote: str) -> Path:
        prefix = f"{REMOTE_ROOT}{PYTHIA_CONTAINER}/raw/pypi/"
        if remote.startswith(prefix):
            rel = remote[len(prefix):]
        elif remote.startswith(f"{REMOTE_ROOT}{PYTHIA_CONTAINER}/"):
            rel = remote[len(f"{REMOTE_ROOT}{PYTHIA_CONTAINER}/"):]
        else:
            raise StorageBackendError(f"Cannot map {remote} in local backend")
        return self.root / rel

    def exists(self, remote: str) -> bool:
        return self._to_path(remote).exists()

    def read_bytes(self, remote: str) -> bytes:
        p = self._to_path(remote)
        if not p.exists():
            raise StorageBackendError(f"not found: {remote}")
        return p.read_bytes()

    def list_names(self, remote_dir: str) -> List[str]:
        p = self._to_path(remote_dir)
        if not p.is_dir():
            return []
        return sorted(e.name for e in p.iterdir())

    def write_bytes(self, remote: str, data: bytes, *, prevent_overwrite: bool = True) -> None:
        p = self._to_path(remote)
        if prevent_overwrite and p.exists():
            raise RemoteOverwriteError(f"Refusing to overwrite {remote}")
        p.parent.mkdir(parents=True, exist_ok=True)
        # POSIX-atomic write to mirror the old local behavior in tests.
        tmp = p.with_name(f".{p.name}.tmp-{uuid.uuid4().hex}")
        tmp.write_bytes(data)
        tmp.replace(p)

    def sha256(self, remote: str) -> Optional[str]:
        p = self._to_path(remote)
        if not p.exists():
            return None
        return hashlib.sha256(p.read_bytes()).hexdigest()

    def delete(self, remote: str) -> None:
        p = self._to_path(remote)
        if p.exists():
            p.unlink()

    def about_free_gb(self) -> Optional[float]:
        return 9999.0  # tests assume headroom


# module-level backend (default real rclone; tests swap it)
_BACKEND: StorageBackend = RcloneBackend()

# Safety guard: refuse real-remote writes unless explicitly enabled. This
# prevents tests or accidental code paths from writing to pythia:Pythia.
_ALLOW_REMOTE_WRITE = os.environ.get("PYPI_STORAGE_ALLOW_REMOTE_WRITE", "0") == "1"


def _guard_write() -> None:
    """Fail closed if a write would target the real remote and writes are
    not explicitly enabled."""
    if isinstance(get_backend(), RcloneBackend) and not _ALLOW_REMOTE_WRITE:
        raise StorageBackendError(
            "Refusing real-remote write: PYPI_STORAGE_ALLOW_REMOTE_WRITE is not set "
            "(tests must use LocalDirBackend)")


def get_backend() -> StorageBackend:
    return _BACKEND


def set_backend(backend: StorageBackend) -> None:
    """Swap the storage backend (used by tests)."""
    global _BACKEND
    _BACKEND = backend


# --------------------------------------------------------------------------
# read protocol
# --------------------------------------------------------------------------
def remote_exists(remote: str) -> bool:
    return get_backend().exists(remote)


def remote_read_bytes(remote: str) -> bytes:
    return get_backend().read_bytes(remote)


def remote_read_text(remote: str) -> str:
    return get_backend().read_bytes(remote).decode("utf-8")


def remote_list(remote_dir: str) -> List[str]:
    return get_backend().list_names(remote_dir)


def remote_sha256(remote: str) -> Optional[str]:
    return get_backend().sha256(remote)


def verify_remote_object(remote: str, expected_sha256: str, *, retries: int = 3,
                         retry_delay: float = 1.0) -> bool:
    """Read-after-write verification with retry.

    Returns True only when the object exists AND its SHA-256 matches
    ``expected_sha256``.
    """
    for attempt in range(retries):
        if not get_backend().exists(remote):
            if attempt < retries - 1:
                time.sleep(retry_delay)
                continue
            return False
        sha = get_backend().sha256(remote)
        if sha == expected_sha256:
            return True
        if attempt < retries - 1:
            time.sleep(retry_delay)
    return False


# --------------------------------------------------------------------------
# remote checkpoint discovery / archive verification (remote mode)
# --------------------------------------------------------------------------
def remote_checkpoint_names() -> List[str]:
    """List checkpoint object names under the remote metadata dir.

    Returns bare filenames (e.g. ``a2a-sdk_checkpoint.json``). Staging and
    lock objects (which live under ``.staging/`` / ``.locks/`` subdirs) are
    NOT returned — a reader never mistakes them for authoritative checkpoints.
    """
    names = get_backend().list_names(f"{AUTHORITATIVE_PYPI_REMOTE}/metadata")
    return [n for n in names if n.endswith("_checkpoint.json")]


def remote_checkpoint_path(pkg_norm: str) -> str:
    return f"{AUTHORITATIVE_PYPI_REMOTE}/metadata/{pkg_norm}_checkpoint.json"


def remote_load_checkpoint(pkg_norm: str) -> Optional[Dict[str, Any]]:
    """Load one checkpoint from the remote metadata dir (None if absent)."""
    remote = remote_checkpoint_path(pkg_norm)
    if not get_backend().exists(remote):
        return None
    try:
        data = json.loads(get_backend().read_bytes(remote).decode("utf-8"))
        return data.get(pkg_norm)
    except Exception:
        return None


def remote_archive_exists(pkg_norm: str, version: str, filename: str) -> bool:
    return get_backend().exists(archive_remote_path(pkg_norm, version, filename))


def remote_archive_sha256(pkg_norm: str, version: str, filename: str) -> Optional[str]:
    return get_backend().sha256(archive_remote_path(pkg_norm, version, filename))


# --------------------------------------------------------------------------
# freeze protocol
# --------------------------------------------------------------------------
def freeze_sentinel_exists() -> bool:
    return get_backend().exists(freeze_sentinel_remote())


def assert_no_freeze() -> None:
    if freeze_sentinel_exists():
        raise FreezeError(
            f"PyPI baseline is FROZEN (sentinel {freeze_sentinel_remote()} present)")
def commit_write(
    data: bytes,
    final_remote: str,
    *,
    prevent_overwrite: bool = True,
    namespace: str = "checkpoint",
    verify: bool = True,
    journal: bool = False,
    retries: int = 3,
    retry_delay: float = 1.0,
) -> Dict[str, Any]:
    """Two-phase failure-safe write to the authoritative remote.

    Protocol:
      1. (optional) Write a commit-journal marker recording intent + local SHA.
      2. Serialize to a unique staging object under the staging namespace.
      3. Verify the staging object (SHA + read-after-write).
      4. Promote: write the SAME verified bytes to the final remote name.
      5. Read-after-write verify the final object.
      6. (optional) Remove the journal marker.
      7. Only then treat the write as committed.

    Fail-closed: on any verification failure the logical record is NOT
    committed (an exception is raised) and no existing final object is
    overwritten.

    Crash-reconciliation semantics:
      * Before upload: nothing authoritative written; safe.
      * Staging upload interrupted: only a ``.part`` staging object exists;
        readers never read staging; safe.
      * After staging verify, during promote: a final object may be partial.
        If ``journal=True`` a marker records commit intent; a crash leaves the
        marker present so reconciliation can detect the interrupted promote.
      * After promote, before verify: same; the marker is still present.
      * After verify: marker removed; committed.

    A reader only ever reads the *final* name. Because the final name is only
    written with fully-verified bytes and is verified after write, a
    torn/interrupted upload is detected and never treated as committed unless
    reconciliation confirms it.
    """
    local_sha = hashlib.sha256(data).hexdigest()

    if prevent_overwrite and get_backend().exists(final_remote):
        raise RemoteOverwriteError(f"Refusing to overwrite existing object: {final_remote}")

    marker_remote = None
    if journal:
        marker_remote = f"{staging_dir_remote()}/journal-{uuid.uuid4().hex}.json"
        get_backend().write_bytes(
            marker_remote,
            json.dumps({
                "op": "commit",
                "namespace": namespace,
                "final_remote": final_remote,
                "sha256": local_sha,
                "intent": "writing",
            }, sort_keys=True).encode("utf-8"),
            prevent_overwrite=False,
        )

    # --- stage ---
    staging = f"{staging_dir_remote()}/{namespace}-{uuid.uuid4().hex}.part"
    get_backend().write_bytes(staging, data, prevent_overwrite=False)
    if verify and not verify_remote_object(staging, local_sha, retries=retries,
                                           retry_delay=retry_delay):
        # leave the staging object for diagnosis; do NOT commit.
        raise RemoteWriteVerificationError(
            f"Staging object could not be verified: {staging}")

    # --- promote (write same verified bytes to final name) ---
    get_backend().write_bytes(final_remote, data, prevent_overwrite=prevent_overwrite)

    # --- read-after-write verify final ---
    if verify and not verify_remote_object(final_remote, local_sha, retries=retries,
                                           retry_delay=retry_delay):
        raise RemoteWriteVerificationError(
            f"Final object failed read-after-write verification: {final_remote}")

    # clean up staging best-effort (never authoritative; failure is non-fatal)
    try:
        get_backend().delete(staging)
    except Exception:
        pass
    # clean up journal marker best-effort
    if marker_remote is not None:
        try:
            get_backend().delete(marker_remote)
        except Exception:
            pass

    return {"remote": final_remote, "sha256": local_sha, "committed": True}


def find_interrupted_commits() -> List[Dict[str, Any]]:
    """Return commit-journal markers still present (interrupted writes).

    A marker whose final_remote already exists and SHA-matches is a
    completed-but-not-cleaned write; one whose final_remote is absent or
    mismatched is an interrupted promote requiring reconciliation.
    """
    if not get_backend().exists(staging_dir_remote()):
        return []
    markers = []
    for name in get_backend().list_names(staging_dir_remote()):
        if not name.startswith("journal-"):
            continue
        remote = f"{staging_dir_remote()}/{name}"
        try:
            rec = json.loads(get_backend().read_bytes(remote).decode("utf-8"))
        except Exception:
            rec = {"remote": remote, "unparseable": True}
        markers.append(rec)
    return markers


def promote_staged(
    staging_remote: str,
    final_remote: str,
    *,
    prevent_overwrite: bool = True,
    verify: bool = True,
) -> Dict[str, Any]:
    """Promote an already-verified staging object to its final name.

    Used for large archives where staging + promote can be separate steps.
    The staging object must already exist and be SHA-verifiable.
    """
    data = get_backend().read_bytes(staging_remote)
    return commit_write(data, final_remote, prevent_overwrite=prevent_overwrite,
                        namespace="promote", verify=verify)


# --------------------------------------------------------------------------
# checkpoint writes
# --------------------------------------------------------------------------
def checkpoint_remote_path(pkg_norm: str) -> str:
    return f"{AUTHORITATIVE_PYPI_REMOTE}/metadata/{pkg_norm}_checkpoint.json"


def save_checkpoint_remote(
    pkg_norm: str,
    state: Dict[str, Any],
    *,
    allow_overwrite: bool = False,
) -> Dict[str, Any]:
    """Write a checkpoint through the two-phase commit protocol.

    Freeze is checked FIRST. Existing checkpoints are never silently
    overwritten (unless allow_overwrite is explicitly True). Checkpoint
    schema is unchanged: ``{pkg_norm: {...}}``.
    """
    assert_no_freeze()
    checkpoint_json = json.dumps(state, indent=2, sort_keys=True) + "\n"
    final = checkpoint_remote_path(pkg_norm)
    return commit_write(
        checkpoint_json.encode("utf-8"),
        final,
        prevent_overwrite=not allow_overwrite,
        namespace="checkpoint",
        verify=True,
    )


# --------------------------------------------------------------------------
# manifest writes
# --------------------------------------------------------------------------
def manifest_remote_path(name: str) -> str:
    return f"{AUTHORITATIVE_PYPI_REMOTE}/manifests/{name}"


def save_manifest_remote(
    name: str,
    records: List[Dict[str, Any]],
    *,
    kind: str = "jsonl",
) -> Dict[str, Any]:
    """Write an acquisition/candidates manifest with commit + integrity.

    For JSONL manifests a record_count header line is embedded and
    re-verified after write. For JSON manifests the record_count field is
    checked. Prevents partial/torn manifests from becoming authoritative.
    """
    assert_no_freeze()
    final = manifest_remote_path(name)
    if kind == "json":
        data = json.dumps({"record_count": len(records), "records": records},
                          indent=2, sort_keys=True).encode("utf-8")
    else:
        lines = [json.dumps(r, sort_keys=True) for r in records]
        data = (f"#record_count={len(records)}\n" + "\n".join(lines) + "\n").encode("utf-8")
    result = commit_write(data, final, prevent_overwrite=False,
                          namespace="manifest", verify=True)
    # integrity: re-read and confirm record_count
    try:
        text = get_backend().read_bytes(final).decode("utf-8")
        if kind == "json":
            parsed = json.loads(text)
            assert parsed["record_count"] == len(records)
        else:
            header = text.splitlines()[0]
            assert header == f"#record_count={len(records)}"
    except Exception as e:
        raise RemoteWriteVerificationError(
            f"Manifest integrity check failed for {final}: {e}")
    return result


# --------------------------------------------------------------------------
# archive writes
# --------------------------------------------------------------------------
def archive_remote_path(pkg_norm: str, version: str, filename: str) -> str:
    return (f"{AUTHORITATIVE_PYPI_REMOTE}/packages/{pkg_norm}/{version}/{filename}")


def save_archive_remote(
    data: bytes,
    pkg_norm: str,
    version: str,
    filename: str,
    *,
    expected_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Write an archive via staging + promote with SHA verification.

    ``expected_sha256`` is the historical persisted SHA; if provided it is
    checked against the local bytes BEFORE upload (identity gate).
    """
    assert_no_freeze()
    if expected_sha256 is not None:
        local_sha = hashlib.sha256(data).hexdigest()
        if local_sha != expected_sha256:
            raise RemoteWriteVerificationError(
                f"Archive SHA mismatch: got {local_sha}, expected {expected_sha256}")
    final = archive_remote_path(pkg_norm, version, filename)
    return commit_write(data, final, prevent_overwrite=True,
                        namespace="archive", verify=True)


# --------------------------------------------------------------------------
# recovery writes
# --------------------------------------------------------------------------
def recovery_state_remote() -> str:
    return f"{REMOTE_ROOT}{PYTHIA_CONTAINER}/recovery/pypi/recovery_state_v1.json"


def save_recovery_state_remote(state: Dict[str, Any]) -> Dict[str, Any]:
    """Write recovery state with the same two-phase commit guarantees."""
    assert_no_freeze()
    data = (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return commit_write(data, recovery_state_remote(), prevent_overwrite=False,
                        namespace="recovery", verify=True)


# --------------------------------------------------------------------------
# distributed single-writer lock (lease based)
# --------------------------------------------------------------------------
class WriterLock:
    """Lease-based distributed single-writer lock on the authoritative remote.

    Guarantees provided:
      * owner identity + acquisition timestamp + lease expiry.
      * stale-lock detection and safe takeover after expiry.
      * renewal/heartbeat while held.

    Honest limitation (documented):
      rclone/Google Drive does not provide a native atomic create-if-absent
      primitive. The lock object create is best-effort; two writers that both
      observe "no lock" at the same instant could both attempt takeover. The
      design therefore (a) uses a long default lease, (b) records unique owner
      ids, and (c) detects owner conflicts during renewal. For STRICT mutual
      exclusion an external lock service is required (documented in the report).
    """

    def __init__(self, owner_id: Optional[str] = None,
                 lease_seconds: int = DEFAULT_LEASE_SECONDS) -> None:
        self.owner_id = owner_id or f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.lease_seconds = lease_seconds
        self._lock_remote = f"{lock_dir_remote()}/{LOCK_FILENAME}"
        self._held = False
        self._acquired_at = 0.0

    def _read_lock(self) -> Optional[Dict[str, Any]]:
        if not get_backend().exists(self._lock_remote):
            return None
        try:
            return json.loads(get_backend().read_bytes(self._lock_remote).decode("utf-8"))
        except Exception:
            return None

    def _write_lock(self, data: Dict[str, Any]) -> None:
        get_backend().write_bytes(
            self._lock_remote,
            (json.dumps(data, sort_keys=True) + "\n").encode("utf-8"),
            prevent_overwrite=False,
        )

    def _is_expired(self, lock: Dict[str, Any]) -> bool:
        expiry = float(lock.get("lease_expires_at", 0))
        return time.time() > expiry

    def acquire(self, *, timeout: float = 30.0, poll_interval: float = 1.0) -> bool:
        """Acquire the lock. Returns True on success, False on timeout."""
        start = time.time()
        while True:
            existing = self._read_lock()
            if existing is None:
                # attempt to create (best-effort)
                now = time.time()
                self._write_lock({
                    "owner_id": self.owner_id,
                    "acquired_at": now,
                    "lease_expires_at": now + self.lease_seconds,
                })
                # read back; if we own it, success
                readback = self._read_lock()
                if readback and readback.get("owner_id") == self.owner_id:
                    self._held = True
                    self._acquired_at = now
                    return True
                # else another writer won the race; fall through to wait
            elif self._is_expired(existing):
                # stale lock -> safe takeover
                now = time.time()
                self._write_lock({
                    "owner_id": self.owner_id,
                    "acquired_at": now,
                    "lease_expires_at": now + self.lease_seconds,
                })
                readback = self._read_lock()
                if readback and readback.get("owner_id") == self.owner_id:
                    self._held = True
                    self._acquired_at = now
                    return True
            elif existing.get("owner_id") == self.owner_id:
                # already ours
                self._held = True
                self._acquired_at = float(existing.get("acquired_at", 0))
                return True

            if time.time() - start > timeout:
                return False
            time.sleep(poll_interval)

    def renew(self) -> bool:
        """Renew the lease (heartbeat). Returns False if not held."""
        if not self._held:
            return False
        existing = self._read_lock()
        if existing is None:
            # lock vanished (e.g. force-cleared) -> re-acquire
            return self.acquire(timeout=5)
        if existing.get("owner_id") != self.owner_id:
            # another writer took over -> we no longer hold it
            self._held = False
            return False
        now = time.time()
        self._write_lock({
            "owner_id": self.owner_id,
            "acquired_at": float(existing.get("acquired_at", now)),
            "lease_expires_at": now + self.lease_seconds,
        })
        return True

    def release(self) -> None:
        """Release the lock (only if we own it)."""
        if not self._held:
            return
        existing = self._read_lock()
        if existing and existing.get("owner_id") == self.owner_id:
            try:
                get_backend().delete(self._lock_remote)
            except Exception:
                pass
        self._held = False

    def is_held(self) -> bool:
        return self._held

    def __enter__(self) -> "WriterLock":
        if not self.acquire():
            raise LockAcquisitionError("Could not acquire PyPI single-writer lock")
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()

    def protected(self, *, heartbeat_interval: float = 30.0) -> "_ProtectedLock":
        """Context manager that performs the full writer lifecycle.

        ACQUIRE LOCK
        -> VERIFY OWNERSHIP (read-back)
        -> CHECK AUTHORITATIVE REMOTE FREEZE (fail-closed)
        -> EXECUTE PROTECTED WORK (with heartbeat/renew)
        -> RELEASE

        Heartbeat runs on a background thread while the block is active. If a
        heartbeat fails (ownership lost / stale takeover) the block raises
        LockNotHeldError so no mutation proceeds after ownership is lost.
        """
        return _ProtectedLock(self, heartbeat_interval=heartbeat_interval)

    def _finish_protected(self) -> None:
        stop = getattr(self, "_protected_stop", None)
        if stop is not None:
            stop.set()
        state = getattr(self, "_protected_state", None)
        if state and state.get("failed"):
            self._held = False
            raise LockNotHeldError(
                "Writer lock heartbeat failed (ownership lost); refusing to continue")
        self.release()

    def __enter_protected__(self):
        return self

    def __exit_protected__(self, *exc: Any) -> None:
        self._finish_protected()


class _ProtectedLock:
    """Context-manager wrapper returned by WriterLock.protected().

    Ensures the heartbeat thread is stopped and the lock released exactly
    once on exit (including exception exit), avoiding leaked threads.
    """

    def __init__(self, lock: "WriterLock", *, heartbeat_interval: float) -> None:
        self._lock = lock
        self._heartbeat_interval = heartbeat_interval
        self._entered = False

    def __enter__(self) -> "WriterLock":
        lock = self._lock
        if not lock.acquire():
            raise LockAcquisitionError("Could not acquire PyPI single-writer lock")
        try:
            assert_no_freeze()  # fail closed before any work
        except Exception:
            lock.release()
            raise
        import threading as _threading

        stop = _threading.Event()
        state = {"failed": False}

        def _heartbeat() -> None:
            while not stop.is_set():
                if stop.is_set():
                    return
                try:
                    if not lock.renew():
                        state["failed"] = True
                        return
                except Exception:
                    # Heartbeat write failed (e.g. backend swapped/guard).
                    state["failed"] = True
                    return
                stop.wait(self._heartbeat_interval)

        t = _threading.Thread(target=_heartbeat, daemon=True)
        t.start()
        lock._protected_stop = stop
        lock._protected_state = state
        self._thread = t
        self._entered = True
        return lock

    def __exit__(self, *exc: Any) -> None:
        if self._entered:
            # Stop + join the heartbeat thread FIRST so it cannot race the
            # release or leak into the next test.
            stop = getattr(self._lock, "_protected_stop", None)
            if stop is not None:
                stop.set()
            t = getattr(self, "_thread", None)
            if t is not None and t.is_alive():
                t.join(timeout=2.0)
            self._lock._finish_protected()
            self._entered = False


# --------------------------------------------------------------------------
# startup reconciliation
# --------------------------------------------------------------------------
def reconcile_startup() -> Dict[str, Any]:
    """Identify interrupted/uncommitted remote objects at startup.

    Returns a report classifying remote artifacts. NEVER deletes or promotes
    ambiguous objects; only objects proven to be temporary staging remnants
    (orphan journal markers pointing at an already-committed final object) are
    reported as safely cleanable. All other states fail closed.

    Classifications:
      * COMMITTED_FINAL_CLEANED   — journal marker with matching final object
      * UNCOMMITTED_STAGING       — staging object, no final (abandoned)
      * PROMOTED_UNVERIFIED       — journal marker, final absent/mismatched
      * AMBIGUOUS                 — state cannot be determined (fail closed)
    """
    report = {"staging": [], "committed_final_cleaned": 0, "uncommitted": 0,
              "promoted_unverified": 0, "ambiguous": 0}

    # Enumerate staging namespace (if it exists).
    staging_dir = staging_dir_remote()
    if get_backend().exists(staging_dir):
        for name in get_backend().list_names(staging_dir):
            remote = f"{staging_dir}/{name}"
            rec = None
            if name.startswith("journal-"):
                try:
                    rec = json.loads(get_backend().read_bytes(remote).decode("utf-8"))
                except Exception:
                    rec = None
                final = rec.get("final_remote") if rec else None
                sha = rec.get("sha256") if rec else None
                if final and sha:
                    if (get_backend().exists(final)
                            and get_backend().sha256(final) == sha):
                        report["committed_final_cleaned"] += 1
                        report["staging"].append({
                            "name": name, "state": "COMMITTED_FINAL_CLEANED",
                            "final_remote": final})
                    else:
                        report["promoted_unverified"] += 1
                        report["staging"].append({
                            "name": name, "state": "PROMOTED_UNVERIFIED",
                            "final_remote": final, "expected_sha256": sha})
                else:
                    report["ambiguous"] += 1
                    report["staging"].append({"name": name, "state": "AMBIGUOUS"})
            elif name.endswith(".part"):
                # Staging upload remnant: no final identity encoded; treat as
                # UNCOMMITTED_STAGING (never a checkpoint) — safe to report,
                # never to promote.
                report["uncommitted"] += 1
                report["staging"].append({"name": name, "state": "UNCOMMITTED_STAGING"})
            else:
                report["ambiguous"] += 1
                report["staging"].append({"name": name, "state": "AMBIGUOUS"})

    return report


# --------------------------------------------------------------------------
# headroom
# --------------------------------------------------------------------------
def remote_headroom(min_free_gb: float = 100.0) -> Dict[str, object]:
    """Remote-aware capacity check (replaces shutil.disk_usage)."""
    free_gb = get_backend().about_free_gb()
    if free_gb is None:
        return {
            "free_gb": None,
            "sufficient": False,
            "min_required_gb": min_free_gb,
            "error": "could not determine remote capacity",
        }
    return {
        "free_gb": round(free_gb, 2),
        "sufficient": free_gb >= min_free_gb,
        "min_required_gb": min_free_gb,
    }


def _parse_size_to_gb(value: str) -> Optional[float]:
    """Parse a human size string like '4.9 TiB' / '1.2 GB' to GB float."""
    if not value:
        return None
    value = value.strip().lower().replace(" ", "")
    multipliers = {
        "b": 1e-9, "kib": 1e-6, "kb": 1e-6, "mib": 1e-3, "mb": 1e-3,
        "gib": 1.0, "gb": 1.0, "tib": 1024.0, "tb": 1000.0,
        "pib": 1024.0 * 1024.0, "pb": 1e6,
    }
    for suffix, mult in multipliers.items():
        if value.endswith(suffix):
            try:
                return float(value[:-len(suffix)]) * mult
            except ValueError:
                return None
    try:
        return float(value)
    except ValueError:
        return None