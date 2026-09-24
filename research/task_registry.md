# Pythia Task Registry

This registry is the persistent coordination index for the Pythia roadmap. Statuses are based on filesystem, report, manifest, log, test, and experiment evidence verified on 2026-09-15. `UNKNOWN` means the repository does not provide the value.

## Current assignments

- **OP current task:** PYTHIA-004 Textbooks — reconcile Stage 1 textbook artifacts and prepare the planned `PYT-DATA-002` policy comparison.
- **CD current task:** PYTHIA-003 Python documentation processor — reconcile the missing documentation output path and inconsistent manifests/reports. **Reconciliation infrastructure now in place:** `research/decision_registry.md`, `research/experiment_registry.md`, `research/run_registry.md`, `research/tokenizer/`, `research/data_quality/`, `research/evaluation/`, `data/raw/peps/`, `data/sft/` subdirectories, and `data/filtered/stage4/` created.
- **Lead current task:** maintain this coordination state and require filesystem/report/test verification before any completion claim.

**Session state summary** (for coordination; no acquisition activity performed by Session 1):

- **Session 2 — Stack Overflow**: 100,000 records scanned; 0 stackoverflow.com records found; all communities are niche StackExchange sites. BigQuery public dataset access blocked (GCP credentials not found). Source profiling classified as SOURCE_PROFILING_ONLY. SPy project continues separately toward 10,000 record scale-up.
- **Session 3 — PyPI**: 5,000 package candidate manifest; 10 packages acquired per checkpoints; known failed package: `cffi`. Acquisition/checkpoint consistency being repaired before full-scale acquisition.
- **Session 4 — GitHub**: 150-candidate pilot; 8 repositories ACQUIRED and filesystem-verified; remaining candidates constrained by ~300-second wall-clock limit. Acquisition paused for Drive/Git storage recovery; scaling to ~150 repos planned.
- **CodeSearchNet**: Session 2 is beginning acquisition work; no raw directory or snapshot presently present.

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

## PYTHIA-001 — Project foundation

- **Task ID:** PYTHIA-001
- **Task:** Project foundation
- **Owner (OP/CD/Lead):** Lead
- **Status:** completed
- **Priority:** high
- **Dependencies:** None
- **Input:** Pythia-160M objective, C3AN framework, and project-layout requirements
- **Expected output:** Repository foundation, configuration, research home, raw/filtered/log directories, and baseline documentation
- **Actual output:** `README.md`, `config.py`, `requirements.txt`, `research/`, `data/`, `logs/`, `scripts/`, and `tests/` exist; HEAD is `b9d898d`
- **Files changed:** `README.md`; `config.py`; `requirements.txt`; `research/`; `scripts/`; `tests/`; data directory scaffolding
- **Experiment ID:** UNKNOWN
- **Dataset version:** UNKNOWN
- **Notes:** Foundation is filesystem-verified. Completion does not imply a final corpus, tokenizer, model, or evaluation exists.
- **Last verified:** 2026-09-15
- **Next action:** Use the foundation as the coordination baseline; do not infer downstream completion.

## Configurable data root (infrastructure)

