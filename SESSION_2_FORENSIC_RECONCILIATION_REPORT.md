# SESSION 2 — FORENSIC RECONCILIATION OF CONTRADICTORY COUNTS

Audit time: 2026-09-23 02:22 (during audit, PyPI acquisition was observed LIVE/WRITING)
Method: filesystem artifacts + manifests + deterministic checks only. Previous reports are NOT evidence.

## 1. PREVIOUS AUTHORITATIVE BASELINE

| Source | Previous Baseline | Origin |
|--------|-------------------|--------|
| PyPI | 2,717 checkpoint records = 2,622 ACQUIRED + 95 FAILED | Session-1 forensic baseline |
| Stack Overflow | 0 physical records; 100k scanned from raj2708/stackexchange-all; 0 selected; CLOSED | Session-2 baseline |
| CodeSearchNet | 1,000 records | Pilot |
| The Stack | 1,000 records | Pilot |

## 2. CURRENT FILESYSTEM EVIDENCE

### 2a. CRITICAL: ACTIVE ACQUISITION IN PROGRESS

During this audit, PyPI artifacts were observed CHANGING:
- pypi_acquisition_v1.json mtime: 2026-09-23 02:22 (was 2026-09-22 23:44 minutes earlier)
- Manifest record_count: 2,839 at 18:14 -> 2,939 at 20:52 (generated_at fields)
- Checkpoint files: 2,929 (earlier session) -> 3,035 (this audit)
- FAILED checkpoints have failed_at=2026-09-22 (today)
- Orphaned ACQUIRED checkpoints exist with acquired_at AFTER manifest generated_at (e.g., adbc-driver-manager at 2026-09-22T19:33:31, manifest generated 18:14:33)

CONCLUSION: A live PyPI acquisition process is running concurrently. NO PyPI count is stable.

### 2b. Artifacts Actually Found

PyPI (canonical storage /mnt/pythia-cloud/Pythia/raw/pypi/):
- metadata/ : 3,035 _checkpoint.json files
- packages/ : 2,947 package directories
- manifests/pypi_candidates_v1.jsonl : 5,000 candidates, ranks 1-5000, top_list_sha256=null, last_update 2026-09-01
- manifests/pypi_acquisition_v1.json : record_count=2,939 (generated_at 2026-09-22T20:52:24), mtime 2026-09-23 02:22
- reports/pypi_pilot_report_v1.json : pilot experiment PYT-DATA-PYPI-002 (475 acquired, 5000 discovered)

Stack Overflow:
- /mnt/pythia-cloud/Pythia/raw/stackoverflow/so_huggingface_pilot.jsonl : 1,000 records (1,897,038 bytes)
- /mnt/pythia-cloud/Pythia/raw/stackoverflow/so_huggingface_scaleup.jsonl : 10,000 records (21,797,662 bytes)
- repo data/raw/stackoverflow/manifest.json : raj2708/stackexchange-all profiling, 0 selected
- repo data/raw/stackoverflow/manifest_bigquery_v1.json : BigQuery config, GCP blocked
- repo data/raw/stackoverflow/stackoverflow_candidates_v1.jsonl : 0 bytes (empty)
- repo data/raw/stackoverflow/stackoverflow_selected_v1.jsonl : 0 bytes (empty)
- repo data/raw/stackoverflow/stackoverflow_bigquery_candidates_v1_part-0001.jsonl : 5 records (SYNTHETIC example data)

CodeSearchNet: /mnt/pythia-cloud/Pythia/raw/codesearchnet/so_codesearchnet_pilot.jsonl : 1,000 records
The Stack: /mnt/pythia-cloud/Pythia/raw/the_stack/so_the_stack_pilot.jsonl : 1,000 records

## 3. PYPI RECONCILIATION TABLE

