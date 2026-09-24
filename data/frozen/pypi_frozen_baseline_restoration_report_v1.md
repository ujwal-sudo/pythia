# SESSION 2 — PYPI FROZEN-BASELINE RESTORATION + 6 EXTERNAL CHECKPOINT FORENSICS

## Status: FROZEN BASELINE RESTORED — RECOVERY CAN PROCEED

## Final Reconciliation

1. Frozen baseline before:
   3041 checkpoints / 2945 ACQUIRED / 96 FAILED

2. Current checkpoint count:
   3047

3. External checkpoints:
   exactly 6 (confirmed):
   - moyopy (rank 3042) FAILED identity_mismatch:filename_version_mismatch
   - clickhouse-sqlalchemy (rank 3043) FAILED
   - python-editor (rank 3044) FAILED
   - databricks (rank 3045) FAILED
   - dogpile-cache (rank 3046) FAILED
   - types-pyasn1 (rank 3047) FAILED
   All written by the concurrent scaleup (fixed pipeline) at 2026-09-23 06:12-06:14 UTC.
   All are FAILED, candidate ranks 3042-3047, NOT in the frozen 2945 ACQUIRED manifest,
   NOT overlapping any frozen record.

4. Original baseline records changed:
   exactly 0 (pre-freeze checkpoints still 2945 ACQUIRED + 96 FAILED, mtimes unchanged)

5. Original baseline records missing:
   exactly 0

6. Manifest changed:
   YES (format/SHA differs: 81f78a0d -> e081a09e) — caused by the fixed pipeline's
   _regenerate_manifests_from_checkpoints adding identity fields (archive_filename,
   observed_filename_version, requested_version, resolved_version) and REQUIRES_RECONCILIATION
   paths. record_count UNCHANGED = 2945. All 50 recovery historical identities present.
   The 6 FAILED packages correctly excluded.

7. Candidate manifest changed:
   NO (SHA e26e2035... unchanged)

8. Recovery state changed:
   NO (50 records intact: 48 RECOVERED_VERIFIED, 1 IDENTITY_MISMATCH, 1 NO_PYTHON_CODE)

9. External artifacts quarantined:
   YES at /mnt/pythia-cloud/Pythia/recovery/quarantine_external_checkpoints_v1/
   (6 checkpoints + 6 archives copied, hash-preserved; quarantine_manifest_v1.json)

10. Concurrent writer protection:
    VERIFIED — freeze sentinel placed at /mnt/pythia-cloud/Pythia/raw/pypi/.FREEZE_SENTINEL;
    _save_checkpoint, run_scaleup, run_pilot all refuse while sentinel present (BLOCKED_FROZEN).
    Concurrent writer (opencode agent 26025) currently stopped.

11. Tests:
    passed: 116 (5 new regression tests: freeze-sentinel blocks checkpoint write,
    blocks scaleup, blocks pilot, allows write without sentinel, external-checkpoint detection)
    failed: 0
    skipped: 1 (pre-existing GitHub integration mock)

## Notes
- The 6 external checkpoints demonstrate the safety fix working correctly: the
  concurrent scaleup's extension attempts (ranks 3042-3047) were all REJECTED as
  identity_mismatch (the resolved latest version's archive disagreed with the label).
- The manifest SHA change is a serialization-format change from the safety fix,
  NOT a data-identity change. Baseline identities are fully preserved.
- The concurrent writer is stopped; the sentinel now prevents any relaunch from
  mutating checkpoints. Remove the sentinel only when recovery completes and is authorized.

## Evidence preserved
- Quarantine: /mnt/pythia-cloud/Pythia/recovery/quarantine_external_checkpoints_v1/
- Recovery state: /mnt/pythia-cloud/Pythia/recovery/pypi/recovery_state_v1.json (unchanged)
- Frozen snapshot: data/frozen/pypi_recovery_snapshot_v1.json