- **Task ID:** PYTHIA-019
- **Task:** Configurable data root with PYTHIA_DATA_ROOT env var
- **Owner (OP/CD/Lead):** CD
- **Status:** completed
- **Priority:** high
- **Dependencies:** PYTHIA-001
- **Input:** Existing config.py with hardcoded `PROJECT_ROOT / "data"` paths
- **Expected output:** `DATA_ROOT` with env var override, all canonical paths derive from `DATA_ROOT`, backward-compatible fallback when unset, validation helper script
- **Actual output:** `config.py` updated with `DATA_ROOT = Path(os.environ.get("PYTHIA_DATA_ROOT", str(PROJECT_ROOT / "data")))`; canonical layout `RAW_DIR`, `FILTERED_DIR`, `FINAL_DIR`, `MANIFEST_DIR`, `SNAPSHOT_DIR` all from `DATA_ROOT`; `scripts/research/check_data_root.py` validation helper; `research/cloud_storage.md` policy document; all 36 existing tests pass unchanged; Google Drive mount `/mnt/pythia-cloud` verified read/write (~4.948 TiB free)
- **Files changed:** `config.py`; `scripts/research/check_data_root.py`; `research/cloud_storage.md`; `research/project_status.md`; `research/task_registry.md`
- **Experiment ID:** UNKNOWN
- **Dataset version:** UNKNOWN
- **Notes:** When `PYTHIA_DATA_ROOT=/mnt/pythia-cloud` is set, all large dataset paths resolve to the Google Drive mount. When unset, paths fall back to local `data/` directory. All existing data (60 GitHub repos, Stack Overflow, PyPI) remains in place; no acquisition, relocation, or deduplication was performed. Safety policy: do not move existing data; local repo remains fully functional without cloud mount.
- **Last verified:** 2026-09-17
- **Next action:** Monitor PATH configuration for new workstreams that may benefit from cloud-backed data root

## PYTHIA-002 — AST validator

- **Task ID:** PYTHIA-002
- **Task:** AST validator
- **Owner (OP/CD/Lead):** CD
- **Status:** completed
- **Priority:** high
- **Dependencies:** PYTHIA-001
- **Input:** Python source samples and syntax-validation requirements
- **Expected output:** Non-executing authoritative AST validation with structured diagnostics and metadata
- **Actual output:** `scripts/validators/ast_validator.py` implements `validate_python`; 11 validator tests pass
- **Files changed:** `scripts/validators/ast_validator.py`; `tests/test_ast_validator.py`
- **Experiment ID:** UNKNOWN
- **Dataset version:** UNKNOWN
- **Notes:** Validator reports syntax and source-structure metadata only; it does not establish semantic correctness, PEP8 compliance, or Knowledge Graph validity.
- **Last verified:** 2026-09-15
- **Next action:** Preserve the validator logic and integrate it only through verified pipeline runs.

## PYTHIA-003 — Python documentation processor

- **Task ID:** PYTHIA-003
- **Task:** Python documentation processor
- **Owner (OP/CD/Lead):** CD
- **Status:** blocked
- **Priority:** high
- **Dependencies:** PYTHIA-001; PYTHIA-002
- **Input:** `data/raw/python_docs/python-3.14-docs-html.zip`
- **Expected output:** Extracted, AST-valid, filtered Stage 1 candidates plus a versioned manifest and report
- **Actual output:** Processor and 7 tests exist; report and raw manifest record 10,030 candidates, 4,512 syntax-valid, and 317 retained; recorded output `data/filtered/stage1/python_docs.jsonl` is missing; `python_docs_filtered_v3.jsonl` has 96 records
- **Files changed:** `scripts/scrapers/python_docs.py`; `tests/test_python_docs_scraper.py`; `data/raw/python_docs/manifest.json`; `logs/python_docs_report.json`; `data/filtered/stage1/python_docs_filtered_v3.jsonl`
- **Experiment ID:** EXP-20260915-DATA-001
- **Dataset version:** UNKNOWN (documentation version recorded as 3.14)
- **Notes:** Historical run reports 317 retained, but the recorded output path does not exist. Do not overwrite the v3 artifact or historical reports while reconciling.
- **Last verified:** 2026-09-15
- **Next action:** Reconcile the output path and counts, then rerun with a new traceable dataset/output version.

## PYTHIA-004 — Textbooks

