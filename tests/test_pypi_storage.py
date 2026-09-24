"""Tests for the PyPI remote storage abstraction (pypi_storage).

These tests use the isolated LocalDirBackend so that write-path semantics
can be validated deterministically WITHOUT performing any real PyPI writes
to pythia:Pythia. No remote data is touched.
"""
from __future__ import annotations

import json
import os
import sys
import time
import tempfile
import unittest
import hashlib
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

import scripts.scrapers.pypi_storage as storage
from scripts.scrapers.pypi_storage import (
    LocalDirBackend,
    WriterLock,
    commit_write,
    freeze_sentinel_exists,
    freeze_sentinel_remote,
    map_local_path_to_remote,
    remote_headroom,
    save_archive_remote,
    save_checkpoint_remote,
    save_manifest_remote,
    set_backend,
)


class StorageTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._root = Path(self._tmp.name)
        self._backend = LocalDirBackend(self._root)
        self._prev_backend = storage.get_backend()
        set_backend(self._backend)

    def tearDown(self) -> None:
        set_backend(self._prev_backend)
        self._tmp.cleanup()

    # helpers -------------------------------------------------------------
    def _write_freeze(self) -> None:
        self._backend.write_bytes(freeze_sentinel_remote(), b"frozen",
                                  prevent_overwrite=False)

    def _clear_freeze(self) -> None:
        if self._backend.exists(freeze_sentinel_remote()):
            self._backend.delete(freeze_sentinel_remote())


# --------------------------------------------------------------------------
# 1. canonical path mapping
# --------------------------------------------------------------------------
class TestPathMapping(StorageTestBase):
    def test_canonical_root_maps_to_pythia(self):
        root = storage.canonical_pypi_root()
        self.assertEqual(str(root), "/mnt/pythia-cloud/Pythia/raw/pypi")

    def test_canonical_path_mapping(self):
        self.assertEqual(
            map_local_path_to_remote("/mnt/pythia-cloud/Pythia/raw/pypi/metadata/x_checkpoint.json"),
            "pythia:Pythia/raw/pypi/metadata/x_checkpoint.json",
        )

    def test_legacy_root_normalized_to_pythia(self):
        # The legacy config root (/mnt/pythia-cloud/raw/pypi) must be
        # normalized into the canonical remote layout (WITH Pythia container).
        self.assertEqual(
            map_local_path_to_remote("/mnt/pythia-cloud/raw/pypi/manifests/pypi_candidates_v1.jsonl"),
            "pythia:Pythia/raw/pypi/manifests/pypi_candidates_v1.jsonl",
        )

    def test_already_remote_unchanged(self):
        self.assertEqual(
            map_local_path_to_remote("pythia:Pythia/raw/pypi/metadata/a.json"),
            "pythia:Pythia/raw/pypi/metadata/a.json",
        )

    def test_wrong_root_rejected(self):
        with self.assertRaises(storage.RemotePathMappingError):
            map_local_path_to_remote("/home/user/data/raw/pypi/x.json")

    def test_session4_path_rejected(self):
        with self.assertRaises(storage.RemotePathMappingError):
            map_local_path_to_remote("/mnt/pythia-cloud/Pythia/raw/github/manifests/github_candidates_v1.jsonl")
        with self.assertRaises(storage.RemotePathMappingError):
            map_local_path_to_remote("pythia:Pythia/raw/github/x")


# --------------------------------------------------------------------------
# 2. freeze blocks write
# --------------------------------------------------------------------------
class TestFreeze(StorageTestBase):
    def test_freeze_sentinel_detected(self):
        self._write_freeze()
        self.assertTrue(freeze_sentinel_exists())

    def test_no_freeze_when_absent(self):
        self.assertFalse(freeze_sentinel_exists())

    def test_assert_no_freeze_raises(self):
        self._write_freeze()
        with self.assertRaises(storage.FreezeError):
            storage.assert_no_freeze()

    def test_checkpoint_write_blocked_by_freeze(self):
        self._write_freeze()
        with self.assertRaises(storage.FreezeError):
            save_checkpoint_remote("pkg", {"pkg": {"state": "ACQUIRED"}})

    def test_archive_write_blocked_by_freeze(self):
        self._write_freeze()
        with self.assertRaises(storage.FreezeError):
            save_archive_remote(b"data", "pkg", "1.0.0", "pkg-1.0.0.tar.gz")

    def test_manifest_write_blocked_by_freeze(self):
        self._write_freeze()
        with self.assertRaises(storage.FreezeError):
            save_manifest_remote("manifest.jsonl", [])


