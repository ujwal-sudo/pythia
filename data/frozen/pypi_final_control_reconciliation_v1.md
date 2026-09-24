# SESSION 2 — FINAL PYPI CONTROLLED RECOVERY DECISION + CROSS-SESSION RECONCILIATION

## 1. CROSS-SESSION RECONCILIATION RESULT
Session 1 reported 7 ACQUIRED_WITHOUT_ARCHIVE (dill, icalendar, multiprocess, pathos, pox, ppft, texttable).
Session 2 reported 0. FINAL: **Session 2 is CORRECT.** All 7 have `.tgz` archives (excluded by Session 1's
`.tar.gz/.whl/.zip`-only filter). Confirmed by full-extension inventory + SHA match 7/7.
The difference is ENTIRELY due to archive-extension coverage.

## 2. SEVEN-PACKAGE ARCHIVE VERIFICATION TABLE
| Package | Filename | Ext | Checkpoint state | Checkpoint SHA match | Canonical | Filtered by S1 | Final class |
|---|---|---|---|---|---|---|---|
| dill | dill-0.1a1.tgz | tgz | ACQUIRED | MATCH (e16fd9c0...) | yes | yes | ACQUIRED_ARCHIVE_PRESENT |
| icalendar | iCalendar-1.1.tgz | tgz | ACQUIRED | MATCH (68001102...) | yes | yes | ACQUIRED_ARCHIVE_PRESENT |
| multiprocess | multiprocess-0.70.1.tgz | tgz | ACQUIRED | MATCH (2b0f87a6...) | yes | yes | ACQUIRED_ARCHIVE_PRESENT |
| pathos | pathos-0.1a1.tgz | tgz | ACQUIRED | MATCH (fc4e194a...) | yes | yes | ACQUIRED_ARCHIVE_PRESENT |
| pox | pox-0.1a1.tgz | tgz | ACQUIRED | MATCH (e78f93b7...) | yes | yes | ACQUIRED_ARCHIVE_PRESENT |
| ppft | ppft-1.6.4.5.tgz | tgz | ACQUIRED | MATCH (800f4fbb...) | yes | yes | ACQUIRED_ARCHIVE_PRESENT |
| texttable | texttable-0.8.0.tgz | tgz | ACQUIRED | MATCH (2f74bbce...) | yes | yes | ACQUIRED_ARCHIVE_PRESENT |
All 7/7 SHA-verified via rclone read-only (mount down; remote used). Identity gate: archives pass (SHA-anchored).

## 3. FAILED-ARCHIVE RECONCILIATION
- Session 1 "93 FAILED_WITHOUT_ARCHIVE + 9 partial": DISPROVEN. Extension-filter artifact.
- Session 2 "0 FAILED_WITHOUT_ARCHIVE": CONFIRMED.
- 3 deterministic (dbt-semantic-interfaces, docx2txt, metricflow): valid tar.gz archives NOW present on disk
  (150/9/823 members respectively) — original acquisition produced corrupt artifact, valid archive now on disk.
  Remain FAILED (not promoted). NOT retried.
- 6 external (moyopy, clickhouse-sqlalchemy, python-editor, databricks, dogpile-cache, types-pyasn1):
  confirmed quarantined (6 checkpoints + archives at quarantine path), excluded from baseline/recovery.

## 4. RECOVERY STATE
- 48/48 RECOVERED_VERIFIED valid, all 48 have canonical archives (no promotion needed).
- Recovery state unchanged (50 records).

## 5. PARAMIKO / PYQT5 SCOPE DECISION STATUS
- paramiko/secsh: ACCEPTABLE RENAME EVIDENCE (SHA-anchored; archive metadata 'secsh' = historical dist name).
  NOT converted to corpus inclusion; identity policy must explicitly permit before inclusion.
- pyqt5-qt5: OUT-OF-SCOPE (native-only wheel, 0 Python files). No state change.

## 6. 93-TRANSIENT RETRY POLICY
EXISTING project policy referenced (not re-invented): pypi_exact_version_recovery_policy_v1.md +
pypi_sha_recovery.py. Covers: SHA-anchored resolution, identity gate, SHA/filename/metadata verification,
content_hash, normalized_hash, resumability, duplicate prevention. Future execution must use this policy.

## 7. PHASE A/B/C/D AUTHORIZATION MATRIX
| Phase | Purpose | Status | Can execute now? | Required gate |
|---|---|---|---|---|
| A | Recover missing ACQUIRED | 0 missing (7-pkg reconciled) | NO | reconciliation CLOSED (this report closes it) |
| B | Resolve paramiko identity | 1 review | NO | identity-policy decision |
| C | Retry eligible transient | 93 | NO | explicit authorization |
| D | Resume 3048-5000 | 1,953 | NO | Session 3 audit + mount stable + freeze lift |

"Ready for recovery authorization" = PREPARATION-READY, NOT EXECUTION-AUTHORIZED.

## 8. INFRASTRUCTURE SAFETY GATE
- Fuse mount raw/pypi: **UNAVAILABLE** (mount down; rclone remote works read-only).
  Per gate: this is a STOP condition for execution. Do not fall back to local as authoritative.
- Freeze sentinel: PRESENT. Checkpoints: 3047. Manifest SHA e081a09e. Candidate SHA e26e2035.
  No competing writer. Recovery 50. Quarantine 6.

## 9. IMMUTABILITY CHECK
- Checkpoint state changed: NO. Manifest changed: NO. Candidate manifest: NO.
- Recovery state: NO. Quarantine: NO. Archives: NO. Freeze: PRESENT. Tests: 116/0/1.

## 10. FINAL RECOMMENDATION FOR NEXT SESSION
- Reconciliation: COMPLETE (7-pkg + failed-archive + recovery all closed; Session 2 "0 missing" CONFIRMED).
- Preparation: COMPLETE (decision matrix, retry policy, execution plan documented).
- Execution: NOT STARTED. Freeze: STILL ACTIVE.
- Exact conditions for execution authorization:
  1. Fuse cloud mount RESTORED and stable (currently down - BLOCKER).
  2. Session 3 final 5K-resume audit accepted.
  3. Freeze sentinel explicitly removed by authorized session (only for Phase D).
  4. Identity gate enforced for every record.
  5. Resume begins at rank 3048 only; no historical checkpoint rewritten;
     no FAILED silently converted; deterministic checkpoints on failure; concurrency controlled.
