# PYPI FREEZE-REMOVAL EVENT RECORD (Session 3 — authorized pilot gate)

Event: EXPLICIT, AUTHORIZED removal of the PyPI freeze sentinel for a BOUNDED PILOT only.
Date: 2026-09-25
Authorization: explicit user instruction authorizing freeze removal + bounded pilot execution.
Scope: pilot only. NOT authorized: 93 transient recovery, 3 deterministic, 6 quarantined,
full resume, 5K scale-up, background acquisition, corpus population.

## Pre-removal frozen baseline (authoritative, verified read-only)

```
Candidates:       5,000  (SHA e26e2035f67b646796a7cfa1474ae2e39fcccd14b13daa333090b2f9652532dc)
Checkpoints:      3,047
ACQUIRED:         2,945
FAILED:             102  (93 transient / 3 deterministic / 6 identity-mismatch quarantined)
TIMEOUT:              0
Unprocessed:      1,953  (derived boundary = rank 3048)
Acquisition manifest SHA: e081a09ef4b6f62d020789df5589db1a66af355eacc65e1b69bf275152d23c4b
Canonical archives: 2,954
Recovery:            50  (48/1/1)
Quarantine:          13  files
.locks:             empty (prot-a incident documented separately, evidence preserved)
.staging:           absent
```

## State-derived next unprocessed candidates (pilot target set, ranks 3048+)

```
3048 readerwriterlock
3049 nvidia-cuda-nvdisasm
3050 translationstring
3051 isal
3052 recurring-ical-events
3053 apify-fingerprint-datapoints
```

## Removal action

- Sentinel: pythia:Pythia/raw/pypi/.FREEZE_SENTINEL
- Action: `rclone delete` (authorized, single object).
- Execution config for the pilot: PYPI_REMOTE_STORAGE=1, PYPI_STORAGE_ALLOW_REMOTE_WRITE=1,
  PYTHIA_DATA_ROOT=/mnt/pythia-cloud/Pythia.
- Pilot path: run_scaleup (remote mode, WriterLock protected lifecycle, journal mandatory,
  reconcile_startup fail-closed gate), bounded batch, max_batches=1.
- Any ambiguity / ownership loss / journal inconsistency / unexpected state => FAIL CLOSED AND STOP.

## Historical evidence preservation

The frozen-baseline snapshot above, the prot-a lock incident record, the preflight report,
and this event record are preserved in data/frozen/. No historical evidence is deleted.
## Interrupted pilot attempt (tool timeout) — event

- The first bounded-pilot attempt was interrupted by a 900 s tool timeout while stalled in the
  pre-flight `verify_checkpoint_consistency()` (which read 3,047 checkpoints individually in
  remote mode). It was killed BEFORE reaching the batch loop.
- No checkpoints or archives were created (remote verified: checkpoints 3,047, packages 2,959).
- The WriterLock was acquired but the process was killed before release, leaving a stale
  `metadata/.locks/writer.lock` (600 s lease, now expired; owner = the killed pilot process).
  This is NOT the historical prot-a lock. It is a stale leftover of this run and will be taken
  over by the next run's designed stale-lock recovery (tested: test_expired_lock_takeover).
- Fix applied: `verify_checkpoint_consistency()` optimized to derive acquired/failed from the
  acquisition manifest record_count + remote checkpoint-name listing (one lsf) instead of
  reading every checkpoint individually.