# --------------------------------------------------------------------------
# 3. checkpoint writes
# --------------------------------------------------------------------------
class TestCheckpointWrites(StorageTestBase):
    def test_successful_commit(self):
        res = save_checkpoint_remote("pkg", {"pkg": {"state": "ACQUIRED", "v": "1.0"}})
        self.assertTrue(res["committed"])
        self.assertTrue(self._backend.exists("pythia:Pythia/raw/pypi/metadata/pkg_checkpoint.json"))

    def test_existing_checkpoint_cannot_overwrite(self):
        save_checkpoint_remote("pkg", {"pkg": {"state": "ACQUIRED"}})
        with self.assertRaises(storage.RemoteOverwriteError):
            save_checkpoint_remote("pkg", {"pkg": {"state": "ACQUIRED"}})

    def test_allow_overwrite_flag(self):
        save_checkpoint_remote("pkg", {"pkg": {"state": "ACQUIRED"}})
        res = save_checkpoint_remote("pkg", {"pkg": {"state": "ACQUIRED"}}, allow_overwrite=True)
        self.assertTrue(res["committed"])

    def test_interrupted_upload_no_commit(self):
        # Simulate staging write succeeding but final promote failing:
        # force the backend to raise on the final write.
        orig = self._backend.write_bytes

        def fail_final(remote, data, *, prevent_overwrite=True):
            if "checkpoint.json" in remote:
                raise storage.StorageBackendError("simulated upload failure")
            return orig(remote, data, prevent_overwrite=prevent_overwrite)

        self._backend.write_bytes = fail_final  # type: ignore[method-assign]
        with self.assertRaises(storage.StorageBackendError):
            save_checkpoint_remote("pkg", {"pkg": {"state": "ACQUIRED"}})
        # No final checkpoint object exists.
        self.assertFalse(self._backend.exists("pythia:Pythia/raw/pypi/metadata/pkg_checkpoint.json"))

    def test_partial_object_ignored(self):
        # Write a torn object directly to the final name (simulating a bad
        # leftover); a subsequent commit_write must refuse to overwrite it.
        self._backend.write_bytes(
            "pythia:Pythia/raw/pypi/metadata/pkg_checkpoint.json",
            b"{broken", prevent_overwrite=False)
        with self.assertRaises(storage.RemoteOverwriteError):
            save_checkpoint_remote("pkg", {"pkg": {"state": "ACQUIRED"}})

    def test_sha_mismatch_causes_failure(self):
        # expected_sha is checked in save_archive_remote (identity gate).
        with self.assertRaises(storage.RemoteWriteVerificationError):
            save_archive_remote(
                b"data", "pkg", "1.0", "pkg-1.0.tar.gz",
                expected_sha256="0" * 64)


# --------------------------------------------------------------------------
# 4. manifest writes
# --------------------------------------------------------------------------
class TestManifestWrites(StorageTestBase):
    def test_manifest_commit_and_record_count(self):
        save_manifest_remote("candidates.jsonl", [{"rank": 1, "package": "a"}])
        text = self._backend.read_bytes("pythia:Pythia/raw/pypi/manifests/candidates.jsonl").decode()
        self.assertTrue(text.startswith("#record_count=1\n"))

    def test_concurrent_manifest_writer_uses_commit_protocol(self):
        # A manifest rewrite is allowed (resumability) but must go through
        # the two-phase commit so the final object is never torn and its
        # record_count integrity is verified.
        save_manifest_remote("candidates.jsonl", [{"rank": 1}])
        save_manifest_remote("candidates.jsonl", [{"rank": 1}, {"rank": 2}])
        text = self._backend.read_bytes(
            "pythia:Pythia/raw/pypi/manifests/candidates.jsonl").decode()
        self.assertTrue(text.startswith("#record_count=2\n"))


