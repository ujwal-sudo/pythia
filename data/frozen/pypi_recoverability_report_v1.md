# SESSION 2 — PYPI RECOVERABILITY REPORT

Status: PYPI RECOVERABILITY ANALYSIS COMPLETE — EXACT-VERSION RECOVERY FEASIBLE

Historical baseline:
- checkpoints: 3,041
- ACQUIRED: 2,945
- FAILED: 96

25-record pilot:
- verified: 1 (encutils)
- reconstructable: 24
- recoverable: 24 (EXACT_VERSION_RECOVERABLE via archive SHA)
- ambiguous: 0
- unrecoverable: 0

Additional sample:
- size: 49
- verified: 0
- reconstructable: 47
- recoverable: 47 (EXACT_VERSION_RECOVERABLE via archive SHA)
- ambiguous: 0
- unrecoverable: 0
- archive-recoverable-but-identity-unproven: 2 (livekit-blingfire, pyqt5-qt5 — matched wheels, not sdists)

Root finding:
- intended-version evidence: the historical checkpoint archive_sha256 is a cryptographic fingerprint of the ACTUAL downloaded archive. Matching it against PyPI release history uniquely identifies the true distribution/version in 71/74 analyzed records (96%). matched_size == checkpoint archive_size in every verified case (independent corroboration).
- dominant failure pattern: historical version LABEL = package-latest (info.version fallback at acquisition), while the actual archive = first-non-yanked-sdist (old version). The SHA reveals the true intended version deterministically.
- recoverability: EXACT-VERSION RECOVERY FEASIBLE — for ~96% of records the intended package/version is uniquely determined by the frozen archive SHA-256; exact distribution URLs/SHA are available from PyPI release history.

Operational estimate:
- archive downloads: ~2,945 (exact distributions re-downloaded)
- storage: ~4.34 GB (matches historical total)
- runtime: ~1-3 hours (download-dominated; ~1.4 MiB mean archive)
- main constraint: network reliability (retries); resumability already implemented (per-record state)

Policy implications:
- exact-version recovery: retains ~96% of the set with correct identity (true versions, not labels); highest provenance quality; requires re-download of exact distributions; research reproducible (SHA-anchored).
- quarantine: would preserve evidence but exclude records whose identity is unproven; only ~2-4% at risk; loses the recoverable ~96% unnecessarily if chosen alone.
- (No policy chosen; evidence only.)

Frozen evidence modified:
- NO — frozen raw/pypi untouched (2945/3041); only new analysis artifacts written under /mnt/pythia-cloud/Pythia/recovery/analysis_v1/.

Remaining uncertainty:
- The 2/74 non-sdist cases (wheels) need a decision on whether wheel archives are acceptable recovery units.
- Percentage applies to the analyzed 74-record sample, NOT the full 2,945 (must not extrapolate blindly, though pattern appears systematic).
- Historical archives already on disk are the SAME files identified by SHA; re-download is a safety/verification measure, not strictly a data-acquisition need.

Next action (not executed):
- Proceed to a policy decision mission (exact-version recovery vs quarantine) based on this evidence, then a larger controlled recovery batch under the fixed pipeline. Do NOT start broad recovery automatically.
