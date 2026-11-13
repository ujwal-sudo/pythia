"""Offline tests for PyPI release selection and remediation resume logic."""

from __future__ import annotations

import json
import io
import hashlib
import sys
import tarfile
from pathlib import Path

import pytest

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

import scripts.scrapers.pypi as pypi


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _file(name, sha, upload, packagetype="sdist", yanked=False):
    return {
        "packagetype": packagetype,
        "filename": name,
        "url": f"https://example.invalid/{name}",
        "digests": {"sha256": sha},
        "size": 10,
        "upload_time_iso_8601": upload,
        "yanked": yanked,
    }


def _payload():
    # Deliberately oldest-first insertion order, matching the PyPI payloads
    # that caused the historical wrong-version acquisitions.
    return {
        "info": {
            "version": "3.0.0",
            "license": "MIT",
            "classifiers": [],
            "project_urls": {},
            "home_page": "",
        },
        "releases": {
            "0.1.0": [_file("demo-0.1.0.tar.gz", "old", "2020-01-01T00:00:00Z")],
            "1.0.0": [_file("demo-1.0.0.tar.gz", "middle", "2022-01-01T00:00:00Z")],
            "3.0.0": [_file("demo-3.0.0.tar.gz", "yanked", "2024-01-01T00:00:00Z", yanked=True)],
            "2.0.0": [_file("demo-2.0.0.tar.gz", "new", "2023-01-01T00:00:00Z")],
        },
    }


def test_fetch_package_metadata_selects_newest_non_yanked_release(monkeypatch):
    monkeypatch.setattr(pypi.requests, "get", lambda *a, **k: FakeResponse(_payload()))
    meta = pypi.fetch_package_metadata("demo")
    assert meta is not None
    assert meta["version"] == "2.0.0"
    assert meta["resolved_version"] == "2.0.0"
    assert meta["archive_filename"] == "demo-2.0.0.tar.gz"
    assert meta["archive_sha256"] == "new"
    assert meta["pypi_url"].endswith("/demo/2.0.0/")


def test_fetch_package_metadata_honours_explicit_version(monkeypatch):
    monkeypatch.setattr(pypi.requests, "get", lambda *a, **k: FakeResponse(_payload()))
    meta = pypi.fetch_package_metadata("demo", requested_version="1.0.0")
    assert meta is not None
    assert meta["version"] == "1.0.0"
    assert meta["archive_filename"] == "demo-1.0.0.tar.gz"
    assert meta["requested_version"] == "1.0.0"


def test_fetch_package_metadata_prefers_info_version_over_higher_prerelease(monkeypatch):
    payload = _payload()
    payload["info"]["version"] = "1.0.0"
    payload["releases"]["1.0.0"] = [
        _file("demo-1.0.0.tar.gz", "stable", "2024-01-01T00:00:00Z")
    ]
    payload["releases"]["2.0.0rc1"] = [
        _file("demo-2.0.0rc1.tar.gz", "pre", "2025-01-01T00:00:00Z")
    ]
    monkeypatch.setattr(pypi.requests, "get", lambda *a, **k: FakeResponse(payload))
    meta = pypi.fetch_package_metadata("demo")
    assert meta is not None
    assert meta["version"] == "1.0.0"
    assert meta["archive_filename"] == "demo-1.0.0.tar.gz"


def test_fetch_package_metadata_missing_explicit_version(monkeypatch):
    monkeypatch.setattr(pypi.requests, "get", lambda *a, **k: FakeResponse(_payload()))
    assert pypi.fetch_package_metadata("demo", requested_version="9.9.9") is None


def test_repair_pending_overrides_existing_checkpoint(monkeypatch):
    candidates = [
        {"rank": 1, "package": "pkg-a", "normalized": "pkg-a"},
        {"rank": 2, "package": "pkg-b", "normalized": "pkg-b"},
        {"rank": 3, "package": "pkg-c", "normalized": "pkg-c"},
    ]
    monkeypatch.setattr(
        pypi, "_load_repair_plan",
        lambda: {"pkg-a": {"kind": "identity_mismatch"}, "pkg-b": {"kind": "identity_mismatch"}},
    )
    monkeypatch.setattr(
        pypi, "_list_repair_marker_norms",
        lambda kind: {"pkg-b"} if kind == "completed" else set(),
    )
    monkeypatch.setattr(
        pypi, "_iter_checkpoint_paths",
        lambda: [Path("pkg-a_checkpoint.json"), Path("pkg-b_checkpoint.json")],
    )
    unprocessed = pypi.get_unprocessed_candidates(candidates)
    assert [c["normalized"] for c in unprocessed] == ["pkg-a", "pkg-c"]


def test_repair_plan_addendum_merges_without_replacing_original(monkeypatch, tmp_path):
    plan_v1 = tmp_path / "repair_plan_v1.json"
    plan_v2 = tmp_path / "repair_plan_v2.json"
    plan_v1.write_text(json.dumps({"entries": {"old": {"kind": "identity_mismatch"}}}))
    plan_v2.write_text(json.dumps({"entries": {"new": {"kind": "retry_failed"}}}))
    monkeypatch.setattr(pypi, "PYPI_REMOTE_STORAGE", False)
    monkeypatch.setattr(pypi, "REPAIR_PLAN_PATH", plan_v1)
    monkeypatch.setattr(pypi, "REPAIR_PLAN_ADDENDUM_PATH", plan_v2)
    assert set(pypi._load_repair_plan()) == {"old", "new"}


