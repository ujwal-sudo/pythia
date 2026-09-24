# SESSION 2 — PYPI RECOVERY AUTHORIZATION PLAN (DRY-RUN, NOT EXECUTED)

Freeze remains ACTIVE. This plan is a future-execution blueprint only.

## Phase A — Resolve existing local/recovery evidence
- Candidate set: 48 RECOVERED_VERIFIED + 6 quarantine + baseline SHA-verified archives (~2910)
- Prerequisite: Session 1 authoritative archive inventory (final counts)
- Verification: confirm local archives SHA-match checkpoints; confirm recovery archives duplicate-free
- Checkpoint/manifest implications: NONE (read-only)
- Rollback: N/A (no writes)

## Phase B — Resolve identity-mismatch cases
- Candidate set: paramiko (secsh rename), pyqt5-qt5 (no-python-code)
- Prerequisite evidence: confirm paramiko->secsh rename history; confirm pyqt5-qt5 out of Python-source scope
- Verification: package-history confirmation; corpus-scope decision
- Rollback: keep as IDENTITY_MISMATCH / NO_PYTHON_CODE; do not promote

## Phase C — Recover genuinely missing SHA-anchored artifacts
- Candidate set: D_PROVEN_MISSING (~36 est, from baseline 2945 minus present)
- Prerequisite: Session 1 authoritative inventory confirms which are truly missing
- Verification: SHA-anchor via PyPI release history; identity gate; download to recovery area only
- Checkpoint/manifest implications: new recovery records only, never historical writes
- Rollback: on failure -> NETWORK_ERROR/ARCHIVE_UNAVAILABLE; no baseline change

## Phase D — Handle eligible transient failures
- Candidate set: 93 transient FAILED (network errors)
- Prerequisite: confirm SHA-anchor availability for each
- Verification: bounded retry under safe pipeline with identity gate
- Rollback: FAILED remains FAILED; no ACQUIRED without identity proof

## Phase E — Resume new acquisition from rank 3048
- Candidate set: 1,953 unprocessed (ranks 3048-5000)
- Prerequisite: freeze lifted by explicit authorization; Session 3 5K-resume audit complete
- Verification: full identity gate; new experiment ID (distinct from PYT-DATA-PYPI-003 recovery)
- Rollback: sentinel re-armed on any anomaly; checkpoint guard active

## Global guardrails
- Freeze sentinel must be explicitly lifted only at Phase E by authorized session.
- Every ACQUIRED/RECOVERED_VERIFIED requires full identity verification (SHA+filename+metadata).
- Recovery writes ONLY under /mnt/pythia-cloud/Pythia/recovery/pypi/.
- Historical 3041 checkpoints + 2945 manifest never modified.
