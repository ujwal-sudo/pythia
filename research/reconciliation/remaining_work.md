# Pythia-160M Repository Reconciliation — Remaining Work

This document lists the next real tasks in order, following the complete repository reconciliation against the final-final Pythia-160M master plan.

## Immediate Next Steps (Priority: high)

1. **Acquire traceable Stack Overflow source snapshot**
   - Task: PYTHIA-005
   - Owner: OP
   - Dependency: Blocked by lack of source acquisition
   - Action: Acquire and checksum a traceable Stack Overflow Python subset; run `scripts/prepare_so.py` into versioned artifacts at `data/filtered/stage2/stackoverflow_candidates.jsonl`

2. **Resolve Jupyter provenance**
   - Task: PYTHIA-006
   - Owner: OP
   - Dependency: Blocked by empty raw data
   - Action: Acquire a real Jupyter notebook/code snapshot with provenance before processing

3. **Begin preliminary deduplication on Stage 1 candidates**
   - Task: PYTHIA-009
   - Owner: CD
   - Dependency: Upstream: Stage 1 artifacts reconciled (complete)
   - Action: Implement exact and near-deduplication using the configured 0.85 similarity threshold on existing Stage 1 candidate files (thinkpython, atbs, atbs_ch1, python_docs). Record duplicate counts and produce a versioned deduplicated corpus.

4. **Assemble the final corpus**
   - Task: PYTHIA-010
   - Owner: OP
   - Dependency: Upstream: PYTHIA-003 through PYTHIA-009 verified
   - Action: Assemble curriculum specification and versioned final corpus at `data/final/corpus.jsonl` with manifest and provenance. Target: ~4B validated Python tokens (quality takes precedence over hitting the numeric target).

5. **Define and register tokenizer experiment**
   - Task: PYTHIA-011
   - Owner: CD
   - Dependency: Upstream: Corpus policy and versioning stable (PYTHIA-010)
   - Action: Introduce canonical tokenizer version `PYTHIA-TOK-v0.1`. Define tokenizer experiment after corpus policy and versioning are stable. No training yet — just versioning and configuration.

## Infrastructure Tasks (Priority: medium)

6. **Create Knowledge Graph scaffolding**
   - Task: PYTHIA-012 (structural phase)
   - Owner: CD
   - Dependency: Stable data interfaces (post-PYTHIA-010)
   - Action: Create `research/knowledge_graph/` with entity documentation (modules, functions, classes, signatures, types, relationships, patterns, error/fix relationships). Do NOT build/download the full KG in this task.

7. **Prepare SFT data structures with metadata**
   - Task: PYTHIA-011 SFT phase (infrastructure)
   - Owner: CD/OP
   - Dependency: PYTHIA-010 (final corpus)
   - Action: Ensure `data/sft/repair_pairs/`, `data/sft/docstring_to_code/`, `data/sft/instruction/`, `data/sft/reasoning/` directories exist with metadata/documentation explaining each dataset's role. Do NOT collect SFT data yet.

8. **Populate evaluation infrastructure with common result schema**
   - Task: PYTHIA-016 (infrastructure phase)
   - Owner: CD
   - Dependency: Model checkpoint availability (future)
   - Action: Establish clean module boundaries and common result schema under `evaluation/`. Implement `run_eval(config: dict | None = None) -> dict` interface. Results must support: experiment ID, timestamp, model checkpoint, tokenizer version, dataset version, git commit, seed, benchmark version, metrics, runtime metadata. Create subdirectories: humaneval/, mbpp/, livecodebench/, perplexity/, ast_validity/, execution/, docstring_to_code/, pythia_specific/, tokenizer/, ablations/, contamination/, reporting/.

9. **Introduce canonical dataset/model/tokenizer versions**
   - Task: PYTHIA versioning
   - Owner: CD/OP/Lead
   - Dependency: Ongoing
   - Action: Introduce canonical version records for all future work: PYTHIA-DATA-v0.1, PYTHIA-TOK-v0.1, Pythia-160M-v0.1. Do not retroactively rename historical runs. Assign dataset versions traceably from this point forward.

10. **Update Lead coordination files with reconciliation status**
    - Task: General coordination
    - Owner: Lead
    - Dependency: This reconciliation task
    - Action: Ensure `research/project_status.md`, `research/task_registry.md`, `research/decision_registry.md`, `research/experiment_registry.md`, and `research/run_registry.md` reflect the actual final state. Record last verification date (2026-09-17).

## Notes on Task Order

- Tasks 1-3 are independent but all depend on immutable raw data preservation. Stack Overflow and Jupyter acquisition can proceed in parallel after raw-source establishment.
- Task 4 (final corpus) depends on deduplication (Task 3) completing first.
- Tasks 5-9 are largely independent infrastructure setup tasks that can proceed in parallel once their respective dependencies are met.
- Task 10 is ongoing and should be done at the conclusion of every meaningful experiment session.

## Completed Infrastructure (No Further Action Required)

- Repository reconciliation against the final plan (Step 1-15 of the reconciliation process)
- All research structure files (decision_registry.md, experiment_registry.md, run_registry.md)
- All scaffolding directories (data/sft/, data/raw/peps/, data/filtered/stage4/, research/tokenizer/, research/data_quality/, research/evaluation/)
- Config constants update (config.py)
- Test suites (all 28 existing tests pass)
- Historical artifact preservation (no overwrites or deletions)