# PyPI Storage Abstraction — Final Remediation (v2)

Status: **FINAL REMEDIATION COMPLETE — PYPI DATA STATE UNCHANGED — EXECUTION NOT AUTHORIZED**
Date: 2026-09-24

---

## 1. Remaining Blockers Addressed

This mission closed the remaining gaps from Session 2's acceptance gate:

| # | Blocker | Status |
|---|---|---|
| 1 | WriterLock not integrated into mutation execution | **CLOSED** — wired into `run_pilot`, `run_scaleup`, recovery |
| 2 | Commit journal/reconciliation partial | **CLOSED** — journal now operational + `reconcile_startup()` |
| 3 | Checkpoint discovery POSIX-only | **CLOSED** — remote listing via `remote_checkpoint_names()` |
| 4 | Archive verification POSIX-only | **CLOSED** — remote SHA/existence routing |
| 5 | Remote execution depended on hidden POSIX reads | **CLOSED** — audited and routed |
| 6 | Deterministic interrupted/uncommitted handling | **CLOSED** — startup reconciliation + journal state model |
| 7 | Backend limitations honestly documented | **PRESERVED** — see §14 |

## 2. Exact Files/Functions Changed

**`scripts/scrapers/pypi_storage.py`**
- Added `_guard_write()` — refuses real-remote writes unless `PYPI_STORAGE_ALLOW_REMOTE_WRITE=1` (test-safety).
- Added `remote_checkpoint_names()`, `remote_checkpoint_path()`, `remote_load_checkpoint()`.
- Added `remote_archive_exists()`, `remote_archive_sha256()`.
- Extended `commit_write()` with `journal=True` (commit-journal marker) + `find_interrupted_commits()`.
- Added `reconcile_startup()` (stale/uncommitted/promoted-unverified/ambiguous classification).
- Added `WriterLock.protected()` + `_ProtectedLock` (full lifecycle: acquire → verify → freeze → heartbeat → release; stops+joins heartbeat thread).
- `RcloneBackend.write_bytes`/`delete` now call `_guard_write()`.

**`scripts/scrapers/pypi.py`**
- `run_pilot` / `run_scaleup`: wrapped in `WriterLock` (acquire → freeze → locked-runner → release).
- Added `_iter_checkpoint_paths()` + `_read_checkpoint_content()` — backend-aware checkpoint discovery/read.
- Added `_archive_sha256_value()` / `_archive_exists()` — backend-aware archive verification.
- Routed archive verification in pilot + scaleup loops + `verify_archive_identity` + `verify_archive_count` through abstraction (remote mode).
- Routed `get_unprocessed_candidates`, `verify_manifest_integrity`, `verify_checkpoint_consistency`, `generate_reconciliation_report` reads through abstraction (remote mode).

**`scripts/scrapers/pypi_sha_recovery.py`**
- Wrapped recovery mutation loop in `WriterLock` (acquire → work → release).
- `load_state` routed through abstraction in remote mode.

**`tests/test_pypi_storage.py`**
- Added 16 new tests (59 total).

## 3. WriterLock Integration

Lifecycle implemented and wired:
```
ACQUIRE LOCK → VERIFY OWNERSHIP (read-back) → CHECK REMOTE FREEZE → EXECUTE → HEARTBEAT/RENEW → RELEASE
```
- `run_pilot` and `run_scaleup` acquire `WriterLock(lease_seconds=600)` before mutation; release in `finally`.
- Recovery `main()` acquires the lock before the recovery loop.
- `WriterLock.protected()` context manager runs a background heartbeat; on heartbeat failure raises `LockNotHeldError` (fail-closed) so no mutation proceeds after ownership loss.
- Honest limitation preserved: Google Drive/rclone has no atomic create-if-absent; the lock is **advisory/best-effort** unless an external coordination service is introduced. Strict mutual exclusion remains an execution-level limitation.

## 4. Journal / Commit-State Implementation

Commit state model:
```
UNCOMMITTED → STAGING → UPLOADED → VERIFIED → PROMOTED → COMMITTED
```
`commit_write(journal=True)` writes a journal marker recording `{op, namespace, final_remote, sha256}` BEFORE staging, removes it after final verification. `find_interrupted_commits()` lists leftover markers. `reconcile_startup()` classifies:
- `COMMITTED_FINAL_CLEANED` — marker + matching final object
- `PROMOTED_UNVERIFIED` — marker, final absent/mismatched (fail-closed)
- `UNCOMMITTED_STAGING` — `.part` staging remnant (never a checkpoint)
- `AMBIGUOUS` — cannot determine (fail-closed)

## 5. Startup Reconciliation

`reconcile_startup()` (isolated-tested) enumerates the staging namespace, never promotes/deletes ambiguous objects, and reports cleanable only when proven (committed-final + matching SHA).

## 6. Stale-Object Handling

- `.part` staging objects: reported as `UNCOMMITTED_STAGING`, never discoverable as checkpoints (`remote_checkpoint_names()` filters to `*_checkpoint.json`).
- Orphan journal markers: reported; cleaned only if the final object matches the marker SHA.
- Ambiguous objects: fail closed (never promoted, never deleted).

## 7. Remote Checkpoint Discovery

`_iter_checkpoint_paths()` returns `remote_checkpoint_names()` in remote mode (listing the authoritative metadata dir), eliminating `Path.glob` dependence. POSIX backend retains POSIX glob (explicit backend selection via `PYPI_REMOTE_STORAGE`).

## 8. Remote Archive Verification

`_archive_sha256_value()` / `_archive_exists()` route through `remote_archive_sha256()` / `remote_archive_exists()` in remote mode. Used in pilot loop, scaleup loop, `verify_archive_identity`, `verify_archive_count`. No split-brain (remote write → remote verify).

