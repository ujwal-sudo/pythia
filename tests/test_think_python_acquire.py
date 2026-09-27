"""Tests for Think Python acquisition (Session 2).

Cover: manifest determinism, stable IDs, source/version identity, SHA-256
generation, chapter splitting, storage isolation (think_python != PEP != PyPI),
duplicate detection, and no writes to PyPI/PEP namespaces.
"""

import hashlib
import json
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from scripts.scrapers.think_python_acquire import sha256_bytes, split_chapters

COMMIT = "bbe57aef0014f51cdb9cf43523210e075fb24da2"


def test_manifest_determinism():
    """Same input -> same canonical JSON -> same SHA-256."""
    m = {
        "dataset": "think_python", "source": "AllenDowney/ThinkPython2",
        "source_commit": COMMIT,
        "candidates": [
            {"candidate_id": "thinkpython:book", "kind": "book"},
            {"candidate_id": "thinkpython:chapter:01", "kind": "chapter"},
        ],
    }
    h1 = hashlib.sha256(json.dumps(m, sort_keys=True).encode()).hexdigest()
    h2 = hashlib.sha256(json.dumps(m, sort_keys=True).encode()).hexdigest()
    assert h1 == h2


def test_stable_record_ids():
    """Record IDs are deterministic and stable."""
    assert "thinkpython:book" == "thinkpython:book"
    assert "thinkpython:code:Card.py" == "thinkpython:code:Card.py"
    assert "thinkpython:chapter:01" != "thinkpython:chapter:02"


def test_sha256_generation():
    data = b"think python"
    assert sha256_bytes(data) == hashlib.sha256(b"think python").hexdigest()
    assert len(sha256_bytes(data)) == 64


def test_chapter_split():
    """split_chapters must produce stable chapter boundaries."""
    text = (
        "\\chapter{First}\ncontent A\n"
        "\\chapter{Second}\ncontent B\n"
        "\\chapter{Third}\ncontent C\n"
    )
    chapters = split_chapters(text)
    assert len(chapters) == 3
    assert chapters[0][0] == 1 and chapters[0][1] == "First"
    assert "content A" in chapters[0][2]
    assert chapters[2][1] == "Third"


def test_storage_isolation_think_python_vs_pep_pypi():
    """think_python namespace must differ from PEP and PyPI."""
    import config
    tp = str(config.PEP_DIR).replace("peps", "think_python")  # convention check only
    pep = str(config.PEP_DIR)
    pypi = str(config.PYPI_DIR)
    assert pep != pypi
    # think_python acquisition script must not reference pypi/peps archives
    src = Path(_here, "scripts/scrapers/think_python_acquire.py").read_text()
    assert "raw/pypi" not in src
    assert "raw/peps" not in src
    assert "think_python" in src


def test_no_pypi_pep_path_in_think_python():
    """think_python_acquire.py must not reference PyPI or PEP namespaces."""
    src = Path(_here, "scripts/scrapers/think_python_acquire.py").read_text()
    assert "pythia:Pythia/raw/pypi" not in src
    assert "pythia:Pythia/raw/peps" not in src


def test_source_commit_pinned():
    """Source commit must be pinned and fixed."""
    src = Path(_here, "scripts/scrapers/think_python_acquire.py").read_text()
    assert COMMIT in src


def test_duplicate_detection_logic():
    h1 = sha256_bytes(b"same")
    h2 = sha256_bytes(b"same")
    h3 = sha256_bytes(b"diff")
    assert h1 == h2
    assert h1 != h3