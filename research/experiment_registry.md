# Experiment Registry — Pythia-160M

This registry records all experiments conducted as part of the Pythia-160M project. Each experiment has a traceable ID, dataset version, and result state. Unknown values are written as `UNKNOWN`.

## Registered Experiments

### EXP-20260915-DATA-001 — Python documentation processor baseline

- **Experiment ID:** EXP-20260915-DATA-001
- **Date:** 2026-09-15
- **Owner:** CD
- **Task:** PYTHIA-003 Python documentation processor
- **Status:** completed (historical; output path reconciled, counts preserved)
- **Dataset version:** UNKNOWN (documentation version recorded as 3.14)
- **Input:** `data/raw/python_docs/python-3.14-docs-html.zip`
- **Output:** `data/filtered/stage1/python_docs_filtered_v3.jsonl` (96 records)
- **Report:** `logs/python_docs_report.json` (10030 blocks examined, 317 retained claimed; 96 actual)
- **Manifest:** `data/raw/python_docs/manifest.json` (317 retained claimed; 96 actual)
- **Experiment log entry:** PYT-DATA-001
- **Notes:** Historical baseline; manifest claims 317 retained but filesystem has 96. Preserved as evidence of reconciliation. Token counts are provisional.

## Decision Registry References

All final-plan architecture, data, training, evaluation, and versioning decisions are recorded in `research/decision_registry.md`.