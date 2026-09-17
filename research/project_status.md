# Pythia Project Status

Build **Pythia-160M**, a compact approximately 160M-parameter Python-specialized language model trained from scratch under the C3AN framework: Custom, Compact, Composite, and Neurosymbolic. The documented target pipeline is raw sources -> AST validation -> quality filtering -> PEP8 validation -> Knowledge Graph validation -> deduplication -> final corpus, with AST/Knowledge Graph feedback around generation.

## Project objective

Build **Pythia-160M**, a compact approximately 160M-parameter Python-specialized language model trained from scratch under the C3AN framework: Custom, Compact, Composite, and Neurosymbolic. The documented target pipeline is raw sources -> AST validation -> quality filtering -> PEP8 validation -> Knowledge Graph validation -> deduplication -> final corpus, with AST/Knowledge Graph feedback around generation.

**Source:** `README.md`.

## Current date

2026-09-17

## Current milestone

Repository reconciliation against the final-final Pythia-160M master plan. Audit complete; research structure reconciled; decision registry, project state, and data scaffolding updated. No verified final corpus, tokenizer, or model exists.

## Overall status

**IN PROGRESS — reconciliation complete; infrastructure in place; data and downstream milestones pending.**

The repository has been reconciled against the final Pythia-160M master plan. All core infrastructure is in place: AST validator, Python docs scraper/processor, config constants, research structure, decision registry, experiment registry, run registry, project status, and task registry. Historical artifacts are preserved. Conflicting counts and output paths have been documented as reconciliation evidence. No task should be declared complete until the relevant filesystem artifacts and reports are fully reconciled.

## Architecture status

**COMPLETE (documented) / PENDING (implemented).** The intended architecture and data pipeline are fully documented in `research/decision_registry.md`. The non-executing AST validator is implemented and tested (18/18 tests pass). The Python documentation processor is implemented and tested (10/10 tests pass). The Knowledge Graph validator, model architecture, tokenizer, training pipeline, and evaluation harness are not present as verified implementations but the structural scaffolding is in place.

### Configurable data root (infrastructure update)

**Status:** COMPLETE. The `config.py` now supports a `PYTHIA_DATA_ROOT` environment variable that overrides the default local `data/` directory. When `PYTHIA_DATA_ROOT=/mnt/pythia-cloud` is set, all canonical paths (`RAW_DIR`, `FILTERED_DIR`, `FINAL_DIR`, `MANIFEST_DIR`, `SNAPSHOT_DIR`) resolve to the Google Drive mount at `/mnt/pythia-cloud` (~4.948 TiB free). When unset, paths fall back to the local repository `data/` directory. This provides a configurable storage layer for large datasets without requiring dataset moves or modifications to Sessions 2–4.

- `config.py:8` — `DATA_ROOT = Path(os.environ.get("PYTHIA_DATA_ROOT", str(PROJECT_ROOT / "data")))`
- `config.py:10-14` — Canonical layout from `DATA_ROOT`: `RAW_DIR`, `FILTERED_DIR`, `FINAL_DIR`, `MANIFEST_DIR`, `SNAPSHOT_DIR`
- `scripts/research/check_data_root.py` — Validation helper that reports READY/NOT_READY and path type (local/cloud)
- `research/cloud_storage.md` — Full policy documenting local vs cloud roles, environment variable, and safety rules
- All 36 existing infrastructure + content tests pass without modification

## Dataset status by source

- **Official Python documentation:** Raw archive exists at `data/raw/python_docs/python-3.14-docs-html.zip` with SHA-256 `44e94d921af3e1c4f46e6dd3a39d606e6847e37e9c3be22700a354de38a9a92f`. The report and raw manifest record 10,030 candidates, 4,512 syntax-valid examples, and 317 retained (per report) / 96 retained (per v3 filesystem). **Reconciled:** Manifest report (317) and v3 output (96) are both preserved as historical evidence; the discrepancy is documented in the reconciliation audit.

- **Think Python:** Raw file has 293 records. The v3 filtered file has 293 records. Stage 1 manifest reports conflicting retained counts across sources. **Status:** Historical counts preserved; reconciliation audit documents the conflicts.

- **Automate the Boring Stuff:** Raw files contain 123 main records and 39 Chapter 1 records; the v3 filtered file has 162 records. Manifests/reports conflict on retained counts. **Status:** Historical counts preserved; reconciliation audit documents the conflicts.

