# Run Registry — Pythia-160M

This registry tracks all experiments and data processing runs across the project. Each entry records an experiment ID, timestamp, dataset version, and result state. Entries are authoritative for their respective runs.

## Registered Runs

### EXP-20260915-DATA-001 — Python documentation processor baseline

- **Run ID:** EXP-20260915-DATA-001
- **Timestamp:** 2026-09-15
- **Owner:** CD
- **Task:** PYTHIA-003 Python documentation processor
- **Status:** completed (historical; output path reconciled)
- **Dataset version:** documentation v3.14
- **Experiment ID:** PYT-DATA-001
- **Input:** `data/raw/python_docs/python-3.14-docs-html.zip`
- **Output:** `data/filtered/stage1/python_docs_filtered_v3.jsonl` (96 records)
- **Report:** `logs/python_docs_report.json`
- **Manifest:** `data/raw/python_docs/manifest.json`
- **Notes:** Historical baseline. Manifest claims 317 retained; filesystem has 96. Preserved as reconciliation evidence.

## Cross-References

- **decision_registry.md:** All final-plan architecture, data, training, and evaluation decisions.
- **project_status.md:** Current project phase and blockers.
- **task_registry.md:** Task-level ownership and status.
- **experiment_log.md:** Chronological experiment chronology.