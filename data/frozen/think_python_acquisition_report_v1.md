# SESSION 2 — THINK PYTHON ACQUISITION & PROVENANCE ESTABLISHMENT (FINAL REPORT)

## Overall status: THINK PYTHON ACQUISITION — COMPLETE
## (with an explicitly reported PyPI control-state anomaly — see §Critical)

Candidates: 94
Acquired: 94
Failed: 0
Skipped: 0
Duplicates: 0
Invalid: 0

Manifest SHA-256: c9c854b1d7d499cbfbca8ad2cb7c83b29c0b2683f4ca98ddd2b7f4d38fb9691f
Source revision/version: AllenDowney/ThinkPython2 @ commit bbe57aef0014f51cdb9cf43523210e075fb24da2 (master, 2024-04-09)
Dataset namespace: pythia:Pythia/raw/think_python/

Content SHA-256 coverage: 94/94 (100%)
Provenance coverage: 94/94 (100%)
Duplicate hashes: 0

Tests: 203 passed / 1 skipped / 2 subtests (full suite); 8 new Think Python tests pass
Evidence/report: data/frozen/think_python_acquisition_report_v1.md

PyPI state: UNCHANGED (3,047 checkpoints, candidate/manifest SHAs match, recovery 50)
PyPI freeze: ACTIVE-at-mission-start, but see CRITICAL anomaly below
PEP state: UNCHANGED (756 records)

---

## CRITICAL CONTROL-STATE ANOMALY (must be escalated)
During final integrity verification, the following was observed on the authoritative remote:

1. `.FREEZE_SENTINEL` at pythia:Pythia/raw/pypi/ is ABSENT (was present at mission start).
2. An active PyPI scaleup process (PID 909683) is running with
   PYPI_REMOTE_STORAGE=1 PYPI_STORAGE_ALLOW_REMOTE_WRITE=1, holding
   metadata/.locks/writer.lock (owner 909683-80f502d7, lease active).
3. The writer was launched by an opencode agent (PID 625145) — consistent with the
   recurring concurrent-writer pattern seen earlier in Session 2.

Session 2 did NOT remove the sentinel and did NOT launch this writer.
This is an external/competing process. It is reported here because the mission's
mandatory safety rule requires STOP-and-report on any PyPI control-state ambiguity.
PyPI checkpoints still = 3,047 at last check, but the writer is active.

## 1. Source
- Title: Think Python, 2nd Edition
- Author: Allen Downey
- Edition: 2nd Edition
- Authoritative source: AllenDowney/ThinkPython2 (github.com/AllenDowney/ThinkPython2)
- Source revision: commit bbe57aef0014f51cdb9cf43523210e075fb24da2 (master)
- License: MIT (LaTeX source + code, c. Allen Downey); book text CC BY-NC 3.0 per greenteapress
- Acquisition date: 2026-09-25

## 2. Inventory
Candidates: 94 = 1 book + 22 chapters + 65 code examples + 4 glossary + 2 meta
Acquired: 94 / Failed: 0 / Skipped: 0 / Duplicates: 0 / Invalid: 0

## 3. Integrity
Manifest SHA-256: c9c854b1d7d499cbfbca8ad2cb7c83b29c0b2683f4ca98ddd2b7f4d38fb9691f
Content SHA-256 coverage: 94/94; unique content hashes: 94; duplicate hashes: 0
SHA sample verification: 8/8 match (independent re-hash of remote archives)

## 4. Provenance
Provenance coverage: 94/94 (source, source_url, source_commit, edition, license, acquisition_date)
License coverage: 94/94 (MIT for LaTeX/code; CC BY-NC 3.0 for book text)

## 5. Storage
Dataset namespace: pythia:Pythia/raw/think_python/
Archive count: 94 (archives/ = book.tex, chapters/, code/, glossary/, meta/)
Metadata count: 1 state file (think_python_acquisition_state_v1.json) + manifest
Total storage size: 1.817 MiB (96 objects incl. manifests/state)

## 6. Tests
8 new Think Python tests: manifest determinism, stable IDs, SHA-256 generation,
chapter splitting, storage isolation (think_python != PEP != PyPI), no-PyPI/PEP path,
source-commit pinning, duplicate detection. Full suite: 203 passed / 1 skipped / 2 subtests.
Resume verified (re-run: 0 new; no re-downloads; state persists).

## 7. Isolation
Think Python destination (raw/think_python) != PEP (raw/peps) != PyPI (raw/pypi) — verified.
No PyPI files/checkpoints/manifests/recovery modified by this mission.
PEP unchanged. PyPI checkpoints unchanged (3,047) as of last verification.

## 8. Dataset classification
Family: Think Python | Stage: 1 High-quality Python foundations | Use: BASE PRETRAINING
SFT: No | Reasoning-only: No | Neurosymbolic-only: No

## 9. Resume / reproducibility
Manifest pinned to commit bbe57aef; source URLs commit-pinned; per-record state persisted;
resume deterministic. A future operator can reconstruct exactly what was acquired.

## Completion status
THINK PYTHON ACQUISITION — COMPLETE
(Think Python acquisition itself is complete and verified. The PyPI control-state anomaly
above is a separate cross-session issue that must be escalated to the PyPI control authority.)