# --------------------------------------------------------------------------
# 5. archive writes
# --------------------------------------------------------------------------
class TestArchiveWrites(StorageTestBase):
    def test_archive_successful(self):
        data = b"archive-bytes"
        res = save_archive_remote(data, "pkg", "1.0.0", "pkg-1.0.0.tar.gz")
        self.assertTrue(res["committed"])
        self.assertTrue(self._backend.exists(
            "pythia:Pythia/raw/pypi/packages/pkg/1.0.0/pkg-1.0.0.tar.gz"))

    def test_archive_no_silent_overwrite(self):
        save_archive_remote(b"a", "pkg", "1.0.0", "pkg-1.0.0.tar.gz")
        with self.assertRaises(storage.RemoteOverwriteError):
            save_archive_remote(b"b", "pkg", "1.0.0", "pkg-1.0.0.tar.gz")

    def test_archive_upload_failure(self):
        orig = self._backend.write_bytes

        def fail(remote, data, *, prevent_overwrite=True):
            if "packages/pkg" in remote:
                raise storage.StorageBackendError("upload failed")
            return orig(remote, data, prevent_overwrite=prevent_overwrite)

        self._backend.write_bytes = fail  # type: ignore[method-assign]
        with self.assertRaises(storage.StorageBackendError):
            save_archive_remote(b"a", "pkg", "1.0.0", "pkg-1.0.0.tar.gz")
        self.assertFalse(self._backend.exists(
            "pythia:Pythia/raw/pypi/packages/pkg/1.0.0/pkg-1.0.0.tar.gz"))


# --------------------------------------------------------------------------
# 6. read-after-write / verify
# --------------------------------------------------------------------------
class TestReadAfterWrite(StorageTestBase):
    def test_verify_remote_object_match(self):
        remote = "pythia:Pythia/raw/pypi/metadata/x_checkpoint.json"
        data = b"hello"
        self._backend.write_bytes(remote, data, prevent_overwrite=False)
        self.assertTrue(storage.verify_remote_object(
            remote, "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"))

    def test_verify_remote_object_mismatch(self):
        remote = "pythia:Pythia/raw/pypi/metadata/x_checkpoint.json"
        self._backend.write_bytes(remote, b"hello", prevent_overwrite=False)
        self.assertFalse(storage.verify_remote_object(remote, "0" * 64, retries=1))

    def test_remote_missing_after_upload_detected(self):
        # A commit_write whose final object vanishes (simulated) fails closed.
        remote = "pythia:Pythia/raw/pypi/metadata/z_checkpoint.json"
        orig_verify = storage.verify_remote_object

        def vanish(*args, **kwargs):
            return False  # never verifies

        storage.verify_remote_object = vanish  # type: ignore[assignment]
        try:
            with self.assertRaises(storage.RemoteWriteVerificationError):
                commit_write(b"x", remote, namespace="checkpoint")
        finally:
            storage.verify_remote_object = orig_verify


# --------------------------------------------------------------------------
# 7. stale temporary object
# --------------------------------------------------------------------------
class TestStaleTemporary(StorageTestBase):
    def test_staging_objects_never_authoritative(self):
        # A leftover .part staging object must not be readable as a checkpoint.
        self._backend.write_bytes(
            "pythia:Pythia/raw/pypi/metadata/.staging/checkpoint-deadbeef.part",
            b"{garbage}", prevent_overwrite=False)
        self.assertFalse(self._backend.exists(
            "pythia:Pythia/raw/pypi/metadata/stale_checkpoint.json"))


