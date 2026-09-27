# SESSION 1 — GLOBAL DATASET & INFRASTRUCTURE CONSISTENCY AUDIT (v1)

Status: **GLOBAL AUDIT — ISSUES FOUND — cross-session provenance/schema inconsistencies; SO mount dependency**
Date: 2026-09-25
Mode: READ-ONLY. No datasets, manifests, checkpoints, archives, recovery state, or configuration modified.

---

## Audit Scope

Verified the independently operating sessions (1–4) remain compatible as the corpus expands:
- Session 1 → global infrastructure / integration audit (this mission)
- Session 2 → Think Python + PEP acquisition
- Session 3 → PyPI
- Session 4 → GitHub

---

## 1. Dataset Isolation

| Dataset | Namespace | Isolation |
|---|---|---|
| Python docs | `data/raw/python_docs/` (local) | Clean |
| PEPs | `pythia:Pythia/raw/peps/` (archives/manifests/metadata) | Clean |
| Think Python | `pythia:Pythia/raw/think_python/` (archives/manifests/metadata) | Clean |
| PyPI | `pythia:Pythia/raw/pypi/` + `pythia:Pythia/recovery/pypi/` | Clean |
| GitHub | `pythia:Pythia/raw/github/` | Clean |
| Stack Overflow | `pythia:Pythia/raw/stackoverflow/` + local `data/raw/stackoverflow/` | Clean (split local/remote) |
| CodeSearchNet | `pythia:Pythia/raw/codesearchnet/` | Clean |
| The Stack | `pythia:Pythia/raw/the_stack/` | Clean |
| Jupyter | local `data/raw/jupyter/` (empty) | Empty (no data) |

**Cross-namespace contamination: NONE found.** No PyPI artifacts under github/peps/think_python; no github artifacts under pypi. PEP report explicitly verifies "PEP destination != PyPI destination".

**Anomaly:** `pythia:Pythia/raw/pypi/reports/` contains **two distinct files both named `pypi_pilot_report_v1.json`** (Google Drive IDs differ; sizes 522 vs 512 bytes; modtimes 2026-09-22 vs 2026-09-18). Duplicate filename collision within the reports namespace.

**Anomaly:** `pythia:Pythia/raw/pypi/metadata/.locks/writer.lock` present, owned by `909683-80f502d7` (non-Session-1 process), modtime 2026-09-25 04:41:50. Lease expired. Transient coordination artifact; not checkpoint data.

### Dataset isolation: **PASS** (with 2 noted anomalies)

---

## 2. Provenance Consistency

Required fields per `research/data_contract.md` + `research/source_schema_mapping.md`:
`source`, `source_type`, `source_url`, `acquisition_date`, `license`, `record_id`, `content_hash`.

| Dataset | source | source_url | acquisition_date | license | record_id | content_hash |
|---|---|---|---|---|---|---|
| PEP (756) | YES | YES | YES | partial | YES (`pep:NNNN`) | YES (756/756) |
| Think Python (94) | YES | YES | YES (provenance) | YES | YES (`thinkpython:...`) | YES (94/94) |
| PyPI checkpoints (3047) | implicit | NO | YES (`acquired_at`) | YES (`licence_status`) | NO (derivable `pypi:{pkg}:{ver}`) | NO |
| GitHub (150) | YES | YES (`url`) | YES (`acquired_at`) | YES (`license_key`) | **NO** | **NO** |
| Stack Overflow pilot (1000) | YES | **NO** | **NO** | **NO** | **NO** | **NO** |
| CSN pilot (1000) | YES | **NO** | **NO** | **NO** | **NO** | **NO** |
| The Stack pilot (1000) | YES | **NO** | **NO** | **NO** | YES (`record_id: 0` placeholder) | **NO** |
| Python docs (manifest) | YES | YES | **NO** (retrieved_at only) | YES | schema: `python_docs:{ver}:{hash}` | YES (sha256 in manifest) |

