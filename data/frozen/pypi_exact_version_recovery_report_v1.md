# SESSION 2 — PYPI EXACT-VERSION RECOVERY REPORT

Status: PYPI EXACT-VERSION POLICY ESTABLISHED — 50-RECORD RECOVERY PASSED

Policy:
- exact-version rule: formalized (data/frozen/pypi_exact_version_recovery_policy_v1.md) — RECOVERED_VERIFIED requires package+intended-version+exact-distribution+SHA+metadata/filename identity+extraction+content_hash+normalized_hash
- SHA identity: historical archive_sha256 is the PRIMARY identity anchor; matched against PyPI release history; package-latest NEVER used as identity
- wheel policy: wheel identity deterministically established via dist-info METADATA (Name/Version) + filename + SHA; livekit-blingfire + pyside6 recovered; pyqt5-qt5 correctly NO_PYTHON_CODE (native libs only)

Batch:
- attempted: 50
- recovered_verified: 48
- identity_unproven: 0
- identity_mismatch: 1 (paramiko — internal metadata pkg 'secsh' != 'paramiko'; correct conservative reject)
- unavailable: 0
- hash_mismatch: 0
- other: 1 NO_PYTHON_CODE (pyqt5-qt5)

Hashes:
- content_hash: 48/48 recovered
- normalized_hash: 48/48 recovered

Resumability:
- verified: YES (re-run produced 0 pending; no re-downloads; per-record state persisted)

Tests:
- passed: 111
- failed: 0
- skipped: 1 (pre-existing GitHub mock)

Frozen evidence modified:
- NO (by recovery) — recovery wrote only to /mnt/pythia-cloud/Pythia/recovery/pypi/ (~160MB).
- NOTE: external concurrent opencode agent (port 26025) RELAUNCHED pypi scaleup during the session; checkpoint count drifted 3041->3047 (6 external checkpoints). Scaleup stopped again. Manifest unchanged at 2945. Documented in recovery snapshot; not caused by recovery.

Remaining blockers:
- paramiko-style historical records where the package was renamed (internal metadata != modern name) require a policy decision (accept as same-project rename vs reject).
- 1 pilot-style metadata key inconsistency (encutils stores observed_archive_sha256 vs archive_sha256_observed); SHA verified, cosmetic only.
- Concurrent writer (opencode 26025) must remain stopped to protect the frozen baseline during any future recovery batch.

Next action (not executed):
- Separate authorization to proceed to the next controlled batch (e.g., next 100-500). Do NOT scale automatically.
