# Experiment Log

Chronological human-readable experiment log. Planned, completed, failed, and blocked experiments are recorded without inventing results. Historical detail from the previous log is preserved below the canonical entries.

## Canonical format

```text
Experiment ID:
Date:
Owner:
Purpose:
Dataset version:
Tokenizer version:
Model version:
Configuration:
Result:
Interpretation:
Artifacts:
Status:
```

## Entries

### PYT-DATA-001 — Stage 1 strict preliminary filtering baseline

- **Experiment ID:** PYT-DATA-001
- **Date:** 2026-09-15
- **Owner:** OP
- **Purpose:** Establish a reproducible baseline for strict preliminary Stage 1 filtering of Think Python and ATBS textbook code.
- **Dataset version:** UNKNOWN (Think Python 2nd Edition and ATBS 3rd Edition are recorded; no formal `data-v...` version exists)
- **Tokenizer version:** UNKNOWN (provisional whitespace-based `text.split()` count)
- **Model version:** N/A
- **Configuration:** Minimum provisional tokens 50; maximum 2048; minimum comment ratio 0.1; maximum PEP8 violations 5; AST validator `scripts.validators.ast_validator.validate_python`; pycodestyle 2.14.0
- **Result:** Think Python examined 293, syntax-valid 287, provisional-token `<50` 293, below comment ratio 276, PEP8 rejected 0, exact duplicate hashes 56, retained 0. ATBS examined 123, syntax-valid 56, provisional-token `<50` 106, below comment ratio 107, PEP8 rejected 13, retained 5.
- **Interpretation:** Strict code-only filtering retained 0/293 Think Python and 5/123 ATBS records. Results are strongly limited by provisional token counting and by applying a code-only documentation ratio to educational examples that may rely on external textbook prose.
- **Artifacts:** `research/results/data/pyt-data-001.json`; `data/filtered/stage1/thinkpython_filtered_v3.jsonl`; `data/filtered/stage1/atbs_filtered_v3.jsonl`; `data/filtered/stage1/stage1_manifest.json`; legacy output paths recorded in the result JSON are absent
- **Status:** completed (historical record; filesystem/output reconciliation pending)

### EXP-20260915-DATA-001 — Python 3.14 documentation ingestion

- **Experiment ID:** EXP-20260915-DATA-001
- **Date:** 2026-09-15
- **Owner:** UNKNOWN
- **Purpose:** Ingest and validate Python 3.14 documentation code examples for Stage 1 candidates.
- **Dataset version:** UNKNOWN (documentation version recorded as 3.14; no formal `data-v...` version exists)
- **Tokenizer version:** `provisional_python_tokenize_significant_tokens_v1`
- **Model version:** N/A
- **Configuration:** Minimum provisional tokens 50; maximum 2048; minimum comment ratio 0.1; maximum PEP8 violations 5; AST validator `scripts.validators.ast_validator.validate_python`
- **Result:** 10,030 blocks examined; 10,030 Python candidates; 4,512 syntax-valid; 416 syntax-invalid; 3,588 too short; 0 too long; 569 low-documentation; 38 PEP8 rejected; 5,102 exact duplicates; 317 retained.
- **Interpretation:** The recorded run reports successful processing and preserved archive provenance. The recorded output path is missing from the current filesystem, so the 317-record output is not currently filesystem-verified.
- **Artifacts:** `data/raw/python_docs/python-3.14-docs-html.zip` (SHA-256 `44e94d921af3e1c4f46e6dd3a39d606e6847e37e9c3be22700a354de38a9a92f`); `data/raw/python_docs/manifest.json`; `logs/python_docs_report.json`; recorded output `data/filtered/stage1/python_docs.jsonl` (absent); extant `data/filtered/stage1/python_docs_filtered_v3.jsonl` (96 records)
- **Status:** completed (historical record; output verification blocked)

### PYT-DATA-002 — Filtering policy comparison

- **Experiment ID:** PYT-DATA-002
- **Date:** UNKNOWN
- **Owner:** OP
- **Purpose:** Compare strict code-only filtering, final-tokenizer-based length filtering, and context-aware educational-example handling.
- **Dataset version:** UNKNOWN
- **Tokenizer version:** UNKNOWN; Policy B is blocked until a final tokenizer exists
- **Model version:** N/A
- **Configuration:** Policy A: strict current code-only filter; Policy B: final-tokenizer-based length filtering; Policy C: context-aware educational examples preserving surrounding textbook explanation as metadata
- **Result:** UNKNOWN (not run)
- **Interpretation:** UNKNOWN (not run)
- **Artifacts:** UNKNOWN
- **Status:** planned

## Preserved historical detail

The following detail is retained from the pre-coordination experiment log so historical measurements are not silently discarded:

```text
Experiment PYT-DATA-001
Date: 2026-09-15
Git Commit: 42e2f53d09fbec4f38a8a4aa994d9da171bd1cfc
Dataset Versions: Think Python 2nd Edition (293 records), ATBS 3rd Edition (123 records)
Filtering Configuration: min provisional token length 50, max 2048, min comment ratio 0.1, PEP8 max violations 5
AST Validator: scripts.validators.ast_validator.validate_python
PEP8 Implementation: pycodestyle 2.14.0
Provisional Token Count Method: whitespace-based text.split(); labeled provisional because final Pythia tokenizer does not exist yet
Exact Counts:
  - Think Python: examined 293, syntax-valid 287, token < 50: 293, below comment ratio 0.1: 276, PEP8 rejected: 0, exact duplicate hashes: 56, retained: 0
  - ATBS: examined 123, syntax-valid 56, token < 50: 106, below comment ratio 0.1: 107, PEP8 rejected: 13, retained: 5
Known Limitations: Provisional whitespace-based token counting; educational code examples often lack internal comments but have external textbook prose; code-only documentation rule may be inappropriate for tutorial/exercise data
Interpretation: Under current strict preliminary Stage 1 filtering, Think Python retained 0/293 records and ATBS retained 5/123 records. Outcomes may be strongly affected by provisional whitespace token counting and code-only documentation requirements.
Follow-up: Experiment PYT-DATA-002: Policy comparison - Policy A (strict code-only filter), Policy B (final tokenizer-based length filtering), Policy C (context-aware educational examples with preserved textbook explanation as metadata)
```