# --------------------------------------------------------------------------
# 8. distributed lock
# --------------------------------------------------------------------------
class TestWriterLock(StorageTestBase):
    def test_acquire_and_release(self):
        lock = WriterLock(owner_id="owner-a")
        self.assertTrue(lock.acquire())
        self.assertTrue(lock.is_held())
        lock.release()
        self.assertFalse(lock.is_held())

    def test_active_lease_prevents_second_writer(self):
        lock_a = WriterLock(owner_id="owner-a", lease_seconds=600)
        self.assertTrue(lock_a.acquire())
        lock_b = WriterLock(owner_id="owner-b", lease_seconds=600)
        # Same instant -> second writer cannot acquire (lock not expired).
        self.assertFalse(lock_b.acquire(timeout=0.2, poll_interval=0.05))

    def test_expired_lock_takeover(self):
        lock_a = WriterLock(owner_id="owner-a", lease_seconds=1)
        self.assertTrue(lock_a.acquire())
        # Force expiry by writing an expired lock directly.
        self._backend.write_bytes(
            storage.lock_dir_remote() + "/writer.lock",
            json.dumps({"owner_id": "owner-a", "acquired_at": 0,
                        "lease_expires_at": time.time() - 100}).encode(),
            prevent_overwrite=False)
        lock_b = WriterLock(owner_id="owner-b", lease_seconds=600)
        self.assertTrue(lock_b.acquire(timeout=0.5, poll_interval=0.05))

    def test_duplicate_writer_same_owner_ok(self):
        lock_a = WriterLock(owner_id="same", lease_seconds=600)
        self.assertTrue(lock_a.acquire())
        lock_b = WriterLock(owner_id="same", lease_seconds=600)
        self.assertTrue(lock_b.acquire())  # same owner already holds

    def test_heartbeat_renew(self):
        lock = WriterLock(owner_id="owner-a", lease_seconds=600)
        self.assertTrue(lock.acquire())
        self.assertTrue(lock.renew())
        # readback shows renewed lease
        data = json.loads(self._backend.read_bytes(
            storage.lock_dir_remote() + "/writer.lock").decode())
        self.assertGreater(float(data["lease_expires_at"]), time.time())

    def test_heartbeat_failure_when_stolen(self):
        lock_a = WriterLock(owner_id="owner-a", lease_seconds=600)
        self.assertTrue(lock_a.acquire())
        # owner-b force-takes the lock
        self._backend.write_bytes(
            storage.lock_dir_remote() + "/writer.lock",
            json.dumps({"owner_id": "owner-b", "acquired_at": time.time(),
                        "lease_expires_at": time.time() + 600}).encode(),
            prevent_overwrite=False)
        self.assertFalse(lock_a.renew())

    def test_stale_lock_recovery(self):
        # A lock with an expired lease can be safely taken over.
        self._backend.write_bytes(
            storage.lock_dir_remote() + "/writer.lock",
            json.dumps({"owner_id": "dead-writer", "acquired_at": 0,
                        "lease_expires_at": time.time() - 1000}).encode(),
            prevent_overwrite=False)
        lock = WriterLock(owner_id="new-writer", lease_seconds=600)
        self.assertTrue(lock.acquire(timeout=0.5, poll_interval=0.05))


# --------------------------------------------------------------------------
# 9. headroom
# --------------------------------------------------------------------------
class TestHeadroom(StorageTestBase):
    def test_headroom_remote_aware(self):
        result = remote_headroom(min_free_gb=10.0)
        self.assertTrue(result["sufficient"])
        self.assertIsNotNone(result["free_gb"])

    def test_headroom_failure(self):
        # Swap in a backend whose about returns None.
        class NoHeadroomBackend(LocalDirBackend):
            def about_free_gb(self):
                return None

        set_backend(NoHeadroomBackend(self._root))
        result = remote_headroom(min_free_gb=10.0)
        self.assertFalse(result["sufficient"])
        self.assertIsNone(result["free_gb"])


