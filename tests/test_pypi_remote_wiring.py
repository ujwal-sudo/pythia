"""Remote-mode wiring tests for the PyPI pipeline.

These tests load ``scripts.scrapers.pypi`` with ``PYPI_REMOTE_STORAGE=1`` and
run the ACTUAL remote-mode code paths (``get_unprocessed_candidates``,
``_download_file``, ``_iter_checkpoint_paths``, ``_save_checkpoint``,
``reconcile_startup``) against an isolated ``LocalDirBackend`` seeded to
mimic the authoritative frozen state.

They are NOT LocalDirBackend-only shim unit tests: they exercise the pypi.py
branch logic that selects remote routing. They are also NOT live-remote tests:
no bytes are written to ``pythia:Pythia``. Live-remote read-only evidence is
recorded separately (see the preflight report).

Evidence separation:
  * LocalDirBackend tests (this file + test_pypi_storage.py): logic/wiring proof
  * RcloneBackend/live-remote: recorded read-only (lsf/cat/hashsum/about) in
    the control preflight; not required for these tests.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import scripts.scrapers.pypi_storage as storage
from scripts.scrapers.pypi_storage import LocalDirBackend, set_backend


@pytest.fixture(scope="module", autouse=True)
def remote_pypi_module():
    """Load scripts.scrapers.pypi in remote mode as an independent module.

    Uses a unique module name so the shared ``scripts.scrapers.pypi`` module
    (used by other tests in POSIX mode) is never mutated. The environment is
    restored afterwards.
    """
    saved_env = dict(os.environ)
    try:
        os.environ["PYPI_REMOTE_STORAGE"] = "1"
        os.environ["PYTHIA_DATA_ROOT"] = "/mnt/pythia-cloud/Pythia"

        # Reload config so DATA_ROOT reflects the canonical root.
        import config
        config = importlib.reload(config)

        spec = importlib.util.spec_from_file_location(
            "pypi_remote_mode_mod", PROJECT_ROOT / "scripts/scrapers/pypi.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        yield mod
    finally:
        os.environ.clear()
        os.environ.update(saved_env)
        import config
        importlib.reload(config)


@pytest.fixture(autouse=True)
def isolated_backend():
    """Swap the storage backend to an isolated temp dir for each test."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        backend = LocalDirBackend(root)
        prev = storage.get_backend()
        set_backend(backend)
        yield backend
        set_backend(prev)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _seed_manifest(backend, records, name="pypi_acquisition_v1.json"):
    data = json.dumps({"record_count": len(records), "packages": records}).encode()
    backend.write_bytes(
        f"pythia:Pythia/raw/pypi/manifests/{name}", data, prevent_overwrite=False)


def _seed_checkpoint(backend, pkg_norm, state):
    payload = json.dumps({pkg_norm: {"state": state}}).encode()
    backend.write_bytes(
        f"pythia:Pythia/raw/pypi/metadata/{pkg_norm}_checkpoint.json",
        payload, prevent_overwrite=False)


def _make_candidates(n=5000):
    return [{"rank": i + 1, "package": f"c{i+1:04d}", "normalized": f"c{i+1:04d}"}
            for i in range(n)]


# --------------------------------------------------------------------------
# 1. remote checkpoint discovery / read / write
# --------------------------------------------------------------------------
def test_remote_checkpoint_discovery_and_read(remote_pypi_module, isolated_backend):
    _seed_checkpoint(isolated_backend, "c0001", "ACQUIRED")
    _seed_checkpoint(isolated_backend, "c0002", "FAILED")
    paths = remote_pypi_module._iter_checkpoint_paths()
    names = sorted(p.name for p in paths)
    assert names == ["c0001_checkpoint.json", "c0002_checkpoint.json"]
    data = remote_pypi_module._read_checkpoint_content(paths[0])
    assert data.get("c0001", {}).get("state") == "ACQUIRED"


