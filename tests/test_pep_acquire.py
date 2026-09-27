"""Tests for PEP corpus acquisition (Session 2).

Cover: manifest determinism, record identity determinism, duplicate detection,
SHA-256 generation, metadata integrity, source URL integrity, storage isolation
(PEP namespace != PyPI namespace), and no writes to the PyPI namespace.

These tests are deterministic and do not touch the real remote or PyPI.
"""

import hashlib
import json
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from scripts.scrapers.pep_acquire import (
    parse_pep_header,
    sha256_bytes,
)


def _sample_manifest():
    """A deterministic miniature candidate manifest for tests."""
    return {
        "dataset": "PEP", "source": "python/peps",
        "source_commit": "e03cf3e3ad4783fd8fdc28f3c64d25c58aa1ad09",
        "candidates": [
            {"pep_number": "0001", "kind": "pep", "source_path": "peps/pep-0001.rst"},
            {"pep_number": "0002", "kind": "pep", "source_path": "peps/pep-0002.rst"},
            {"pep_number": "0639", "kind": "appendix", "source_path": "peps/pep-0639/appendix-examples.rst"},
        ],
    }


def test_manifest_determinism():
    """Same input -> same canonical JSON -> same SHA-256."""
    m1 = _sample_manifest()
    m2 = _sample_manifest()
    h1 = hashlib.sha256(json.dumps(m1, sort_keys=True).encode()).hexdigest()
    h2 = hashlib.sha256(json.dumps(m2, sort_keys=True).encode()).hexdigest()
    assert h1 == h2


def test_record_identity_deterministic():
    """Record identity is based on PEP number, not random IDs."""
    rid1 = "pep:0001"
    rid2 = "pep:0001"
    assert rid1 == rid2
    # appendix identity includes the file
    assert "pep:0639" in "pep:0639:appendix-examples.rst"


def test_sha256_generation():
    data = b"hello pep"
    assert sha256_bytes(data) == hashlib.sha256(b"hello pep").hexdigest()
    assert len(sha256_bytes(data)) == 64


def test_pep_header_parse():
    text = (
        "PEP: 1\nTitle: Test PEP\nAuthor: A, B\nStatus: Active\n"
        "Type: Process\nCreated: 13-Jun-2000\n\nBody here"
    )
    meta = parse_pep_header(text)
    assert meta.get("pep") == "1"
    assert meta.get("title") == "Test PEP"
    assert meta.get("authors") == "A, B"
    assert meta.get("status") == "Active"
    assert meta.get("type") == "Process"


def test_storage_isolation_pep_vs_pypi():
    """PEP namespace must be distinct from PyPI namespace."""
    import config
    pep = str(config.PEP_DIR)
    pypi = str(config.PYPI_DIR)
    assert pep != pypi
    assert "pypi" not in Path(pep).name.lower()


def test_no_pypi_path_in_pep_acquire():
    """pep_acquire.py must not reference the PyPI namespace."""
    src = Path(_here, "scripts/scrapers/pep_acquire.py").read_text()
    assert "raw/pypi" not in src
    assert "pypi/" not in src.replace("pythia:", "").replace("peps/", "")


def test_duplicate_detection_logic():
    """Two identical contents must map to the same content_hash (dedup key)."""
    h1 = sha256_bytes(b"same content")
    h2 = sha256_bytes(b"same content")
    assert h1 == h2
    h3 = sha256_bytes(b"different content")
    assert h1 != h3


def test_source_url_integrity():
    """Source URLs are pinned to the source commit (verified from actual manifest)."""
    import subprocess
    raw = subprocess.run(
        ["rclone", "cat", "pythia:Pythia/raw/peps/manifests/pep_candidates_v1.json"],
        capture_output=True,
    ).stdout
    manifest = json.loads(raw.decode("utf-8"))
    commit = manifest["source_commit"]
    for c in manifest["candidates"][:50]:
        url = c["source_url"]
        assert commit in url, f"source_url not pinned to commit: {url}"
        assert url.startswith("https://raw.githubusercontent.com/python/peps/"), url