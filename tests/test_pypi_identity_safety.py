"""Regression tests for the PyPI version-identity safety fix.

These tests are fully offline and deterministic. They reproduce the
confirmed acquisition failure class (version-selection / labeling bug)
and prove the new identity gate rejects wrong-version artifacts even
when the SHA matches, and rejects unsafe cache reuse.

Frozen evidence referenced (read-only, never mutated):
  data/frozen/pypi_version_forensic_evidence_v1.json
"""

import hashlib
import io
import os
import sys
import tarfile
import tempfile
from pathlib import Path

import pytest

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from scripts.scrapers.pypi import (
    parse_version_from_filename,
    _archive_metadata_identity,
    verify_archive_identity,
)


# --------------------------------------------------------------------- helpers
def _make_targz(inner_files, name="pkg", version="1.0.0"):
    """Create a deterministic tar.gz containing the given files.

    inner_files: list of (relative_path, bytes). A PKG-INFO entry is
    auto-added when the caller does not supply one.
    """
    has_pkginfo = any(p.endswith("PKG-INFO") for p, _ in inner_files)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        if not has_pkginfo:
            pkginfo = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n".encode()
            info = tarfile.TarInfo(name=f"{name}-{version}/PKG-INFO")
            info.size = len(pkginfo)
            tf.addfile(info, io.BytesIO(pkginfo))
        for rel, data in inner_files:
            info = tarfile.TarInfo(name=rel)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return buf.read()


@pytest.fixture
def tmp_archive(tmp_path):
    """Yield a tempdir and a function to write a tar.gz returning its Path."""
    def _write(data_bytes, fname="artifact.tar.gz"):
        p = tmp_path / fname
        p.write_bytes(data_bytes)
        return p
    return _write


# --------------------------------------------------------------- unit: parsing
def test_parse_version_from_filename_standard():
    assert parse_version_from_filename("absl-py-0.1.0.tar.gz") == "0.1.0"
    assert parse_version_from_filename("encutils-1.0.0.tar.gz") == "1.0.0"
    assert parse_version_from_filename("Events-0.1.0.tar.gz") == "0.1.0"


def test_parse_version_from_filename_missing():
    assert parse_version_from_filename("") is None
    assert parse_version_from_filename("not-a-version.tar.gz") is None


# ------------------------------------------------------------ archive metadata
def test_archive_metadata_identity_reads_pkginfo(tmp_archive):
    data = _make_targz([], name="demo", version="3.2.1")
    p = tmp_archive(data)
    ident = _archive_metadata_identity(p)
    assert ident["package"] == "demo"
    assert ident["version"] == "3.2.1"


def test_archive_metadata_identity_missing_file(tmp_path):
    ident = _archive_metadata_identity(tmp_path / "nope.tar.gz")
    assert ident["package"] is None
    assert ident["version"] is None


# -------------------------------------------------------------------- CASE A
# absl-py-style mismatch: requested 2.5.0, archive is 0.1.0 (filename + PKG-INFO).
def test_case_a_absl_py_style_mismatch_is_rejected(tmp_archive):
    data = _make_targz([], name="absl-py", version="0.1.0")
    p = tmp_archive(data, "absl-py-0.1.0.tar.gz")
    meta = {"version": "2.5.0", "archive_filename": "absl-py-0.1.0.tar.gz", "archive_sha256": None}
    r = verify_archive_identity("absl-py", "2.5.0", meta, p)
    assert r["ok"] is False
    assert r["status"] in ("REJECT", "QUARANTINE")
    assert "mismatch" in r["reason"]


# -------------------------------------------------------------------- CASE B
# matching control: encutils 1.0.0 must be accepted.
def test_case_b_encutils_control_is_accepted(tmp_archive):
    data = _make_targz([], name="encutils", version="1.0.0")
    p = tmp_archive(data, "encutils-1.0.0.tar.gz")
    meta = {"version": "1.0.0", "archive_filename": "encutils-1.0.0.tar.gz", "archive_sha256": None}
    r = verify_archive_identity("encutils", "1.0.0", meta, p)
    assert r["ok"] is True
    assert r["status"] == "ACCEPT"


