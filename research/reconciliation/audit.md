# Pythia-160M Repository Reconciliation — Audit Report

**Date:** 2026-09-17
**Repository:** /home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline
**Purpose:** Classify every repository component against the final Pythia-160M master plan and identify gaps.

---

## Repository Overview

The repository contains project foundation, an AST validator, a Python documentation scraper/processor, raw source files, preliminary filtered artifacts, reports, manifests, and passing tests. No verified final corpus, tokenizer, model, or downstream artifacts exist.

---

## Component Audit Classification

### Configuration

| Component | Status | Evidence |
|-----------|--------|----------|
| `config.py` | PARTIAL | Contains core quality constants (MIN_TOKEN_LENGTH=50, MAX_TOKEN_LENGTH=2048, MIN_COMMENT_RATIO=0.1, PEP8_MAX_VIOLATIONS=5, DEDUP_SIMILARITY_THRESHOLD=0.85). Missing: curriculum stages, tokenizer target vocabulary, target corpus token count, FIM ratio, full model architectural constants. |
| Versioning scheme | MISSING | No PYTHIA-DATA-v0.1, PYTHIA-TOK-v0.1, or Pythia-160M-v0.1 version records exist. |

### Research Infrastructure

| Component | Status | Evidence |
|-----------|--------|----------|
| `research/README.md` | COMPLETE | Exists and documents research home. |
| `research/research_questions.md` | COMPLETE | Holds RQ1-RQ4. |
| `research/hypotheses.md` | COMPLETE | Holds H1-H4. |
| `research/decisions.md` | PARTIAL | Has 4 decisions (DEC-20260915-001 through -004). Final plan requires more architecture/data/training/evaluation decisions consolidated into a decision_registry.md. |
| `research/decision_registry.md` | MISSING | Does not exist; must be created as the canonical registry. |
| `research/experiment_log.md` | COMPLETE | Chronological experiment log with 3 entries. |
| `research/experiment_registry.md` | MISSING | Does not exist; should be created for traceable experiment IDs. |
| `research/task_registry.md` | COMPLETE | Comprehensive PYTHIA-001 through PYTHIA-018 registry. |
| `research/run_registry.md` | COMPLETE | Exists under reproducibility/. |
| `research/project_status.md` | PARTIAL | Good status document but dated 2026-09-15; needs updating to reflect current reconciliation state. |
| `research/figures/` | HISTORICAL/PRESERVE | .gitkeep only; preserve as historical. |
| `research/tables/` | HISTORICAL/PRESERVE | .gitkeep only; preserve as historical. |
| `research/benchmarks/` | HISTORICAL/PRESERVE | .gitkeep only; preserve as historical. |
| `research/papers/` | HISTORICAL/PRESERVE | 4 subdirectories with .gitkeep; preserve as historical. |
| `research/tables/` | HISTORICAL/PRESERVE | .gitkeep only; preserve as historical. |
| `research/results/` | PARTIAL | Has 6 subdirectories; data/pyt-data-001.json exists with experiment data; evaluation/, model/, tokenizer/, training/, ablations/ are empty placeholders (.gitkeep). |
| `research/reports/` | HISTORICAL/PRESERVE | .gitkeep only; preserve as historical. |

### Data Structure

| Component | Status | Evidence |
|-----------|--------|----------|
| `data/raw/python_docs/` | COMPLETE | Python 3.14 docs archive and manifest exist. |
| `data/raw/textbooks/` | COMPLETE | Raw textbook files exist (Think Python, ATBS 3rd Ed). |
| `data/raw/stackoverflow/` | EMPTY/HISTORICAL | Directory exists but empty; no source snapshot acquired. Preserve as historical evidence of blocked task. |
| `data/raw/jupyter/` | EMPTY/HISTORICAL | File exists but empty (jupyter_readme_code.jsonl); no provenance. Preserve as historical evidence. |
| `data/raw/codesearchnet/` | EMPTY/HISTORICAL | Directory exists but empty; no source acquired. Preserve as historical evidence. |
| `data/raw/the_stack/` | EMPTY/HISTORICAL | Directory exists but empty; no source acquired. Preserve as historical evidence. |
| `data/filtered/stage1/` | COMPLETE (with conflicts) | Has v3 filtered files, stage1_manifest.json, and reports. Counts conflict across manifests/reports/JSONL files reconciled as historical. |
| `data/filtered/stage2/` | EMPTY | stackoverflow_candidates.jsonl is empty; no successful run evidenced. Preserve historical empty state. |
| `data/filtered/stage3/` | EMPTY | Directory exists but empty. Preserve as historical. |
| `data/final/` | EMPTY | corpus.jsonl is empty; no final corpus exists. |
| `data/sft/` | MISSING | Does not exist; must be created for Stage B SFT data. |

