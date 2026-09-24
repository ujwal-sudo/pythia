# PyPI Storage Abstraction — Implementation Verification + Remediation Preparation (v2)

Status: **VERIFICATION COMPLETE — CONFIRMED FIXES APPLIED — EXECUTION NOT AUTHORIZED**
Date: 2026-09-24

---

## 1. Actual Repository Inventory

| File | Exists | Size | Notes |
|---|---|---|---|
| `scripts/scrapers/pypi_storage.py` | YES | 850 lines | Storage abstraction: backends, path map, commit protocol, WriterLock, headroom |
| `tests/test_pypi_storage.py` | YES | 446 lines, 43 test functions | Uses isolated `LocalDirBackend` |
| `scripts/scrapers/pypi.py` | YES | ~1500 lines | Modified: remote routing added |
| `scripts/scrapers/pypi_sha_recovery.py` | YES | ~450 lines | Modified: remote routing for state write/read |

**Storage module contents (verified by inspection):**
- Backends: `StorageBackend` (abstract), `RcloneBackend` (real), `LocalDirBackend` (test)
- Path mapping: `canonical_pypi_root`, `map_local_path_to_remote`, `is_session4_path`
- Read: `remote_exists`, `remote_read_bytes/text`, `remote_list`, `remote_sha256`, `verify_remote_object`
- Commit: `commit_write`, `promote_staged`, `find_interrupted_commits`
- Writes: `save_checkpoint_remote`, `save_manifest_remote`, `save_archive_remote`, `save_recovery_state_remote`
- Freeze: `freeze_sentinel_exists`, `assert_no_freeze`
- Lock: `WriterLock` (lease-based)
- Headroom: `remote_headroom`

## 2. Test-File Discrepancy Resolution

**Session 3 claimed `tests/test_pypi_storage.py` does not exist. This is FALSE (or refers to a stale snapshot).**

Actual evidence:
- File exists at `tests/test_pypi_storage.py` (446 lines)
- 12 test classes, 43 test functions
- pytest collects 43, all pass
- Tests import and exercise `scripts.scrapers.pypi_storage` directly
- All tests use `LocalDirBackend` (isolated temp dir) — no test writes to `pythia:Pythia`
- The `pythia:Pythia/...` strings in tests are path-mapping assertions only, never actual writes

The discrepancy is explained: the file was created during the immediately preceding Session 1 storage-engineering mission. Session 3's review may have predated the file's creation or inspected a different checkout state.

## 3. Complete Wiring Map

### CHECKPOINTS
| Function | Backend | Classification |
|---|---|---|
| `_save_checkpoint` | REMOTE: `save_checkpoint_remote` when `PYPI_REMOTE_STORAGE=1`; POSIX `_atomic_write_json` otherwise | **WIRED** (remote mode) |
| `mark_acquired` | calls `_save_checkpoint` | **WIRED** (inherits) |
| `mark_failed` | calls `_save_checkpoint` | **WIRED** (inherits) |
| `_load_checkpoint` | REMOTE: `remote_read_text`; POSIX otherwise | **WIRED** (this mission) |

### MANIFESTS
| Function | Backend | Classification |
|---|---|---|
| `write_acquisition_manifest` | REMOTE: `save_manifest_remote`; POSIX otherwise | **WIRED** (this mission) |
| `write_candidates_manifest` | REMOTE: `save_manifest_remote`; POSIX otherwise | **WIRED** (this mission) |
| `_regenerate_and_write_manifests` | calls the above | **WIRED** (inherits) |
| `load_candidates_manifest` | REMOTE: `remote_read_text`; POSIX otherwise | **WIRED** (this mission) |

### ARCHIVES
| Function | Backend | Classification |
|---|---|---|
| `_download_file` | REMOTE: temp + `save_archive_remote`; POSIX `.part`+`replace` otherwise | **WIRED** (this mission) |
| archive existence/verification | POSIX `.exists()`/`.stat()`/`sha256_file()` | **PARTIALLY WIRED** — verification still reads local path |

### RECOVERY
| Function | Backend | Classification |
|---|---|---|
| `save_state` | REMOTE: `commit_write(recovery_state_remote)`; POSIX otherwise | **WIRED** |
| `load_state` | REMOTE: `remote_read_text`; POSIX otherwise | **WIRED** (this mission) |
| `append_manifest` | REMOTE: **REFUSED** (non-atomic append); POSIX otherwise | **WIRED** (fail-closed) |
| recovery manifest read | POSIX | **POSIX ONLY** |