# --------------------------------------------------------------------------
# 10. resume + immutability + session4 isolation
# --------------------------------------------------------------------------
class TestResumeAndIsolation(StorageTestBase):
    def test_resume_after_successful_commit(self):
        # Commit one checkpoint, then "resume" by reading it back and
        # committing the next — the first remains immutable.
        save_checkpoint_remote("a", {"a": {"state": "ACQUIRED"}})
        save_checkpoint_remote("b", {"b": {"state": "ACQUIRED"}})
        a = json.loads(self._backend.read_bytes(
            "pythia:Pythia/raw/pypi/metadata/a_checkpoint.json").decode())
        b = json.loads(self._backend.read_bytes(
            "pythia:Pythia/raw/pypi/metadata/b_checkpoint.json").decode())
        self.assertEqual(a["a"]["state"], "ACQUIRED")
        self.assertEqual(b["b"]["state"], "ACQUIRED")

    def test_historical_checkpoint_immutability(self):
        save_checkpoint_remote("hist", {"hist": {"state": "ACQUIRED"}})
        orig = self._backend.read_bytes(
            "pythia:Pythia/raw/pypi/metadata/hist_checkpoint.json")
        # Another write of the same name must fail (no silent overwrite).
        with self.assertRaises(storage.RemoteOverwriteError):
            save_checkpoint_remote("hist", {"hist": {"state": "FAILED"}})
        self.assertEqual(self._backend.read_bytes(
            "pythia:Pythia/raw/pypi/metadata/hist_checkpoint.json"), orig)

    def test_session4_path_isolation(self):
        # The storage shim must never map Session 4 github paths.
        from scripts.scrapers.pypi_storage import is_session4_path
        self.assertTrue(is_session4_path("/mnt/pythia-cloud/Pythia/raw/github"))
        self.assertTrue(is_session4_path("pythia:Pythia/raw/github/repo/sha"))
        self.assertFalse(is_session4_path("/mnt/pythia-cloud/Pythia/raw/pypi"))


# --------------------------------------------------------------------------
# 11. recovery path mapping
# --------------------------------------------------------------------------
class TestRecoveryPathMapping(StorageTestBase):
    def test_recovery_state_path_maps(self):
        self.assertEqual(
            map_local_path_to_remote("/mnt/pythia-cloud/Pythia/recovery/pypi/recovery_state_v1.json"),
            "pythia:Pythia/recovery/pypi/recovery_state_v1.json",
        )

    def test_recovery_archives_path_maps(self):
        self.assertEqual(
            map_local_path_to_remote("/mnt/pythia-cloud/Pythia/recovery/pypi/archives/x/1.0/x-1.0.tar.gz"),
            "pythia:Pythia/recovery/pypi/archives/x/1.0/x-1.0.tar.gz",
        )


# --------------------------------------------------------------------------
# 12. commit journal / crash reconciliation
# --------------------------------------------------------------------------
class TestCommitJournal(StorageTestBase):
    def test_journal_marker_written_and_cleaned(self):
        remote = "pythia:Pythia/raw/pypi/metadata/j_checkpoint.json"
        storage.commit_write(b"{}", remote, namespace="checkpoint", journal=True)
        # After successful commit the marker is removed.
        markers = storage.find_interrupted_commits()
        self.assertEqual([m for m in markers if m.get("final_remote") == remote], [])
        # final object exists
        self.assertTrue(self._backend.exists(remote))

    def test_interrupted_commit_leaves_marker(self):
        # Simulate: write a journal marker + staging, then fail before final.
        remote = "pythia:Pythia/raw/pypi/metadata/j2_checkpoint.json"
        staging = storage.staging_dir_remote() + "/journal-deadbeef.json"
        self._backend.write_bytes(
            staging,
            json.dumps({"op": "commit", "namespace": "checkpoint",
                        "final_remote": remote, "sha256": "0" * 64,
                        "intent": "writing"}).encode(),
            prevent_overwrite=False)
        markers = storage.find_interrupted_commits()
        self.assertTrue(any(m.get("final_remote") == remote for m in markers))
        # Final object must NOT be present (never committed).
        self.assertFalse(self._backend.exists(remote))


