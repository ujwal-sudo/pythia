# Pythia Project Status

This file is the single source of truth for the current Pythia coordination state. Facts below are limited to repository, report, manifest, log, test, and experiment evidence. Unknown values are written as `UNKNOWN`.

## Project objective

Build **Pythia-160M**, a compact approximately 160M-parameter Python-specialized language model trained from scratch under the C3AN framework: Custom, Compact, Composite, and Neurosymbolic. The documented target pipeline is raw sources -> AST validation -> quality filtering -> PEP8 validation -> Knowledge Graph validation -> deduplication -> final corpus, with AST/Knowledge Graph feedback around generation.

Source: `README.md`.

## Current date

2026-09-15

## Current milestone

Stage 1 data foundation and artifact reconciliation. The repository has a project foundation, an AST validator, a Python documentation processor, raw source files, preliminary filtered artifacts, reports, manifests, and passing tests. No verified final corpus or downstream model stack exists.

## Overall status

**IN PROGRESS — foundation and Stage 1 components exist; corpus and downstream milestones are not complete.**

The main verification issue is that existing Stage 1 reports, manifests, and filtered files disagree about record counts and output paths. No task should be declared complete until the relevant filesystem artifacts and reports are reconciled.

## Architecture status

**PARTIAL.** The intended architecture and data pipeline are documented in `README.md`. The non-executing AST validator is implemented and tested. The Knowledge Graph validator, feedback/regeneration loop, model architecture, tokenizer, training pipeline, and evaluation harness are not present as verified implementations.

## Dataset status by source

- **Official Python documentation:** Raw archive exists at `data/raw/python_docs/python-3.14-docs-html.zip` with SHA-256 `44e94d921af3e1c4f46e6dd3a39d606e6847e37e9c3be22700a354de38a9a92f`. The report and raw manifest record 10,030 candidates, 4,512 syntax-valid examples, and 317 retained examples. The recorded output path `data/filtered/stage1/python_docs.jsonl` is absent; `data/filtered/stage1/python_docs_filtered_v3.jsonl` exists with 96 records. **Blocked pending output reconciliation.**
- **Think Python:** Raw file has 293 records. The v3 filtered file has 293 records. The recorded strict baseline retained 0/293 under provisional filtering, while `stage1_manifest.json` reports conflicting retained counts. **In progress / blocked pending reconciliation.**
- **Automate the Boring Stuff:** Raw files contain 123 main records and 39 Chapter 1 records; the v3 filtered file has 162 records. The recorded strict baseline retained 5/123 for the main set and 1/39 for Chapter 1, while the manifest reports conflicting counts. **In progress / blocked pending reconciliation.**
- **Stack Overflow:** `scripts/prepare_so.py` exists, but `data/filtered/stage2/stackoverflow_candidates.jsonl` is empty and no raw Stack Overflow snapshot, manifest, or report is present. **Blocked.**
- **Jupyter:** `data/raw/jupyter/jupyter_readme_code.jsonl` exists but is empty. **Blocked.**
- **CodeSearchNet:** No raw directory, source snapshot, processor, manifest, or report is present. **Blocked.**
- **The Stack:** No raw directory, source snapshot, processor, manifest, or report is present. **Blocked.**

## Tokenizer status

No custom tokenizer implementation or tokenizer artifact is present. `requirements.txt` includes `tiktoken`, but this is only a dependency declaration. Existing data reports use provisional methods (`text.split()`, `char_count // 4`, or significant-token counting). Formal tokenizer version: `UNKNOWN`.

## Knowledge Graph status

No Knowledge Graph implementation or graph artifact is present. Existing candidate records mark `kg_validation_status` as `pending`. Status: **NOT STARTED**.

## Neurosymbolic layer status

The intended Generate -> AST Validation -> Knowledge Graph Validation -> Feedback/Regeneration flow is documented. AST validation exists; Knowledge Graph validation, inference integration, and feedback/regeneration are not implemented or verified. Status: **PARTIAL / NOT STARTED beyond AST validation**.

## Evaluation status

