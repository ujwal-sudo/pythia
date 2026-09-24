# Canonical Data Contract — Pythia-160M

This document defines the canonical metadata schema that every future source must be able to provide when contributing to the Pythia-160M training corpus. It is the contract by which heterogeneous sources are reconciled into a unified dataset.

This version (2026-09-18) explicitly maps each contract field against the actual metadata produced by the acquired sources: Python Documentation, Stack Overflow, GitHub, and PyPI. CodeSearchNet and The Stack are noted as pending sources. Fields not yet provided by a source are marked with [GAP] and documented below.

## Schema Fields (Alphabetical) with Source Mapping

| Field | Type | Required | Provided By | Source-Specific Origin | Transformation | Gap / TODO | Preserve Source-Specific |
|---|---|---|---|---|---|---|---|
| **source** | string | REQUIRED | ✓ All | Python Docs: `python_docs`<br>Stack Overflow: `stackoverflow`<br>GitHub: `github`<br>PyPI: `pypi` | None — standardize to lower-case canonical names | None | None |
| **source_type** | string | REQUIRED | ✓ All | Python Docs: `raw`<br>Stack Overflow: `raw` (Hugging Face streaming)<br>GitHub: `raw` (cloned repos)<br>PyPI: `raw` | None — map to `raw`/`processed`/`filtered`/`final` | None | None |
✅ design: per-package pypi:{project_name} (per-package); see unit-of-data semantics below
✅ design: per-package pypi:{project_name} (per-package); see unit-of-data semantics below
✅ design: per-package pypi:{project_name} (per-package); see unit-of-data semantics below
✅ design: per-package pypi:{project_name} (per-package); see unit-of-data semantics below
| **license_status** | string | RECOMMENDED | ✓ Stack Overflow: `CLEAR`/`UNKNOWN`/`RESTRICTED_OR_REVIEW` from processing<br>✓ GitHub: `CLEAR`/`UNKNOWN`/`RESTRICTED_OR_REVIEW` from license_key classification<br>✗ Python Docs: [GAP] — only `PSF License` documented, no status field<br>✗ PyPI: [GAP] — not yet tracked | Map to `CLEAR`/`UNKNOWN`/`RESTRICTED_OR_REVIEW` | [GAP] Python Docs lacks license_status field; PyPI lacks entirely | `license`, `license_url`, `is_opensource` |
| **record_id** | string | REQUIRED | ✓ Python Docs: [GAP] — not explicitly defined per-record; implied by `content_hash`<br>✓ Stack Overflow: Would be constructed as `so_{qid}_{answer_id}` from processing script<br>✓ GitHub: `{owner}_{repo}_{commit}` from processing<br>✗ PyPI: [GAP] — not yet defined per record | None — generate canonical format per source | [GAP] Python Docs and PyPI lack explicit per-record identifiers; SO and GitHub have construction plans | `record_id`, `uuid`, `incremental_id` |
✅ design: SHA-256 of normalized Python code content (not entire archive); normalize \r\n→\n, strip trailing whitespace per line, remove docstrings
| **normalized_hash** | string | RECOMMENDED | [GAP] — not yet computed for any source | SHA-256 after normalization (whitespace stripping, comment removal, \r\n→\n) | [GAP] All sources — not yet implemented | `normalized_hash`, `exact_hash` |
✅ design: PyPI API → metadata_filter → quality_gate → final_corpus chain; see provenance infrastructure below
| **preprocessing_version** | string | RECOMMENDED | [GAP] — not yet tracked across any source | Version of the preprocessing pipeline applied, e.g. `v1`, `PYT-DATA-v0.1` | [GAP] All sources — not yet tracked | `preprocessing_version`, `pipeline_version`, `transform_version` |
| **validator_version** | string | RECOMMENDED | ✓ Python Docs: `scripts.validators.ast_validator` (used during processing)<br>✓ GitHub: `scripts.validators.ast_validator` (used during processing)<br>✗ Stack Overflow: [GAP] — would use during quality gating<br>✗ PyPI: [GAP] — not yet tracked | Standardize to `scripts.validators.ast_validator` or future `PYTHIA-TOK-v0.1` | [GAP] SO and PyPI lack formal recording | `validator_version`, `ast_validator_version`, `validation_software` |
| **dataset_version** | string | RECOMMENDED | [GAP] — not yet assigned across any source | The Pythia-DATA version this record belongs to, e.g. `PYTHIA-DATA-v0.1` | [GAP] All sources — not yet assigned; linked to `research/dataset_versioning.md` | `dataset_version`, `pythia_data_version` |
| **split** | string | RECOMMENDED | [GAP] — not yet defined for any source | `train`/`validation`/`holdout`/`test` | [GAP] All sources — not yet defined | `split`, `data_split`, `set_assignment` |
✅ design: python_requires, classifiers, ast_valid, ast_invalid, license_status, token_count_status (per-package); see quality_metadata below
✅ design: per-package pypi:{project_name} (per-package); see unit-of-data semantics below
| **token_count_status** | string | OPTIONAL | ✓ Python Docs: PROVISIONAL (no PYTHIA-TOK-v0.1)<br>✓ Stack Overflow: PROVISIONAL (metadata.token_count is preliminary estimate)<br>✓ GitHub: PROVISIONAL (would use provisional method)<br>✗ PyPI: [GAP] — not yet tracked | Standardize to `PROVISIONAL` until `PYTHIA-TOK-v0.1` exists; then `FINAL` | [GAP] PyPI lacks token_count_status tracking | `token_count_status`, `count_status` |

## Provenance Chain (Updated)