**Schema inconsistencies (confirmed):**
- Stack Overflow, CodeSearchNet, The Stack pilot records carry only `source` + `collected_at` + dataset_name; they lack the canonical required fields (`source_url`, `acquisition_date`, `license`, `record_id`, `content_hash`).
- GitHub records lack `record_id` and `content_hash` (they have `commit_sha`, `cloud_path`, `state` instead).
- The Stack `record_id` is the integer `0` (placeholder, not a real identifier).
- PyPI checkpoints lack `source_url`, `record_id`, `content_hash` (derivable but not persisted; documented in prior audits).
- Record-ID conventions inconsistent across sources: `pep:0001`, `thinkpython:chapter:01`, `pypi:{pkg}:{ver}` (schema), `{owner}_{repo}_{commit}` (GitHub schema, not populated), SO/CSN/TheStack absent/placeholder.

### Provenance consistency: **PARTIAL**

---

## 3. Manifest Consistency

| Dataset | Candidates | Acquired | Failed | Skipped | Duplicates | Manifest SHA | Reconciled |
|---|---|---|---|---|---|---|---|
| PEP | 756 | 756 | 0 | 0 | 0 | `9cbf1a73...` (verified) | YES |
| Think Python | 94 | 94 | 0 | 0 | 0 | (in manifest) | YES |
| GitHub | 150 | 19 | 1 | 113 | 0 | `9614a6d4...` | PARTIAL — mixed states (7 LEGACY_ACQUIRED_UNVERIFIED, 9 TIMEOUT_PERMANENT, 1 RESUME_SNAPSHOTTING) |
| PyPI | 5,000 | 2,945 | 102 | 0 | 0 | `e26e2035...` (verified) | YES (3047 checkpoints = 2945 + 102) |
| Stack Overflow (local) | 0 selected | 0 | 0 | 0 | 0 | — | Remote has 1000 pilot + 10000 scaleup; local candidates=0 |
| CSN | (1000 pilot) | — | — | — | — | — | Pilot only |
| The Stack | (1000 pilot) | — | — | — | — | — | Pilot only |

**Verified:** PEP manifest SHA `9cbf1a73f4c478a8ec74c567900875639ce01ef6e0a7a9d3340964b117e8d30d` matches the mission-stated value. PyPI candidates SHA `e26e2035...` unchanged.

**Discrepancies:**
- GitHub candidate states do not sum to a clean acquired/failed accounting (150 = 19 ACQ + 1 FAIL + 7 LEGACY + 9 TIMEOUT + 113 SKIP + 1 RESUME). "Skipped: 113" dominates — the acquisition is in-progress/pilot-scoped.
- Stack Overflow: local `stackoverflow_candidates_v1.jsonl` = 0 selected, but remote has 1000 pilot / 10000 scaleup records. The local manifest and remote data are not reconciled in a single canonical manifest.

### Manifest consistency: **PARTIAL**

---

## 4. Storage Architecture

| Session / Source | Storage mechanism |
|---|---|
| Session 2 – PEP | direct rclone (`rclone_lsf/cat/copyto` to `pythia:Pythia/raw/peps`) |
| Session 2 – Think Python | direct rclone (`pythia:Pythia/raw/think_python`) |
| Session 3 – PyPI | `pypi_storage.py` abstraction (gated by `PYPI_REMOTE_STORAGE`); POSIX fallback |
| Session 4 – GitHub | direct rclone (`github_acquire.py`, `check_drive_mounted` verifies rclone not FUSE) |
| Stack Overflow scrapers | **FUSE mount dependency** — `stackoverflow/config.py: DRIVE_ROOT = "/mnt/pythia-cloud/Pythia"`, `run_all.py: os.path.ismount("/mnt/pythia-cloud")` raises if not mounted |

**Key finding:** Stack Overflow scrapers require the `/mnt/pythia-cloud` FUSE mount (`os.path.ismount` check), which is **not present** in the current environment (confirmed `not a mountpoint`). PEP/Think Python/GitHub use direct rclone (mount-independent). SO is the outlier that would fail to run in the current environment.

**PyPI storage:** abstraction correctly isolated to `pythia:Pythia/raw/pypi`; Session 4 `raw/github` paths are rejected by `is_session4_path`. No namespace collisions, no cache duplication detected. `.staging/` absent (clean).

### Storage architecture: **PARTIAL** (SO FUSE-mount dependency)

---

## 5. Training-Stage Separation

