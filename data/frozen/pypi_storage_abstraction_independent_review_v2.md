# PyPI Storage Abstraction — Independent Review v2 (Session 3)

Status: **REVIEW BLOCKED — EXACT BLOCKERS IDENTIFIED**
Reviewer: Session 3 (independent safety/audit, separate from Session 1 implementation and Session 2 execution control)
Date: 2026-09-24
PyPI freeze: ACTIVE. Execution: NOT AUTHORIZED.

---

## 1. Scope
Independent, read-only re-review of Session 1's FINAL storage-abstraction remediation against the previously identified blockers. No PyPI state was modified. All remote checks used read-only rclone (`lsf`, `cat`, `hashsum`, `about`).

## 2. Evidence reviewed
- `scripts/scrapers/pypi_storage.py` (850 lines: backends, path map, commit protocol, journal, `find_interrupted_commits`, `reconcile_startup`, `WriterLock`, headroom)
- `scripts/scrapers/pypi.py` (live definitions, remote-mode branches, scale-up loop)
- `scripts/scrapers/pypi_sha_recovery.py` (remote routing for recovery state)
- `tests/test_pypi_storage.py` (58 tests) and full suite (174 passed, 1 skipped, 2 subtests)
- Session 1 report `pypi_storage_abstraction_verification_v2.md` — found to be **stale vs the current code** (report: 43 storage tests / 159 total; code now has 58 / 174)
- Live read-only remote validation of `pythia:Pythia`

## 3. Previous blockers — classification
| Blocker | Class |
|---|---|
| Manifest writes not routed | **CLOSED** (live `write_candidates_manifest`/`write_acquisition_manifest` route to `save_manifest_remote` in remote mode). Limitation: pilot-report write still POSIX (`_atomic_write_json` at pypi.py:978/1380). |
| Archive writes not routed | **STILL OPEN** — see Blocking 1 |
| Remote reads not routed | **PARTIALLY CLOSED** — checkpoint read, candidate manifest read, checkpoint discovery are remote-aware; acquisition-manifest read for resume/consistency is POSIX — see Blocking 2 |
| Recovery mapping incomplete | **CLOSED** (`save_recovery_state_remote`, `recovery_state_remote`, `load_state`/`save_state` remote-routed; append refused fail-closed) |
| WriterLock not wired | **CLOSED WITH LIMITATION** — acquired in `run_pilot` (822) and `run_scaleup` (1336); advisory/best-effort; **no heartbeat during multi-hour runs** (see Blocking 5) |
| Commit journal/reconciliation incomplete | **CLOSED WITH LIMITATION** — `journal=True` option, `find_interrupted_commits()`, `reconcile_startup()` exist; journal is **opt-in, not default**; `reconcile_startup` not called at run start |
| POSIX checkpoint discovery | **CLOSED** (`_iter_checkpoint_paths` remote-aware) |
| POSIX archive verification | **STILL OPEN** — see Blocking 3/4 |
| Incomplete crash recovery | **CLOSED WITH LIMITATION** — journal/reconcile infra exists but opt-in |
| No proof of remote-mode resume safety | **NOT PROVEN** — resume boundary is computed from a POSIX manifest read; no test exercises remote-mode resume — see Blocking 2 |

## 4. Current implementation verification
**Correct in remote mode (`PYPI_REMOTE_STORAGE=1`):** `_save_checkpoint`→`save_checkpoint_remote`; `_load_checkpoint`→`remote_read_text`; `_iter_checkpoint_paths`→`remote_checkpoint_names`; `_read_checkpoint_content`→`remote_read_text`; `write_candidates_manifest`/`write_acquisition_manifest`→`save_manifest_remote`; `load_candidates_manifest`→`remote_read_text`; `run_pilot`/`run_scaleup` freeze guards remote-aware; `verify_storage_headroom`→`remote_headroom`; recovery `save_state`/`load_state` remote-routed; identity gate `verify_archive_identity` wired in pilot (931) and scaleup (1537).

## 5. WriterLock findings
- Call sites: `run_pilot` (822), `run_scaleup` (1336). Correct acquire-before-mutate / release-in-finally.
- **No `renew()`/heartbeat anywhere during the run** (confirmed: zero `.renew(` calls in pypi.py). A 600 s lease therefore expires ~10 min into any multi-hour batch; the "held" state becomes stale and a second writer could acquire mid-run.
- Classified **ADVISORY / BEST-EFFORT** (as documented by Session 1). Google Drive/rclone has no atomic create-if-absent; two writers observing "no lock" can both proceed. Strict mutual exclusion requires an external lock service — **none exists**.

