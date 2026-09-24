# SESSION 2 — PYPI STORAGE ABSTRACTION REVIEW ADJUDICATION + REMEDIATION GATE (v1)

## 1. VERIFIED REPOSITORY FACTS
- scripts/scrapers/pypi_storage.py EXISTS (29,607 bytes): path mapping, StorageBackend/
  RcloneBackend/LocalDirBackend, freeze protocol, commit_write/promote_staged, save_checkpoint_remote,
  save_manifest_remote, save_archive_remote, save_recovery_state_remote, WriterLock, remote_headroom.
- tests/test_pypi_storage.py EXISTS (17,979 bytes): 39 tests, ALL PASS (39/39 in 0.63s).
- pypi.py IMPORTS storage symbols; PYPI_REMOTE_STORAGE env flag defined (default off).
- _save_checkpoint IS remote-wired (freeze via freeze_sentinel_exists in remote mode; routes to
  save_checkpoint_remote when enabled). mark_acquired/mark_failed go through _save_checkpoint.
- verify_storage_headroom IS remote-wired (remote_headroom when enabled; else local shutil).
- pypi_sha_recovery.py save_state IS remote-wired (assert_no_freeze + commit_write); append_manifest
  REFUSES remote (raises RuntimeError) - honest.
- Manifest writes (_atomic_write_json -> write_acquisition_manifest) NOT remote-wired (pure POSIX).
- Archive downloads (_download_file -> part.open/part.replace) NOT remote-wired (pure POSIX).
- Read paths (_load_checkpoint, is_acquired, checkpoint discovery, manifest reads, resume-boundary)
  NOT remote-wired (pure POSIX pathlib).
- WriterLock class EXISTS in pypi_storage.py (with __enter__/__exit__) but has ZERO call sites in
  pypi.py or pypi_sha_recovery.py.
- assert_no_freeze, map_local_path_to_remote, remote_exists are imported in pypi.py but NEVER invoked
  (dead imports except the checkpoint/freeze/headroom call sites noted above).
- run_scaleup (line 1232) and run_pilot (line 742) freeze checks use POSIX PYPI_FREEZE_SENTINEL.exists(),
  NOT remote assert_no_freeze.
- Two duplicate defs in pypi.py: _atomic_write_json (504,691), _download_file (722,896); Python uses
  the LAST definition; both are pure POSIX.

## 2. SESSION 3 CLAIM-BY-CLAIM ADJUDICATION
| Claim | Finding |
|---|---|
| 1. storage functions zero call sites | PARTIALLY CONFIRMED - save_checkpoint_remote, freeze_sentinel_exists, remote_headroom ARE called (checkpoint write + headroom); but MANIFEST/ARCHIVE writes, READ paths, and WriterLock have zero call sites; assert_no_freeze/map_local_path_to_remote/remote_exists are dead imports |
| 2. real PyPI write paths remain POSIX/FUSE | PARTIALLY CONFIRMED - checkpoint writes wired; manifest/archive writes remain POSIX |
| 3. verify_storage_headroom still uses shutil.disk_usage | PARTIALLY CONFIRMED - remote_headroom used when PYPI_REMOTE_STORAGE=1; local shutil used when flag off (default) |
| 4. distributed writer locking absent | CONFIRMED - WriterLock exists but is never instantiated/called in the pipeline |
| 5. manifest/archive/recovery remote protocols incomplete/unwired | PARTIALLY CONFIRMED - recovery save_state wired; manifest+archive NOT wired; append_manifest correctly refuses remote |
| 6. recovery paths not mapped | PARTIALLY CONFIRMED - recovery save_state wired via recovery_state_remote(); recovery archives/append NOT wired |
| 7. no commit journal/startup reconciliation | CONFIRMED - no journal/reconciliation/GC in storage module (only staging naming); crash recovery not implemented |
| 8. test_pypi_storage.py absent | REFUTED - file exists with 39 tests, ALL PASS |
| 9. multiple guarantees E | PARTIALLY CONFIRMED - genuine backend limits remain (atomic conditional create, lock atomicity, consistency) but some guarantees (freeze-fail-closed in checkpoint path, Session4 isolation) are A-proven by tests |

## 3. DISPUTED TEST-FILE RESOLUTION
tests/test_pypi_storage.py EXISTS. 39 tests, all passing. Session 1's "39 storage tests" report is CORRECT;
Session 3's "test file absent" claim is REFUTED.

## 4. WIRING ANALYSIS (write classes)
| Write class | Wired? |
|---|---|
| Checkpoint (mark_acquired/mark_failed via _save_checkpoint) | WIRED |
| Headroom (verify_storage_headroom) | WIRED |
| Recovery state (save_state) | WIRED |
| Recovery manifest append | NOT WIRED (correctly refused) |
| Acquisition manifest | NOT WIRED (POSIX) |
| Candidate manifest | NOT WIRED (POSIX) |
| Archive download/commit | NOT WIRED (POSIX) |
| Writer lock | NOT WIRED (class exists, never called) |