# -------------------------------------------------------------------- CASE C
# SHA-only false positive: expected SHA == observed SHA, but requested version
# disagrees with the archive version. Must be REJECTED.
def test_case_c_sha_match_but_wrong_version_is_rejected(tmp_archive):
    data = _make_targz([], name="foo", version="0.1.0")
    p = tmp_archive(data, "foo-0.1.0.tar.gz")
    # The observed SHA is the hash of the *wrong* (0.1.0) archive.
    observed_sha = hashlib.sha256(data).hexdigest()
    meta = {
        "version": "2.0.0",  # label claims 2.0.0
        "archive_filename": "foo-0.1.0.tar.gz",  # but file is 0.1.0
        "archive_sha256": observed_sha,  # SHA matches the downloaded file
    }
    r = verify_archive_identity("foo", "2.0.0", meta, p, expected_sha256=observed_sha)
    assert r["ok"] is False
    assert r["status"] == "REJECT"
    # The SHA was verified to match, yet identity still rejected.
    assert r.get("sha_verified") is True
    assert r["reason"] == "filename_version_mismatch"


# -------------------------------------------------------------------- CASE D
# cache false positive: existing cached archive is the wrong version (SHA matches
# itself). Requested version differs. Must NOT be reused.
def test_case_d_cache_wrong_version_not_reused(tmp_archive):
    cached = _make_targz([], name="bar", version="0.1.0")
    p = tmp_archive(cached, "bar-0.1.0.tar.gz")
    cached_sha = hashlib.sha256(cached).hexdigest()
    meta = {
        "version": "5.0.0",
        "archive_filename": "bar-0.1.0.tar.gz",
        "archive_sha256": cached_sha,
    }
    r = verify_archive_identity("bar", "5.0.0", meta, p, expected_sha256=cached_sha)
    assert r["ok"] is False
    assert r["status"] == "REJECT"
    assert r["reason"] == "filename_version_mismatch"


# -------------------------------------------------------------------- CASE E
# missing metadata: archive cannot expose package/version. Without an expected
# SHA, identity cannot be proven -> DO NOT mark ACQUIRED.
def test_case_e_missing_metadata_not_acquired(tmp_archive):
    # tar.gz with ONLY a README (no PKG-INFO, no METADATA).
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        readme = b"hello"
        info = tarfile.TarInfo(name="README.txt")
        info.size = len(readme)
        tf.addfile(info, io.BytesIO(readme))
    buf.seek(0)
    p = tmp_archive(buf.read(), "mystery.tar.gz")
    ident = _archive_metadata_identity(p)
    assert ident["package"] is None
    assert ident["version"] is None
    meta = {"version": "9.9.9", "archive_filename": "mystery.tar.gz", "archive_sha256": None}
    r = verify_archive_identity("mystery", "9.9.9", meta, p)
    # No SHA and no internal metadata => identity unprovable => not ACCEPTED.
    assert r["ok"] is False
    assert r["status"] == "QUARANTINE"


# ------------------------------------------------------------------ determinism
def test_determinism_repeat_same_input_same_result(tmp_archive):
    data = _make_targz([], name="demo", version="1.0.0")
    p = tmp_archive(data, "demo-1.0.0.tar.gz")
    meta = {"version": "1.0.0", "archive_filename": "demo-1.0.0.tar.gz", "archive_sha256": None}
    results = [verify_archive_identity("demo", "1.0.0", meta, p) for _ in range(5)]
    assert all(r["status"] == "ACCEPT" for r in results)
    assert len({r["reason"] for r in results}) == 1


def test_determinism_wrong_version_stable(tmp_archive):
    data = _make_targz([], name="demo", version="0.1.0")
    p = tmp_archive(data, "demo-0.1.0.tar.gz")
    meta = {"version": "9.9.9", "archive_filename": "demo-0.1.0.tar.gz", "archive_sha256": None}
    results = [verify_archive_identity("demo", "9.9.9", meta, p) for _ in range(5)]
    assert all(r["status"] == "REJECT" for r in results)