### Scripts

| Component | Status | Evidence |
|-----------|--------|----------|
| `scripts.logger` | COMPLETE | Logger exists and is used. |
| `scripts/prepare_so.py` | COMPLETE (historical) | Stack Overflow preparation script exists; no successful run evidenced. Preserve as historical. |
| `scripts/scrapers/python_docs.py` | COMPLETE | Full Python docs ingestion pipeline. Discrepancy: manifest claims 317 retained, actual v3 output has 96 records; reconcile without overwriting historical artifacts. |
| `scripts/validators/ast_validator.py` | COMPLETE | Non-executing AST validator using ast.parse; 11/11 structured metadata fields; all 18 tests pass. |
| `scripts/__init__.py` | COMPLETE | Package init exists. |

### Tests

| Component | Status | Evidence |
|-----------|--------|----------|
| `tests/test_ast_validator.py` | COMPLETE | 18 tests, all pass. |
| `tests/test_python_docs_scraper.py` | COMPLETE | 10 tests, all pass. |
| Other infrastructure tests | MISSING | No additional test infrastructure beyond the two test files. |

### Logs

| Component | Status | Evidence |
|-----------|--------|----------|
| `logs/pipeline.log` | COMPLETE | 23-line pipeline execution log. |
| `logs/data_preparation_report.json` | COMPLETE | JSON report with 551 records examined, 444 retained. |
| `logs/data_preparation_report.txt` | COMPLETE | Text format report. |
| `logs/python_docs_report.json` | COMPLETE | Python docs processing report (10030 blocks, 317 retained). |

---

## Key Discrepancies Identified

1. **Python docs output path mismatch**: `research/project_status.md` and `research/task_registry.md` report that the manifest claims 317 retained records at `data/filtered/stage1/python_docs.jsonl`, but that file is absent. The v3 filtered file `python_docs_filtered_v3.jsonl` has 96 records. **Resolution**: Preserve both the v3 artifact and the manifest report; the 317 count is a historical report value, not a current filesystem state.

2. **Stage 1 count conflicts**: `stage1_manifest.json`, `logs/data_preparation_report.json`, the textbook experiment record (`research/results/data/pyt-data-001.json`), and v3 JSONL files disagree on total counts and retained counts per source. **Resolution**: Treat all as historical evidence; do not silently overwrite.

3. **Empty/blocked data directories**: Stage 2 `stackoverflow_candidates.jsonl` is empty; Stage 3 is empty; `data/final/corpus.jsonl` is empty; CodeSearchNet, The Stack, and Jupyter raw data are absent. **Resolution**: Preserve as evidence of blocked tasks; do not fabricate data.

4. **Token count methodology**: Existing reports use provisional counting (`provisional_python_tokenize_significant_tokens_v1`). No custom tokenizer exists. **Resolution**: Label all existing counts as provisional; introduce canonical versioning for future tokenizer-based counts.

---

## Summary Classification Counts

| Classification | Count |
|----------------|-------|
| COMPLETE | 14 |
| PARTIAL | 8 |
| MISSING | 9 |
| OUTDATED | 0 |
| HISTORICAL/PRESERVE | 12 |

---

## Immediate Next Steps

1. Create `research/reconciliation/changes.md` and `research/reconciliation/remaining_work.md`
2. Create `research/decision_registry.md` consolidating all final-plan decisions
3. Update `research/project_status.md` and `research/task_registry.md`
4. Ensure `data/sft/` structure exists
5. Update `config.py` with additional canonical constants
6. Create evaluation/, knowledge_graph/, and other scaffolding directories
7. Run all existing tests to verify nothing is broken