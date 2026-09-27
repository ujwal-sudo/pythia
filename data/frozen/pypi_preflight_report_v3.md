# PYPI PREFLIGHT REPORT (v3) — Session 3 (PyPI Owner)

Status: **PYPI PREFLIGHT — READY FOR EXPLICIT EXECUTION AUTHORIZATION**
Date: 2026-09-25
Freeze: ACTIVE. Freeze removal: NOT AUTHORIZED. Execution: NOT AUTHORIZED.

---

## 1. State

```
Candidates:      5,000   (SHA e26e2035f67b646796a7cfa1474ae2e39fcccd14b13daa333090b2f9652532dc)
Checkpoints:     3,047
ACQUIRED:        2,945
FAILED:            102
TIMEOUT:             0
Unprocessed:     1,953   (ranks 3048–5000; next unprocessed rank 3048)
```

All values re-verified read-only against `pythia:Pythia` after remediation (rclone lsf/cat/hashsum only). No PyPI state was modified.

## 2. Failure classes (preserved, distinguishable)

```
Transient:              93   (eligible for controlled exact-version retry ONLY after execution authorization)
Deterministic:           3   (dbt-semantic-interfaces, docx2txt, metricflow — manual review before retry)
Identity mismatch:       6   (ranks 3042–3047 — quarantined, not retried)
```

## 3. Archives

```
Canonical archives:      2,954   (2,945 ACQUIRED + 9 FAILED-with-archive)
ACQUIRED with archive:   2,945   (0 missing — the earlier "7 missing" was an inventory file-filter artifact
                                 that missed .tgz archives: dill, icalendar, multiprocess, pathos, pox,
                                 ppft, texttable all verified present)
Missing:                    0
Hash failures:              0 (identity gate + SHA verification enforced on every archive path)
```

## 4. Control safety

```
WriterLock:            WIRED (acquired in run_pilot/run_scaleup via protected lifecycle)
Heartbeat:             ACTIVE (background thread renews every 30 s; ownership loss → LockNotHeldError, fail closed)
Remote storage:        PYPI_REMOTE_STORAGE=1 routes writes/reads through the storage abstraction
Journal:               MANDATORY (journal=True on checkpoint/manifest/archive/recovery/report writes)
Reconciliation:        reconcile_startup() invoked at run start in remote mode; AMBIGUOUS /
                       PROMOTED_UNVERIFIED state blocks start (fail closed)
Remote resume:         boundary derived from authoritative state = 3048 (verified read-only; not hardcoded)
Remote archive access: backend-aware (existence/SHA/reuse/identity-metadata parsed from remote bytes)
Remote download:       consolidated _download_file routes through save_archive_remote (no shadowing)
Remote FAILED-skip:    backend-aware _load_checkpoint; 102 FAILED records skipped
Write guard:           PYPI_STORAGE_ALLOW_REMOTE_WRITE=1 required for real-remote writes (accident protection)
```

## 5. Remediation performed this session (code only; no PyPI data changed)

1. Consolidated `_download_file` — removed the legacy POSIX duplicate (pypi.py) that shadowed the remote-aware implementation.
2. Removed shadowed legacy POSIX `write_candidates_manifest`/`write_acquisition_manifest` duplicates.
3. Made commit journal mandatory (`journal=True`) in `save_checkpoint_remote`, `save_manifest_remote`, `save_archive_remote`, `save_recovery_state_remote`, and recovery `commit_write`.
4. Wired `reconcile_startup()` into `run_pilot`/`run_scaleup` (fail-closed on ambiguous/unverified remote state).
5. Switched `run_pilot`/`run_scaleup` to the `WriterLock.protected()` lifecycle (heartbeat thread, freeze check, ownership-loss fail-closed).
6. `get_unprocessed_candidates` now derives FAILED from authoritative checkpoint state (was hardcoded 2).
7. `generate_reconciliation_report` FAILED scan now backend-aware over all checkpoints.
8. Added remote-aware `_mkdir_remote_aware()` and `_write_report()` (pilot report routed through the abstraction).
9. Made `_archive_metadata_identity` backend-aware (parses PKG-INFO/METADATA from remote bytes; in-memory tar/zip parse).

## 6. Tests

```
LocalDirBackend tests:   test_pypi_storage.py (58) + shim-level coverage
Remote-wiring tests:     test_pypi_remote_wiring.py (12) — exercise the ACTUAL PYPI_REMOTE_STORAGE=1 code
                         paths (resume boundary=3048, FAILED skip, archive existence/SHA/metadata,
                         _download_file routing, freeze block, reconcile classification, WriterLock
                         heartbeat + ownership-loss fail-closed) against an isolated backend
Live remote evidence:    read-only rclone lsf/cat/hashsum (see sections 1–3, 7)
Full suite:              187 passed, 1 skipped, 2 subtests passed
```

Evidence separation maintained: LocalDirBackend tests are logic/wiring proof; live-remote evidence is read-only.

## 7. Freeze

```
Freeze:               ACTIVE (.FREEZE_SENTINEL present, verified read-only)
Freeze removal:       NOT AUTHORIZED (separate explicit gate required)
```

## 8. Historical `prot-a` writer.lock incident (preserved)

- `writer.lock` was observed present on the frozen remote (owner `prot-a`, acquired 2026-09-24 17:17 UTC, 600 s lease), documented in `pypi_storage_abstraction_independent_review_v2.md`.
- Session 3 did not create or remove it; only read-only rclone operations were performed.
- The object subsequently disappeared (a third-party remote mutation). `.locks/` is now empty and no new lock/staging exists.
- The incident remains documented as an unexplained remote mutation; evidence is not erased.

## 9. Accepted limitations (documented, not blocking)

- WriterLock is advisory/best-effort (Google Drive/rclone has no atomic create-if-absent); strict mutual exclusion requires an external lock service. Heartbeat + ownership-loss fail-closed + freeze + single-writer process control mitigate for a controlled run.
- Remote promotion is not a POSIX atomic rename; two-phase staging + read-after-write verify + mandatory journal make readers crash-safe and state fail-closed.
- Eventual consistency is handled by read-after-write retries.

## 10. Execution boundary

```
PyPI execution:   NOT AUTHORIZED
Recovery (93 transient retry): NOT AUTHORIZED
Resume (3048–5000): NOT AUTHORIZED
Phase C / Phase D: NOT AUTHORIZED
Final corpus:     NOT AUTHORIZED
```

---

## Final status

> **PYPI PREFLIGHT — READY FOR EXPLICIT EXECUTION AUTHORIZATION**

Technical readiness is established. This does NOT authorize execution. Freeze removal and execution require separate explicit authorization.