- **Task ID:** PYTHIA-004
- **Task:** Textbooks
- **Owner (OP/CD/Lead):** OP
- **Status:** blocked
- **Priority:** high
- **Dependencies:** PYTHIA-001; PYTHIA-002
- **Input:** `thinkpython_code.jsonl`, `atbs3e_code.jsonl`, and `atbs3e_ch1_code.jsonl`
- **Expected output:** Versioned, validated textbook candidates and a policy comparison with preserved raw inputs
- **Actual output:** Raw files contain 293 Think Python, 123 ATBS, and 39 ATBS Chapter 1 records; v3 files contain 293 and 162 candidate records; strict baseline records 0/293 Think Python and 5/123 ATBS retained; manifests/reports conflict
- **Files changed:** `data/raw/textbooks/*`; `data/filtered/stage1/*_v3.jsonl`; `data/filtered/stage1/stage1_manifest.json`; `logs/data_preparation_report.*`; `research/results/data/pyt-data-001.json`
- **Experiment ID:** PYT-DATA-001; PYT-DATA-002 planned
- **Dataset version:** UNKNOWN (Think Python 2nd Edition and ATBS 3rd Edition are recorded)
- **Notes:** Provisional token counting and code-only documentation ratios limit interpretation. The v3 files are not verified strict filtered corpora.
- **Last verified:** 2026-09-15
- **Next action:** Reconcile candidate-versus-retained semantics and counts, preserve raw/v3 artifacts, and run `PYT-DATA-002` with a new version.

## PYTHIA-005 — Stack Overflow

- **Task ID:** PYTHIA-005
- **Task:** Stack Overflow
- **Owner (OP/CD/Lead):** OP
- **Status:** in_progress
- **Priority:** high
- **Dependencies:** PYTHIA-001; PYTHIA-002
- **Input:** Stack Overflow source/API and `scripts/prepare_so.py` and `scripts/scrapers/stackoverflow_hf.py` and `scripts/scrapers/stackoverflow_bigquery.py`
- **Expected output:** Immutable raw snapshot, provenance, validated candidates, manifest, and report
- **Actual output:** Preparation script exists; `data/filtered/stage2/stackoverflow_candidates.jsonl` is empty; no raw snapshot, manifest, or successful report is present; Phase 1 streaming sanity check completed with HF dataset `raj2708/stackexchange-all`; BigQuery public dataset extraction script created and tested (query construction and chunked output writing demonstrated); Phase 1 HF profiling classified as SOURCE_PROFILING_ONLY
- **Files changed:** `scripts/prepare_so.py`; `scripts/scrapers/stackoverflow_hf.py`; `scripts/scrapers/stackoverflow_select.py`; `scripts/scrapers/stackoverflow_token_budget.py`; `scripts/scrapers/stackoverflow_bigquery.py`; `data/raw/stackoverflow/stackoverflow_candidates_v1.jsonl`; `data/raw/stackoverflow/stackoverflow_bigquery_candidates_v1_part-0001.jsonl`; `data/raw/stackoverflow/manifest.json`; `data/raw/stackoverflow/manifest_bigquery_v1.json`; `research/results/data/stackoverflow_acquisition_v1.json`; `research/results/data/stackoverflow_hf_source_profile_v1.json`; `research/results/data/stackoverflow_acquisition_v1.json`; `research/results/data/stackoverflow_bigquery_experiment_v1.json`
- **Experiment ID:** PYT-DATA-SO-001; PYT-DATA-SO-002
- **Dataset version:** raj2708/stackexchange-all (Phase 1 HF); bigquery-public-data.stackoverflow (Phase 2+)
- **Notes:** Phase 1 HF profiling: 100k records scanned, 0 stackoverflow.com records found, all communities niche StackExchange sites. BigQuery extraction script demonstrates query construction and chunked output writing. Python relevance: python_core = <python> tag (primary); python_ecosystem = numpy, pandas, scipy, matplotlib, tensorflow, pytorch, django, flask, fastapi (separate metadata). Quality tiers: Tier A (accepted + score>=10), Tier B (non-accepted + score>=20), Tier C (accepted + score>=5). Token budget: preliminary metadata.token_count mean=477.1; final count needs Pythia tokenizer. Next action: execute small BigQuery query (100 records) to verify schema and output format, then controlled extraction run.
- **Last verified:** 2026-09-17
- **Next action:** Run small BigQuery query to verify schema mapping and output format (100-record milestone); if successful, begin controlled extraction with quality-tiered filtering

## PYTHIA-006 — Jupyter