# ------------------------------------------------------- expected vs observed
def test_identity_facts_preserved(tmp_archive):
    data = _make_targz([], name="foo", version="0.5.0")
    p = tmp_archive(data, "foo-0.5.0.tar.gz")
    meta = {"version": "0.5.0", "archive_filename": "foo-0.5.0.tar.gz", "archive_sha256": None}
    r = verify_archive_identity("foo", "0.5.0", meta, p)
    assert r["requested_package"] == "foo"
    assert r["requested_version"] == "0.5.0"
    assert r["resolved_version"] == "0.5.0"
    assert r["observed_filename_version"] == "0.5.0"
    assert r["observed_metadata_version"] == "0.5.0"


# ------------------------------------------------- checkpoint consistency (no
# hardcoded failed list: FAILED state must be derived from authoritative
# checkpoints automatically).
def test_checkpoint_consistency_counts_new_failed(tmp_path, monkeypatch):
    """Newly FAILED / identity-mismatch checkpoints must be recognized
    automatically, without any hardcoded package list."""
    import json
    from scripts.scrapers import pypi

    meta_dir = tmp_path / "metadata"
    manifest_path = tmp_path / "pypi_acquisition_v1.json"
    meta_dir.mkdir(exist_ok=True)
    manifest_path.write_text(json.dumps({"record_count": 3, "packages": []}))

    monkeypatch.setattr(pypi, "PYPI_METADATA_DIR", meta_dir)
    monkeypatch.setattr(pypi, "PYPI_ACQUISITION_MANIFEST_PATH", manifest_path)

    # No checkpoints yet -> failed = 0
    res = pypi.verify_checkpoint_consistency()
    assert res["failed"] == 0
    assert res["acquired"] == 3

    # Write a FAILED checkpoint that is NOT in any hardcoded list.
    (meta_dir / "some-new-pkg_checkpoint.json").write_text(json.dumps({
        "some-new-pkg": {"state": "FAILED", "failure_reason": "identity_mismatch:filename_version_mismatch"}
    }))
    # Write a SKIPPED checkpoint.
    (meta_dir / "skip-pkg_checkpoint.json").write_text(json.dumps({
        "skip-pkg": {"state": "SKIPPED", "reason": "already_acquired"}
    }))

    res2 = pypi.verify_checkpoint_consistency()
    assert res2["failed"] == 1, "new FAILED checkpoint must be auto-detected"
    assert res2["skipped"] == 1
    assert res2["total_checkpoints"] == 3 + 1 + 1


def test_checkpoint_consistency_no_hardcoded_failed(tmp_path, monkeypatch):
    """The old implementation hardcoded dbt-semantic-interfaces/metricflow.
    The fix must not depend on any package name list."""
    import inspect
    from scripts.scrapers import pypi
    src = inspect.getsource(pypi.verify_checkpoint_consistency)
    assert "dbt-semantic-interfaces" not in src
    assert "metricflow" not in src
    assert "failed_packages" not in src


# ------------------------------------------- live-replay-resolved behavior
# These cases encode what the live replay proved: when the resolved version
# disagrees with the requested version (the historical absl-py mechanism),
# the gate must REJECT even if the archive SHA is valid for itself.
def test_live_replay_resolved_version_mismatch_rejected(tmp_archive):
    """absl-py live replay: requested 0.1.0, API resolved 2.5.0, returned file
    is absl-py-0.1.0.tar.gz whose SHA is valid for itself. Must be REJECTED."""
    data = _make_targz([], name="absl-py", version="0.1.0")
    p = tmp_archive(data, "absl-py-0.1.0.tar.gz")
    obs_sha = hashlib.sha256(data).hexdigest()
    meta = {
        "version": "2.5.0",               # resolved (wrong, from info.version)
        "archive_filename": "absl-py-0.1.0.tar.gz",
        "archive_sha256": obs_sha,        # valid for the downloaded file
    }
    r = verify_archive_identity("absl-py", "0.1.0", meta, p, expected_sha256=obs_sha)
    assert r["ok"] is False
    assert r["status"] == "REJECT"
    assert r["reason"] == "resolved_version_mismatch"
    assert r.get("sha_verified") is True, "SHA verified yet identity still rejected"


