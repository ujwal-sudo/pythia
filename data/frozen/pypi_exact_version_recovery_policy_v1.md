# PYPI EXACT-VERSION RECOVERY POLICY — v1

Status: FORMALIZED
Date: 2026-09-23
Scope: Recovery/remediation of the 2,945 historical PyPI ACQUIRED records.
Applies to: new recovery records ONLY. Historical data is IMMUTABLE.

## 1. Definitions
- Historical record: the frozen checkpoint/acquisition-manifest entry (untouched).
- Recovery record: a NEW versioned record produced by this pipeline.
- RECOVERED_VERIFIED: the ONLY success state.

## 2. A historical record may become RECOVERED_VERIFIED ONLY when ALL of:
1. package identity is established
2. intended version is established
3. exact distribution is identified
4. archive SHA-256 is independently verified (expected == observed)
5. archive metadata/filename identity is consistent with intended version
6. extraction succeeds where applicable
7. deterministic content_hash is computed
8. deterministic normalized_hash is computed

## 3. SHA-anchored version recovery (primary mechanism)
- The historical archive_sha256 is the PRIMARY identity anchor where present.
- For each recoverable record:
    historical package + historical archive_sha256
    -> identify the exact PyPI distribution (from PyPI release history)
    -> verify package, version, filename, distribution SHA.
- Package "latest" metadata is NEVER used as an identity source.
- If multiple PyPI distributions share the same SHA: record the ambiguity
  explicitly as VERSION_AMBIGUOUS / IDENTITY_UNPROVEN. Do not guess.
- If no exact SHA match exists: do NOT silently substitute another
  distribution. Mark ARCHIVE_UNAVAILABLE or IDENTITY_UNPROVEN.

## 4. Wheel policy
- Wheel archives may be recovered ONLY when wheel metadata (dist-info/METADATA,
  RECORD, filename) deterministically establishes package/version identity to
  the same standard as sdists.
- If wheel identity cannot be independently established: classify
  IDENTITY_UNPROVEN. Do NOT discard; do NOT force into the recovered set.

## 5. Recovery states
RECOVERED_VERIFIED | IDENTITY_MISMATCH | ARCHIVE_UNAVAILABLE | HASH_MISMATCH |
NO_PYTHON_CODE | EXTRACTION_FAILED | IDENTITY_UNPROVEN | NETWORK_ERROR |
OTHER_BLOCKED
- Only RECOVERED_VERIFIED counts as success.

## 6. Recovery metadata (for RECOVERED_VERIFIED)
Keep historical and recovery fields SEPARATE:
- historical_package, historical_version, historical_archive_sha256
- requested_package, requested_version
- resolved_package, resolved_version, resolved_filename, resolved_url, resolved_sha256
- observed_filename_version, observed_metadata_version
- content_hash, normalized_hash
- provenance_chain, preprocessing_version, validator_version, dataset_version, quality_metadata

## 7. Resumability
- Recovery is resumable per record (per-record state persisted after each).
- On interruption: completed records remain completed; incomplete remain
  retryable; no completed record is re-downloaded; historical evidence untouched.

## 8. Data mutation
- Historical checkpoints, acquisition manifest, candidate manifest, archives:
  IMMUTABLE.
- Recovery writes ONLY under /mnt/pythia-cloud/Pythia/recovery/pypi/.
- No global deduplication; no corpus construction; no model/tokenizer training.