- PEP → Base pretraining (confirmed in PEP report: "NOT SFT/reasoning/neurosymbolic")
- Think Python → Base pretraining (per PEP report and stage1 manifest)
- PyPI → Base (checkpoints stored raw; final corpus empty)
- GitHub → Base (per PEP report ownership)
- Python docs / ATBS → Base (stage1 filtered)
- Stack Overflow, CodeSearchNet, The Stack → base-pretraining candidate sources (not yet classified as SFT in records)

**Verification:** `config.py` curriculum stages A (base) / B (SFT) / C (neurosymbolic) are defined but no SFT/reasoning/repair/AST/KG material is currently being written into base-pretraining namespaces. `final/corpus.jsonl` is **0 bytes** — raw acquisition ≠ final corpus holds. `data/filtered/stage2` (SO candidates) is 0 lines; stage3/stage4 empty.

**Ambiguity:** Stack Overflow / CSN / The Stack pilot records do not carry an explicit `stage`/`dataset_version`/`split` field, so their base-vs-SFT classification is implicit (by source assignment) rather than explicit in records.

### Training-stage separation: **PASS** (with implicit-classification note)

---

## 6. PyPI Immutability

| Item | Expected | Actual | Status |
|---|---|---|---|
| Checkpoints | 3,047 | 3,047 | PASS |
| ACQUIRED | 2,945 | 2,945 | PASS |
| FAILED | 102 | 102 | PASS |
| Unprocessed | 1,953 | 1,953 | PASS |
| Candidate manifest SHA | `e26e2035...` | `e26e2035...` | PASS |
| Acquisition manifest | — | record_count 2,945 | PASS |
| Freeze | ACTIVE | **ABSENT (REMOVED during audit)** | **FAIL** |
| Recovery | 50 records (48/1/1) | 50 records (48/1/1) | PASS |
| Quarantine | 13 files | 13 files | PASS |
| `.staging/` | absent | absent | PASS |

**CRITICAL — Freeze sentinel removed during this audit.**
- At audit start (2026-09-25 ~04:41 UTC) `.FREEZE_SENTINEL` was PRESENT at `pythia:Pythia/raw/pypi/.FREEZE_SENTINEL` (content: "PyPI baseline FROZEN during Session 2 recovery...").
- At audit end (~04:45 UTC) the sentinel is ABSENT — `rclone lsf/cat` returns "directory not found"; the PyPI root lists only manifests/, metadata/, packages/, remediation_v1/, reports/.
- **This mission did NOT remove it** (strictly read-only: `cat`/`lsf`/`hashsum` only). An external process removed it during the audit window.
- Checkpoints (3,047), manifests, recovery (50), quarantine (13) remain unchanged — but the freeze guard is no longer present, so PyPI writes are no longer refused by the sentinel.

**No unauthorized acquisition detected** (no new checkpoints, manifests unchanged). The freeze-sentinel removal is the only PyPI immutability violation observed.

### PyPI immutability: **FAIL** (freeze sentinel removed by external process; all data otherwise unchanged)

---

## 7. Cross-Session Compatibility

Confirmed incompatibilities that would surface at corpus-merge time:
1. **Record-ID conventions differ** across PEP (`pep:NNNN`), Think Python (`thinkpython:...`), PyPI schema (`pypi:{pkg}:{ver}`), GitHub schema (`{owner}_{repo}_{commit}`); SO/CSN/TheStack lack record_id (or placeholder `0`).
2. **Hash fields inconsistent**: PEP/ThinkPython use `content_hash`; PyPI uses `archive_sha256` (archive-level, not content); GitHub has none; SO/CSN/TheStack have none.
3. **Metadata names differ**: PyPI uses `licence_status`/`licence_reason` (UK spelling) vs schema's `license`; PEP uses `acquisition_status`; GitHub uses `state`/`last_stage`.
4. **Dataset-version conventions**: `PYTHIA-DATA-v0.x` documented but not propagated into every record; PEP/ThinkPython carry `source_commit`+`provenance`; others do not.
5. **Storage paths**: SO scrapers assume FUSE mount; PEP/TP/GitHub use direct rclone; PyPI uses abstraction — three different storage conventions.
6. **Conflicting manifests**: PyPI has 2 acquisition-manifest variants on remote (`pypi_acquisition_v1.json` record_count=2945); GitHub candidate states non-uniform; SO local-vs-remote not reconciled.
7. **Accidental source mixing**: none detected; namespaces are isolated.

