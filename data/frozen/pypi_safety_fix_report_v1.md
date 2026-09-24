# SESSION 2 — PYPI SAFETY FIX REPORT

Status: PYPI SAFETY FIX COMPLETE — REGRESSION VERIFIED

Root cause addressed:
- version resolution: YES — fetch_package_metadata now separates requested_version vs resolved_version and flags used_info_version_fallback; identity gate rejects any contradiction regardless of fallback
- archive identity: YES — verify_archive_identity() checks requested pkg/version vs resolved filename version AND archive internal PKG-INFO/METADATA version AND SHA, before ACQUIRED
- cache reuse: YES — file-existence is no longer sufficient; cached artifact must pass full identity gate (SHA + filename + metadata), else QUARANTINE/REJECT
- checkpoint labeling: YES — mark_acquired persists requested_version, resolved_version, observed_filename_version, observed_metadata_version, archive_sha256_expected/observed; identity mismatches become mark_failed('identity_mismatch:<reason>')
- manifest regeneration: YES — _regenerate_manifests_from_checkpoints no longer synthesizes archive_path from unverified version label; uses recorded archive_filename or REQUIRES_RECONCILIATION marker

Regression tests:
- total: 12 (new) + 107 (existing suite)
- new: 12
- passed: 12/12 new; 107/107 existing (1 pre-existing GitHub skip, unrelated)
- failed: 0
- skipped: 1 (pre-existing test_github_acquire_clean integration mock)

Critical tests:
- wrong-version/SHA-match (CASE C): PASSED — SHA equality alone rejected when filename/version disagree
- cache false-positive (CASE D): PASSED — wrong-version cache not reused
- matching control (CASE B): PASSED — encutils 1.0.0 accepted only when all checks agree
- missing metadata (CASE E): PASSED — QUARANTINE, never ACQUIRED

Existing test suite:
- 107 passed, 1 skipped (pre-existing), 2 subtests passed. No regressions.

Frozen evidence:
- preserved: YES — all 4 files hash-identical to pre-fix backup (recorded in this session)

Live replay:
- NOT EXECUTED — pipeline is now SAFE for a later read-only/live replay (identity gate enforces requested-vs-observed identity and FAILED/QUARANTINE on any mismatch)

Remaining gaps:
- verify_checkpoint_consistency still uses a hardcoded failed_packages list (dbt-semantic-interfaces, metricflow) — undercounts FAILED (96 actual). Separate from version bug; flagged for follow-up.
- Candidate manifest carries no version intent (by design); requested_version at acquire time = resolved latest label, so the gate protects against filename/PKG-INFO contradictions rather than a separately-specified target version. Acceptable for the confirmed failure class.

Next action (not executed):
- Authorize a read-only/live PyPI replay mission to confirm the fixed pipeline against live API responses (capture sel.version vs info.version, verify identity gate behavior end-to-end). Do NOT resume scale-up until that replay passes.