- **Task ID:** PYTHIA-006
- **Task:** Jupyter
- **Owner (OP/CD/Lead):** OP
- **Status:** blocked
- **Priority:** medium
- **Dependencies:** PYTHIA-001; PYTHIA-002
- **Input:** Jupyter notebook/source data
- **Expected output:** Immutable notebook/code snapshot, processor, validated candidates, manifest, and report
- **Actual output:** `data/raw/jupyter/jupyter_readme_code.jsonl` exists but is empty; no processor, manifest, report, or filtered output exists
- **Files changed:** `data/raw/jupyter/jupyter_readme_code.jsonl`
- **Experiment ID:** UNKNOWN
- **Dataset version:** UNKNOWN
- **Notes:** No Jupyter records are available.
- **Last verified:** 2026-09-15
- **Next action:** Acquire a real Jupyter source snapshot with provenance before processing.

## PYTHIA-007 — CodeSearchNet

- **Task ID:** PYTHIA-007
- **Task:** CodeSearchNet
- **Owner (OP/CD/Lead):** OP
- **Status:** blocked
- **Priority:** medium
- **Dependencies:** PYTHIA-001; PYTHIA-002
- **Input:** CodeSearchNet Python subset
- **Expected output:** Immutable raw snapshot, provenance, validated candidates, manifest, and report
- **Actual output:** No CodeSearchNet raw directory, processor, manifest, report, or filtered output is present
- **Files changed:** UNKNOWN
- **Experiment ID:** UNKNOWN
- **Dataset version:** UNKNOWN
- **Notes:** Source acquisition is not evidenced.
- **Last verified:** 2026-09-15
- **Next action:** Acquire and checksum the source subset, then define the processing run.

## PYTHIA-008 — The Stack

- **Task ID:** PYTHIA-008
- **Task:** The Stack
- **Owner (OP/CD/Lead):** OP
- **Status:** blocked
- **Priority:** medium
- **Dependencies:** PYTHIA-001; PYTHIA-002
- **Input:** Heavily filtered The Stack Python subset
- **Expected output:** Immutable raw snapshot, provenance, validated candidates, manifest, and report
- **Actual output:** No The Stack raw directory, processor, manifest, report, or filtered output is present
- **Files changed:** UNKNOWN
- **Experiment ID:** UNKNOWN
- **Dataset version:** UNKNOWN
- **Notes:** Source acquisition is not evidenced.
- **Last verified:** 2026-09-15
- **Next action:** Acquire and checksum the source subset, then define the processing run.

## PYTHIA-009 — Deduplication

- **Task ID:** PYTHIA-009
- **Task:** Deduplication
- **Owner (OP/CD/Lead):** CD
- **Status:** in_progress
- **Priority:** high
- **Dependencies:** PYTHIA-003; PYTHIA-004; PYTHIA-005; PYTHIA-006; PYTHIA-007; PYTHIA-008
- **Input:** Candidate JSONL files and exact-hash fields
- **Expected output:** Tested exact and near-deduplication with a versioned deduplicated corpus and manifest
- **Actual output:** Exact hashes, duplicate statuses, and duplicate counts exist in candidate artifacts/reports; no verified near-deduplication implementation or deduplicated final corpus exists
- **Files changed:** `scripts/scrapers/python_docs.py`; Stage 1 candidate files; `data/filtered/stage1/stage1_manifest.json`
- **Experiment ID:** PYT-DATA-001; EXP-20260915-DATA-001
- **Dataset version:** UNKNOWN
- **Notes:** The configured similarity threshold is 0.85, but no near-deduplication result is recorded.
- **Last verified:** 2026-09-15
- **Next action:** Define and test deduplication after source artifacts are reconciled; preserve all historical candidate outputs.

## PYTHIA-010 — Curriculum/final corpus

