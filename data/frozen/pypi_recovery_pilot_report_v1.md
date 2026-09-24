# SESSION 2 — PYPI RECOVERY PILOT REPORT

Status: PYPI RECOVERY PILOT PARTIALLY PASSED — GAPS REMAIN

Frozen baseline:
- checkpoints: 3,041 (unchanged)
- ACQUIRED: 2,945 (unchanged)
- FAILED: 96 (unchanged)

Recovery batch:
- attempted: 25
- recovered_verified: 1 (encutils 1.0.0)
- identity_mismatch: 24
- archive_unavailable: 0
- hash_mismatch: 0
- no_python_code: 0
- other: 0

Identity:
- package matches: 25/25 (requested package always matched)
- version matches: 1/25 (only encutils; requested==resolved AND filename/metadata agree)
- filename matches: 1/25 (only encutils; all others filename version != label)
- metadata matches: 1/25 (only encutils)
- SHA matches: 1/25 verified (encutils); others quarantined before SHA step

Historical mismatches:
- 24/25 historical records carry a version label that does NOT match the actual archive content.
- For 23 of these, historical_version == live resolved info.version (package latest), but the resolved archive FILENAME/METADATA is an OLD version (e.g., absl-py labeled 2.5.0, archive absl-py-0.1.0; s3transfer labeled 0.19.2, archive 0.0.1; psutil labeled 7.2.2, archive 0.1.1).
- This is the confirmed historical version-selection/labeling bug (info.version fallback), now caught at recovery.
- a2a-sdk: historical 1.1.4 != live resolved 1.1.5 (package's latest moved on) — separate failure mode.
- azure-mgmt-eventhub / paramiko: gate caught filename/unprovable-identity.

Content:
- content_hash: computed for the 1 recovered record (encutils) using canonical normalize_code_for_hash.
- normalized_hash: computed via project canonical normalization.
- AST validation: analyze_package ran for the recovered record (python_files/ast_valid/ast_invalid recorded).

Resumability:
- verified: YES — re-running recovery on the same batch produced 0 pending records; no duplication; state persisted per record.

Tests:
- passed: 111
- failed: 0
- skipped: 1 (pre-existing GitHub integration mock)

Frozen evidence modified:
- YES/NO: NO — frozen /mnt/pythia-cloud/Pythia/raw/pypi untouched (manifest 2945, checkpoints 3041, SHA 81f78a0d...); recovery wrote only to /mnt/pythia-cloud/Pythia/recovery/pypi/.

Remaining blockers:
- The historical 2,945-record ACQUIRED set is broadly mislabeled: only a small fraction will recover as RECOVERED_VERIFIED under strict identity (the live replay showed ~1/5 control matching; pilot shows 1/25).
- Historical version labels reflect package-latest at acquisition time, not the actual archive version; correct recovery requires either (a) re-acquiring the exact requested version distributions, or (b) accepting only records whose requested version == actual archive version.
- No decision yet on whether to treat the historical set as partially invalid and re-acquire correct versions.

Next action (not executed):
- Do NOT expand the recovery batch automatically.
- Recommend a dedicated decision mission: determine recovery policy for the mislabeled majority (re-acquire exact requested versions vs. quarantine-and-drop), then run a larger controlled batch under that policy.