## 5. READ-PATH WIRING ANALYSIS
| Read class | Wired? |
|---|---|
| _load_checkpoint / is_acquired | NOT WIRED (POSIX) |
| Checkpoint discovery / map | NOT WIRED (POSIX glob) |
| Manifest reads | NOT WIRED (POSIX) |
| Recovery-state reads | NOT WIRED (POSIX) |
| Resume-boundary calculation | NOT WIRED (POSIX) |

## 6. BACKEND LIMITATION ANALYSIS
Session 3's backend limitations are ACCEPTED (they reflect real Google Drive/rclone constraints):
- no atomic create-if-absent locking; remote promotion != POSIX atomic rename;
- advisory lease != guaranteed mutual exclusion; read-after-write verification != atomic commit.
These are NOT "solved" by relabeling. They remain E in the guarantee matrix unless an external primitive
is added. The storage module's two-phase staging+verify+promote is a correct best-effort design but does
NOT close these gaps.

## 7. QUARANTINE-COUNT RECONCILIATION
Quarantine dir (pythia:Pythia/recovery/quarantine_external_checkpoints_v1/) contains 13 FILES
= 6 checkpoint records + 6 archives + 1 quarantine manifest. "13 items" (Session 1) = file count;
"6 quarantined records" (authoritative) = checkpoint count. Same state, different counting convention.
NO actual state discrepancy.

## 8. ADJUDICATION SUMMARY (each claim)
- abstraction wiring: PARTIALLY CONFIRMED (checkpoint+headroom+recovery-state wired; manifest/archive/read/lock not)
- test-file existence: REFUTED (39 tests exist and pass)
- freeze wiring: PARTIALLY CONFIRMED (checkpoint path remote-aware; run_scaleup/run_pilot still POSIX)
- writer lock: CONFIRMED absent from pipeline (class only)
- checkpoint commit: CONFIRMED wired (with freeze + no-overwrite)
- archive commit: CONFIRMED NOT wired
- manifest commit: CONFIRMED NOT wired
- recovery commit: PARTIALLY CONFIRMED (state wired; archive/append not)
- read-path wiring: CONFIRMED NOT wired
- headroom: PARTIALLY CONFIRMED (conditional on flag)
- crash recovery: CONFIRMED absent (no journal/reconciliation)
- Session 4 isolation: CONFIRMED implemented + tested (A-proven)

## 9. REMEDIATION GATE
### BLOCKING (Session 1 must satisfy before any execution)
1. Wire all real PyPI write paths: acquisition manifest, candidate manifest, archive downloads/commits.
2. Wire all required READ paths: _load_checkpoint, is_acquired, checkpoint discovery, manifest reads,
   recovery-state reads, resume-boundary calculation (through the storage abstraction).
3. Route recovery archive writes + replace append-with-atomic-rewrite in remote mode.
4. Integrate WriterLock into run_scaleup/run_pilot/recovery (acquire before writes, release after) with
   lease expiry/heartbeat/stale-takeover; prove single-writer.
5. Make run_scaleup/run_pilot freeze checks remote-aware (assert_no_freeze), remove dead imports.
6. Add commit journal + startup reconciliation + stale-staging GC so interrupted commits are
   recoverable and partially-uploaded finals are never authoritative.
7. Add full test suite for the newly-wired paths (39 existing tests must continue to pass).
8. Remove POSIX-only assumptions from remote mode (read/write both abstracted).
9. Prove resume safety + historical immutability through the abstraction (tests).
10. Prove freeze-first behavior: every mutation path checks authoritative remote freeze before write.
### NON-BLOCKING
- Remove duplicate function definitions (single source of truth).
- Document backend guarantee matrix honestly; keep E classifications.
- Add Session 4 isolation coverage for read paths (currently write-path only).
### BACKEND LIMITATIONS (accepted, not fixable by code alone)
- No atomic conditional create on Google Drive -> advisory lease only; true mutual exclusion unavailable
  without an external primitive (e.g., a server-side conditional-create service).
- Remote promotion not POSIX-atomic -> two-phase verify is best-effort.
- Eventual consistency -> read-after-write retry window.

## 10. SESSION 1 ACCEPTANCE GATE AFTER REMEDIATION
PASS only when: all BLOCKING items implemented + 39 existing + new tests pass + honest guarantee matrix
keeps E classifications + no real PyPI writes during implementation/testing + read AND write paths both
abstracted + freeze enforced on every mutation path + single-writer enforced + crash reconciliation present.

## 11. EXECUTION BOUNDARY
EXECUTION NOT AUTHORIZED. Even after remediation + acceptance, Session 3 must independently re-review;
then Session 2 final preflight; then separate explicit freeze removal. Phase C/D remain blocked.

