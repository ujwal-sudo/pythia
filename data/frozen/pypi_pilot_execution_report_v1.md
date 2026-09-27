# PYPI BOUNDED PILOT EXECUTION REPORT (Session 3 — authorized pilot)

Status: **PILOT COMPLETE — STOPPED FOR MANDATORY RECONCILIATION — AWAITING NEXT AUTHORIZATION**
Date: 2026-09-25
Authorization scope: bounded pilot only (freeze removal + 3-candidate batch).

---

## 1. Pilot configuration

- Execution mode: `PYPI_REMOTE_STORAGE=1`, `PYPI_STORAGE_ALLOW_REMOTE_WRITE=1`,
  `PYTHIA_DATA_ROOT=/mnt/pythia-cloud/Pythia`
- Command: `scaleup --batch-size 3 --max-batches 1 --verify-every 1`
- Batch: ranks 3048–3050 (state-derived next unprocessed candidates):
  `readerwriterlock` (3048), `nvidia-cuda-nvdisasm` (3049), `translationstring` (3050)
- Freeze sentinel removed under explicit authorization (event recorded in
  `pypi_freeze_removal_pilot_event_v1.md`).

## 2. Pre-flight verification (during run)

```
Loaded 5000 candidates (manifest SHA e26e2035…)
Pre-flight checkpoint state: total=3047, acquired=2945, failed=102, skipped=0
Unprocessed: 1953 (ranks 3048–5000)   # boundary derived from state, not hard-coded
```

## 3. Pilot outcome (3 candidates)

| Rank | Package | Archive | State | Reason |
|---|---|---|---|---|
| 3048 | readerwriterlock | readerwriterlock-1.0.0.tar.gz (4.4k) | FAILED | identity_mismatch:filename_version_mismatch (req 1.0.9 vs file 1.0.0) |
| 3049 | nvidia-cuda-nvdisasm | nvidia_cuda_nvdisasm-13.2.51…whl (4.34M) | FAILED | identity_mismatch:identity_unprovable_no_sha (req 13.4.92) |
| 3050 | translationstring | translationstring-0.1.tar.gz (21.1k) | FAILED | identity_mismatch:filename_version_mismatch (req 1.4 vs file 0.1) |

All 3 archives were downloaded, uploaded to the remote, SHA-verified
(expected == observed), then **REJECTED by the identity gate** because the
resolved PyPI "latest" version disagrees with the actual archive filename/version.
This is the documented systemic identity bug; the gate **failed closed** and did
not mark any package ACQUIRED. 0 acquired / 3 FAILED.

## 4. Required validation properties

1. remote download — PASS (3 temp downloads → `save_archive_remote`)
2. remote archive write — PASS (3 archives present on `pythia:…/packages/`)
3. checkpoint creation — PASS (3 checkpoints written remotely)
4. checkpoint hash — PASS (`archive_sha256_expected == archive_sha256_observed`)
5. journal behavior — PASS (staging dir empty; no leftover journal markers)
6. reconciliation — PASS (`reconcile_startup()` at start returned clean)
7. WriterLock heartbeat — PASS (acquired, held; lease renewed; ownership confirmed via robust readback)
8. ownership protection — PASS (robust ownership confirmation; stale takeover tested)
9. resume state — PASS (unprocessed=1953 derived from authoritative state, starting rank 3048)
10. failure accounting — PASS (3 FAILED recorded; ACQUIRED unchanged; categories preserved)
11. no POSIX fallback — PASS (all I/O through the storage abstraction; `PYPI_REMOTE_STORAGE=1`)

## 5. Post-pilot reconciliation (read-only)

```
Candidates:       5,000  (SHA e26e2035… UNCHANGED)
Checkpoints:      3,050  (was 3,047; +3 pilot FAILED)
ACQUIRED:         2,945  (UNCHANGED — pilot acquired 0)
FAILED:             105  (was 102; +3 pilot identity-mismatch)
TIMEOUT:              0
Unprocessed:      1,950  (next derived rank 3051)
Acquisition manifest SHA: e081a09e… (UNCHANGED — FAILED not in ACQUIRED manifest)
Canonical archives: 2,957  (was 2,954; +3 pilot archives)
Recovery:            50   (UNCHANGED)
Quarantine:          13   (UNCHANGED)
Journal/staging:     clean
Freeze:             REMOVED (by this authorized pilot; re-arm pending)
```

## 6. Leftover writer lock (documented)

- `metadata/.locks/writer.lock` remains from the pilot process (owner
  `972092-076fbad7`, lease unexpired at report time). The pilot process was
  interrupted during post-batch report generation (tool timeout) before
  releasing the lock. This is a stale leftover of THIS authorized pilot — not
  the historical prot-a lock. It is documented, not deleted; future runs will
  take it over via designed stale-lock recovery once the lease expires.

## 7. Interruptions during execution (documented)

- Attempt 1: stalled in the pre-flight checkpoint scan (fixed: verify_checkpoint_consistency
  optimized); no state written.
- Attempt 2: WriterLock takeover ownership-confirmation failed under Google Drive eventual
  consistency (fixed: robust readback); left a fresh lock.
- Attempt 3: SUCCESSFUL pilot (this run). Lock left un-released due to post-batch timeout.

## 8. STOP — MANDATORY GATE

Per authorization: STOP → RECONCILE → REPORT → WAIT FOR NEXT AUTHORIZATION.

NOT authorized: 93 transient recovery, 3 deterministic, 6 quarantined, full resume,
5K scale-up, background acquisition, corpus population.

## 9. Recommended next authorization request

- Re-arm the freeze sentinel (or hold the freeze OFF only under explicit new authorization).
- Resolve the systemic latest-version/archive-version identity bug before any full resume,
  OR treat identity-rejected packages as FAILED (as designed) and continue.
- Then: controlled recovery of the 93 transient FAILED (Phase C), then authorized resume.

STOPPED. Awaiting explicit authorization.