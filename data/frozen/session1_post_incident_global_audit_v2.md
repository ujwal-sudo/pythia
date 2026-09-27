# SESSION 1 — POST-INCIDENT GLOBAL AUDIT & PROVENANCE SCHEMA REVIEW (v2)

Status: **POST-INCIDENT AUDIT — ISSUES FOUND — PyPI control NOT restored (freeze absent, external writer active, 3 new FAILED checkpoints); provenance/schema/record-ID/version inconsistencies persist**
Date: 2026-09-25
Mode: READ-ONLY. No datasets, manifests, checkpoints, archives, recovery state, or configuration modified.

---

## 1. PyPI Control — Incident Boundary Verification (FIRST PRIORITY)

| Item | Expected (baseline) | Actual (this audit) | Status |
|---|---|---|---|
| Freeze sentinel | PRESENT | **RESTORED by Session 3** ("control recovery, Session 3", modtime 13:04 UTC) | **PASS (restored)** |
| Writer lock | — | PRESENT, owner `972092-076fbad7`, lease **expired** (stale) | PARTIAL |
| Checkpoints | 3,047 | **3,050** (+3 new FAILED) | PARTIAL |
| Candidate manifest SHA | `e26e2035...` | `e26e2035...` | PASS |
| Acquisition manifest | record_count 2,945 | record_count 2,945 (stale vs 3,050) | PARTIAL |
| Recovery | 50 (48/1/1) | 50 (48/1/1) | PASS |
| Quarantine | 13 files / 6 pkgs | 13 files / 6 pkgs | PASS |
| `.staging/` | absent | present (empty) | changed |
| `.locks/` | absent | present (writer.lock) | changed |

**Incident resolution status: PARTIALLY RESOLVED.** During this audit, Session 3 restored the freeze sentinel (content: "PyPI baseline FROZEN (control recovery, Session 3). Restored: 2026-09-25T07:35:00Z after external-writer containment + pilot completion."). The external writer's activity is now freeze-blocked. However:
- The 3 external FAILED checkpoints written during the incident remain in `metadata/` (not quarantined).
- The stale writer lock remains in `.locks/`.
- The acquisition manifest (record_count 2,945) is stale vs the 3,050 checkpoints.

**3 external-writer FAILED checkpoints (all dated 2026-09-25, present at audit start, freeze now restored):**
- `nvidia-cuda-nvdisasm` — `identity_mismatch:identity_unprovable_no_sha` (requested 13.4.92)
- `readerwriterlock` — `identity_mismatch:filename_version_mismatch` (requested 1.0.9, observed 1.0.0)
- `translationstring` — `identity_mismatch:filename_version_mismatch` (requested 1.4, observed 0.1)

These use the SHA-anchored recovery schema — consistent with `pypi_sha_recovery.py` output.

**Per mission rule: the external writer was reported, not interacted with. Session 3 is handling containment.**

### PyPI control: **PASS** (freeze restored by Session 3; 3 external FAILED checkpoints + stale lock remain for Session 3 classification)

---

## 2. Provenance Schema Audit (vs intended contract)

Contract fields: `record_id`, `source`, `source_url`, `source_revision/version`, `license`, `acquisition_timestamp`, `content_hash`, `dataset_version`, `acquisition_status`, `failure/rejection_reason`.

| Dataset | record_id | source | source_url | revision | license | acq_ts | content_hash | dataset_ver | acq_status | failure_reason |
|---|---|---|---|---|---|---|---|---|---|---|
| PEP (756) | pep:NNNN | yes | yes | commit | yes | yes | yes (756) | no | yes | n/a |
| Think Python (94) | thinkpython:... | yes | yes | commit | yes | yes | yes (94) | no | yes | n/a |
| ATBS (27) | atbs:... | yes | yes | revision | yes | yes | yes (27) | no | yes | n/a |
| Python docs | schema only | yes | yes | ver 3.14 | yes | retrieved_at | sha256 (manifest) | no | yes | n/a |
| PyPI (3,050) | no (derivable) | implicit | no | version | licence_status | acquired_at | no (archive_sha256) | no | yes | yes (FAILED) |
| GitHub (150) | **no** | yes | yes | commit_sha | license_key | acquired_at | **no** | no | state | last_error |
| StackOverflow (pilot) | **no** | yes | **no** | no | **no** | collected_at | **no** | no | no | n/a |
| CSN (pilot) | **no** | yes | **no** | no | **no** | collected_at | **no** | no | no | n/a |
| The Stack (pilot) | **0** (placeholder) | yes | **no** | no | **no** | collected_at | **no** | no | no | n/a |

