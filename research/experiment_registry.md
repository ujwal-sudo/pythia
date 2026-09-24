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



### EXP-20260920-SESS1-INTEGRATION — Cross-source integration reconciliation

- **Experiment ID:** EXP-20260920-SESS1-INTEGRATION
- **Date:** 2026-09-20
- **Owner:** Session 1
- **Task:** Final cross-source integration reconciliation (Missions 1-12)
- **Status:** complete (findings documented; blockers identified)
- **Dataset version:** PYTHIA-DATA-v0.1 (current base version)
- **Input:** All acquired sources: Python Docs (317 retained), Stack Overflow (100k scanned, 0 selected), GitHub (25 repos, 150 candidates), PyPI (5000 packages discovered, 0 per-package metadata)
- **Output:** This reconciliation report (SESSION1_FINAL_REPORT.md); updated data_contract.md; updated experiment_registry.md
- **Report:** SESSION1_FINAL_REPORT.md — all 15 sections with gap classifications
- **Experiment log entry:** PYT-DATA-001 (continued)
- **Notes:** Integration not ready for first unified corpus build. Primary blocker: PyPI per-package metadata. Secondary blockers: SO content_hash computation, provenance chain structuring, normalized dedup pipeline not implemented, rclone mount persistence verification limitation. All historical artifacts preserved; no data deleted. Negative results auditable.

### EXP-20260919-SESSION1-INFRASTRUCTURE — Session 1 infrastructure audit and contract update

- **Experiment ID:** EXP-20260919-SESSION1-INFRASTRUCTURE
- **Date:** 2026-09-19
- **Owner:** Session 1
- **Task:** Data contract audit, source-to-schema validation, quality-gate review, unit-of-data model, dataset versioning, reproducibility, dedup readiness, token count infrastructure, research registry update, storage verification
- **Status:** in progress (infrastructure phase)
- **Dataset version:** PYTHIA-DATA-v0.1 (current base version)
- **Input:** All acquired sources: Python Docs (317 retained), Stack Overflow (100k scanned, 0 selected), GitHub (25 repos, 150 candidates), PyPI (1000 verified archives, pilot report)
- **Report:** data_contract.md updated; source_schema_mapping.md updated; all 65 tests passing
- **Manifest:** data_contract.md, source_schema_mapping.md, experiment_registry.md updated
- **Experiment log entry:** PYT-DATA-001 (continued)
- **Notes:** Infrastructure audit complete. Data contract mapped canonical fields against actual source metadata. All gaps documented. Source-agnostic integration layer ready for final corpus construction once acquisition is sufficiently mature. Storage verification identifies rclone mount checksum/metadata issues that must be resolved before remote persistence can be guaranteed.

## Decision Registry References

All final-plan architecture, data, training, evaluation, and versioning decisions are recorded in `research/decision_registry.md`.