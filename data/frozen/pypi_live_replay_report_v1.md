# SESSION 2 — PYPI LIVE REPLAY REPORT

Status: PYPI LIVE REPLAY PASSED — PIPELINE SAFE FOR CONTROLLED RECOVERY

Replay:
- packages: 5 (requests, numpy, absl-py, s3transfer, encutils)
- requested identities: recorded pre-request (requests==2.32.3, numpy==1.26.4, absl-py==0.1.0, s3transfer==0.8.2, encutils==1.0.0)
- resolved identities: live API resolved 4/5 to LATEST (2.34.2, 2.5.3, 2.5.0, 0.19.2) with OLD filenames (requests-0.10.0, numpy-1.10.0.post2, absl-py-0.1.0, s3transfer-0.0.1) — historical bug reproduced live
- identity matches: 1/5 (encutils 1.0.0)
- identity mismatches: 4/5 (requests, numpy, absl-py, s3transfer)
- quarantined: 4/5 (none became ACQUIRED)

Historical bug:
- reproduced: YES — live API returned latest resolved_version + old archive filename with used_info_version_fallback=True for 4/5 packages, exactly matching the frozen absl-py/s3transfer evidence
- result: fixed gate REJECTED all 4 (resolved_version_mismatch); NOT ACQUIRED

Cache safety:
- tested: YES (isolated temp fixture: wrong-version cached file with valid self-SHA)
- result: REJECT (sha_verified=True but filename_version_mismatch) — NOT reused, NOT acquired; matching cache accepted

End-to-end:
- ACQUIRED only after verification: YES — encutils was the only ACQUIRE, and only after requested==resolved==filename==PKG-INFO==SHA all agreed
- SHA verification: YES (observed==expected where available; verified separately from identity)
- filename verification: YES (parse_version_from_filename)
- metadata verification: YES (PKG-INFO/METADATA version)

Frozen baseline:
- modified: NO — manifest=2945, checkpoints=3041 unchanged; frozen evidence hashes intact; replay wrote only to isolated /tmp dirs (auto-cleaned)

Tests:
- total: 111 passed, 1 skipped (pre-existing GitHub), 2 subtests
- passed: 111
- failed: 0
- skipped: 1 (pre-existing)

Remaining gaps:
- verify_checkpoint_consistency now scans all checkpoints for FAILED (fix applied + 2 regression tests). Confirmed against live replay that identity-mismatch records are auto-counted.
- The underlying PyPI API releases-dict behavior (release file entries lacking a version field -> info.version fallback) remains a live-API characteristic; the fixed pipeline now rejects it instead of recording a wrong label.

Next action (not executed):
- A separate mission authorizes controlled recovery of the 2,945-package set using the fixed pipeline (identity gate + checkpoint auto-count). Do NOT resume acquisition automatically.
