# SESSION 2 — PYPI FROZEN-MANIFEST IMMUTABILITY CLOSURE + RECOVERY READINESS AUDIT

## Final Report

1. Original frozen manifest found:
   NO — no byte-for-byte copy exists. Searched frozen/ dir, recovery dirs, backups (/tmp/opencode/frozen_backup_*), git history, cloud snapshots. The original manifest artifact was overwritten in place; only its SHA-256 was recorded in the freeze + recovery snapshots.

2. Original manifest SHA:
   81f78a0dcff3a0d13a767948423b23ca49c813bb1091c4ab4e9359c67bb049e4 (recorded in data/frozen/pypi_freeze_snapshot_v1.json and pypi_recovery_snapshot_v1.json at freeze time 03:00/03:54)

3. Current manifest SHA:
   e081a09ef4b6f62d020789df5589db1a66af355eacc65e1b69bf275152d23c4b

4. Byte-for-byte original preserved:
   NO (overwritten in place; not recoverable from checkpoints — checkpoints lack archive_path/archive_filename)

5. Baseline identity integrity:
   UNCHANGED — all 2945 ACQUIRED identities and 96 FAILED identities preserved; all 50 recovery historical identities present in manifest; 6 external FAILED packages correctly excluded.

6. Baseline:
   UNCHANGED = 3041 (2945 ACQUIRED + 96 FAILED)
   CHANGED = 0
   MISSING = 0
   ADDED = 0 (the 6 external are separate, quarantined, not baseline)

7. External quarantined checkpoints:
   6/6 verified — all present, all hashes MATCH originals (verified SHA-256)

8. Recovery state:
   48 RECOVERED_VERIFIED / 1 IDENTITY_MISMATCH / 1 NO_PYTHON_CODE (50 total, intact)

9. Freeze sentinel:
   PRESENT (/mnt/pythia-cloud/Pythia/raw/pypi/.FREEZE_SENTINEL)

10. Freeze protection:
    VERIFIED — run_scaleup=BLOCKED_FROZEN, run_pilot=BLOCKED_FROZEN, _save_checkpoint refuses writes while sentinel present (verified live)

11. Recovery readiness:
    VERIFIED — all 13 capabilities present: SHA-anchored identity resolution, filename/metadata version verification, archive SHA verification, extraction, content_hash, normalized_hash, provenance, deterministic state, resumability, quarantine, writer protection

12. Tests:
    passed: 116 / failed: 0 / skipped: 1 (pre-existing)

13. Historical manifest preservation:
    PARTIAL — the original manifest's SHA-256 and record identities are preserved in frozen snapshots + recovery state, but the original byte-for-byte artifact was overwritten in place by the safety-fix regeneration (_regenerate_manifests_from_checkpoints) and is NOT byte-preserved anywhere.

## Final Status:

B. RECOVERY READY — HISTORICAL MANIFEST PRESERVATION PARTIAL

## Notes
- The manifest mutation was caused by the safety fix's _regenerate_manifests_from_checkpoints
  (adding archive_filename/observed_*/requested_version/resolved_version fields and
  REQUIRES_RECONCILIATION archive paths). Record identities (package+version) are fully
  preserved; only the serialized format and archive_path semantics changed.
- The original archive_path values were themselves SYNTHETIC (derived from the wrong
  version labels — the historical bug), so their loss is not a data-identity loss.
- The 6 external FAILED checkpoints (ranks 3042-3047) are quarantined separately and
  excluded from the 2945 baseline.
- encutils (pilot-style) lacks a provenance_chain field in recovery state — cosmetic,
  from the earlier pilot code path; SHA-verified.
