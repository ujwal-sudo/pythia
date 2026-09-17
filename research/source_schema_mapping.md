# Source Schema Mapping — Pythia-160M

This document maps each source-specific schema into the common canonical schema defined in `research/data_contract.md`. It does not rewrite or modify any active source pipelines.

## Mapping Conventions

- **REQUIRED**: Must be present in every record contributing to the canonical corpus.
- **OPTIONAL**: May be present but need not exist for every source.
- **SOURCE_SPECIFIC**: Only applicable to this source; mapped to `quality_metadata` in the common schema if present.

## Python Docs

| Canonical Field | Status | Source-Specific Mapping |
|---|---|---|
| `source` | REQUIRED | `python_docs` |
| `source_type` | REQUIRED | `raw` (or `processed` if through scraper) |
| `source_version` | RECOMMENDED | Documentation version, e.g., `3.14` |
| `source_url` | REQUIRED | `https://docs.python.org/3.14/` |
| `acquisition_date` | REQUIRED | Date archive was downloaded |
| `license` | REQUIRED | `Python Software Foundation License` |
| `record_id` | REQUIRED | `python_docs:{version}:{hash}` |
| `content_hash` | REQUIRED | SHA-256 of normalized code |
| `provenance` | RECOMMENDED | `raw_path` → `python_docs_scraper` |
| `quality_metadata` | OPTIONAL | `comment_ratio`, `docstring_count`, `pep8_violations` |
| `token_count` | OPTIONAL | Provisional (whitespace-based) |
| `token_count_status` | OPTIONAL | `PROVISIONAL` |

## Textbooks (Think Python, ATBS)

| Canonical Field | Status | Source-Specific Mapping |
|---|---|---|
| `source` | REQUIRED | `thinkpython` or `atbs` |
| `source_type` | REQUIRED | `raw` |
| `source_version` | RECOMMENDED | Edition: `Think Python 2nd Edition`, `Automate the Boring Stuff 3rd Edition` |
| `source_url` | RECOMMENDED | Source URL |
| `acquisition_date` | REQUIRED | Date raw files were obtained |
| `license` | REQUIRED | Varies by textbook publisher |
| `record_id` | REQUIRED | Source-path + hash |
| `content_hash` | REQUIRED | SHA-256 |
| `provenance` | RECOMMENDED | `raw_path` → `stage1_filter` |
| `quality_metadata` | OPTIONAL | `comment_ratio`, `pep8_violations`, `syntax_valid` |
| `token_count` | OPTIONAL | Provisional |
| `token_count_status` | OPTIONAL | `PROVISIONAL` |

## Stack Overflow (Session 2)

| Canonical Field | Status | Source-Specific Mapping |
|---|---|---|
| `source` | REQUIRED | `stackoverflow` |
| `source_type` | REQUIRED | `raw` (Hugging Face streaming) |
| `source_version` | RECOMMENDED | Dataset version, e.g., `raj2708/stackexchange-all` |
| `source_url` | REQUIRED | `https://huggingface.co/datasets/raj2708/stackexchange-all` |
| `acquisition_date` | REQUIRED | Date of HF streaming acquisition |
| `license` | REQUIRED | `CC-BY-SA-4.0` (per metadata) |
| `record_id` | REQUIRED | HF record identifier |
| `content_hash` | REQUIRED | SHA-256 of answer text |
| `provenance` | RECOMMENDED | `HF streaming` → `quality_filter` |
| `quality_metadata` | OPTIONAL | `answer_score`, `is_accepted`, `tier_a/b/c` |
| `token_count` | OPTIONAL | Provisional (metadata.token_count) |
| `token_count_status` | OPTIONAL | `PROVISIONAL` |
| `pypi_overlap` | SOURCE_SPECIFIC | Recorded in `quality_metadata` as `pypi_name` if applicable |

> **Note**: Session 2's existing data (stackoverflow_acquisition_v1.json, data/raw/stackoverflow/) already follows this mapping. This schema does not modify their work.

## PyPI (Session 3 — pending)

| Canonical Field | Status | Source-Specific Mapping |
|---|---|---|
| `source` | REQUIRED | `pypi` |
| `source_type` | REQUIRED | `raw` |
| `source_version` | RECOMMENDED | Package version, e.g., `2.0.0` |
| `source_url` | REQUIRED | PyPI project URL |
| `acquisition_date` | REQUIRED | Date of PyPI snapshot |
| `license` | REQUIRED | Package license |
| `record_id` | REQUIRED | `pypi:{package_name}:{version}` |
| `content_hash` | REQUIRED | SHA-256 of package metadata + source |
| `provenance` | RECOMMENDED | `PyPI API` → `metadata_filter` |
| `quality_metadata` | OPTIONAL | `python_requires`, `classifiers` |
| `token_count` | OPTIONAL | Provisional |