- **Task ID:** PYTHIA-010
- **Task:** Curriculum/final corpus
- **Owner (OP/CD/Lead):** OP
- **Status:** blocked
- **Priority:** high
- **Dependencies:** PYTHIA-003 through PYTHIA-009
- **Input:** Verified Stage 1-3 candidates and deduplication outputs
- **Expected output:** Curriculum specification, versioned final corpus, manifest, and provenance
- **Actual output:** `data/final/corpus.jsonl` exists but is empty; no curriculum specification or final manifest exists
- **Files changed:** `data/final/corpus.jsonl`; `config.py`
- **Experiment ID:** UNKNOWN
- **Dataset version:** UNKNOWN
- **Notes:** The README documents an intended approximately 5-6 GB target, but no corpus reaching that state is present.
- **Last verified:** 2026-09-15
- **Next action:** Assemble only after upstream source and deduplication tasks are verified.

## PYTHIA-011 — Custom tokenizer

- **Task ID:** PYTHIA-011
- **Task:** Custom tokenizer
- **Owner (OP/CD/Lead):** CD
- **Status:** blocked
- **Priority:** high
- **Dependencies:** PYTHIA-010; verified corpus policy
- **Input:** Versioned Python corpus and tokenizer requirements
- **Expected output:** Custom tokenizer implementation, trained artifacts, version, and compression/quality evaluation
- **Actual output:** `tiktoken` is listed in `requirements.txt`; no tokenizer implementation or artifact exists; existing counts are provisional
- **Files changed:** `requirements.txt`
- **Experiment ID:** UNKNOWN
- **Dataset version:** UNKNOWN
- **Notes:** Formal tokenizer version is `UNKNOWN`.
- **Last verified:** 2026-09-15
- **Next action:** Define a tokenizer experiment after corpus policy and versioning are stable.

## PYTHIA-012 — Knowledge Graph

- **Task ID:** PYTHIA-012
- **Task:** Knowledge Graph
- **Owner (OP/CD/Lead):** CD
- **Status:** blocked
- **Priority:** high
- **Dependencies:** PYTHIA-002; PYTHIA-010
- **Input:** Validated corpus and graph schema requirements
- **Expected output:** Knowledge Graph implementation, populated graph, validator, and feedback interface
- **Actual output:** No graph implementation or artifact exists; candidate records mark `kg_validation_status` as `pending`
- **Files changed:** UNKNOWN
- **Experiment ID:** UNKNOWN
- **Dataset version:** UNKNOWN
- **Notes:** Knowledge Graph status is not started beyond pending markers.
- **Last verified:** 2026-09-15
- **Next action:** Define schema and validation tests after stable data interfaces exist.

## PYTHIA-013 — Model architecture

- **Task ID:** PYTHIA-013
- **Task:** Model architecture
- **Owner (OP/CD/Lead):** CD
- **Status:** blocked
- **Priority:** high
- **Dependencies:** PYTHIA-010; PYTHIA-011
- **Input:** Versioned corpus, tokenizer, and model requirements
- **Expected output:** Approximately 160M-parameter architecture specification, implementation, configuration, and tests
- **Actual output:** README documents the approximately 160M objective; no model code or architecture artifact exists
- **Files changed:** `README.md`
- **Experiment ID:** UNKNOWN
- **Dataset version:** UNKNOWN
- **Notes:** Architecture is an objective, not a verified implementation.
- **Last verified:** 2026-09-15
- **Next action:** Specify architecture after tokenizer and corpus direction are verified.

## PYTHIA-014 — Pretraining

- **Task ID:** PYTHIA-014
- **Task:** Pretraining
- **Owner (OP/CD/Lead):** CD
- **Status:** blocked
- **Priority:** high
- **Dependencies:** PYTHIA-010; PYTHIA-011; PYTHIA-013
- **Input:** Model, tokenizer, corpus, optimizer/schedule configuration, and hardware environment
- **Expected output:** Reproducible pretraining runs, checkpoints, logs, and run-registry entries
- **Actual output:** No training code, configuration, checkpoints, logs, or results exist
- **Files changed:** UNKNOWN
- **Experiment ID:** UNKNOWN
- **Dataset version:** UNKNOWN
- **Notes:** No pretraining evidence is present.
- **Last verified:** 2026-09-15
- **Next action:** Define the first training experiment after architecture and data versions are fixed.

