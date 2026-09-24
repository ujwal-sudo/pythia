# SESSION 2 — PYPI FINAL RECOVERY EXECUTION PLAN (DRY-RUN, NOT EXECUTED)

Freeze remains ACTIVE. This is the plan for eventual execution, pending authorization.

## PHASE A — Recover genuinely missing ACQUIRED archives
- Candidate set: C_ACQUIRED_ARCHIVE_MISSING = 0 (none! all 2,945 ACQUIRED have archives on disk;
  dill/icalendar/multiprocess have .tgz archives, not missing)
- Prerequisite: none — no ACQUIRED archive recovery required
- Verification: N/A
- Rollback: N/A

## PHASE B — Resolve approved identity-review cases
- Candidate set: paramiko (F_IDENTITY_REVIEW_REQUIRED=1)
- Prerequisite: confirm secsh->paramiko package rename history; decide accept-as-rename vs reject
- Verification: SHA-anchored identity already established (0.1-bulbasaur, secsh metadata, SHA matches checkpoint)
- Rollback: keep as IDENTITY_MISMATCH; do not promote

## PHASE C — Handle eligible FAILED records per SHA-anchored policy
- Transient FAILED: 93 (network errors) — eligible for bounded SHA-anchored retry if desired
- Deterministic FAILED: 3 (dbt-semantic-interfaces, metricflow, docx2txt — structural archive errors;
  archives exist on disk; NOT retried; manual review only)
- External identity_mismatch: 6 (ranks 3042-3047, quarantined) — NOT reprocessed
- Prerequisite: confirm transient failures' SHA-anchor availability
- Rollback: FAILED remains FAILED; no ACQUIRED without identity proof

## PHASE D — Resume new acquisition from rank 3048 (ONLY after recovery reconciliation + authorization)
- Candidate set: 1,953 unprocessed (ranks 3048-5000)
- Prerequisite: freeze lifted by explicit authorization; Session 3 5K-resume audit complete
- Verification: full identity gate; new experiment ID (distinct from recovery)
- Rollback: sentinel re-armed on any anomaly

## Global guardrails
- Freeze sentinel removed ONLY at Phase D by authorized session
- Every ACQUIRED/RECOVERED_VERIFIED requires full identity verification
- Recovery writes ONLY under /mnt/pythia-cloud/Pythia/recovery/pypi/
- Historical 3,041 checkpoints + 2,945 manifest never modified
