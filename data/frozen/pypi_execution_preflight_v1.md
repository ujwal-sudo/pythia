# SESSION 2 — PYPI EXECUTION PREFLIGHT (READ-ONLY, NOT EXECUTED)

Status: PREFLIGHT COMPLETE — EXECUTION NOT AUTHORIZED (fuse mount BLOCKED)

## Infrastructure verification
- Authoritative fuse mount raw/pypi: UNAVAILABLE (mount down; rclone remote works read-only) — BLOCKER for execution
- Candidate manifest SHA: e26e2035f67b6467... MATCH
- Checkpoints: 3047 MATCH
- Manifest SHA: e081a09ef4b6f62d... MATCH
- Recovery: 50 (48 VERIFIED / 1 MISMATCH / 1 NO_PYTHON) MATCH
- Quarantine: 6 MATCH
- Freeze sentinel: PRESENT MATCH
- Competing writer: none MATCH
- Scale-up/pilot process: none MATCH
- Identity gate: PRESENT (pypi_sha_recovery + verify_archive_identity) MATCH
- Resume boundary: 3048 MATCH (1,953 unprocessed)
- Historical checkpoint rewrite protection: VERIFIED (freeze-sentinel guard raises OSError)
- ACQUIRED/FAILED skip: VERIFIED (pending-skip in recovery)
- Deterministic failures cannot become ACQUIRED: VERIFIED (IDENTITY/HASH/NO_PYTHON gates)
- Full identity required: VERIFIED (sha/filename/metadata identity in recover_one)
- 93-transient retry policy: VERIFIED (existing pypi_sha_recovery policy)
- Execution plan current: VERIFIED (pypi_final_recovery_execution_plan_v1.md)

## PHASE C DRY-RUN PLAN — 93 transient FAILED records
- Exact starting set: the 93 baseline FAILED records with network-error reasons
  (metadata_fetch_failed / unexpected_error:ConnectionResetError)
- Selection mechanism: from FAILED checkpoints; SHA-anchor each against PyPI release history
- Concurrency: single process; no parallel writers (freeze sentinel + no competing writer)
- Checkpoint behavior: on success write RECOVERED_VERIFIED to recovery state ONLY (never historical);
  historical FAILED checkpoint NOT rewritten
- Identity gate: requested==resolved==filename==metadata==SHA before any RECOVERED_VERIFIED
- SHA verification: computed downloaded SHA == expected SHA (fail -> HASH_MISMATCH)
- Failure behavior: NETWORK_ERROR / ARCHIVE_UNAVAILABLE / IDENTITY_MISMATCH / QUARANTINE; never ACQUIRED
- Resumability: per-record recovery state persisted after each; rerun skips completed
- Duplicate prevention: recovery_id keyed by pkg:ver; pending-skip on existing state
- Stopping conditions: batch limit; storage headroom; sentinel present; any anomaly re-arms guard
- Rollback/containment: all writes under /mnt/pythia-cloud/Pythia/recovery/pypi/; quarantine on mismatch

## PHASE D DRY-RUN PLAN — 1,953 unprocessed candidates (ranks 3048-5000)
- Exact starting set: candidate manifest ranks 3048-5000 (1,953)
- Selection mechanism: sequential by rank from candidate manifest (unchanged, SHA e26e2035)
- Concurrency: single process; explicit control; no competing writers
- Checkpoint behavior: NEW checkpoints only (ranks >= 3048); historical 2,945 never touched
- Identity gate: full package/version/filename/metadata/SHA verification before ACQUIRED
- SHA verification: downloaded SHA == PyPI digest; fail -> FAILED (deterministic)
- Failure behavior: FAILED checkpoint with deterministic reason; never silent partial
- Resumability: per-record checkpoint; rerun skips completed
- Duplicate prevention: skip if checkpoint exists (ACQUIRED/FAILED) for that package
- Stopping conditions: max-batches; storage headroom; any guard anomaly stops
- Rollback/containment: freeze sentinel re-armed on anomaly; recovery area isolation

## Exact execution prerequisites
1. Fuse cloud mount RESTORED and verified (Session 1 reports restoration) — CURRENTLY NOT MET
2. Session 3 final 5K-resume audit accepted (for Phase D)
3. Freeze sentinel explicitly removed by authorized session (Phase D only)
4. Candidate manifest SHA remains e26e2035...
5. Checkpoint state remains 3,047/2,945/102
6. Identity gate enforced for every record
7. Resume begins at rank 3048 only
8. No historical checkpoint rewritten; no FAILED silently converted
9. Deterministic checkpoints on failure; concurrency controlled

## Blockers
1. Fuse mount NOT restored (Session 1 has not reported) — HARD BLOCKER for all execution
2. Phase D additionally requires Session 3 5K audit acceptance
3. Freeze removal requires explicit authorization (not granted)

## Final authorization status
EXECUTION NOT AUTHORIZED. Preflight is PREPARATION-COMPLETE only.
