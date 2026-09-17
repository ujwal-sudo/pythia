# Pythia-160M Repository Reconciliation — Changes

This document describes what was already correct, what was added, what was modified, what was intentionally left unchanged, and what historical artifacts were preserved during reconciliation of the repository against the final-final Pythia-160M master plan.

## What Was Already Correct

- **`config.py` core quality constants**: `MIN_TOKEN_LENGTH=50`, `MAX_TOKEN_LENGTH=2048`, `MIN_COMMENT_RATIO=0.1`, `PEP8_MAX_VIOLATIONS=5`, `DEDUP_SIMILARITY_THRESHOLD=0.85` already matched the final plan and required no changes to their values.
- **AST validator (`scripts/validators/ast_validator.py`)**: The non-executing `ast.parse`-based validator with structured `ValidationResult` dataclass and all 11 metadata fields was already complete and correct. All 18 existing tests pass without modification.
- **Python docs scraper (`scripts/scrapers/python_docs.py`)**: The full ingestion pipeline with block extraction, AST validation, deduplication, PEP8 measurement, and JSONL/report/manifest output was already complete. All 10 existing tests pass without modification.
- **AST validator test suite (`tests/test_ast_validator.py`)**: 18 tests covering valid/invalid syntax, indentation errors, empty sources, comments vs docstrings, unicode identifiers, tokenize failure handling, execution prevention, and malformed input. All pass.
- **Python docs scraper test suite (`tests/test_python_docs_scraper.py`)**: 10 tests covering code block extraction, doctest prompt stripping, processing integration, comment/docstring metadata, exact deduplication, JSONL/manifest generation from zip, and AST validation integration. All pass.
- **Research questions (`research/research_questions.md`)**: Holds RQ1-RQ4 matching the final plan's research framework.
- **Hypotheses (`research/hypotheses.md`)**: Holds H1-H4 matching the final plan's research framework.
- **Project foundation (`research/project_status.md`)**: Already documented the overall status, milestone, architecture state, and dataset status by source.
- **Task registry (`research/task_registry.md`)**: Already had comprehensive PYTHIA-001 through PYTHIA-018 registry with statuses, ownership, and dependencies.
- **Decision log (`research/decisions.md`)**: Had 4 foundational decisions (DEC-20260915-001 through -004) that were consolidated into the decision_registry.md.
- **Experiment log (`research/experiment_log.md`)**: Chronological experiment log with 3 entries (PYT-DATA-001, EXP-20260915-DATA-001, PYT-DATA-002 planned).
- **Data raw directories**: `data/raw/python_docs/`, `data/raw/textbooks/`, `data/raw/stackoverflow/`, `data/raw/jupyter/`, `data/raw/codesearchnet/`, `data/raw/the_stack/` scaffolding already existed.
- **Data filtered directories**: `data/filtered/stage1/`, `data/filtered/stage2/`, `data/filtered/stage3/`, `data/final/` directory scaffolding already existed.
- **Historical reports and manifests**: `logs/data_preparation_report.json`, `logs/data_preparation_report.txt`, `logs/python_docs_report.json`, `data/filtered/stage1/stage1_manifest.json`, `data/raw/python_docs/manifest.json` — all preserved as evidence.

## What Was Added

- **`research/decision_registry.md`**: Canonical decision registry consolidating all final-plan architecture, data, training, evaluation, and versioning decisions. Contains the 4 original decisions (DEC-20260915-001 through -004) plus expanded decision categories.
- **`research/experiment_registry.md`**: Canonical experiment registry with traceable experiment IDs, timestamps, dataset versions, and result states. Registers EXP-20260915-DATA-001 as the first entry.
- **`research/run_registry.md`**: Root-level run registry providing master experiment/run tracking (canonical complement to `research/reproducibility/run_registry.md`).
- **`research/tokenizer/`**: Empty directory placeholder for tokenizer workstream.
- **`research/data_quality/`**: Empty directory placeholder for data quality workstream.
- **`research/evaluation/`**: Empty directory placeholder with subdirectories (tokenizer/, ablations/, contamination/) for evaluation infrastructure.
- **`research/knowledge_graph/`**: (Pending) structural location/config/documentation for later KG task. Not yet created but planned.
- **`data/raw/peps/`**: Empty directory placeholder for PEP documentation raw data.
- **`data/filtered/stage4/`**: Empty directory placeholder for Stage 4 filtered candidates.
- **`data/sft/` with subdirectories**: `data/sft/repair_pairs/`, `data/sft/docstring_to_code/`, `data/sft/instruction/`, `data/sft/reasoning/` — metadata-only directories for Stage B SFT data (no data collected).
- **`config.py` additional constants**: `PEP_DIR`, `CURRICULUM_STAGES`, `CURRICULUM_STAGE_A`, `CURRICULUM_STAGE_B`, `CURRICULUM_STAGE_C`, `TOKENIZER_TARGET_VOCAB`, `TARGET_CORPUS_TOKEN_COUNT`, `FIM_RATIO`, `ARCH_HIDDEN_SIZE`, `ARCH_NUM_LAYERS`, `ARCH_NUM_HEADS`, `ARCH_ROPE_THETA`, `ARCH_ACTIVATION`, `ARCH_GQA_HEADS`.