### Cross-session compatibility: **PARTIAL**

---

## 8. Reproducibility

A future researcher could determine, for each source:

| Requirement | PEP | ThinkPython | PyPI | GitHub | SO/CSN/TheStack |
|---|---|---|---|---|---|
| source | YES | YES | YES | YES | YES |
| revision/version | YES (commit) | YES (commit) | version per checkpoint | commit_sha | NO |
| acquisition date | YES | YES | YES | YES | collected_at |
| candidate count | YES (756) | YES (94) | YES (5000) | YES (150) | pilot counts |
| accepted/rejected | YES (756/0) | YES (94/0) | YES (2945/102) | states | partial |
| failure reason | n/a | n/a | YES (failure_reason) | last_error | n/a |
| hashes | YES (content_hash) | YES | YES (archive_sha256) | NO | NO |
| artifact location | YES (remote) | YES | YES | YES | YES |
| dataset version | partial | partial | partial | NO | NO |

Missing evidence: SO/CSN/TheStack lack content hashes and source revisions; GitHub lacks content hash; dataset_version not propagated into all records.

### Reproducibility: **PARTIAL**

---

## Discrepancy List

| # | Dataset | Evidence | Severity | Recommended future action (NOT performed) |
|---|---|---|---|---|
| 0 | PyPI | **`.FREEZE_SENTINEL` removed during audit (external process); was present at start, absent at end** | **CRITICAL** | Re-establish freeze; investigate external writer; re-assert execution lock |
| 1 | PyPI reports | Duplicate `pypi_pilot_report_v1.json` (2 Drive IDs, sizes 522/512) | LOW | Reconcile to a single canonical report |
| 2 | GitHub | No `record_id`/`content_hash` in 150 records; mixed states incl. 113 SKIPPED | MEDIUM | Populate record_id + content_hash per schema; reconcile state accounting |
| 3 | SO/CSN/TheStack | Pilot records lack required provenance fields (source_url, license, record_id, content_hash) | HIGH | Add canonical provenance fields or document as pre-processing pilot |
| 4 | The Stack | `record_id: 0` placeholder | MEDIUM | Generate real record_id |
| 5 | Stack Overflow storage | Scrapers require FUSE mount (`os.path.ismount`); mount absent | HIGH | Migrate SO to direct rclone (like PEP/GitHub) |
| 6 | PyPI | `licence_status` UK spelling vs schema `license`; no source_url/record_id/content_hash persisted | MEDIUM | Persist derivable fields at integration |
| 7 | All | dataset_version not propagated into records | MEDIUM | Assign `PYTHIA-DATA-v0.x` per record at corpus build |
| 8 | PyPI locks | `writer.lock` present (expired, external owner) | LOW | Investigate external writer; ensure lease discipline |
| 9 | SO local/remote | local candidates=0 selected vs remote 1000/10000 | MEDIUM | Reconcile into one canonical SO manifest |

---

## Verdicts

- **Dataset isolation:** PASS (2 noted anomalies)
- **Provenance consistency:** PARTIAL
- **Manifest consistency:** PARTIAL
- **Storage architecture:** PARTIAL
- **Training-stage separation:** PASS (implicit-classification note)
- **PyPI immutability:** FAIL (freeze sentinel removed during audit; data otherwise unchanged)
- **Cross-session compatibility:** PARTIAL
- **Reproducibility:** PARTIAL

---

**GLOBAL AUDIT — ISSUES FOUND — CRITICAL: PyPI `.FREEZE_SENTINEL` removed by external process during audit (execution no longer freeze-guarded); plus cross-session provenance/schema inconsistencies (SO/CSN/TheStack/GitHub missing canonical fields), SO FUSE-mount storage dependency, duplicate PyPI report, no dataset-version propagation; PyPI data otherwise immutable and namespaces isolated**

*This mission was strictly read-only. No datasets, manifests, checkpoints, archives, recovery state, or configuration were modified. The freeze-sentinel removal was observed, not caused, by this audit.*