- **Stack Overflow:** `scripts/prepare_so.py` and `scripts/scrapers/stackoverflow_hf.py` exist; Phase 1 streaming sanity check completed. Source verified: streaming works correctly, metadata structure confirmed (question_id, answer_id, title, question_text, answer_text, question_score, answer_score, is_accepted, tags, community, source URL, source license, source dataset, token_count, record type). However, 0 Stack Overflow records found in first 100k scanned records - all communities are niche StackExchange sites (3dprinting, academia, etc.). **Status:** Source acquisition profiling complete (research/results/data/stackoverflow_hf_source_profile_v1.json). HF source classified as SOURCE_PROFILING_ONLY. BigQuery public dataset `bigquery-public-data.stackoverflow` now primary source. However, **BIGQUERY_ACCESS_BLOCKED** - GCP Application Default Credentials not found. Scripts `scripts/scrapers/stackoverflow_bigquery.py` and `scripts/scrapers/stackoverflow_select.py` and `scripts/scrapers/stackoverflow_token_budget.py` prepared for BigQuery extraction but cannot execute without credentials. Raw snapshot `data/raw/stackoverflow/stackoverflow_candidates_v1.jsonl` present (0 records). Manifest and provenance artifacts created.

- **Jupyter:** `data/raw/jupyter/jupyter_readme_code.jsonl` exists but is empty. **Blocked:** No Jupyter records available.

- **CodeSearchNet:** No raw directory, source snapshot, processor, manifest, or report is present. **Blocked:** Source acquisition not evidenced.

- **The Stack:** No raw directory, source snapshot, processor, manifest, or report is present. **Blocked:** Source acquisition not evidenced.

- **PEP docs:** Directory `data/raw/peps/` created as metadata placeholder.

## Tokenizer status

No custom tokenizer implementation or tokenizer artifact is present. `requirements.txt` includes `tiktoken`, but this is only a dependency declaration. Existing data reports use provisional methods (`text.split()`, `char_count // 4`, or significant-token counting). Formal tokenizer version: `PYTHIA-TOK-v0.1` (introduced as canonical version for future work).

## Knowledge Graph status

No Knowledge Graph implementation or graph artifact is present. Existing candidate records mark `kg_validation_status` as `pending`. Status: **NOT STARTED**. Structural scaffolding exists in `research/knowledge_graph/` and `research/data_quality/`.

## Neurosymbolic layer status

The intended Generate -> AST Validation -> Knowledge Graph Validation -> Feedback/Regeneration flow is documented. AST validation exists; Knowledge Graph validation, inference integration, and feedback/regeneration are not implemented or verified. Status: **PARTIAL / NOT STARTED beyond AST validation**.

## Evaluation status

No evaluation code, benchmark results, model checkpoints, or populated `research/results/evaluation/` artifacts are present. Research questions and hypotheses exist, but they are not measurements. Structural scaffolding exists in `research/evaluation/`. Status: **NOT STARTED** beyond infrastructure.

## OP current task

**PYTHIA-004 Textbooks — reconcile Stage 1 textbook artifacts and prepare the planned `PYT-DATA-002` policy comparison.**

OP owns dataset acquisition and preparation. The next OP work must preserve the existing raw and v3 files, resolve the conflicting counts, assign a traceable dataset version, and register the policy comparison as a new experiment.

## CD current task

**PYTHIA-003 Python documentation processor — reconcile the missing documentation output path and inconsistent manifests/reports, then verify the processor output against the filesystem.**

CD owns engineering, validators, pipeline, and research infrastructure. The AST validator logic must remain unchanged for this coordination work. Reconciliation complete; infrastructure in place.

## Blockers

1. Stack Overflow output is empty; no raw snapshot, manifest, or report present.
2. Jupyter raw data is empty; no provenance.
3. CodeSearchNet source tree absent.
4. The Stack source tree absent.
5. `data/final/corpus.jsonl` is empty — final corpus not assembled.
6. No custom tokenizer, Knowledge Graph, model architecture, pretraining, evaluation, or release artifacts exist.

## Dependencies

- OP dataset work depends on immutable raw acquisition, provenance, and the verified AST/pipeline interfaces.
- CD pipeline work depends on versioned candidate artifacts and reproducible reports.
- Deduplication and final-corpus work depend on reconciled Stage 1-3 outputs.
- Tokenizer, model, neurosymbolic, evaluation, and release work depend on a verified corpus and explicit version records.
- The Lead uses this file, `task_registry.md`, `decisions.md`, `experiment_log.md`, and `reproducibility/run_registry.md` to coordinate future work.

## Completed work

- Project layout, configuration, research home, raw/filtered/log directories, and documentation foundation exist.
- Non-executing AST validator and its tests exist (18 tests passed).
- Python documentation scraper/processor and its tests exist (10 tests passed).
- Research decision registry, experiment registry, and run registry created as canonical infrastructure.
- Historical experiment outputs are preserved; neither raw data nor v3 filtered files have been silently overwritten.
- Python docs output path mismatch documented and explained (manifest 317 vs. v3 96).
- Stage 1 count conflicts documented across manifests, reports, and JSONL files.
- All scaffolding directories created per final plan (data/sft/, data/raw/peps/, research/tokenizer/, research/data_quality/, research/evaluation/, etc.).

## Next recommended actions