### READS
| Function | Backend | Classification |
|---|---|---|
| checkpoint discovery (`*.glob`) | POSIX `PYPI_METADATA_DIR.glob` | **POSIX ONLY** |
| `is_acquired` | calls `_load_checkpoint` | **WIRED** (inherits) |
| unprocessed candidates | calls `is_acquired` / checkpoint glob | **PARTIALLY WIRED** |
| resume boundary | from manifest + checkpoint glob | **PARTIALLY WIRED** |
| recovery-state reads | REMOTE: `remote_read_text` | **WIRED** |

### SAFETY
| Function | Backend | Classification |
|---|---|---|
| freeze check (checkpoint path) | REMOTE-aware | **WIRED** |
| freeze check (pilot/scaleup entry) | REMOTE-aware | **WIRED** (this mission) |
| writer lock | `WriterLock` defined but **NO call sites** | **UNWIRED** (defined only) |
| headroom | `verify_storage_headroom` → `remote_headroom` in remote mode | **WIRED** |

## 4. Remote-Mode Analysis (`PYPI_REMOTE_STORAGE=1`)

Paths that route through the abstraction when enabled:
- `_save_checkpoint` → `save_checkpoint_remote`
- `_load_checkpoint` → `remote_read_text`
- `write_acquisition_manifest` / `write_candidates_manifest` → `save_manifest_remote`
- `load_candidates_manifest` → `remote_read_text`
- `_download_file` → temp + `save_archive_remote`
- `verify_storage_headroom` → `remote_headroom`
- pilot/scaleup freeze guard → remote `freeze_sentinel_exists`
- recovery `save_state`/`load_state` → `commit_write`/`remote_read_text`

**Remaining POSIX operations that could still execute in remote mode:**
- `PYPI_METADATA_DIR.glob("*_checkpoint.json")` (checkpoint discovery) — POSIX
- archive verification reads (`sha256_file(archive_path)`, `.stat()`) — POSIX
- `os.walk`/`tarfile`/`zipfile` extraction (operates on local temp archives — acceptable, extraction is local-by-design)
- `_atomic_write_json`/`_atomic_write_jsonl` (still used by `_regenerate_manifests_from_checkpoints` report path and pilot report) — POSIX
- `shutil.disk_usage` only in the POSIX branch of `verify_storage_headroom`

## 5. Freeze Enforcement

Verified fail-closed behavior:
- **Sentinel exists**: `assert_no_freeze()` raises `FreezeError`; checkpoint/manifest/archive/recovery writes blocked.
- **Remote unreachable**: backend raises → write raises → fail-closed (no commit).
- **Local shadow disagrees with remote**: in remote mode the authoritative `freeze_sentinel_remote()` is used, so a stale local sentinel cannot override the remote state. (Note: a missing local sentinel + present remote sentinel still blocks, correctly.)
- Entry-point guards (`run_pilot`, `run_scaleup`) now use remote-aware freeze in remote mode.

## 6. WriterLock Analysis

- **Exists**: yes, `WriterLock` (lease-based: owner id, acquired_at, lease_expires_at, renew/heartbeat, stale takeover).
- **Call sites**: **NONE** in execution code. Defined and tested but not wired into `run_pilot`/`run_scaleup`/recovery.
- **Honesty**: the lock is **advisory/best-effort**. rclone/Google Drive does NOT provide an atomic create-if-absent primitive; two writers observing "no lock" could both attempt takeover. Documented in the class docstring. Strict mutual exclusion requires an external lock service.

## 7. Commit-Protocol Verification (wired)

| Protocol | Staging → Upload → Verify → Promote → Read-after-write → Committed |
|---|---|
| checkpoint | YES (`commit_write` + `save_checkpoint_remote`) |
| archive | YES (`commit_write` + `save_archive_remote`) |
| acquisition manifest | YES (`commit_write` + `save_manifest_remote`, record_count integrity) |
| candidate/frozen manifest | YES (`save_manifest_remote`) |
| recovery state | YES (`commit_write` + `save_recovery_state_remote`) |
| metadata (pilot report) | **NO** — still POSIX `_atomic_write_json` |

**Commit markers/journaling**: `journal=True` option added to `commit_write` (this mission) writes an intent marker; `find_interrupted_commits()` detects leftovers. Currently journaling is opt-in; not enabled by default in call sites.

## 8. Crash-Recovery Analysis

| Crash point | Observable state | Mistaken as committed? |
|---|---|---|
| before upload | nothing written | NO |
| during staging upload | `.part` staging object only | NO (readers never read staging) |
| after staging, before promote | staged object, no final | NO |
| during promote | partial final possible (backend-dependent) | **POSSIBLE** (naive reader) |
| after promote, before verify | partial final | **POSSIBLE** — mitigated only if journal marker present |
| after verify | complete final | YES (correctly committed) |

**Residual risk**: without the journal marker enabled, a crash during/after promote but before read-after-write verify can leave a partial final object that a naive reader could treat as committed. Mitigation: enable `journal=True` on all checkpoint writes OR make readers verify SHA before trusting a checkpoint. `find_interrupted_commits()` exists to support reconciliation.