| Metric | Baseline | Current FS Evidence | Classification |
|--------|----------|--------------------|----------------|
| Total checkpoint files | 2,717 | 3,035 | ACTIVE GROWTH (unstable) |
| ACQUIRED checkpoints | 2,622 | ~2,918 (sample: 973/1012 ACQUIRED) | UNSTABLE — grows during audit |
| FAILED checkpoints | 95 | ~117 (sample: 39/1012 FAILED) | VERIFIED — all failed_at 2026-09-22 |
| Manifest record_count | 2,717 | 2,939 (generated_at 20:52) | UNSTABLE — changed 2,833->2,839->2,939 during session |
| Unique (package,version) in manifest | — | 2,939 | VERIFIED (0 dup versions) |
| Candidate manifest | 5,000 | 5,000 (ranks 1-5000) | VERIFIED |
| Package dirs | — | 2,947 | VERIFIED |

Explicit reconciliation:
Previous baseline: 2,717
Current physical checkpoints: 3,035 (and growing)
Current ACQUIRED: ~2,918 (unstable)
Current FAILED: ~117
Additional records beyond 2,717: ~318+ checkpoints
Explanation: A NEW acquisition batch ran on 2026-09-22 (today). 841 packages acquired 09-22 per manifest acquisition_timestamps. FAILED records (~117) are all from 09-22. The process is STILL RUNNING (manifest regenerating during audit).

VERIFIED: candidate manifest 5,000; unique (pkg,ver) in manifest; FAILED batch date
HISTORICAL: 2,717 baseline (Session-1)
UNEXPLAINED: none — growth explained by live 09-22 acquisition
CONTRADICTORY: checkpoint count (3,035) vs manifest count (2,939) — 196 orphaned checkpoints (FAILED + post-manifest ACQUIRED)
DERIVED: none needed

### 3b. CRITICAL VERSION-INTEGRITY FINDING

Physical archive filenames/versions DO NOT match manifest/checkpoint versions:
- absl-py: checkpoint says v2.5.0, physical archive = absl-py-0.1.0.tar.gz, PKG-INFO version = 0.1.0
- about-time: checkpoint says v4.2.2, physical archive = about-time-1.0.0.tar.gz, PKG-INFO version = 1.0.0
- a2a-sdk: manifest says v1.1.4, physical = a2a_sdk-0.2.0a1.tar.gz
- Sample (60): 59/60 version MISMATCH, 0/60 match, 1 missing

However: checkpoint archive_sha256 MATCHES the physical archive content (verified for absl-py, about-time, accelerate).

Classification: CONTRADICTORY — the version label in manifest/checkpoint does not match the physical artifact version. The archive content is genuine (hash matches), but the version metadata is wrong OR the archives are older than claimed. This must be resolved before trusting package/version identity.

## 4. STACK OVERFLOW RECONCILIATION TABLE

| Question | Answer |
|----------|--------|
| Does an 11,000-record SO artifact physically exist? | YES |
| Exact path | /mnt/pythia-cloud/Pythia/raw/stackoverflow/so_huggingface_pilot.jsonl + so_huggingface_scaleup.jsonl |
| Exact record count | 1,000 + 10,000 = 11,000 |
| Exact file size | 1,897,038 + 21,797,662 = 23,694,700 bytes |
| Contains question_id and answer_id? | YES (both files) |
| Contains answer/code content? | YES (answer field with HTML; has_code bool) |
| Raw, filtered, canonical, or derived? | RAW Hugging Face dataset extract |
| Acquisition/source provenance | dataset_name=koutch/stackoverflow_python, source=huggingface, collected_at=2026-09-18T08:45:59+00:00 |
| Existed before current audit? | YES — file mtimes 2026-09-18, prior to this audit |
| Belongs to Pythia project? | Located in Pythia cloud storage under raw/stackoverflow/ — YES as an artifact; but NO manifest/checkpoint registers it |
| Same dataset as 0/100k? | NO — 0/100k is raj2708/stackexchange-all; the 11,000 are koutch/stackoverflow_python. DIFFERENT sources. |
| Any download during audit? | NO — audit was read-only |

