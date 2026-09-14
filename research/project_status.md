# Project Status

## Stage 1 Baseline Experiment

**Experiment ID:** PYT-DATA-001
**Status:** completed
**Date:** 2026-09-15

### Baseline Results

- Think Python 2nd Edition: 0/293 retained under strict preliminary Stage 1 filtering
- Automate the Boring Stuff 3rd Edition: 5/123 retained under strict preliminary Stage 1 filtering

### Current Limitations

- Provisional whitespace-based token counting (final Pythia tokenizer does not exist yet)
- Code-only documentation rule (comment/docstring ratio < 0.1 applied to code only)
- Educational examples often lack internal comments but have external textbook prose

### Next Planned Experiment

- Experiment PYT-DATA-002: Policy comparison - Policy A (strict code-only filter), Policy B (final tokenizer-based length filtering), Policy C (context-aware educational examples with preserved textbook explanation as metadata)

### Coordination State

- Stage 1 baseline experiment completed
- Experiment ID PYT-DATA-001 recorded
- Current limitation: provisional token counting documented
- Current limitation: educational context vs code-only documentation rule documented
- Next planned data-quality experiment: PYT-DATA-002

### Do NOT Mark Complete

- Do not mark final corpus complete
- Do not acquire new datasets in this task
- Do not modify Codex's AST validator implementation
