# Experiment Naming Audit — Pythia-160M

This document audits existing experiment IDs and defines the canonical naming convention for future source-specific and workstream experiments. Historical experiments are NOT renamed.

## Audited Experiment IDs (Existing in Repository)

| Experiment ID | Source/Workstream | Notes |
|---|---|---|
| `PYT-DATA-001` | Original reconciliation (baseline) | Historical; preserved, not renamed |
| `PYT-DATA-SO-001` | Stack Overflow (Session 2) | HF dataset profiling; 0 SO records in first 100k |
| `PYT-DATA-GH-001` | GitHub (Session 4) | 5 pilot repos; 598 files, 5746 Python LOC |
| `PYT-DATA-SO-HF-PROFILE-001` | Stack Overflow HF profiling (Session 2) | Source profile only; no SO community records |
| `pyt-data-001.json` | Data result file | In `research/results/data/`, lowercase, preserved |
| `pyt-data-gh-001.json` | GitHub result file | In `research/results/data/`, lowercase, preserved |
| `stackoverflow_acquisition_v1.json` | SO acquisition v1 | In `research/results/data/`, preserved |
| `stackoverflow_hf_source_profile_v1.json` | SO HF profile v1 | In `research/results/data/`, preserved |

## Canonical Naming Convention

All future experiment IDs MUST follow this pattern:

```
PYT-DATA-<source_code>-<sequence_number>
```

or

```
PYT-<workstream_code>-<sequence_number>
```

### Source Codes (prefix after `PYT-DATA-`)

| Code | Source/Workstream | Example |
|---|---|---|
| `SO` | Stack Overflow | `PYT-DATA-SO-001` |
| `PYPI` | PyPI (Session 3) | `PYT-DATA-PYPI-001` |
| `GH` | GitHub (Session 4) | `PYT-DATA-GH-001` |
| `TK` | Tokenizer training | `PYT-DATA-TK-001` |
| `TR` | Training run | `PYT-DATA-TR-001` |
| `EV` | Evaluation | `PYT-DATA-EV-001` |
| `AB` | Ablation experiment | `PYT-DATA-AB-001` |

### Workstream Codes (prefix after `PYT-`)

| Code | Workstream | Example |
|---|---|---|
| `TOK` | Tokenizer workstream | `PYT-TOK-001` |
| `TRA` | Training workstream | `PYT-TRA-001` |
| `EVE` | Evaluation workstream | `PYT-EVE-001` |
| `ABL` | Ablation workstream | `PYT-ABL-001` |
| `INT` | Integration workstream | `PYT-INT-001` |

### Sequence Numbers

- Sequence numbers are assigned incrementally within each prefix.
- `001` = first experiment in that prefix.
- Historical experiments keep their original numbers; new experiments start at `001` for their prefix.
- Sequence numbers are never retroactively reassigned.

## Naming Rules

1. **Prefix**: Always `PYT-DATA-` for data experiments or `PYT-` for workstream experiments.
2. **Separator**: Single hyphen between prefix and sequence number.
3. **Sequence**: 3-digit zero-padded number (`001`, `002`, … `999`, then `1000+`).
4. **No spaces**: Experiment IDs must not contain spaces.
5. **No special characters**: Only alphanumeric characters and hyphens allowed.
6. **Historical preservation**: Existing experiment IDs are never renamed. New experiments get the next available sequence number in their prefix.
7. **Consistency**: The same source/ workstream always maps to the same code (e.g., Stack Overflow is always `SO`).

## Mapped Experiment IDs

| Pattern | Meaning | Status |
|---|---|---|
| `PYT-DATA-SO-001` | Stack Overflow data experiment | Audited, preserved |
| `PYT-DATA-PYPI-001` | PyPI data experiment | To be assigned (Session 3) |
| `PYT-DATA-GH-001` | GitHub data experiment | Audited, preserved |
| `PYT-DATA-TK-001` | Tokenizer data experiment | To be assigned (after tokenizer) |
| `PYT-DATA-TR-001` | Training run experiment | To be assigned (after model) |
| `PYT-DATA-EV-001` | Evaluation experiment | To be assigned (after model) |
| `PYT-DATA-AB-001` | Ablation experiment | To be assigned |
| `PYT-TOK-001` | Tokenizer workstream experiment | To be assigned |
| `PYT-TRA-001` | Training workstream experiment | To be assigned |
| `PYT-EVE-001` | Evaluation workstream experiment | To be assigned |
| `PYT-ABL-001` | Ablation workstream experiment | To be assigned |

## Naming Audit — What Was Already Correct

- All existing experiment IDs follow a consistent pattern (mix of `PYT-DATA-<source>-<number>` and descriptive filenames).
- No experiment IDs were fabricated or guessed; all are traceable to actual runs.
- The lowercase `.json` files (`pyt-data-001.json`, `pyt-data-gh-001.json`) are result files, not experiment IDs themselves, but follow the same naming convention.

## Naming Audit — Gaps

- No `PYT-DATA-PYPI-001` experiment exists yet (Session 3 pending).
- No `PYT-DATA-TK-001`, `PYT-DATA-TR-001`, `PYT-DATA-EV-001`, or `PYT-DATA-AB-001` experiments exist yet.
- The `PYT-TOK-*`, `PYT-TRA-*`, `PYT-EVE-*`, `PYT-ABL-*` workstream prefixes are not yet in use but are defined for future use.

## Naming Rule: Do Not Rename Historical Experiments

- `PYT-DATA-001` remains as-is (historical reconciliation baseline).
- `PYT-DATA-SO-001` remains as-is (historical SO profiling).
- `PYT-DATA-GH-001` remains as-is (historical GitHub pilot).
- New experiments starting with these prefixes will use `002`, `003`, etc., not `001`.

## Quick Reference: Assigning a New Experiment ID

To assign a new experiment ID:

1. Determine the appropriate prefix (`PYT-DATA-<source_code>` or `PYT-<workstream_code>`).
2. Check the highest existing sequence number for that prefix.
3. Assign `highest + 1` as the new sequence number.
4. Example: If `PYT-DATA-SO-001` and `PYT-DATA-SO-003` exist, the next SO experiment is `PYT-DATA-SO-004`.
5. Example: If no `PYT-DATA-PYPI-` experiments exist yet, the first is `PYT-DATA-PYPI-001`.