## PYTHIA-015 — Neurosymbolic inference/feedback

- **Task ID:** PYTHIA-015
- **Task:** Neurosymbolic inference/feedback
- **Owner (OP/CD/Lead):** CD
- **Status:** blocked
- **Priority:** high
- **Dependencies:** PYTHIA-002; PYTHIA-012; PYTHIA-013
- **Input:** Model, AST validator, Knowledge Graph, and feedback interface
- **Expected output:** Generate -> AST -> Knowledge Graph -> feedback/regeneration loop with tests
- **Actual output:** Only the intended diagram and AST validator exist; no Knowledge Graph, inference integration, or feedback/regeneration implementation exists
- **Files changed:** `README.md`
- **Experiment ID:** UNKNOWN
- **Dataset version:** UNKNOWN
- **Notes:** No neurosymbolic result is recorded; generated code must not be executed as part of validation without an explicit safe policy.
- **Last verified:** 2026-09-15
- **Next action:** Define interfaces and tests after the Knowledge Graph and model exist.

## PYTHIA-016 — Evaluation

- **Task ID:** PYTHIA-016
- **Task:** Evaluation
- **Owner (OP/CD/Lead):** CD
- **Status:** blocked
- **Priority:** high
- **Dependencies:** PYTHIA-013; PYTHIA-014; PYTHIA-015
- **Input:** Model/checkpoints, benchmarks, tokenizer, and evaluation protocol
- **Expected output:** Evaluation harness, registered runs, metrics, and result artifacts
- **Actual output:** Research questions and hypotheses exist; `research/results/evaluation/` is empty; no harness or measurements exist
- **Files changed:** `research/research_questions.md`; `research/hypotheses.md`; `research/results/evaluation/.gitkeep`
- **Experiment ID:** UNKNOWN
- **Dataset version:** UNKNOWN
- **Notes:** Questions and hypotheses are not evaluation results.
- **Last verified:** 2026-09-15
- **Next action:** Define benchmarks and metrics after a model checkpoint is available.

## PYTHIA-017 — HuggingFace release

- **Task ID:** PYTHIA-017
- **Task:** HuggingFace release
- **Owner (OP/CD/Lead):** CD
- **Status:** blocked
- **Priority:** medium
- **Dependencies:** PYTHIA-014; PYTHIA-016
- **Input:** Verified model, dataset/model versions, licenses, evaluation, and model card
- **Expected output:** Traceable HuggingFace release artifacts and publication record
- **Actual output:** `huggingface_hub` is listed in requirements; no release artifact or publication record exists
- **Files changed:** `requirements.txt`
- **Experiment ID:** UNKNOWN
- **Dataset version:** UNKNOWN
- **Notes:** No release evidence is present.
- **Last verified:** 2026-09-15
- **Next action:** Prepare release checklist only after model and evaluation are verified.

## PYTHIA-018 — Research/writeup

- **Task ID:** PYTHIA-018
- **Task:** Research/writeup
- **Owner (OP/CD/Lead):** Lead
- **Status:** in_progress
- **Priority:** medium
- **Dependencies:** PYTHIA-001 through PYTHIA-017 evidence
- **Input:** Research questions, hypotheses, experiment records, reports, decisions, and results
- **Expected output:** Writeup/paper whose claims are traceable to registered experiments and artifacts
- **Actual output:** Research README, questions, hypotheses, decision/experiment/run infrastructure, and preliminary data records exist; no paper or completed result set exists
- **Files changed:** `research/README.md`; `research/research_questions.md`; `research/hypotheses.md`; `research/decisions.md`; `research/experiment_log.md`; `research/reproducibility/run_registry.md`; research result scaffolding
- **Experiment ID:** PYT-DATA-001; EXP-20260915-DATA-001
- **Dataset version:** UNKNOWN
- **Notes:** No claims should exceed the recorded evidence. This coordination-layer update is part of the research infrastructure, not a completed writeup.
- **Last verified:** 2026-09-15
- **Next action:** Keep records current and draft only from verified, registered results.