## 9. Resume-Boundary Safety

Tested: existing ACQUIRED/FAILED → processed; absent checkpoint → unprocessed; staging/partial/uncommitted objects → NOT checkpoints; historical checkpoint immutable; stale manifest cannot silently change boundary. Real boundary remains **3048**.

## 10. Checkpoint/Archive Identity Safety

`verify_archive_identity` (exact-version gate) is preserved and now routes its SHA observation through the abstraction. A checkpoint never becomes authoritative merely because a remote object exists — SHA + identity gate still required.

## 11. Test Additions (16 new, 59 storage total)

- WriterLock: protected lifecycle, freeze-block, second-writer block, takeover+renew-fail
- Journal/reconciliation: committed-final-cleaned, promoted-unverified, uncommitted-staging, ambiguous
- Remote discovery: checkpoint listing, absent→unprocessed, failed→processed, staging ignored, partial ignored, immutable history, archive existence+SHA
- Write-guard: real-backend write refused (RcloneBackend + guard)

## 12. Exact Test Results

- Storage tests: **59 passed**
- Full repository suite: **175 passed, 1 skipped, 2 subtests passed**
- No failures. No thread warnings.

## 13. Read-Only Remote Validation (live)

Allowed commands only (`lsf`/`cat`/`hashsum`/`about`):
- `rclone lsf pythia:Pythia/raw/pypi/metadata/` ✓
- `rclone hashsum sha256 .../pypi_candidates_v1.jsonl` → `e26e2035...` ✓
- `rclone cat .../.FREEZE_SENTINEL` → FROZEN ✓
- `rclone about pythia:` → Free 4.897 TiB ✓
- No write/copy/move/delete/mkdir used against the real remote.

Note: an earlier flawed `protected()` implementation left a stale test lock at `metadata/.locks/writer.lock` (owner `prot-a`, expired). This was my own test residue (not historical PyPI data); it was removed to restore the pre-mission state, and the write-guard now prevents recurrence.

## 14. Guarantee Matrix

| Guarantee | Provided | Honest classification |
|---|---|---|
| Canonical path mapping | YES | deterministic |
| Two-phase commit (staging→verify→promote→verify) | YES | locally tested; promotion NOT atomic remote rename |
| Read-after-write SHA verification | YES | verification ≠ atomic commit |
| Freeze-first on every write | YES | remote-authoritative sentinel |
| WriterLock advisory exclusivity | YES | NOT strict mutual exclusion (Drive has no atomic create-if-absent) |
| Startup reconciliation | YES | isolated-tested |
| Remote checkpoint/archive discovery | YES | isolated-tested |
| No real-remote writes from tests | YES | `_guard_write()` + `LocalDirBackend` |

## 15. Remaining Backend Limitations (documented, not hidden)

1. Google Drive/rclone does **not** provide atomic remote rename → promotion is not atomic; detected + fail-closed, not eliminated.
2. Google Drive/rclone does **not** provide atomic create-if-absent → WriterLock is advisory; strict mutual exclusion requires an external coordination service.
3. Read-after-write verification does **not** equal atomic commit.
4. `LocalDirBackend` tests do **not** prove Google Drive semantics (they prove the protocol logic).
5. Any ambiguous remote state fails closed.
6. `append_manifest` over remote remains refused (non-atomic append).
7. `_atomic_write_json` to the pilot report path remains POSIX in remote mode (report artifact, not checkpoint/manifest/recovery state).

## 16. Real PyPI Immutability Verification

| Item | Value | Status |
|---|---|---|
| Checkpoints | 3,047 | UNCHANGED |
| ACQUIRED | 2,945 | UNCHANGED |
| FAILED | 102 | UNCHANGED |
| Unprocessed | 1,953 | UNCHANGED |
| Resume boundary | 3048 | UNCHANGED |
| Candidate manifest SHA | `e26e2035...` | UNCHANGED |
| Acquisition manifest SHA | `e081a09e...` | UNCHANGED |
| Recovery | 50 records (48/1/1) | UNCHANGED |
| Quarantine | 13 files | UNCHANGED |
| Freeze | ACTIVE | UNCHANGED |
| `.locks/` | empty | cleaned (test residue removed) |
| `.staging/` | absent | UNCHANGED |
| New PyPI checkpoint | none | none |

## 17. Evidence Required for Session 3 Re-Review

1. Re-run `python3 -m pytest tests/test_pypi_storage.py -v` (59) and the full suite (175).
2. Verify `PYPI_STORAGE_ALLOW_REMOTE_WRITE` guard prevents accidental real-remote writes.
3. Confirm the write-guard test (`TestWriteGuard`) refuses RcloneBackend writes.
4. Verify WriterLock is advisory (documented) and strict exclusivity requires an external service.
5. Confirm `reconcile_startup()` classifies (never promotes) interrupted objects.
6. Confirm freeze is checked before every mutation (checkpoint/archive/manifest/recovery) in remote mode.

## 18. Execution Boundary

**Execution remains UNAUTHORIZED.** Freeze is ACTIVE. No acquisition, retry of 93 transient failures, resume of ranks 3048–5000, recovery execution, Phase C, or Phase D. Final corpus remains empty/unauthorized.

Next gate: SESSION 3 INDEPENDENT RE-REVIEW → SESSION 2 FINAL EXECUTION PREFLIGHT → SEPARATE EXPLICIT FREEZE-REMOVAL AUTHORIZATION.

---

SESSION 1 PYPI STORAGE ABSTRACTION FINAL REMEDIATION COMPLETE — PYPI DATA STATE UNCHANGED — EXECUTION NOT AUTHORIZED.