# Task Registry

## Experiment PYT-DATA-001: Stage 1 Strict Preliminary Filtering Baseline

**Status:** completed
**Date:** 2026-09-15
**Researcher:** opencode agent

### Objective

Establish a reproducible baseline for Stage 1 data-quality filtering using provisional methods before later experiments with alternative policies.

### Configuration

- Min provisional token length: 50
- Max provisional token length: 2048
- Min comment ratio: 0.1
- PEP8 max violations: 5 (pycodestyle 2.14.0)
- AST validator: scripts.validators.ast_validator.validate_python

### Baseline Counts

| Dataset | Examined | Syntax-Valid | Token < 50 | Below Ratio 0.1 | PEP8 Rejected | Retained |
|---------|----------|-------------|------------|-----------------|---------------|----------|
| Think Python | 293 | 287 | 293 | 276 | 0 | 0 |
| ATBS | 123 | 56 | 106 | 107 | 13 | 5 |

### Known Limitations

- Provisional whitespace-based token counting (split on whitespace)
- Code-only comment/docstring ratio applied; educational code examples may have external prose
- No final Pythia tokenizer available; token counts are explicitly labeled provisional

### Next Planned Experiment

- **PYT-DATA-002:** Policy comparison (Policy A: strict code-only filter, Policy B: final tokenizer-based length filtering, Policy C: context-aware educational examples)

### Artifacts Preserved

- `data/raw/` directory: all original raw data unchanged
- `data/filtered/stage1/`: Stage 1 filtered outputs preserved as baseline
- `research/results/data/pyt-data-001.json`: machine-readable experiment record
- `research/experiment_log.md`: human-readable experiment log entry
- `research/project_status.md`: project status updated