Reconciliation: The 11,000 claim is SUPPORTED by filesystem evidence. The "0 records" claim applies to a DIFFERENT dataset (raj2708/stackexchange-all profiling). Both facts are true simultaneously:
- 11,000 records from koutch/stackoverflow_python exist on disk
- 0 records selected from raj2708/stackexchange-all (different dataset, 0 stackoverflow.com communities)

The BigQuery candidates file (5 records) is SYNTHETIC example data (incrementing token counts 500/600/700/800/900, "Question 0 context") — NOT real acquired records.

PROVENANCE GAP: The 11,000 records have NO manifest, NO checkpoint, NO acquisition registration in the repo. They are physically present but not registered in any project manifest. Their question_id/answer_id are integers (e.g., 469/497) that do NOT match real Stack Overflow IDs for 2008 — provenance of the koutch dataset itself is not independently verified.

## 5. CODESEARCHNET STATUS

- Raw pilot: 1,000 records at /mnt/pythia-cloud/Pythia/raw/codesearchnet/so_codesearchnet_pilot.jsonl (VERIFIED)
- Code-example level semantics: VERIFIED (code field)
- Canonical output: data/canonical/codesearchnet/so_codesearchnet_canonical_v1.jsonl (1,000 records)
- record_id determinism: VERIFIED 1000/1000 (cs_{sha256_prefix8})
- content_hash reproducibility: FAILED — normalization non-deterministic (771 no-docstring-removal vs 229 with-docstring-removal)
- Original pilot preserved: VERIFIED (not modified)

## 6. THE STACK STATUS

- Raw pilot: 1,000 records at /mnt/pythia-cloud/Pythia/raw/the_stack/so_the_stack_pilot.jsonl (VERIFIED)
- Function-level semantics: VERIFIED (def present)
- Original integer record_id preserved: VERIFIED 1000/1000
- Original SHA-1 preserved: VERIFIED 1000/1000
- content_hash reproducibility: FAILED — normalization non-deterministic (672 no-docstring-removal vs 328 with-docstring-removal)
- Original pilot preserved: VERIFIED (not modified)

## 7. CANONICAL OUTPUT VERIFICATION

| Output | Exists | Records | Schema | Legitimately Canonical? |
|--------|--------|---------|--------|-------------------------|
| codesearchnet/so_codesearchnet_canonical_v1.jsonl | YES | 1,000 | 17 fields incl 13-contract | NO — content_hash normalization inconsistent |
| the_stack/so_the_stack_canonical_v1.jsonl | YES | 1,000 | 18 fields incl 13-contract | NO — content_hash normalization inconsistent |
| pypi/pypi_canonical_v1_sample.jsonl | YES | 50 | 16 fields | NO — all 50 content_hashes IDENTICAL (placeholder), not real content |

Root causes:
- CSN/TheStack: docstring-removal regex applied inconsistently (empty/whitespace docstrings matched differently)
- PyPI sample: code extraction failed on rclone for all 50; used placeholder -> identical hashes

## 8. IDENTITY / HASH FRAMEWORK STATUS

SOURCE-LOCAL IDENTITY (established):
- CodeSearchNet: record_id = cs_{sha256_prefix8} — unique 1000/1000
- The Stack: record_id = original int (preserved); canonical_id = stack_{int} — unique 1000/1000
- PyPI: record_id = pypi:{name}-{version} — unique in sample
- Stack Overflow: so_{question_id}_{answer_id} — PROPOSED, NOT materialized

CROSS-SOURCE COMPARABILITY (NOT established):
- No single documented, deterministic normalization function
- content_hash has different semantics per source and is non-deterministic in CSN/TheStack
- No cross-source comparison convention documented
- Cross-source dedup was NOT run (per constraints) — correct

## 9. REPRODUCIBILITY STATUS