## GitHub (Session 4)

| Canonical Field | Status | Source-Specific Mapping |
|---|---|---|
| `source` | REQUIRED | `github` |
| `source_type` | REQUIRED | `raw` |
| `source_version` | RECOMMENDED | `{owner}/{repo}` @ `{commit_sha}` |
| `source_url` | REQUIRED | GitHub repository URL |
| `acquisition_date` | REQUIRED | Date of repository clone |
| `license` | RECOMMENDED | Detected from `license` file or `CLAUDE.md` |
| `record_id` | REQUIRED | `{owner}_{repo}_{commit}` |
| `content_hash` | REQUIRED | SHA-256 of repository content (at commit) |
| `provenance` | RECOMMENDED | `clone` → `AST_validate` → `filter` |
| `quality_metadata` | OPTIONAL | `python_files`, `ast_valid_count`, `doc_count` |
| `token_count` | OPTIONAL | Provisional (~86K tokens observed in GH-001 pilot) |
| `token_count_status` | OPTIONAL | `PROVISIONAL` |

## The Stack (Session 2/3 boundary — pending)

| Canonical Field | Status | Source-Specific Mapping |
|---|---|---|
| `source` | REQUIRED | `the_stack` |
| `source_type` | REQUIRED | `raw` |
| `source_version` | RECOMMENDED | Snapshot date/version |
| `source_url` | RECOMMENDED | The Stack archive URL |
| `acquisition_date` | REQUIRED | Date acquired |
| `license` | RECOMMENDED | Varies (per-repo license) |
| `record_id` | REQUIRED | Repo-relative path + hash |
| `content_hash` | REQUIRED | SHA-256 of file content |
| `provenance` | RECOMMENDED | `raw_archive` → `processor` |
| `quality_metadata` | OPTIONAL | `python_files`, `syntax_valid` |

## Jupyter (Session 2/3 boundary — empty)

| Canonical Field | Status | Source-Specific Mapping |
|---|---|---|
| `source` | REQUIRED | `jupyter` |
| `source_type` | REQUIRED | `raw` |
| `acquisition_date` | REQUIRED | Date notebook acquired |
| `license` | RECOMMENDED | Varies by notebook |
| `record_id` | REQUIRED | Notebook path + cell identifier |
| `content_hash` | REQUIRED | SHA-256 of code cells |

## CodeSearchNet (pending)

| Canonical Field | Status | Source-Specific Mapping |
|---|---|---|
| `source` | REQUIRED | `codesearchnet` |
| `source_type` | REQUIRED | `raw` |
| `source_url` | RECOMMENDED | CodeSearchNet API endpoint |
| `acquisition_date` | REQUIRED | Date acquired |
| `license` | RECOMMENDED | Per-repository license |
| `record_id` | REQUIRED | Record identifier from API |
| `content_hash` | REQUIRED | SHA-256 of code snippet |

## Reasoning (ablation/experiment only)

> **Important**: Reasoning data MUST NOT silently become part of the clean base-pretraining corpus. Inclusion in pretraining must be an explicit ablation/experiment.

| Canonical Field | Status | Source-Specific Mapping |
|---|---|---|
| `source` | REQUIRED | `reasoning` |
| `source_type` | REQUIRED | `raw` or `processed` |
| **`provenance`** | REQUIRED | Must trace to explicit experiment ID, not automatic inclusion |
| `reasoning_type` | RECOMMENDED | `fim_prefix`, `fim_middle`, `fim_suffix`, `instruction`, `docstring2code`, `repair` |
| `content_hash` | REQUIRED | SHA-256 of reasoning snippet |

## Reddit (pending)

| Canonical Field | Status | Source-Specific Mapping |
|---|---|---|
| `source` | REQUIRED | `reddit` |
| `source_type` | REQUIRED | `raw` |
| `source_url` | RECOMMENDED | Subreddit and post URL |
| `acquisition_date` | REQUIRED | Date acquired |
| `license` | RECOMMENDED | Per-subreddit license |
| `record_id` | REQUIRED | Post ID or comment ID |
| `content_hash` | REQUIRED | SHA-256 of text |

## Summary: REQUIRED vs OPTIONAL vs SOURCE_SPECIFIC

| Category | Fields |
|---|---|
| **REQUIRED** (every record) | `source`, `source_type`, `source_url`, `acquisition_date`, `license`, `record_id`, `content_hash` |
| **OPTIONAL** (if present, mapped to `quality_metadata`) | `source_version`, `acquisition_date`, `provenance`, `preprocessing_version`, `validator_version`, `dataset_version`, `split`, `token_count`, `token_count_status` |
| **SOURCE_SPECIFIC** (recorded in `quality_metadata` only) | PyPI overlap, generated/vendor detection, fork status, documentation metrics, etc. — stored source-specifically, not in canonical fields |