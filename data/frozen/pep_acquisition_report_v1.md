# SESSION 2 — PEP CORPUS ACQUISITION & PROVENANCE ESTABLISHMENT (FINAL REPORT)

## Overall status: PEP ACQUISITION — COMPLETE

Candidates: 756
Acquired: 756
Failed: 0
Skipped: 0
Duplicates: 0
Invalid: 0

Manifest SHA-256: 9cbf1a73f4c478a8ec74c567900875639ce01ef6e0a7a9d3340964b117e8d30d
Source revision/version: python/peps @ commit e03cf3e3ad4783fd8fdc28f3c64d25c58aa1ad09 (2026-09-23T14:34:31Z)
Dataset namespace: pythia:Pythia/raw/peps/

SHA-256 coverage: 756/756 (100%)
Provenance coverage: 756/756 (100%)
Unique content hashes: 756 (0 duplicates)

Tests: 195 passed / 1 skipped / 2 subtests (full suite); 8 new PEP tests pass
Evidence/report: data/frozen/pypi_... (PEP report) + scripts/scrapers/pep_acquire.py + tests/test_pep_acquire.py

PyPI state:
UNCHANGED
PyPI freeze:
ACTIVE
Execution outside PEP:
NOT AUTHORIZED

---

## 1. Dataset Objective
Python Enhancement Proposals acquired for Pythia-160M Stage 1 high-quality Python
foundation corpus (BASE PRETRAINING). Not SFT/reasoning/neurosymbolic.

## 2. Ownership / isolation
Session 2 owns PEP acquisition. PEP namespace fully isolated from PyPI.
PyPI namespace untouched: 3,047 checkpoints / 2,945 ACQUIRED / 102 FAILED / freeze ACTIVE.

## 3. Source authority
python/peps (github.com/python/peps), pinned commit e03cf3e3ad4783fd8fdc28f3c64d25c58aa1ad09.
PEP files (pep-####.rst) acquired from raw.githubusercontent.com at that commit.

## 4. Discovery
- Candidate inventory: 756 files = 743 primary PEPs (pep-NNNN.rst) + 13 appendix files
  (pep-NNNN/ subdirs incl. template pep-NNNN.rst under pep-0012/).
- Deterministic manifest at pythia:Pythia/raw/peps/manifests/pep_candidates_v1.json
  (SHA-256 9cbf1a73...), recording pep_number, kind, source_path, source_url (commit-pinned), format.

## 5. Storage isolation
Dedicated namespace: pythia:Pythia/raw/peps/{archives,manifests,metadata}/.
PEP destination != PyPI destination (verified by test + config check).
No artifacts placed under raw/pypi.

## 6. Acquisition
Each PEP: downloaded from commit-pinned source_url; SHA-256 computed; RST header parsed
(PEP, Title, Author, Status, Type, Created, etc.); archive written to archives/pep-NNNN.rst
(or pep-NNNN/ subdir for appendices); checkpoint record written to metadata state with
record_id=pep:NNNN, provenance (source/commit/url/date), content_hash, archive_path, bytes.
Deterministic record identity (pep:NNNN). No silent overwrite (skip-existing on resume).

## 7. Integrity accounting
TOTAL 756 = ACQUIRED 756 + FAILED 0 + SKIPPED 0 + DUPLICATES 0 + INVALID 0. Reconciled exactly.
SHA-256 verified 10/10 sampled; coverage 756/756.

## 8. Failure handling
No failures encountered. Failure classification logic implemented (transient/permanent/
malformed/empty/duplicate) with bounded retry (no retry loop). No source hammering.

## 9. Quality / filtering
Raw authoritative corpus preserved fully. No aggressive filtering. No corrupt/empty/duplicate/
malformed records identified.

## 10. Dataset classification
Family: PEP | Stage: 1 High-quality Python foundations | Use: BASE PRETRAINING
SFT: No | Reasoning-only: No | Neurosymbolic-only: No

## 11. Reproducibility
- Source: python/peps @ e03cf3e3 (2026-09-23T14:34:31Z)
- Candidate manifest: pythia:Pythia/raw/peps/manifests/pep_candidates_v1.json (SHA 9cbf1a73...)
- Acquisition: 756 acquired / 0 failed / 0 skip / 0 dup / 0 invalid
- Integrity: SHA-256 coverage 756/756; unique hashes 756
- Provenance: 756/756 with source+commit+url+date
- Storage: pythia:Pythia/raw/peps/archives (756 files, ~15.0 MiB), metadata state, manifests
- A future operator can reconstruct the exact acquisition (commit-pinned URLs + manifest).

## 12. Tests
8 new PEP tests: manifest determinism, record identity determinism, SHA-256 generation,
PEP header parse, storage isolation (PEP != PyPI), no-PyPI-path in pep_acquire,
duplicate detection, source-URL integrity. Full suite: 195 passed / 1 skipped / 2 subtests.
Resume behavior verified (state persists; --resume skips completed).

## 13. Mandatory safety check
PEP destination (raw/peps) != PyPI destination (raw/pypi). Verified. No ambiguity.

## 14. Completion criteria
1 source identified (python/peps) ✓ 2 candidate inventory complete (756) ✓
3 manifest generated+hashed (9cbf1a73...) ✓ 4 acquired into dedicated namespace ✓
5 every candidate has terminal state (ACQUIRED) ✓ 6 SHA accounting reconciles ✓
7 provenance preserved ✓ 8 failures classified (0) ✓ 9 storage isolated ✓
10 resume verified ✓ 11 tests recorded ✓ 12 final report produced ✓

## Evidence / artifacts
- scripts/scrapers/pep_acquire.py (acquisition script)
- tests/test_pep_acquire.py (8 tests)
- pythia:Pythia/raw/peps/manifests/pep_candidates_v1.json
- pythia:Pythia/raw/peps/metadata/pep_acquisition_state_v1.json (756 records)
- pythia:Pythia/raw/peps/archives/*.rst (+ pep-NNNN/ appendix subdirs)