## 6. Commit / crash findings
- Protocol implemented: staging → upload → verify → promote → read-after-write verify → committed. `journal=True` writes an intent marker; `find_interrupted_commits()` detects leftovers; `reconcile_startup()` exists.
- **Limitation**: journal is opt-in and not enabled by any call site; `reconcile_startup()` is not invoked at run start. A crash during/after promote (before verify) can leave a partial final object that a naive reader could treat as committed unless `journal=True` is enabled. Promotion is **not atomic** (documented honestly).
- The 58-test suite covers interrupted-commit, journal-marker, ambiguous-fails-closed, promoted-unverified-detected, uncommitted-staging-never-checkpoint — but all against **LocalDirBackend** (POSIX-atomic), so they prove protocol logic, **not** Google Drive/rclone semantics.

## 7. Remote-read findings
- Remote-aware: checkpoint read, candidate manifest read, checkpoint discovery, recovery-state read.
- **POSIX-only still reachable in remote mode:** `get_unprocessed_candidates` (manifest read, pypi.py:1028–1030); `verify_manifest_integrity` (1049); `verify_checkpoint_consistency` acquired-count (1064); `verify_archive_count` (1100 os.walk); `generate_reconciliation_report` FAILED scan (1173–1175); scale-up loop FAILED-skip (1411–1413); archive existence/stat/SHA (1435–1445).

## 8. Resume findings
- **BLOCKING**: `get_unprocessed_candidates` reads the acquisition manifest via POSIX `PYPI_ACQUISITION_MANIFEST_PATH.read_text` (1028–1030). With the FUSE mount down, `exists()` → False → processed set empty → **all 5,000 candidates are treated as unprocessed → resume would restart at rank 1, not 3048.** No test exercises remote-mode resume boundary.
- Also: the scale-up loop FAILED-skip (`cp.exists()`/`cp.read_text()`, 1411–1413) is POSIX → FAILED checkpoints are **not skipped in remote mode** → re-processing of 102 FAILED records.
- `get_unprocessed_candidates` also still hardcodes only `{dbt-semantic-interfaces, metricflow}` as failed (1037) — inconsistent with the 102-failed accounting.

## 9. Identity findings
- Identity chain intact: `verify_archive_identity` (159) checks package/version/distribution/filename/metadata/SHA; extraction and content_hash/normalized_hash in recovery pipeline. Wired into scale-up (1537) and pilot (931).
- The historical latest-version/first-non-yanked mismatch cannot silently pass: it is rejected as `identity_mismatch:filename_version_mismatch` (as evidenced by the 6 quarantined externals).
- Cache reuse cannot bypass identity validation: the identity gate is applied to the (re)downloaded archive regardless; a reused archive still passes the gate. (Note: in remote mode the archive-existence check is POSIX and broken, so reuse actually fails to local-read — see Blocking 4.)

## 10. Test evidence
- Full suite: **174 passed, 1 skipped, 2 subtests**. Storage: **58 tests**.
- **UNIT PROOF (LocalDirBackend only):** path mapping, freeze-block, checkpoint/manifest/archive commit, read-after-write verify, staging never authoritative, WriterLock acquire/renew/stale-takeover, journal/crash markers, recovery path mapping, immutability, resume-after-commit, headroom.
- **REMOTE SEMANTICS PROOF: NONE.** No test exercises `RcloneBackend` against `pythia:Pythia`; no test covers remote-mode resume boundary, remote-mode FAILED-skip, or remote-mode archive download. The live `writer.lock` on the remote (owner `prot-a`) suggests an external protocol/lock test ran against the real remote — unverified, un-cleaned.

## 11. Live read-only validation (rclone lsf/cat/hashsum/about)
- `pythia:Pythia` reachable; `.FREEZE_SENTINEL` present; checkpoints 3,047; acquisition manifest `record_count=2945`; candidate manifest SHA `e26e2035…`; acquisition manifest SHA `e081a09e…`; recovery state 50 (48 RECOVERED_VERIFIED / 1 NO_PYTHON_CODE / 1 IDENTITY_MISMATCH); quarantine 13 files; `.staging` absent.
- **Finding:** `pythia:Pythia/raw/pypi/metadata/.locks/writer.lock` **exists** — `{"owner_id":"prot-a","acquired_at":1790270221,"lease_expires_at":1790270821}` (created 2026-09-24 17:17 UTC, 600 s lease, unexpired at review time). A lock object was **written to the frozen remote** — an immutability violation and evidence of a live remote write during the freeze. Not part of the frozen baseline.

## 12. Immutability verification
| Item | Expected | Observed | Status |
|---|---|---|---|
| Checkpoints | 3,047 | 3,047 | UNCHANGED |
| ACQUIRED | 2,945 | 2,945 | UNCHANGED |
| FAILED | 102 | 102 | UNCHANGED |
| Unprocessed | 1,953 | 1,953 | UNCHANGED |
| Candidate SHA | e26e2035… | e26e2035… | UNCHANGED |
| Acquisition SHA | e081a09e… | e081a09e… | UNCHANGED |
| Recovery | 50 | 50 | UNCHANGED |
| Quarantine | 13 | 13 | UNCHANGED |
| Freeze | ACTIVE | ACTIVE | UNCHANGED |
| `.staging/` | absent | absent | OK |
| `.locks/writer.lock` | absent | **PRESENT** | **VIOLATION** |

