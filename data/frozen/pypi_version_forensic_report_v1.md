# SESSION 2 — PYPI VERSION FORENSIC REPORT

Status: ROOT CAUSE IDENTIFIED (code-level, from frozen artifacts)

Frozen baseline:
- checkpoints: 3,041
- ACQUIRED: 2,945
- FAILED: 96

Sample:
- mismatches examined: 40 (plus 6 deep-verified; earlier sample 80/72-8)
- exact version matches: 1/40 (encutils 1.0.0 — control case)
- version mismatches: 32/40 (80%+; plus 7 ARCHIVE_MISSING)
- archive SHA matches: 33/33 present (100%) — SHA identity always matches
- archive SHA mismatches: 0

Root cause:
- earliest confirmed divergence: version-selection / labeling in fetch_package_metadata
- cause classification: C (version-selection bug) + H (checkpoint labeling bug) + I (manifest labeling bug); secondary: G (cache reuse lacks identity verify)
- evidence:
  - scripts/scrapers/pypi.py fetch_package_metadata (lines 115-175):
    - iterates d["releases"] dict; picks FIRST non-yanked release with an sdist; break
    - archive_fname = sel.get("filename")       (e.g. absl-py-0.1.0.tar.gz)
    - archive_sha = sel.get("digests.sha256")   (hash of the OLD file)
    - version = sel.get("version") or info.get("version")   <-- fallback to LATEST info.version
  - run_scaleup/run_pilot (lines 562-590, 1063-1092):
    - archive_path = packages/{norm}/{version}/{archive_name}
    - verifies ONLY sha256_file(archive_path) == meta["archive_sha256"]   (NO filename/version/PKG-INFO check)
    - mark_acquired(version=meta["version"])   <-- stores the (wrong) label
  - _regenerate_manifests_from_checkpoints (line 430):
    - manifest archive_path is SYNTHETIC: packages/{pkg}/{info.version}/{pkg}-{info.version}.tar.gz
  - Verified on disk: dir=manifest_v (2.5.0), archive=0.1.0, PKG-INFO=0.1.0, SHA matches checkpoint.
  - encutils matches because selected sdist WAS the latest version.

Pipeline:
- candidate manifest: VERIFIED CORRECT (5,000 entries, no version field; SHA e26e2035…; immutable)
- version selection: VERIFIED INCORRECT (picks first non-yanked sdist; version label = sel.version or info.version fallback)
- PyPI lookup: NOT VERIFIED (requires network; local frozen state consistent with API returning old sdist for some packages)
- distribution selection: VERIFIED INCORRECT (sel chosen from releases dict order, not by max version; filename reveals true version)
- download: VERIFIED CORRECT for SHA (downloaded file SHA == sel.digests.sha256)
- archive: VERIFIED (internal PKG-INFO matches filename — archive is internally truthful, just not the labeled version)
- checkpoint labeling: VERIFIED INCORRECT (stores meta["version"], not archive filename/PKG-INFO version)

Cache/reuse:
- evidence: line 567-573 / 1068-1074 — if archive exists at path, verified = (sha match) OR True when no sha256 in metadata; no filename-version or PKG-INFO verification before ACQUIRED
- conclusion: SHA-only verification passes because the checkpoint's archive_sha256 was taken from the SAME (old) distribution entry. Cache reuse would also pass if file exists; identity is never cross-checked against version.

Required safeguards:
1. record requested package/version from selection intent
2. record resolved distribution URL + filename
3. verify archive filename version == requested version
4. verify archive internal PKG-INFO/METADATA version == requested version
5. compute downloaded archive SHA
6. compare to expected SHA (where available; FAIL if unavailable, do not auto-pass)
7. verify package/version identity BEFORE marking ACQUIRED
8. any mismatch -> FAILED/QUARANTINED, never ACQUIRED
9. cache reuse must verify identity (version+P/SHA), not merely file existence/size
10. checkpoint + manifest must preserve expected-vs-observed identity (requested vs actual)

Remaining uncertainty:
- Exact PyPI API release-dict ordering and whether sel["version"] is None vs old (needs network replay; frozen artifacts cannot show the live response). Local evidence is fully consistent with the fallback-to-info.version mechanism.
- Whether every mismatch is the same mechanism (sample suggests systemic: 0 exact matches in earlier 80-pkg sample; 1 in 40-pkg sample = encutils control).

Next action (DO NOT execute automatically):
- Re-run fetch_package_metadata against a small set of known mismatched packages (with network) to capture the live API response and confirm sel["version"]/info.version behavior.
- Then implement safeguards 1-10 and rebuild acquisition with identity verification before any re-acquisition.