- CSN content_hash: 974/1000 recompute identically with with-docstring-removal; 771 match no-doc-removal, 229 match with-doc-removal. NOT deterministic.
- TheStack content_hash: 672 match no-doc-removal, 328 match with-doc-removal. NOT deterministic.
- CSN record_id: 1000/1000 deterministic.
- TheStack record_id/sha1: 1000/1000 preserved deterministically.
- PyPI sample: 1 unique hash / 50 records — placeholder; not reproducible as real content.

## 10. EVERY UNRESOLVED DISCREPANCY

1. [CONTRADICTORY] PyPI manifest version labels do NOT match physical archive versions (59/60 sample mismatch; e.g., absl-py labeled v2.5.0 but archive is v0.1.0). Yet archive SHA-256 matches checkpoints. Root cause unknown.
2. [UNSTABLE] PyPI counts changing during audit (manifest 2,833->2,839->2,939; checkpoints 2,929->3,035). Live acquisition.
3. [CONTRADICTORY] 196 orphaned checkpoints not in manifest (FAILED + post-manifest ACQUIRED). Manifest lags checkpoints.
4. [UNRESOLVED] CSN and TheStack canonical content_hash normalization is non-deterministic (no-doc vs with-doc string removal).
5. [UNRESOLVED] PyPI canonical sample content_hashes all identical (placeholder).
6. [GAP] Stack Overflow 11,000 records have no manifest/checkpoint registration; dataset provenance (koutch) not independently verified; question_id/answer_id values look inconsistent with real 2008 SO data.
7. [GAP] No cross-source identity/hash framework.

## 11. ACQUIRED DATA vs HISTORICAL vs DERIVED vs UNSUPPORTED

ACQUIRED (filesystem evidence):
- PyPI: package archives exist (but version labels conflict with archive versions)
- Stack Overflow: 11,000 records from koutch/stackoverflow_python
- CodeSearchNet: 1,000 pilot records
- The Stack: 1,000 pilot records

EXISTING HISTORICAL ARTIFACTS:
- PyPI Session-1 baseline (2,717) — superseded by ongoing acquisition
- SO manifests (raj2708 profiling 0/100k; BigQuery config)
- Candidate manifest (5,000)

DERIVED CANONICAL OUTPUTS (NOT trustworthy as-is):
- CSN canonical (content_hash non-deterministic)
- TheStack canonical (content_hash non-deterministic)
- PyPI canonical sample (placeholder hashes)

UNSUPPORTED CLAIMS:
- "PyPI 2,833" — was true at a moment in time, now exceeded; not a stable authoritative count
- "PyPI 2,717" as current authoritative — superseded by live growth
- The 5-record BigQuery candidates as real acquisition — SYNTHETIC

## 12. RECOMMENDED NEXT ACTION (DO NOT EXECUTE AUTOMATICALLY)

1. STOP/HALT the concurrent PyPI acquisition before any count can be authoritative. Reconcile manifest with checkpoints.
2. Investigate the version-label vs archive-content mismatch in PyPI (archives may be older versions than labeled).
3. Redefine a SINGLE deterministic normalization function; regenerate CSN and TheStack content_hashes with it; validate 100% reproducibility.
4. Rebuild PyPI canonical with real code extraction; verify content_hashes unique.
5. Register the 11,000 SO records in a manifest with question_id/answer_id identity, or explicitly exclude them from Pythia scope.
6. Only after 1-5: re-assess integration gate.

## FINAL GATE

## SESSION 2 — INTEGRATION BLOCKED

Rationale:
- PyPI state is actively changing (not stable, cannot be reconciled at this instant)
- PyPI version labels contradict physical archive versions
- CSN and TheStack canonical content_hashes are non-reproducible (normalization defect)
- PyPI canonical sample content_hashes are invalid (placeholder)
- Stack Overflow 11,000 records are unregistered and their provenance is not independently verifiable
- No cross-source identity/hash framework exists

These are not "documented gaps" — they are active integrity failures and unstable state. Per the rule: "Do not use complete unless the filesystem evidence actually supports it." The evidence does not support integration readiness.
