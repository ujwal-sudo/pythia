# Pythia-160M Research Infrastructure

Pythia-160M is a research and reproducibility project for a compact, Python-specialized language model under the C3AN framework: Custom, Compact, Composite, and Neurosymbolic.

This directory is the canonical home for research questions, hypotheses, experiment logs, decision records, results artifacts, paper drafts, and reproducibility metadata. It must preserve both positive and negative outcomes. Do not fabricate, cherry-pick, or backfill experimental measurements.

## Research Areas

- Tokenization: Python-specialized tokenizer behavior versus appropriate general-purpose baselines.
- Data quality: quality-over-quantity Python corpus construction and filtering.
- Model scale: competitiveness of an approximately 160M-parameter Python-specialized model.
- Neurosymbolic feedback: AST, Knowledge Graph, and tooling feedback effects on code generation quality.

## Traceability

Every reported result must be traceable to:

- code commit
- config commit or config hash
- dataset version
- model version
- experiment ID
- hardware and software environment
- exact command or run script

## Versioning Policies

Dataset versions use `data-vYYYYMMDD.N-source-or-stage`, for example `data-v20260914.1-python-docs-stage1`. Any filtering threshold, source change, parser change, or deduplication change requires a new dataset version.

Model versions use `pythia-160m-vYYYYMMDD.N-purpose`, for example `pythia-160m-v20260914.1-baseline`. Any architecture, tokenizer, training data, optimizer, schedule, or checkpoint selection change requires a new model version.

Experiment IDs use `EXP-YYYYMMDD-AREA-NNN`, where `AREA` is one of `TOK`, `DATA`, `MODEL`, `TRAIN`, `EVAL`, `ABL`, or `NS`.

## Required Records

- Log every planned and completed run in `experiment_log.md`.
- Register reproducible runs in `reproducibility/run_registry.md`.
- Record material project decisions in `decisions.md`.
- Store result artifacts under `results/` by area.
- Store paper-specific work under `papers/`.
- Preserve failed, null, and negative results with the same care as successful results.