def test_parallel_candidate_worker_reacquires_with_identity_verification(monkeypatch, tmp_path):
    payload = {
        "package": "demo",
        "version": "2.0.0",
        "resolved_version": "2.0.0",
        "archive_filename": "demo-2.0.0.tar.gz",
        "archive_url": "https://example.invalid/demo-2.0.0.tar.gz",
        "archive_sha256": "correct-sha",
        "archive_size": 10,
        "license_status": "CLEAR",
        "license_reason": "permissive",
    }
    monkeypatch.setattr(pypi, "PYPI_PACKAGES_DIR", tmp_path / "packages")
    monkeypatch.setattr(pypi, "checkpoint_path", lambda _norm: tmp_path / "demo_checkpoint.json")
    monkeypatch.setattr(pypi, "_load_checkpoint", lambda _path: {"demo": {"state": "ACQUIRED", "version": "0.1.0"}})
    monkeypatch.setattr(pypi, "fetch_package_metadata", lambda _package: payload)
    monkeypatch.setattr(pypi, "_archive_exists", lambda *a, **k: True)
    monkeypatch.setattr(pypi, "_archive_sha256_value", lambda *a, **k: "correct-sha")
    monkeypatch.setattr(pypi, "verify_archive_identity", lambda **k: {
        "ok": True,
        "observed_filename_version": "2.0.0",
        "observed_metadata_version": "2.0.0",
    })
    monkeypatch.setattr(pypi, "analyze_package", lambda *a, **k: {
        "docstring_ratio": 0.2,
        "comment_ratio": 0.1,
        "ast_valid": 1,
        "ast_invalid": 0,
        "python_files": 1,
        "python_loc": 10,
    })
    acquired = {}
    monkeypatch.setattr(
        pypi,
        "mark_acquired",
        lambda norm, **kwargs: acquired.update({"norm": norm, **kwargs}),
    )
    markers = []
    monkeypatch.setattr(
        pypi,
        "_write_repair_marker",
        lambda kind, norm, data: markers.append((kind, norm, data)),
    )

    result = pypi._process_scaleup_candidate(
        {"package": "demo", "normalized": "demo"}, {"demo"}, timeout=10
    )

    assert result["status"] == "acquired"
    assert acquired["allow_overwrite"] is True
    assert acquired["version"] == "2.0.0"
    assert acquired["identity_verified"] is True
    assert markers[0][0:2] == ("completed", "demo")


def test_local_headroom_checks_active_pypi_mount(monkeypatch, tmp_path):
    seen = {}

    def fake_disk_usage(path):
        seen["path"] = Path(path)
        return (2000 * 1024**3, 1100 * 1024**3, 900 * 1024**3)

    monkeypatch.setattr(pypi, "PYPI_DIR", tmp_path / "raw" / "pypi")
    monkeypatch.setattr(pypi.shutil, "disk_usage", fake_disk_usage)
    result = pypi.verify_storage_headroom(min_free_gb=1.0)
    assert seen["path"] == tmp_path / "raw" / "pypi"
    assert result["sufficient"] is True


def test_analyze_package_ignores_directories_named_like_python_files(tmp_path):
    archive = tmp_path / "demo-1.0.0.tar.gz"
    source = b"value = 1\n"
    with tarfile.open(archive, "w:gz") as tf:
        directory = tarfile.TarInfo("demo-1.0.0/tests/test_dummy.py")
        directory.type = tarfile.DIRTYPE
        tf.addfile(directory)
        pyfile = tarfile.TarInfo("demo-1.0.0/demo.py")
        pyfile.size = len(source)
        tf.addfile(pyfile, io.BytesIO(source))
    result = pypi.analyze_package(archive, "demo")
    assert result["python_files"] == 1
    assert result["ast_valid"] == 1


def test_download_retries_incomplete_stream(monkeypatch, tmp_path):
    responses = [b"short", b"complete"]

    class Response:
        headers = {"content-length": "8"}

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            yield self.payload

    monkeypatch.setattr(
        pypi.requests,
        "get",
        lambda *args, **kwargs: Response(responses.pop(0)),
    )
    monkeypatch.setattr(pypi.time, "sleep", lambda _delay: None)
    destination = tmp_path / "demo.tar.gz"
    pypi._download_file("https://example.invalid/demo.tar.gz", destination, timeout=5, show_progress=False)
    assert destination.read_bytes() == b"complete"


def test_reconstruct_archive_filename_requires_matching_sha_and_identity(monkeypatch, tmp_path):
    packages = tmp_path / "packages"
    archive_dir = packages / "demo" / "2.0.0"
    archive_dir.mkdir(parents=True)
    archive = archive_dir / "demo-2.0.0.tar.gz"
    content = b"Metadata-Version: 2.1\nName: demo\nVersion: 2.0.0\n"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tf:
        info = tarfile.TarInfo("demo-2.0.0/PKG-INFO")
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    archive.write_bytes(buffer.getvalue())
    monkeypatch.setattr(pypi, "PYPI_PACKAGES_DIR", packages)
    monkeypatch.setattr(pypi, "PYPI_REMOTE_STORAGE", False)

    filename, verified = pypi._resolve_checkpoint_archive_filename(
        "demo",
        {"version": "2.0.0", "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()},
    )
    assert filename == "demo-2.0.0.tar.gz"
    assert verified is True
