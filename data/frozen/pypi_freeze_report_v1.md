# SESSION 2 — PYPI FREEZE REPORT

Status: FROZEN
Freeze timestamp: 2026-09-23 03:00:01 UTC

Baseline history:
- 2,717: Session-1 historical forensic baseline (2,622 ACQUIRED + 95 FAILED)
- 2,833: manifest count observed earlier in Session-2 audit (mid-run)
- 2,839: manifest count at 2026-09-22T18:14 (generated_at)
- 2,939: manifest count at 2026-09-22T20:52 (generated_at, pre-freeze)
- 3,035: checkpoint file count observed during live audit (pre-freeze)

Frozen state:
- checkpoints: 3,041
- ACQUIRED: 2,945
- FAILED: 96
- manifest: 2,945 (record_count; matches ACQUIRED exactly)
- candidate manifest: 5,000 (ranks 1-5000; SHA e26e2035f67b...)
- archives: package_dirs=2,953; manifest archive_size sum=4.34GB (deep walk too slow on rclone)

Identity reconciliation:
- exact matches: 0/80 (archive filename version == manifest/checkpoint version)
- version mismatches: 72/80 (VERSION_LABEL_MISMATCH; 8 ARCHIVE_MISSING in sample)
- archive missing: 8/80 in sample
- hash mismatches: 0 (checkpoint archive_sha256 matches physical archive for all verified)
- unexplained: 0 (pattern is systemic; PKG-INFO version matches FILENAME version, NOT manifest label)
- note: absl-py confirmed (label 2.5.0, archive 0.1.0, PKG-INFO 0.1.0) — systemic, not isolated

Writer:
- process: python -m scripts.scrapers.pypi scaleup (PID tree 3429349/3429347/3429346, then relaunched 3488024/3488022/3488021)
- launcher: opencode agent on port 26025 (VS Code session), distinct from this audit session
- stopped: YES (SIGTERM to both process trees); no relaunch observed after ~2min
- files affected: metadata/*_checkpoint.json, packages/<pkg>/<ver>/*.tar.gz, manifests/pypi_acquisition_v1.json

Remaining blockers:
- Systemic VERSION_LABEL_MISMATCH: 100% of sampled archives have filename/PKG-INFO version != manifest/checkpoint version. Archives are genuine (SHA-256 matches) but appear to be older versions than labeled. Root cause not yet determined (download grabbed wrong version? manifest records target version not actual?). Do NOT correct until investigated.
- Archive count exact figure not computable on rclone (deep walk times out); package_dir count used as proxy.

Authoritative decision:
- PyPI state FROZEN at 3,041 checkpoints = 2,945 ACQUIRED + 96 FAILED; manifest 2,945 fully reconciled to candidate manifest (all valid, ranks 1-3041, 0 duplicates, 0 outside manifest).
- The 2,945 ACQUIRED set is the authoritative current baseline. Historical 2,717 preserved as lineage only.
- VERSION_LABEL_MISMATCH is a data-integrity defect that must be resolved before any canonical PyPI use.

Next action (DO NOT execute automatically):
- Investigate root cause of version-label vs archive-content mismatch (check selection_rule 'latest_stable_non_yanked_sdist_by_upload_time' vs actual download; verify fetch_package_metadata returns the version actually downloaded).
- Then decide whether to re-acquire correct-version archives or correct the manifest labels, per forensic principles.