def test_remote_checkpoint_write_via_save(remote_pypi_module, isolated_backend):
    # _save_checkpoint in remote mode routes to save_checkpoint_remote.
    cp = remote_pypi_module.checkpoint_path("zzz")
    remote_pypi_module._save_checkpoint(cp, {"zzz": {"state": "ACQUIRED", "v": "1"}})
    assert isolated_backend.exists(
        "pythia:Pythia/raw/pypi/metadata/zzz_checkpoint.json")
    raw = isolated_backend.read_bytes(
        "pythia:Pythia/raw/pypi/metadata/zzz_checkpoint.json").decode()
    assert json.loads(raw)["zzz"]["state"] == "ACQUIRED"


# --------------------------------------------------------------------------
# 2. remote resume boundary (derived from state, not hardcoded 3048)
# --------------------------------------------------------------------------
def test_remote_resume_boundary_derived_from_state(remote_pypi_module, isolated_backend):
    candidates = _make_candidates(5000)
    # ACQUIRED = ranks 1..2945 ; FAILED = ranks 2946..3047 (102) ; unprocessed 3048..5000
    # Both acquired and failed records have checkpoints (3047 total), matching
    # the authoritative remote state.
    for i in range(1, 2946):
        _seed_checkpoint(isolated_backend, f"c{i:04d}", "ACQUIRED")
    for i in range(2946, 3048):
        _seed_checkpoint(isolated_backend, f"c{i:04d}", "FAILED")
    unprocessed = remote_pypi_module.get_unprocessed_candidates(candidates)
    ranks = sorted(c["rank"] for c in unprocessed)
    assert len(unprocessed) == 1953
    assert ranks[0] == 3048
    assert ranks[-1] == 5000
    # No candidate <=3047 is unprocessed; no candidate >=3048 is processed.
    assert all(r >= 3048 for r in ranks)


def test_remote_failed_skip_uses_backend(remote_pypi_module, isolated_backend):
    # A FAILED checkpoint discovered through the backend must be skipped by
    # the scale-up loop's guard (is_acquired=False, but state==FAILED).
    _seed_checkpoint(isolated_backend, "c0002", "FAILED")
    cp = remote_pypi_module.checkpoint_path("c0002")
    state = remote_pypi_module._load_checkpoint(cp).get("c0002", {}).get("state")
    assert state == "FAILED"
    assert remote_pypi_module.is_acquired("c0002") is False


# --------------------------------------------------------------------------
# 3. remote archive verification / reuse
# --------------------------------------------------------------------------
def test_remote_archive_exists_and_sha(remote_pypi_module, isolated_backend):
    import hashlib
    data = b"archive-bytes"
    sha = hashlib.sha256(data).hexdigest()
    isolated_backend.write_bytes(
        "pythia:Pythia/raw/pypi/packages/pkg/1.0.0/pkg-1.0.0.tar.gz",
        data, prevent_overwrite=False)
    assert remote_pypi_module._archive_exists(
        None, pkg_norm="pkg", version="1.0.0", filename="pkg-1.0.0.tar.gz") is True
    assert remote_pypi_module._archive_sha256_value(
        None, pkg_norm="pkg", version="1.0.0", filename="pkg-1.0.0.tar.gz") == sha


def test_remote_archive_metadata_identity_parsed_remotely(remote_pypi_module, isolated_backend):
    # A tar.gz with PKG-INFO stored ONLY on the remote backend must be parsed
    # through the storage abstraction (no local FUSE dependency).
    import io
    import tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo("PKG-INFO")
        content = b"Metadata-Version: 1.0\nName: demo\nVersion: 3.2.1\n"
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    isolated_backend.write_bytes(
        "pythia:Pythia/raw/pypi/packages/demo/3.2.1/demo-3.2.1.tar.gz",
        buf.getvalue(), prevent_overwrite=False)
    ident = remote_pypi_module._archive_metadata_identity(
        remote_pypi_module.PYPI_PACKAGES_DIR / "demo" / "3.2.1" / "demo-3.2.1.tar.gz")
    assert ident == {"package": "demo", "version": "3.2.1"}