No evaluation code, benchmark results, model checkpoints, or populated `research/results/evaluation/` artifacts are present. Research questions and hypotheses exist, but they are not measurements. Status: **NOT STARTED**.

## OP current task

**PYTHIA-004 Textbooks — reconcile the Stage 1 textbook artifacts and prepare the planned PYT-DATA-002 filtering-policy comparison without overwriting raw data or historical outputs.**

OP owns dataset acquisition and preparation. The next OP work must preserve the existing raw and v3 files, resolve the conflicting counts, assign a traceable dataset version, and register the policy comparison as a new experiment.

## CD current task

**PYTHIA-003 Python documentation processor — reconcile the missing Python documentation output path and inconsistent manifests/reports, then verify the processor output against the filesystem.**

CD owns engineering, validators, pipeline, and research infrastructure. The AST validator logic must remain unchanged for this coordination work.

## Blockers

1. The Python documentation report/manifest claim 317 retained records at `data/filtered/stage1/python_docs.jsonl`, but that file is absent; the existing v3 file has 96 records.
2. Stage 1 manifests/reports conflict: source totals and retained counts differ across `stage1_manifest.json`, `logs/data_preparation_report.json`, the textbook experiment record, and the v3 JSONL files.
3. The v3 textbook files contain source records, including syntax-invalid and duplicate records; they are not verified strict filtered corpora.
4. Stack Overflow output is empty; Jupyter raw data is empty; CodeSearchNet and The Stack source trees are absent.
5. `data/final/corpus.jsonl` is empty.
6. No custom tokenizer, Knowledge Graph, model architecture, pretraining, evaluation, or release artifacts exist.
7. Experiment-specific hardware and software snapshots are unavailable.

## Dependencies

- OP dataset work depends on immutable raw acquisition, provenance, and the verified AST/pipeline interfaces.
- CD pipeline work depends on versioned candidate artifacts and reproducible reports.
- Deduplication and final-corpus work depend on reconciled Stage 1-3 outputs.
- Tokenizer, model, neurosymbolic, evaluation, and release work depend on a verified corpus and explicit version records.
- The Lead uses this file, `task_registry.md`, `decisions.md`, `experiment_log.md`, and `reproducibility/run_registry.md` to coordinate future work.

## Completed work

- Project layout, configuration, research home, raw/filtered/log directories, and documentation foundation exist.
- Non-executing AST validator and its tests exist; the current test run passed 18 tests.
- Python documentation scraper/processor and its tests exist.
- Official Python documentation raw archive, textbook raw files, preliminary v3 filtered files, manifests, reports, and the Stack Overflow preparation script exist.
- Research questions, hypotheses, experiment records, decision-log infrastructure, and reproducibility templates exist.
- The recorded textbook baseline and Python documentation run are preserved as historical records; neither should be silently overwritten.

## Next recommended actions

1. **Exact next action:** Reconcile the Python documentation output mismatch first: verify whether `data/filtered/stage1/python_docs.jsonl` should be generated from the 3.14 archive, preserve `python_docs_filtered_v3.jsonl`, and record the filesystem/report result before starting new data work.
2. Reconcile Stage 1 textbook counts and produce versioned, policy-specific outputs for `PYT-DATA-002`.
3. Prepare Stack Overflow, Jupyter, CodeSearchNet, and The Stack only after raw-source provenance and immutable storage are established.
4. Add explicit dataset/model/tokenizer versions, hardware/software snapshots, and experiment IDs to every meaningful run.
5. Do not mark the final corpus, tokenizer, Knowledge Graph, model, training, evaluation, or release tasks complete without filesystem/report/test verification.

## Last verified filesystem state

Verified on 2026-09-15 at repository HEAD `b9d898d` (`b9d898de9d46e8c2b45ae14dd6ea1ba6b4815ea0`). `python3 -m unittest discover -s tests -v` passed 18 tests. The filesystem contains 8 raw files, 5 filtered files, 4 log files, 26 research files, and the test/script files listed by the repository tree. `data/final/corpus.jsonl` and `data/filtered/stage2/stackoverflow_candidates.jsonl` are empty. The Python documentation output path recorded by the manifest is absent.

## Last updated

2026-09-15

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