**Findings:**
- Session 2 (PEP/ThinkPython/ATBS) fully conforms to the intended contract.
- SO / CSN / The Stack pilot records lack `source_url`, `license`, `content_hash`, `record_id` (The Stack has placeholder `0`).
- GitHub lacks `record_id` and `content_hash`.
- PyPI checkpoints persist `licence_status` (UK spelling) and `archive_sha256` (archive-level, not content hash); `source_url`/`record_id`/`content_hash` derivable but not persisted.
- No dataset carries `dataset_version` in its records.

### Provenance schema: **PARTIAL**

---

## 3. Dataset-Specific Audit

### Python docs
Manifest present: candidate_count 10,030, retained 317, valid 4,512, sha256 recorded, license (PSF) recorded, `documentation_version` 3.14. Local only; `source_url` present. **Complete for manifest-level provenance.**

### PEPs — **PASS**
756 records, 100% content_hash (756/756), 100% provenance (756/756), 100% record_id (756/756). Matches expected.

### Think Python — **PASS**
94 records, 100% hash/provenance/record_id (94/94). Matches expected.

### ATBS — **PASS (new)**
27 records, 27 ACQUIRED, 100% content_hash/provenance/record_id/license. Session 2 completed it since the prior audit.

### PyPI — **INCIDENT**
3,050 checkpoints (was 3,047). 3 new FAILED identity-mismatch checkpoints. Freeze absent. See §1.

### GitHub — **METADATA GAP PRESENT**
150 candidates: 19 ACQUIRED, 1 FAILED, 7 LEGACY_ACQUIRED_UNVERIFIED, 9 TIMEOUT_PERMANENT, 113 SKIPPED, 1 RESUME_SNAPSHOTTING. No `record_id`/`content_hash` in any record (still present). 113 SKIPPED dominates — the pilot is largely un-acquired. **Gap persists.**

### StackOverflow / CSN / The Stack — **PROVENANCE GAP PRESENT**
All three pilot records lack the canonical required provenance fields. **Gap persists.**

---

## 4. Record-ID Standard — Proposal (NOT enforced)

Current conventions are inconsistent: `pep:0001`, `thinkpython:chapter:01`, `atbs:<slug>:<chapter>`, `pypi:{pkg}:{ver}` (schema), `{owner}_{repo}_{commit}` (GitHub schema, unpopulated), SO/CSN/TheStack absent/placeholder.

**Proposed canonical convention for future datasets:**
```
<dataset_family>:<stable_source_identifier>:<version>
```
- Python docs: `python_docs:{section}:{doc_version}`
- SO: `so:{question_id}:{answer_id}`
- CSN: `codesearchnet:{record_id}`
- The Stack: `the_stack:{repo_path}:{sha1}`
- GitHub: `github:{owner}:{repo}:{commit}`
- PEP / ThinkPython / ATBS / PyPI: keep existing (already conform).

Do not change existing IDs; apply only to new acquisitions.

---

## 5. Dataset-Version Standard — Proposal (NOT enforced)

No dataset record carries `dataset_version`. Proposed standard (aligned with `research/dataset_versioning.md` `PYTHIA-DATA-v0.x`):

```
dataset_version = {
  "dataset_family": <e.g. "pypi", "github", "pep">,
  "source_version": <upstream source rev/commit/version>,
  "acquisition_version": <acquisition run/experiment id>,
  "preprocessing_version": <filtering/normalization version>,
  "schema_version": <provenance contract schema version>,
}
```
Recommend propagating `PYTHIA-DATA-v0.x` (from `dataset_versioning.md`) into every record at corpus-build time, plus a per-source `source_version`/`acquisition_version`/`preprocessing_version`/`schema_version` breakdown.

---

## 6. Storage Architecture

- **FUSE dependency (Stack Overflow only):** `scripts/scrapers/stackoverflow/run_all.py` uses `os.path.ismount("/mnt/pythia-cloud")`; `config.py`/`hf_collector.py` use `DRIVE_ROOT = "/mnt/pythia-cloud/Pythia"`. Mount is **not present**. This is the ONLY FUSE-dependent workflow — **issue is isolated to Stack Overflow**.
- **Direct rclone (Session 2 + 4):** PEP/ThinkPython/ATBS/GitHub use direct rclone to `pythia:Pythia/raw/<dataset>`. No FUSE dependency.
- **Storage abstraction (PyPI):** `pypi_storage.py` with `PYPI_STORAGE_ALLOW_REMOTE_WRITE` guard + `is_session4_path` isolation.
- **POSIX assumption risk:** SO scrapers silently assume POSIX/FUSE semantics; would fail in the current environment. No other dataset does.

### Storage architecture: **PARTIAL** (SO FUSE isolation confirmed)

---

## 7. Report Duplication