Every record must support a provenance chain:

```
raw_source → acquisition → preprocessing → validation → filtering → final_corpus
```

Each arrow should carry:
- `preprocessing_version` — version of preprocessing pipeline applied
- `validator_version` — version of AST validator used for syntax gating

The provenance chain must be traceable from the final corpus record back to the immutable raw source snapshot (SHA-256 checksum recorded at acquisition time).

## Contract Compliance

- **Every record** in every source JSONL must include at minimum: `source`, `source_type`, `source_url`, `record_id`, `content_hash`, `acquisition_date`, `license`.
- Records missing required fields are **invalid** and should be rejected from the canonical corpus unless explicitly kept as an ablation.
- The `dataset_version` field must match a recorded version in `research/dataset_versioning.md`.
- The `validator_version` must be recorded for any record that passed through the AST validator.
- **Source-specific metadata must be preserved** alongside normalized fields — do not discard fields that do not fit the common schema (e.g., SO's `python_tag_rules`, GitHub's `doc_metrics`, PyPI's docstring thresholds).


## PyPI Unit-of-Data Semantics

Preserve the distinction between:

  **Package level**: `{package_name, package_version, archive_sha256}`
  **Archive level**: `{source_url, acquisition_date, license (dist-level)}`
  **Extracted level**: `{per-package ast_valid, license_status, content_hash, record_id}`
  **Code unit level**: `{normalized_hash, token_count, quality_metadata}`

These four levels must be preserved alongside canonical fields — do not flatten
into a generic "code record" without preserving the original unit.

Source-specific metadata that must be preserved alongside canonical fields:

  • Package discovered/acquired counts (PYT-DATA-PYPI-003: 1,998 acquired + 2 failed)
  • Per-package license distribution (CLEAR=772, UNKNOWN=211, REVIEW_REQUIRED=17)
  • Per-package AST statistics (ast_valid, ast_invalid)
  • Docstring thresholds (`PYPI_DOCSTRING_THRESHOLD_HIGH` = 0.60, `PYPI_DOCSTRING_THRESHOLD_MEDIUM` = 0.30)
  • `PYPI_CANDIDATE_POOL_SIZE` (5000)

These source-specific fields should be stored in a `source_specific` dict or as separate columns in the training manifest, never discarded or silently overwritten.



## Versioning Note

Until `PYTHIA-TOK-v0.1` exists, all `token_count` values must have `token_count_status: PROVISIONAL`. Once the custom tokenizer is available and versioned, records may be updated to `token_count_status: FINAL` with the new tokenizer-based counts.

## Source-Specific Metadata Preservation

The following source-specific metadata must be preserved alongside canonical fields, even if they do not fit the common schema:

- **Python Docs**: `valid_python_count` (4512), `retained_count` (317), `documentation_version` (3.14), `candidate_count` (10030)
- **Stack Overflow**: `query_selection_rules`, `python_tag_rules`, `quality_thresholds` (tier_a/b/c with record counts), `number_of_source_records_scanned` (100000), `number_selected` (0), `provisional_token_count` method and observed range
- **GitHub**: `license_key` per repo, `size` (bytes), `forks`, `stars`, `created_at`, `default_branch`, `topics`
- **PyPI**: Docstring thresholds (`PYPI_DOCSTRING_THRESHOLD_HIGH` = 0.60, `PYPI_DOCSTRING_THRESHOLD_MEDIUM` = 0.30), `PYPI_CANDIDATE_POOL_SIZE` (5000), per-package license metadata, `home_page` URL
- **CodeSearchNet**: Per-repository license, code snippet metadata from API
- **The Stack**: Per-repo license, file-level metadata, function-level structure information

These source-specific fields should be stored in a `source_specific` dict or as separate columns in the training manifest, never discarded or silently overwritten.

## Pending Sources

### CodeSearchNet

| Field | Status | Notes |
|---|---|---|
| `source` | REQUIRED | `codesearchnet` |
| `source_type` | REQUIRED | `raw` |
| `source_url` | RECOMMENDED | CodeSearchNet API endpoint |
| `acquisition_date` | REQUIRED | Date acquired |
| `license` | RECOMMENDED | Per-repository license |
| `record_id` | REQUIRED | Record identifier from API |
| `content_hash` | REQUIRED | SHA-256 of code snippet |
| Other fields | [GAP] | Not yet acquired/processed |

### The Stack

| Field | Status | Notes |
|---|---|---|
| `source` | REQUIRED | `the_stack` |
| `source_type` | REQUIRED | `raw` |
| `source_url` | RECOMMENDED | The Stack archive URL |
| `acquisition_date` | REQUIRED | Date acquired |
| `license` | RECOMMENDED | Varies (per-repo license) |
| `record_id` | REQUIRED | Repo-relative path + hash |
| `content_hash` | REQUIRED | SHA-256 of file content |
| Other fields | [GAP] | Not yet acquired/processed; function-level unit |

## Summary: REQUIRED vs OPTIONAL vs SOURCE_SPECIFIC

| Category | Fields |
|---|---|
| **REQUIRED** (every record) | `source`, `source_type`, `source_url`, `acquisition_date`, `license`, `record_id`, `content_hash` |
| **OPTIONAL** (if present, mapped to `quality_metadata`) | `source_version`, `provenance`, `preprocessing_version`, `validator_version`, `dataset_version`, `split`, `token_count`, `token_count_status` |
| **SOURCE_SPECIFIC** (recorded in `source_specific` only) | PyPI overlap, generated/vendor detection, fork status, documentation metrics, repo metrics, package metadata, code example structure — stored source-specifically, not in canonical fields |