## 9. Remote Read Paths

Reads now routed through abstraction in remote mode:
- `_load_checkpoint` ✓
- `load_candidates_manifest` ✓
- recovery `load_state` ✓

Still POSIX:
- checkpoint discovery (`PYPI_METADATA_DIR.glob`) 
- archive verification reads

## 10. Headroom

Remote mode: `verify_storage_headroom` → `remote_headroom` (via `rclone about`). POSIX `shutil.disk_usage` remains only in the POSIX branch (correct isolation).

## 11. Session 4 Isolation

- `is_session4_path` + `RemotePathMappingError` reject all `raw/github/*` paths.
- Verified by test `test_session4_path_isolation`.
- Session 4's active `rclone copy` (github-only) is unaffected (0 PyPI writes in its process list).

## 12. Confirmed Blocking Issues (pre-fix)

1. Manifest writes POSIX-only in remote mode — **FIXED** (this mission)
2. Archive download POSIX-only in remote mode — **FIXED** (this mission)
3. Checkpoint/read paths POSIX-only — **FIXED** (this mission: `_load_checkpoint`, `load_candidates_manifest`)
4. Pilot/scaleup freeze used local sentinel in remote mode — **FIXED** (this mission)
5. Recovery path mapping missing — **FIXED** (this mission)
6. WriterLock not wired into execution — **REMAINS** (non-blocking for verification; advisory lock not a safety guarantee)
7. No commit journal by default — **PARTIALLY ADDRESSED** (journal=True option + `find_interrupted_commits`; not enabled by default)

## 13. Implemented Remediation (confirmed safe)

- `pypi_storage.py`: recovery path mapping added; `journal` param + `find_interrupted_commits()` added.
- `pypi.py`: manifest writes, archive download, `_load_checkpoint`, `load_candidates_manifest`, pilot/scaleup freeze, all routed through abstraction in remote mode.
- `pypi_sha_recovery.py`: `load_state` routed through abstraction in remote mode.

## 14. Remaining Backend Limitations (documented, not hidden)

1. Google Drive/rclone has no atomic create-if-absent → `WriterLock` is advisory; strict exclusivity requires external lock service.
2. Promotion is not a POSIX atomic rename; a crash during promote can leave a partial final (mitigated by verify + optional journal, not eliminated).
3. `append_manifest` over remote is refused (non-atomic).
4. `os.walk`/`tarfile` extraction still operates on local temp archives (correct by design — extraction is local).

## 15. Exact Test Results

- Storage tests: **43 passed** (12 classes)
- Full project suite: **159 passed, 1 skipped, 2 subtests passed**
- No test writes to `pythia:Pythia/raw/pypi`; all use `LocalDirBackend`
- No test removes `.FREEZE_SENTINEL`, creates real checkpoints, or modifies real archives/manifests/recovery state

## 16. Real PyPI Immutability Verification

| Item | Value | Status |
|---|---|---|
| Checkpoints | 3,047 | UNCHANGED |
| ACQUIRED | 2,945 | UNCHANGED |
| FAILED | 102 | UNCHANGED |
| Unprocessed | 1,953 | UNCHANGED |
| Candidate manifest SHA | `e26e2035f67b646796a7cfa1474ae2e39fcccd14b13daa333090b2f9652532dc` | UNCHANGED |
| Acquisition manifest SHA | `e081a09ef4b6f62d020789df5589db1a66af355eacc65e1b69bf275152d23c4b` | UNCHANGED |
| Recovery | 50 records | UNCHANGED |
| Quarantine | 13 items | UNCHANGED |
| Freeze | ACTIVE | UNCHANGED |
| `.staging/` on remote | absent | no real writes |
| New PyPI checkpoint | none | none |

## 17. Handoff Requirements for Session 3

1. Independently re-run `python3 -m pytest tests/test_pypi_storage.py -v` (43 tests) and the full suite.
2. Verify `PYPI_REMOTE_STORAGE=1` code paths via code review (no real remote writes).
3. Confirm the documented backend limitations (advisory lock, non-atomic promotion, journal opt-in) are acceptable or require the external lock service.
4. Decide whether `journal=True` should be the default for all checkpoint writes before any real execution.
5. Re-verify immutability after any Session 3 review.

## 18. Execution Status

**Execution remains UNAUTHORIZED.** Freeze is ACTIVE. No acquisition, retry, resume (rank 3048), recovery execution, Phase C, or Phase D authorized. Final corpus remains empty/unauthorized.

---

SESSION 1 STORAGE ABSTRACTION VERIFICATION + REMEDIATION PREPARATION COMPLETE — PYPI DATA STATE UNCHANGED — EXECUTION NOT AUTHORIZED.