## 13. Guarantee matrix
| Guarantee | Class | Evidence |
|---|---|---|
| Remote path mapping | CLOSED | code + tests (LocalDir) |
| Freeze-before-write (checkpoint path) | CLOSED WITH LIMITATION | remote-aware; check-then-act |
| Freeze-before-write (run entry) | CLOSED | remote-aware guard |
| Single-writer exclusion | **NOT GUARANTEED** | advisory lock; no heartbeat; no external service |
| Atomic remote replace | **NOT GUARANTEED** | Drive/rclone has none; fail-closed verify only |
| Archive download (remote mode) | **NOT WIRED** | live `_download_file` is POSIX |
| Remote-mode resume boundary | **NOT PROVEN / BROKEN** | POSIX manifest read |
| Remote-mode FAILED skip | **NOT WIRED** | POSIX `cp.exists()`/`cp.read_text()` |
| Remote-mode archive verify | **NOT WIRED** | POSIX `sha256_file`/`.stat()` |
| Crash reconciliation | CLOSED WITH LIMITATION | journal opt-in; reconcile not invoked |
| Session 4 isolation | CLOSED | `is_session4_path` + tests |

## 14. Remaining limitations
- Advisory writer lock (strict exclusion needs an external lock service — none present).
- Non-atomic remote promotion (fail-closed verify; journal opt-in; no startup reconciliation by default).
- Pilot-report write still POSIX in remote mode.
- Live `writer.lock` on the frozen remote (immutability violation).

## 15. Blocking findings (exact)
1. **Live `_download_file` is POSIX-only.** Two definitions exist; the last (pypi.py:981) is the legacy POSIX `.part`+`rename`; the remote-routed version (772) is shadowed dead code. Archive acquisition in remote mode writes to the unmounted FUSE path → fails.
2. **Remote-mode resume boundary is wrong.** `get_unprocessed_candidates` (1024) reads the acquisition manifest via POSIX; with the mount down, all 5,000 candidates are treated as unprocessed → resume would restart at rank 1, not 3048.
3. **Remote-mode FAILED skip is broken.** Scale-up loop `cp.exists()`/`cp.read_text()` (1411–1413) is POSIX → the 102 FAILED records would be re-processed in remote mode.
4. **Remote-mode archive verification/reuse is broken.** `archive_path.exists()`/`.stat()`/`sha256_file()` (1435–1445) are POSIX → archives cannot be SHA-verified or reused in remote mode.
5. **WriterLock has no heartbeat.** `run_scaleup`/`run_pilot` acquire a 600 s lease with no `renew()`; a multi-hour run loses its lock after ~10 min → a second writer could acquire mid-run. Advisory only.
6. **Immutability violation.** A live `writer.lock` object exists on the frozen remote (owner `prot-a`, unexpired) — a remote write/lock creation during the freeze; not part of the frozen baseline; must be removed/accounted for by Session 2.
7. **No remote-mode resume/execution test.** All 58 storage tests use LocalDirBackend; none exercise `RcloneBackend`, remote-mode resume boundary, FAILED skip, or archive download.

## 16. Exact conditions for Session 2's final preflight
Before any execution preflight can be considered:
1. Collapse the duplicate `_download_file` definitions so the live function routes through `save_archive_remote` in remote mode; add a remote-mode archive-download test.
2. Route `get_unprocessed_candidates` (and `verify_manifest_integrity`, `verify_checkpoint_consistency` acquired-count, `verify_archive_count`, reconciliation FAILED scan) through the backend; add a remote-mode resume-boundary test asserting 3,048.
3. Route the scale-up FAILED-skip and archive existence/SHA checks through the backend.
4. Add a WriterLock heartbeat (`renew`) loop inside `_run_scaleup_locked`/`_run_pilot_locked`; document lease re-acquisition on loss; or provide an external lock service for strict exclusion.
5. Enable `journal=True` by default on checkpoint/manifest/archive/recovery writes and call `reconcile_startup()` at run start; add a startup-reconciliation test.
6. Remove/account for the live `writer.lock`; re-verify immutability (3,047/2,945/102/1,953; SHAs; recovery 50; quarantine 13).
7. Re-run full suite (expect ≥174 passed) plus the new remote-mode tests; verify no `RcloneBackend` write tests touch `pythia:Pythia` without an explicit, authorized protocol test.

---

## FINAL REVIEW DECISION

**C. REVIEW BLOCKED — exact blockers: (1) live `_download_file` POSIX-only; (2) remote-mode resume boundary wrong (POSIX manifest read → rank-1 restart); (3) remote-mode FAILED-skip broken; (4) remote-mode archive verification/reuse broken; (5) WriterLock no heartbeat (lease expires mid-run); (6) immutability violation — live `writer.lock` on the frozen remote; (7) no remote-mode resume/execution tests.**

This does NOT authorize execution. The freeze must remain ACTIVE.