def test_live_replay_encutils_control_accepted(tmp_archive):
    """encutils live replay: requested 1.0.0, resolved 1.0.0, filename 1.0.0,
    PKG-INFO 1.0.0, SHA matches -> ACCEPT."""
    data = _make_targz([], name="encutils", version="1.0.0")
    p = tmp_archive(data, "encutils-1.0.0.tar.gz")
    obs_sha = hashlib.sha256(data).hexdigest()
    meta = {"version": "1.0.0", "archive_filename": "encutils-1.0.0.tar.gz", "archive_sha256": obs_sha}
    r = verify_archive_identity("encutils", "1.0.0", meta, p, expected_sha256=obs_sha)
    assert r["ok"] is True
    assert r["status"] == "ACCEPT"


# ------------------------------------------------------------ freeze guard
# The frozen-baseline guard must refuse checkpoint writes and acquisition
# starts when the freeze sentinel is present (prevents concurrent writers).
def test_freeze_sentinel_blocks_checkpoint_write(tmp_path, monkeypatch):
    import json
    from scripts.scrapers import pypi

    sentinel = tmp_path / ".FREEZE_SENTINEL"
    sentinel.write_text("frozen")
    monkeypatch.setattr(pypi, "PYPI_FREEZE_SENTINEL", sentinel)

    test_cp = tmp_path / "x_checkpoint.json"
    with pytest.raises(OSError):
        pypi._save_checkpoint(test_cp, {"x": {"state": "ACQUIRED"}})
    # No checkpoint file may have been created.
    assert not test_cp.exists()


def test_freeze_sentinel_blocks_run_scaleup(tmp_path, monkeypatch):
    from scripts.scrapers import pypi
    sentinel = tmp_path / ".FREEZE_SENTINEL"
    sentinel.write_text("frozen")
    monkeypatch.setattr(pypi, "PYPI_FREEZE_SENTINEL", sentinel)
    res = pypi.run_scaleup(batch_size=5, max_batches=1)
    assert res.get("final_status") == "BLOCKED_FROZEN"


def test_freeze_sentinel_blocks_run_pilot(tmp_path, monkeypatch):
    from scripts.scrapers import pypi
    sentinel = tmp_path / ".FREEZE_SENTINEL"
    sentinel.write_text("frozen")
    monkeypatch.setattr(pypi, "PYPI_FREEZE_SENTINEL", sentinel)
    res = pypi.run_pilot(limit=2)
    assert res.get("final_status") == "BLOCKED_FROZEN"


def test_no_sentinel_allows_write(tmp_path, monkeypatch):
    from scripts.scrapers import pypi
    sentinel = tmp_path / ".FREEZE_SENTINEL"
    monkeypatch.setattr(pypi, "PYPI_FREEZE_SENTINEL", sentinel)
    # Sentinel does not exist -> write succeeds.
    test_cp = tmp_path / "x_checkpoint.json"
    pypi._save_checkpoint(test_cp, {"x": {"state": "ACQUIRED"}})
    assert test_cp.exists()


# ------------------------------------------------- external checkpoint detection
# Deterministic helper: given a metadata dir and a freeze boundary, return the
# checkpoint files whose mtime exceeds the boundary (post-freeze writes).
def _detect_external_checkpoints(meta_dir, freeze_epoch):
    import os
    out = []
    for f in os.listdir(meta_dir):
        if f.endswith("_checkpoint.json"):
            mt = os.path.getmtime(os.path.join(meta_dir, f))
            if mt > freeze_epoch:
                out.append(f)
    return sorted(out)


def test_external_checkpoint_detection(tmp_path, monkeypatch):
    import os, time
    meta_dir = tmp_path / "metadata"
    meta_dir.mkdir()
    # A pre-freeze checkpoint (old mtime).
    pre = meta_dir / "pre_checkpoint.json"
    pre.write_text("{}")
    old = time.time() - 10000
    os.utime(pre, (old, old))
    # A post-freeze checkpoint (recent mtime).
    post = meta_dir / "post_checkpoint.json"
    post.write_text("{}")
    freeze_epoch = time.time() - 5000
    detected = _detect_external_checkpoints(meta_dir, freeze_epoch)
    assert detected == ["post_checkpoint.json"]
    assert "pre_checkpoint.json" not in detected