# --------------------------------------------------------------------------
# 13. startup reconciliation
# --------------------------------------------------------------------------
class TestStartupReconciliation(StorageTestBase):
    def test_committed_final_cleaned(self):
        # Journal marker whose final object exists + SHA matches.
        final = "pythia:Pythia/raw/pypi/metadata/rc_checkpoint.json"
        data = b'{"rc": {"state": "ACQUIRED"}}'
        self._backend.write_bytes(final, data, prevent_overwrite=False)
        sha = storage.remote_sha256(final)
        marker = storage.staging_dir_remote() + "/journal-abc.json"
        self._backend.write_bytes(
            marker,
            json.dumps({"op": "commit", "namespace": "checkpoint",
                        "final_remote": final, "sha256": sha,
                        "intent": "writing"}).encode(),
            prevent_overwrite=False)
        report = storage.reconcile_startup()
        self.assertEqual(report["committed_final_cleaned"], 1)

    def test_promoted_unverified_detected(self):
        # Journal marker whose final is absent -> promoted but unverified.
        final = "pythia:Pythia/raw/pypi/metadata/rc2_checkpoint.json"
        marker = storage.staging_dir_remote() + "/journal-def.json"
        self._backend.write_bytes(
            marker,
            json.dumps({"op": "commit", "namespace": "checkpoint",
                        "final_remote": final, "sha256": "0" * 64,
                        "intent": "writing"}).encode(),
            prevent_overwrite=False)
        report = storage.reconcile_startup()
        self.assertEqual(report["promoted_unverified"], 1)

    def test_uncommitted_staging_never_checkpoint(self):
        # A .part staging object must never appear as a checkpoint.
        self._backend.write_bytes(
            storage.staging_dir_remote() + "/checkpoint-x.part",
            b"{partial", prevent_overwrite=False)
        report = storage.reconcile_startup()
        self.assertEqual(report["uncommitted"], 1)
        # remote_checkpoint_names must not include it
        self.assertEqual(storage.remote_checkpoint_names(), [])

    def test_ambiguous_fails_closed(self):
        # A staging object that is neither a journal nor a .part is ambiguous.
        self._backend.write_bytes(
            storage.staging_dir_remote() + "/unknown-blob",
            b"???", prevent_overwrite=False)
        report = storage.reconcile_startup()
        self.assertEqual(report["ambiguous"], 1)


# --------------------------------------------------------------------------
# 14. WriterLock protected lifecycle
# --------------------------------------------------------------------------
class TestWriterLockProtected(StorageTestBase):
    def test_protected_acquire_freeze_release(self):
        lock = WriterLock(owner_id="prot-a", lease_seconds=600)
        with lock.protected(heartbeat_interval=600) as pl:
            self.assertTrue(pl.is_held())
        self.assertFalse(lock.is_held())

    def test_protected_blocks_when_frozen(self):
        self._write_freeze()
        lock = WriterLock(owner_id="prot-b", lease_seconds=600)
        with self.assertRaises(storage.FreezeError):
            with lock.protected(heartbeat_interval=600):
                pass  # pragma: no cover

    def test_lock_blocks_second_writer(self):
        lock_a = WriterLock(owner_id="w-a", lease_seconds=600)
        self.assertTrue(lock_a.acquire())
        lock_b = WriterLock(owner_id="w-b", lease_seconds=600)
        self.assertFalse(lock_b.acquire(timeout=0.2, poll_interval=0.05))

    def test_lock_release_after_takeover(self):
        lock_a = WriterLock(owner_id="w-a", lease_seconds=1)
        self.assertTrue(lock_a.acquire())
        # force expiry, then b takes over
        self._backend.write_bytes(
            storage.lock_dir_remote() + "/writer.lock",
            json.dumps({"owner_id": "w-a", "acquired_at": 0,
                        "lease_expires_at": time.time() - 100}).encode(),
            prevent_overwrite=False)
        lock_b = WriterLock(owner_id="w-b", lease_seconds=600)
        self.assertTrue(lock_b.acquire(timeout=0.5, poll_interval=0.05))
        # a's renew now fails (ownership lost)
        self.assertFalse(lock_a.renew())


