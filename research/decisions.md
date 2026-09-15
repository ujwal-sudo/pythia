# Research Decision Log

This log records only decisions evidenced by the repository or the current coordination request. Unknown historical details remain `UNKNOWN`; repository documentation is not treated as proof that an undocumented option was formally considered.

## Format

```text
Decision ID:
Decision:
Date:
Status: proposed | accepted | superseded | rejected
Context:
Options considered:
Chosen approach:
Reason:
Expected effect:
Actual effect:
Related experiment:
Related task:
```

## Decisions

### DEC-20260915-001 — Use a staged quality-over-quantity data pipeline

- **Decision ID:** DEC-20260915-001
- **Decision:** Use a staged quality-over-quantity data pipeline rather than treating corpus size as the primary success criterion.
- **Date:** UNKNOWN (recorded 2026-09-15)
- **Status:** accepted
- **Context:** `README.md` documents Stage 1-3 sources, AST validation, quality filtering, PEP8 validation, Knowledge Graph validation, deduplication, and a final corpus. It states that quality and validation take precedence over simply reaching the intended approximately 5-6 GB target.
- **Options considered:** UNKNOWN
- **Chosen approach:** Curate source-specific candidates through validation and filtering stages before deduplication and final-corpus assembly.
- **Reason:** The repository explicitly prioritizes quality and validation over raw size.
- **Expected effect:** A smaller but more validated Python corpus with traceable source and filtering provenance.
- **Actual effect:** Raw sources, candidate files, manifests, and reports exist, but Stage 1 counts conflict and no verified final corpus exists.
- **Related experiment:** EXP-20260915-DATA-001; PYT-DATA-001
- **Related task:** PYTHIA-003; PYTHIA-004; PYTHIA-009; PYTHIA-010

### DEC-20260915-002 — Use the non-executing AST validator as the syntax gate

- **Decision ID:** DEC-20260915-002
- **Decision:** Use `scripts.validators.ast_validator.validate_python` as the authoritative non-executing Python syntax gate.
- **Date:** UNKNOWN (recorded 2026-09-15)
- **Status:** accepted
- **Context:** `README.md` and the validator docstring identify the standard-library `ast.parse` gate. The validator returns structured syntax and source-structure metadata without executing source.
- **Options considered:** UNKNOWN
- **Chosen approach:** Reject empty, indentation-error, syntax-error, and other invalid input through structured results; report AST metadata separately from semantic, style, and Knowledge Graph validity.
- **Reason:** The repository requires a safe syntax gate and explicitly separates syntax validity from executability, PEP8 compliance, semantic correctness, and Knowledge Graph validity.
- **Expected effect:** Invalid Python is rejected without executing untrusted source, while downstream components receive deterministic metadata.
- **Actual effect:** The validator is implemented and its 11 tests pass; the documentation processor calls it. It has not established semantic or Knowledge Graph correctness.
- **Related experiment:** EXP-20260915-DATA-001; PYT-DATA-001
- **Related task:** PYTHIA-002; PYTHIA-003

### DEC-20260915-003 — Keep token counts provisional until a custom tokenizer exists

- **Decision ID:** DEC-20260915-003
- **Decision:** Label existing token counts as provisional and do not treat them as final Pythia-tokenizer measurements.
- **Date:** 2026-09-15
- **Status:** accepted
- **Context:** `research/experiment_log.md`, `research/results/data/pyt-data-001.json`, and data reports state that the final Pythia tokenizer does not exist and document provisional counting methods.
- **Options considered:** Final-tokenizer-based filtering (planned); provisional whitespace/significant-token/character-estimate methods (used in existing records)
- **Chosen approach:** Preserve provisional counts with explicit method labels and record tokenizer-based filtering as future work.
- **Reason:** A custom tokenizer implementation and version are absent, so final token counts cannot be verified.
- **Expected effect:** Prevent provisional counts from being mistaken for final tokenizer results and keep future policy comparisons reproducible.
- **Actual effect:** Existing baseline results are explicitly limited; Policy B remains blocked until a tokenizer version exists.
- **Related experiment:** PYT-DATA-001
- **Related task:** PYTHIA-004; PYTHIA-011

### DEC-20260915-004 — Use persistent Lead coordination files

- **Decision ID:** DEC-20260915-004
- **Decision:** Maintain `project_status.md`, `task_registry.md`, `decisions.md`, `experiment_log.md`, and `reproducibility/run_registry.md` as the shared Lead coordination layer for independent OP and CD sessions.
- **Date:** 2026-09-15
- **Status:** accepted
- **Context:** The current coordination request requires independent OP and CD sessions to coordinate through the shared repository without modifying model code, tokenizer code, AST validator logic, or dataset contents.
- **Options considered:** UNKNOWN
- **Chosen approach:** Use the five requested files, explicit ownership rules, `UNKNOWN` for unavailable facts, experiment IDs, version traceability, and filesystem/report/test verification.
- **Reason:** Persistent repository records are required for cross-session coordination and reproducibility.
- **Expected effect:** OP, CD, and Lead can resume work without relying on chat summaries or guessing current state.
- **Actual effect:** UNKNOWN (coordination layer newly introduced; verification is pending future sessions).
- **Related experiment:** UNKNOWN
- **Related task:** PYTHIA-001; PYTHIA-018