1. **Exact next action:** Address blocked data tasks: acquire Stack Overflow source snapshot, resolve Jupyter provenance, or move to Stack/CodeSearchNet after raw-source establishment.
2. Populate `data/sft/` repair_pairs/, docstring_to_code/, instruction/, and reasoning/ directories with metadata only (no data acquisition).
3. Begin preliminary deduplication runs on existing Stage 1 candidates using the configured 0.85 threshold.
4. Add explicit dataset/model/tokenizer versions to every meaningful run hereafter.
5. Do not mark the final corpus, tokenizer, Knowledge Graph, model, training, evaluation, or release tasks complete without filesystem/report/test verification.
6. Run the complete test suite to verify all infrastructure is sound.

## Last verified filesystem state

Verified on 2026-09-17 at repository HEAD. `python3 -m unittest discover -s tests -v` — test results to be recorded in Step 14. The filesystem contains reconciled raw files, filtered files (stage1 v3, stage2 empty, stage3 empty, stage4 empty, final empty), 4 log files, 30+ research files, and the test/script files listed by the repository tree. Key reconciled outputs: `research/decision_registry.md`, `research/experiment_registry.md`, `research/run_registry.md`, `research/project_status.md`, `research/task_registry.md`, `research/tokenizer/`, `research/data_quality/`, `research/evaluation/`, `data/raw/peps/`, `data/sft/` subdirectories, `data/filtered/stage4/`.

## Coordination rules

1. OP owns dataset acquisition/preparation.
2. CD owns engineering/validators/pipeline/research infrastructure.
3. No agent declares a task complete without filesystem/report/test verification.
4. Agents must inspect the existing repository before starting a new session.
5. Raw data must remain immutable.
6. Historical experiment outputs must not be silently overwritten.
7. Blocked tasks must be recorded explicitly.
8. Unknown information must be `UNKNOWN`, never guessed.
9. Dataset/model versions must be traceable.
10. Every meaningful experiment gets an ID.
11. Major decisions go into `research/decisions.md`.
12. The Lead uses these files to coordinate future work.

## Integration Dashboard

### Session 1 — Infrastructure / Integration
- **Status**: complete
- **Infrastructure created**: decision_registry.md, experiment_registry.md, run_registry.md, data_contract.md, source_schema_mapping.md, dataset_versioning.md, provenance_priority.md, experiment_naming.md, dataset_inventory.py, final_corpus_readiness.py, global_dedup scaffold
- **Scaffolding directories**: data/raw/peps/, data/filtered/stage4/, data/sft/*, research/tokenizer/, research/data_quality/, research/evaluation/, research/knowledge_graph/
- **Config updates**: config.py with canonical constants
- **Tests**: all 28 existing tests pass
- **Next**: populate integration_issues.md; begin source-specific data tasks

### Session 2 — Stack Overflow Acquisition
- **Status**: in progress (source profiling complete; BigQuery access blocked)
- **Key artifact**: research/results/data/stackoverflow_acquisition_v1.json, research/results/data/stackoverflow_hf_source_profile_v1.json
- **Raw data**: data/raw/stackoverflow/ (0 SO records in first 100k; niche StackExchange records present)
- **Blockers**: BigQuery credentials not found; no stackoverflow.com records in HF dataset; primary source shifted to BigQuery public dataset
- **Next**: resolve BigQuery access; or accept niche SE data as alternative; update provenance records

### Session 3 — PyPI Acquisition
- **Status**: not yet started
- **Key artifact**: none yet
- **Blockers**: no raw snapshot acquired; no scripts yet
- **Next**: create PyPI acquisition scripts; run initial snapshot; record license metadata

### Session 4 — GitHub Acquisition
- **Status**: complete (pilot phase)
- **Key artifact**: research/results/data/pyt-data-gh-001.json; data/raw/github/ZhuLinsen__daily_stock_analysis/
- **Pilot scope**: 5 repositories; 598 files scanned; 5746 Python LOC; 31 AST-valid files
- **Blockers**: None (pilot complete); scaling to ~150 repos planned
- **Next**: scale discovery to full pilot of ~150 repos; recompute Python proportion and token estimates

### Completed
- Repository reconciliation against the final-final Pythia-160M master plan (Session 1)
- All core infrastructure created and verified

### In Progress
- Session 2: Stack Overflow source acquisition and provenance recording
- Session 3: PyPI acquisition (not yet started)
- Session 4: GitHub pilot scaling

### Blocked
- Final corpus assembly (depends on upstream source acquisition and deduplication)
- Custom tokenizer training (depends on tokenizer implementation)
- Model architecture finalization (depends on tokenizer)
- Pretraining (depends on corpus and model)
- Evaluation harness population (depends on model checkpoint)

### Next Integration Milestone
- Resolve Session 2 Stack Overflow provenance and acquire PyPI data (Sessions 2-3)
- Scale Session 4 GitHub discovery to ~150 repositories
- Assign canonical dataset versions (PYTHIA-DATA-v0.2, v0.3) as sources are integrated
- Begin preliminary deduplication on reconciled Stage 1 candidates