# --------------------------------------------------------------------------
# 15. remote discovery + resume-boundary safety
# --------------------------------------------------------------------------
class TestRemoteDiscoveryAndResume(StorageTestBase):
    def test_remote_checkpoint_listing(self):
        save_checkpoint_remote("a", {"a": {"state": "ACQUIRED"}})
        save_checkpoint_remote("b", {"b": {"state": "FAILED"}})
        names = storage.remote_checkpoint_names()
        self.assertEqual(sorted(names),
                         ["a_checkpoint.json", "b_checkpoint.json"])

    def test_absent_checkpoint_unprocessed(self):
        # No checkpoint exists -> unprocessed.
        self.assertIsNone(storage.remote_load_checkpoint("nonexistent"))

    def test_failed_checkpoint_processed(self):
        save_checkpoint_remote("f", {"f": {"state": "FAILED"}})
        rec = storage.remote_load_checkpoint("f")
        self.assertEqual(rec["state"], "FAILED")

    def test_staging_object_not_a_checkpoint(self):
        self._backend.write_bytes(
            storage.staging_dir_remote() + "/checkpoint-stale.part",
            b"{garbage}", prevent_overwrite=False)
        # remote discovery must ignore staging entirely
        self.assertEqual(storage.remote_checkpoint_names(), [])

    def test_uncommitted_object_not_a_checkpoint(self):
        # A partial object in the final name namespace (not a journal) is not
        # discoverable as a checkpoint because it lacks the _checkpoint suffix
        # pattern handled by remote_checkpoint_names; assert it is excluded.
        self._backend.write_bytes(
            "pythia:Pythia/raw/pypi/metadata/zz.part",
            b"{partial}", prevent_overwrite=False)
        names = storage.remote_checkpoint_names()
        self.assertNotIn("zz.part", names)

    def test_historical_checkpoint_immutable(self):
        save_checkpoint_remote("h", {"h": {"state": "ACQUIRED"}})
        orig = self._backend.read_bytes(
            "pythia:Pythia/raw/pypi/metadata/h_checkpoint.json")
        with self.assertRaises(storage.RemoteOverwriteError):
            save_checkpoint_remote("h", {"h": {"state": "FAILED"}})
        self.assertEqual(self._backend.read_bytes(
            "pythia:Pythia/raw/pypi/metadata/h_checkpoint.json"), orig)

    def test_archive_remote_existence_and_sha(self):
        data = b"archive"
        save_archive_remote(data, "pkg", "1.0", "pkg-1.0.tar.gz")
        self.assertTrue(storage.remote_archive_exists("pkg", "1.0", "pkg-1.0.tar.gz"))
        sha = storage.remote_archive_sha256("pkg", "1.0", "pkg-1.0.tar.gz")
        self.assertIsNotNone(sha)
        self.assertEqual(sha, hashlib.sha256(data).hexdigest())


# --------------------------------------------------------------------------
# 16. write-guard (real-remote writes refused in tests)
# --------------------------------------------------------------------------
class TestWriteGuard(StorageTestBase):
    def test_real_backend_write_refused(self):
        # Force the real RcloneBackend; a write must be refused unless the
        # allow-remote-write env is explicitly set.
        import scripts.scrapers.pypi_storage as _s
        prev = _s.get_backend()
        try:
            _s.set_backend(_s.RcloneBackend())
            _s._ALLOW_REMOTE_WRITE = False
            # commit_write does not pre-check freeze; it must be refused by
            # the write guard before any remote mutation.
            with self.assertRaises(storage.StorageBackendError):
                _s.commit_write(b"data", "pythia:Pythia/raw/pypi/metadata/guard_checkpoint.json",
                                namespace="checkpoint")
        finally:
            _s._ALLOW_REMOTE_WRITE = False
            _s.set_backend(prev)


if __name__ == "__main__":
    unittest.main()