# --------------------------------------------------------------------------
# 4. remote _download_file routes through the storage abstraction
# --------------------------------------------------------------------------
def test_remote_download_file_routes_to_backend(remote_pypi_module, isolated_backend, monkeypatch):
    class FakeResp:
        def __init__(self):
            self.headers = {"content-length": "13"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            yield b"archive-bytes"

    import requests as _requests
    monkeypatch.setattr(_requests, "get", lambda *a, **k: FakeResp())

    dest = remote_pypi_module.PYPI_PACKAGES_DIR / "pkg" / "1.0.0" / "pkg-1.0.0.tar.gz"
    remote_pypi_module._download_file("http://example.invalid/pkg-1.0.0.tar.gz", dest, timeout=30)
    assert isolated_backend.exists(
        "pythia:Pythia/raw/pypi/packages/pkg/1.0.0/pkg-1.0.0.tar.gz")
    assert isolated_backend.read_bytes(
        "pythia:Pythia/raw/pypi/packages/pkg/1.0.0/pkg-1.0.0.tar.gz") == b"archive-bytes"


# --------------------------------------------------------------------------
# 5. remote freeze blocks writes
# --------------------------------------------------------------------------
def test_remote_freeze_blocks_checkpoint_write(remote_pypi_module, isolated_backend):
    isolated_backend.write_bytes(
        "pythia:Pythia/raw/pypi/.FREEZE_SENTINEL", b"frozen", prevent_overwrite=False)
    cp = remote_pypi_module.checkpoint_path("zzz")
    with pytest.raises(Exception):
        remote_pypi_module._save_checkpoint(cp, {"zzz": {"state": "ACQUIRED"}})


# --------------------------------------------------------------------------
# 6. startup reconciliation classifies interrupted objects (fail-closed)
# --------------------------------------------------------------------------
def test_reconcile_startup_classifies_ambiguous(remote_pypi_module, isolated_backend):
    # A journal marker whose final object is absent => PROMOTED_UNVERIFIED (fail closed).
    isolated_backend.write_bytes(
        "pythia:Pythia/raw/pypi/metadata/.staging/journal-dead.json",
        json.dumps({"op": "commit", "namespace": "checkpoint",
                    "final_remote": "pythia:Pythia/raw/pypi/metadata/x_checkpoint.json",
                    "sha256": "0" * 64, "intent": "writing"}).encode(),
        prevent_overwrite=False)
    rec = storage.reconcile_startup()
    assert rec["promoted_unverified"] == 1
    assert rec["ambiguous"] == 0


def test_reconcile_startup_committed_final_clean(remote_pypi_module, isolated_backend):
    import hashlib
    data = json.dumps({"x": {"state": "ACQUIRED"}}).encode()
    sha = hashlib.sha256(data).hexdigest()
    isolated_backend.write_bytes(
        "pythia:Pythia/raw/pypi/metadata/x_checkpoint.json", data, prevent_overwrite=False)
    isolated_backend.write_bytes(
        "pythia:Pythia/raw/pypi/metadata/.staging/journal-ok.json",
        json.dumps({"op": "commit", "namespace": "checkpoint",
                    "final_remote": "pythia:Pythia/raw/pypi/metadata/x_checkpoint.json",
                    "sha256": sha, "intent": "writing"}).encode(),
        prevent_overwrite=False)
    rec = storage.reconcile_startup()
    assert rec["committed_final_cleaned"] == 1


# --------------------------------------------------------------------------
# 7. WriterLock protected lifecycle (heartbeat + fail-closed on ownership loss)
# --------------------------------------------------------------------------
def test_writerlock_protected_heartbeat_and_release(remote_pypi_module, isolated_backend):
    lock = storage.WriterLock(owner_id="wiring-test", lease_seconds=60)
    with lock.protected(heartbeat_interval=0.05):
        assert lock.is_held()
        assert lock.renew()
    assert not lock.is_held()


def test_writerlock_ownership_loss_fails_closed(remote_pypi_module, isolated_backend):
    import time
    lock_a = storage.WriterLock(owner_id="owner-a", lease_seconds=600)
    assert lock_a.acquire()
    # owner-b force-takes the lock (simulate stale takeover by another writer)
    isolated_backend.write_bytes(
        storage.lock_dir_remote() + "/writer.lock",
        json.dumps({"owner_id": "owner-b", "acquired_at": time.time(),
                    "lease_expires_at": time.time() + 600}).encode(),
        prevent_overwrite=False)
    assert lock_a.renew() is False
    assert lock_a.is_held() is False