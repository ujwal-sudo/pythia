# Canonical Data Contract — Pythia-160M

This document defines the canonical metadata schema that every future source must be able to provide when contributing to the Pythia-160M training corpus. It is the contract by which heterogeneous sources are reconciled into a unified dataset.

## Schema Fields (Alphabetical)

| Field | Type | Required | Description |
|---|---|---|---|
| **source** | string | REQUIRED | Source identifier: e.g., `python_docs`, `textbooks`, `stackoverflow`, `pypi`, `github`, `the_stack`, `jupyter`, `codesearchnet`, `scientific_python`, `reasoning`, `reddit` |
| **source_type** | string | REQUIRED | Broad category: `raw`, `processed`, `filtered`, `final` |
| **source_version** | string | RECOMMENDED | Version of the source snapshot, e.g., `3.14`, `2026-09-17`, `v1` |
| **source_url** | string | REQUIRED | URL or identifier pointing to the original source |
| **acquisition_date** | string (ISO date) | REQUIRED | Date the source was acquired or generated |
| **license** | string | REQUIRED | License identifier, e.g., `MIT`, `Apache-2.0`, `CC-BY-SA-4.0`, `Python Software Foundation License` |
| **license_status** | string | RECOMMENDED | `CLEAR`, `UNKNOWN`, `RESTRICTED_OR_REVIEW` |
| **record_id** | string | REQUIRED | Unique identifier for this record within its source |
| **content_hash** | string | REQUIRED | SHA-256 hash of the normalized content |
| **normalized_hash** | string | RECOMMENDED | SHA-256 hash after normalization (e.g., whitespace, comment stripping) |
| **provenance** | string | RECOMMENDED | Traceable origin path: `raw_path` → `processor` → `filter_stage` |
| **preprocessing_version** | string | RECOMMENDED | Version of the preprocessing pipeline applied, e.g., `v1`, `PYT-DATA-v0.1` |
| **validator_version** | string | RECOMMENDED | Version of the AST validator used, e.g., `scripts.validators.ast_validator` |
| **dataset_version** | string | RECOMMENDED | The Pythia-DATA version this record belongs to, e.g., `PYTHIA-DATA-v0.1` |
| **split** | string | RECOMMENDED | `train`, `validation`, `holdout`, `test` |
| **quality_metadata** | dict | OPTIONAL | Source-specific quality fields (comment_ratio, pep8_violations, ast_validity, etc.) |
| **token_count** | int | OPTIONAL | Provisional token count (before actual tokenizer exists) |
| **token_count_status** | string | OPTIONAL | `PROVISIONAL` (whitespace-based estimate) or `FINAL` (Pythia-tokenizer-based) |

## RAW / PROVISIONAL / FINAL Token Count Distinction

| Status | Description |
|---|---|
| **RAW** | Token count derived from naive method (e.g., `char_count // 4`, `text.split()`). Must be labeled `token_count_status: PROVISIONAL`. |
| **PROVISIONAL** | Token count using significant-token or tokenize-based methods without the custom Pythia tokenizer. Explicitly labeled as provisional until `PYTHIA-TOK-v0.1` is available. |
| **FINAL** | Token count computed using the actual Pythia tokenizer (`PYTHIA-TOK-v0.1` or later). Only then may records carry `token_count_status: FINAL`. |

## Provenance Chain

Every record must support a provenance chain:

```
raw_source → acquisition → preprocessing → validation → filtering → final_corpus
```

Each arrow should carry a `preprocessing_version` and/or `validator_version` so that downstream experiments can reproduce the exact transformation path.

## Contract Compliance

- **Every record** in every source JSONL must include at minimum: `source`, `source_type`, `source_url`, `record_id`, `content_hash`, `acquisition_date`, `license`.
- Records missing required fields are **invalid** and should be rejected from the canonical corpus unless explicitly kept as an ablation.
- The `dataset_version` field must match the version recorded in `research/dataset_versioning.md`.
- The `validator_version` must be recorded for any record that passed through the AST validator.

## Versioning Note

Until `PYTHIA-TOK-v0.1` exists, all `token_count` values must have `token_count_status: PROVISIONAL`. Once the custom tokenizer is available and versioned, records may be updated to `token_count_status: FINAL` with the new tokenizer-based counts.