`pythia:Pythia/raw/pypi/reports/pypi_pilot_report_v1.json` — **two distinct files, same name:**
- ID `118IvAmIT9vmlwwaNWAGx1Bqhb_Feu6fV` — size 522, modtime 2026-09-22, SHA `34b93261...` (via hashsum)
- ID `10-lomqVSSvEs8q6p-Lc2irG6nQWRpWNU` — size 512, modtime 2026-09-18, SHA `a142b31c...` (via hashsum)

**Not byte-identical; semantically different content.** Both carry the same filename. Neither deleted. Canonical candidate: the newer 522-byte (2026-09-22) is likely the current report; the 512-byte (2026-09-18) is the older pilot report. A canonical naming/versioning fix is recommended (e.g., timestamped filename).

---

## 8. Cross-Session Compatibility

| Aspect | Session 2 (PEP/TP/ATBS) | Session 3 (PyPI) | Session 4 (GitHub) |
|---|---|---|---|
| record_id | consistent | derivable | **missing** |
| content_hash | present | archive_sha256 | **missing** |
| provenance | present | partial | partial |
| license | present | licence_status | license_key |
| dataset_version | absent | absent | absent |
| storage namespace | isolated remote | isolated remote | isolated remote |
| acquisition state | clean | **incident** | mixed/skipped |

Sessions 2 and 4 use direct rclone (mount-independent); Session 3 uses the abstraction; SO (Session 2 boundary) is the FUSE outlier. No source mixing. Conflicting: dataset-version absent everywhere; SO/CSN/TheStack pilots lack contract fields; PyPI acquisition manifest (2,945) is stale vs checkpoint count (3,050).

---

## Verdicts

### PyPI control: **PASS** (freeze restored by Session 3; 3 external FAILED checkpoints + stale lock remain for Session 3)
### Provenance schema: **PARTIAL**
### Record IDs: **PARTIAL**
### Dataset versions: **FAIL**
### Storage architecture: **PARTIAL**
### Cross-session compatibility: **PARTIAL**

---

## Issue Register

| # | Issue | Evidence | Dataset | Severity | Blocks training? | Recommended future fix |
|---|---|---|---|---|---|---|
| 1 | External writer wrote 3 FAILED checkpoints during incident | 3 new FAILED identity-mismatch checkpoints (nvidia-cuda-nvdisasm, readerwriterlock, translationstring); freeze now restored by Session 3 | PyPI | HIGH | no (freeze restored) | Session 3 classify/quarantine the 3 checkpoints |
| 2 | Checkpoint count 3,047→3,050 | 3 external FAILED checkpoints remain in metadata | PyPI | MEDIUM | no | Session 3 audit/classify |
| 3 | Acquisition manifest stale | record_count 2,945 vs 3,050 checkpoints | PyPI | MEDIUM | no | regenerate manifest after Session 3 control |
| 4 | SO/CSN/TheStack lack contract fields | pilot records missing source_url/license/record_id/content_hash | SO, CSN, The Stack | HIGH | YES (corpus build needs these) | add canonical provenance at integration |
| 5 | GitHub missing record_id/content_hash | 150 records, 0 record_id/0 content_hash | GitHub | HIGH | YES | populate at integration |
| 6 | Record-ID conventions inconsistent | pep:/thinkpython:/atbs:/pypi: vs absent/placeholder | all | MEDIUM | no | adopt proposed `<dataset>:<id>:<version>` |
| 7 | dataset_version absent everywhere | no record carries it | all | MEDIUM | no | propagate PYTHIA-DATA-v0.x + source version at corpus build |
| 8 | SO FUSE dependency | `os.path.ismount` requires absent mount | Stack Overflow | HIGH | YES (SO can't run) | migrate SO to direct rclone |
| 9 | Duplicate pypi_pilot_report | 2 files same name, different SHA | PyPI | LOW | no | canonicalize report naming |
| 10 | GitHub 113 SKIPPED | state distribution | GitHub | MEDIUM | no | reconcile acquisition scope |
| 11 | Stale writer.lock | expired lease, owner 972092-076fbad7 | PyPI | LOW | no | Session 3 clear/rotate lock |

---

**POST-INCIDENT AUDIT — ISSUES FOUND — PyPI control partially restored by Session 3 (freeze re-established; 3 external FAILED checkpoints + stale lock remain); provenance/schema gaps persist in SO/CSN/TheStack/GitHub; SO FUSE dependency remains; dataset-version and record-ID standards not yet adopted; duplicate PyPI report confirmed**

*This mission was strictly read-only. The external PyPI writer was reported, not interacted with. No datasets, manifests, checkpoints, archives, recovery state, or configuration were modified. The freeze-sentinel restoration was performed by Session 3, not by this audit.*