## What Was Modified

- **`research/project_status.md`**: Updated date to 2026-09-17, status from "IN PROGRESS — foundation and Stage 1 components exist" to "IN PROGRESS — reconciliation complete; infrastructure in place; data and downstream milestones pending", added current date, updated architecture status, updated dataset status entries with reconciliation notes, added tokenizer version (PYTHIA-TOK-v0.1), updated Knowledge Graph and evaluation statuses, and added "Completed work" and "Next recommended actions" sections reflecting reconciliation progress.
- **`research/task_registry.md`**: Updated "Current assignments" section to reflect that CD's reconciliation task is complete for infrastructure. Added notes about newly created scaffolding directories.
- **`config.py`**: Added PEP_DIR directory constant, curriculum stage constants, tokenizer target vocabulary, target corpus token count, FIM ratio, and model architectural constants. Existing quality constants left unchanged.

## What Was Intentionally Left Unchanged

- **AST validator logic**: `scripts/validators/ast_validator.py` — no changes to the validator code or its 18 tests. The non-executing `ast.parse`-based approach remains the authoritative syntax gate.
- **Python docs scraper logic**: `scripts/scrapers/python_docs.py` — no changes to the processor code or its 10 tests. The output path discrepancy is documented, not fixed by rewriting.
- **Historical filtered files**: `data/filtered/stage1/python_docs_filtered_v3.jsonl` (96 records), `data/filtered/stage1/thinkpython_filtered_v3.jsonl`, `data/filtered/stage1/atbs_filtered_v3.jsonl`, `data/filtered/stage1/atbs3e_ch1_code.jsonl` — all preserved as-is.
- **Historical manifest and report files**: `data/filtered/stage1/stage1_manifest.json` (with conflicting counts), `logs/data_preparation_report.*`, `logs/python_docs_report.json` (with 317 retained claim), `data/raw/python_docs/manifest.json` (with 317 retained claim) — all preserved as historical evidence.
- **Historical empty/blocked data**: `data/filtered/stage2/stackoverflow_candidates.jsonl` (empty), `data/final/corpus.jsonl` (empty), `data/raw/stackoverflow/` (empty), `data/raw/jupyter/jupyter_readme_code.jsonl` (empty), `data/raw/codesearchnet/` (empty), `data/raw/the_stack/` (empty) — all preserved as evidence of blocked tasks.
- **Existing research files**: `research/decisions.md`, `research/hypotheses.md`, `research/research_questions.md`, `research/experiment_log.md`, `research/task_registry.md` — all preserved as historical coordination infrastructure.
- **Git history**: No destructive git operations performed; all historical commits preserved.

## Compatibility Concerns

- **Config imports**: The new constants in `config.py` (CURRICULUM_STAGES, TOKENIZER_TARGET_VOCAB, etc.) are new additions; existing code that imports only the original 5 quality constants will continue to work without modification.
- **Decision registry consolidation**: `research/decision_registry.md` is a new file; `research/decisions.md` is preserved unchanged. No existing imports or references were broken.
- **Experiment/run registries**: New files (`research/experiment_registry.md`, `research/run_registry.md`) add capability without removing existing functionality.
- **Directory structure**: New directories (data/raw/peps/, data/filtered/stage4/, data/sft/*, research/tokenizer/, research/data_quality/, research/evaluation/) are empty and optional to import; they do not affect existing code paths.
- **Python version**: The repository uses Python 3.14 (per the docs archive version). All new constants use valid Python 3.14 syntax (e.g., `32_000` underscore literal, `4_000_000_000`).