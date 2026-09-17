# Integration Issues — Pythia-160M

This document records issues discovered during reconciliation and infrastructure preparation. **No active workstream scripts or data files were modified.** Issues are recorded for tracking; resolution is outside the scope of this reconciliation task unless explicitly assigned.

## Blocked / Pending

### Issue #1: Stack Overflow BigQuery Access Blocked
- **Source**: Session 2 (Stack Overflow acquisition)
- **Details**: BigQuery public dataset `bigquery-public-data.stackoverflow` is the primary alternative source after 0 Stack Overflow records were found in the first 100k Hugging Face `raj2708/stackexchange-all` streaming records. However, GCP Application Default Credentials are not available in the current environment, preventing BigQuery execution.
- **Files affected**: None (read-only recording). Scripts `scripts/scrapers/stackoverflow_bigquery.py`, `stackoverflow_select.py`, and `stackoverflow_token_budget.py` were prepared but cannot execute without credentials.
- **Status**: Blocked — awaiting credential resolution or alternative source.
- **Resolution path**: Obtain GCP ADC, or accept niche StackExchange data as-is, or seek external GCP access.

### Issue #2: No Stack Overflow Records in Sampled HF Dataset
- **Source**: Session 2 (Stack Overflow acquisition)
- **Details**: The Hugging Face `raj2708/stackexchange-all` dataset's first 100k train split records contain 0 `stackoverflow.com` community records. All communities are niche StackExchange sites (3dprinting, academia, etc.). Python relevance cannot be assessed without SO records.
- **Files affected**: None (read-only recording). Existing artifacts: `stackoverflow_hf_source_profile_v1.json`, `stackoverflow_acquisition_v1.json`.
- **Status**: Resolved (profiling complete; alternative source recommended).
- **Resolution**: BigQuery public dataset is the recommended primary source for SO QA pairs.

### Issue 3: PyPI Acquisition Not Yet Started
- **Source**: Session 3 (PyPI acquisition)
- **Details**: No PyPI snapshot has been acquired yet. No scripts, manifests, or result files exist. License metadata is unknown.
- **Files affected**: None (read-only recording).
- **Status**: Not started.
- **Resolution path**: Session 3 to create PyPI acquisition scripts, run initial snapshot, record license metadata.

### Issue 4: CodeSearchNet and The Stack Source Trees Absent
- **Source**: Sessions 2-4 (various)
- **Details**: Neither `data/raw/codesearchnet/` nor `data/raw/the_stack/` have source snapshots, manifests, or reports. These were identified as blocked tasks in the original audit and remain unresolved.
- **Files affected**: None (read-only recording). Refer to original audit audit.md for full details.
- **Status**: Blocked (as documented in original audit).
- **Resolution path**: Session-dependent source acquisition.

### Issue 5: Jupyter Raw Data Empty
- **Source**: Session 2 (partial, listed in original audit)
- **Details**: `data/raw/jupyter/jupyter_readme_code.jsonl` exists but is empty. No Jupyter notebook/code snapshot with provenance is available.
- **Files affected**: None (read-only recording). Refer to original project_status.md.
- **Status**: Blocked (as documented in project_status.md).
- **Resolution path**: Session-dependent source acquisition.

### Issue 6: Tokenizer Not Yet Available — All Counts Provisional
- **Source**: Project-wide
- **Details**: No custom Pythia tokenizer exists (`PYTHIA-TOK-v0.1`). All existing token counts are provisional (whitespace-based or `char_count // 4`). Final token counts cannot be computed until the tokenizer is implemented and versioned.
- **Files affected**: None (read-only recording). Noted in `config.py`, `decision_registry.md`, `dataset_versioning.md`, and `project_status.md`.
- **Status**: Pending (tokenizer development is a separate workstream).
- **Resolution path**: Tokenizer implementation workstream.

### Issue 7: Knowledge Graph Not Started
- **Source**: CD
- **Details**: No Knowledge Graph implementation or graph artifact exists. Candidate records mark `kg_validation_status` as `pending`. Structural scaffolding exists in `research/knowledge_graph/` and `research/data_quality/`, but no entities or relationships have been extracted.
- **Files affected**: None (read-only recording). Refer to `project_status.md` and `knowledge_graph/README.md`.
- **Status**: Not started (structural scaffolding in place).
- **Resolution path**: KG entity/relationship extraction after stable data interfaces exist.

### Issue 8: Evaluation Infrastructure Sparse
- **Source**: CD
- **Details**: Structural scaffolding exists in `research/evaluation/` with subdirectories (tokenizer/, ablations/, contamination/), but no benchmark runners, result schemas, or `run_eval(config) -> dict` interface is implemented. The `final_corpus_readiness.py` tool returns `NOT_READY`.
- **Files affected**: None (read-only recording). Refer to `project_status.md` and `research/evaluation/` directory.
- **Status**: Infrastructure in place, content pending.
- **Resolution path**: Populate evaluation subdirectories with schema definitions and `run_eval` interface.

## Resolved Issues (Read-Only Record)

### Issue #9: Python Docs Output Path Discrepancy (Reconciled)
- **Details**: Manifest claims 317 retained records at `data/filtered/stage1/python_docs.jsonl`, but that file is absent; v3 filtered file has 96 records. Documented in `audit.md` and `changes.md`; both historical artifacts preserved.
- **Resolution**: Manifest report (317) and v3 output (96) preserved as historical evidence; discrepancy documented.

### Issue #10: Stage 1 Count Conflicts (Reconciled)
- **Details**: `stage1_manifest.json`, `logs/data_preparation_report.json`, textbook experiment records, and v3 JSONL files disagreed on counts. All preserved as historical evidence; documented in `audit.md`.
- **Resolution**: All historical counts preserved; no silent overwrites.

## Guidelines for Issue Recording

1. **Never modify** `scripts/scrapers/stackoverflow_*`, `scripts/scrapers/pypi_*`, `scripts/scrapers/github_*`, or any Session 2-4 scripts.
2. **Never modify** `data/raw/stackoverflow/`, `data/raw/pypi/`, `data/raw/github/` or their contents.
3. **Record issues as read-only text** in `research/integration_issues.md`.
4. **Assign ownership** (OP/CD/SessionX) for each issue.
5. **Do not fabricate** statistics or claim resolution unless verified.
6. **Link to relevant artifacts** by file path (not by content summary).
7. **Issues remain open** until explicitly resolved or marked `WONTFIX` with reason.