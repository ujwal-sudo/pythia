# PYPI CONTROLLED PILOT & RECOVERY EXECUTION PLAN (Session 3 — PyPI Owner)

Status: **PLAN ONLY — EXECUTION NOT AUTHORIZED**
Date: 2026-09-25
Freeze: ACTIVE. Freeze removal: NOT AUTHORIZED. Execution: NOT AUTHORIZED.

This document is the deterministic execution plan for the authorized gates that follow.
It does NOT authorize any execution.

---

## 0. Authoritative state (verified read-only 2026-09-25)

```
Candidates:      5,000  (SHA e26e2035f67b646796a7cfa1474ae2e39fcccd14b13daa333090b2f9652532dc)
Checkpoints:     3,047
ACQUIRED:        2,945
FAILED:            102  (93 transient / 3 deterministic / 6 identity-mismatch quarantined)
TIMEOUT:             0
Unprocessed:     1,953  (derived boundary = rank 3048)
Canonical archives: 2,954  (2,945 ACQUIRED + 9 FAILED-with-archive; 0 ACQUIRED missing)
Recovery:           50  (48 RECOVERED_VERIFIED / 1 NO_PYTHON_CODE / 1 IDENTITY_MISMATCH)
Quarantine:         13  files
Freeze:          ACTIVE
```

These figures must not change without new verified evidence.

---

## 1. Phase A — Freeze removal

- **Precondition:** separate, explicit authorization to remove `.FREEZE_SENTINEL`.
- Action: remove the sentinel ONLY after that authorization; record the removal timestamp in the run log.
- The write-guard `PYPI_STORAGE_ALLOW_REMOTE_WRITE=1` and `PYPI_REMOTE_STORAGE=1` must be set for any remote execution.
- Reconcile immediately after removal (read-only) before starting the pilot.

## 2. Phase B — Controlled pilot (first execution step)

Bounded, observable, single-writer, no background process.

- **Scope:** a small bounded batch (e.g., 3–5 candidates from ranks 3048+; not the 93 transient retry, not quarantine).
- **Execution path:** `run_scaleup` (remote mode) or an explicit pilot call; single process; WriterLock `protected()` lifecycle active; journal mandatory; `reconcile_startup()` fail-closed gate at start.
- **The pilot must verify:**
  1. remote download (`_download_file` → `save_archive_remote`)
  2. remote archive write (two-phase commit + SHA verify)
  3. checkpoint creation (remote, `save_checkpoint_remote`, journal=True)
  4. checkpoint hash (content/archive SHA recorded)
  5. journal behavior (marker written then cleaned; `find_interrupted_commits` empty)
  6. reconciliation (`reconcile_startup()` reports clean)
  7. WriterLock heartbeat (renewal active; ownership verified)
  8. ownership protection (loss → `LockNotHeldError`, fail closed)
  9. resume state (next rank derived from actual checkpoints, not hardcoded)
  10. failure accounting (ACQUIRED/FAILED counts increment correctly; no mixing of retry/new-candidate categories)
  11. no POSIX fallback (all I/O through the storage abstraction; `PYPI_REMOTE_STORAGE=1`)
- **Observability:** run logs + a post-pilot report artifact.

## 3. Post-Pilot Gate (MANDATORY STOP)

After the pilot, STOP and produce a fresh read-only reconciliation:
- checkpoint count, ACQUIRED, FAILED, archive count, manifest SHA, recovery state, quarantine state, journal state, lock state, freeze state, next resume boundary.
- Do NOT automatically continue to recovery.

## 4. Phase C — Recovery (93 transient FAILED only)

Only after (a) successful pilot validation AND (b) a separate explicit instruction:
- Retry scope: the **93 transient FAILED** records (exact-version, SHA-anchored, identity gate enforced).
- Excluded: 3 deterministic (manual review), 6 identity-mismatch (quarantined).
- Bounded batches; stop and reconcile between batches; no uncontrolled scale.
- Recovery accounting kept SEPARATE from new-candidate accounting.

## 5. Post-Recovery Gate (MANDATORY STOP)

Reconcile read-only. Then obtain explicit authorization before any continued acquisition/resume.

## 6. Phase D — Resume (unprocessed candidates)

- The next unprocessed rank is DERIVED from authoritative checkpoint state at execution time (currently expected 3048).
- Must not restart at rank 1, must not hard-code a checkpoint, must not silently skip candidates.
- Single writer, journal + reconcile active, identity gate enforced, freeze re-checked.

## 7. Deterministic failure handling

| Class | Count | Treatment |
|---|---|---|
| Transient | 93 | eligible for controlled automated retry in Phase C |
| Deterministic | 3 | manual investigation before any retry |
| Identity-mismatch | 6 | remain quarantined unless separately investigated |

## 8. Absolute safety rules (invariant)

Never: delete historical evidence; erase the `prot-a` incident; remove quarantine evidence; rewrite old checkpoint records; modify the frozen baseline without accounting; run concurrent acquisition; bypass WriterLock; bypass journal/reconciliation; populate `final/corpus.jsonl`; mix PyPI with PEP data.

---

## Required authorization status (report before any action)

```
PYPI PREFLIGHT:
READY

Freeze:
ACTIVE

Execution:
NOT AUTHORIZED

Planned sequence:
Pilot → reconciliation → 93 transient recovery → reconciliation → authorized resume
```

STOPPING here. Waiting for explicit authorization to remove the freeze and execute the bounded pilot.