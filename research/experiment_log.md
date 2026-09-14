## Experiment PYT-DATA-001

**Date:** 2026-09-15
**Git Commit:** 42e2f53d09fbec4f38a8a4aa994d9da171bd1cfc
**Dataset Versions:** Think Python 2nd Edition (293 records), ATBS 3rd Edition (123 records)
**Filtering Configuration:** min provisional token length 50, max 2048, min comment ratio 0.1, PEP8 max violations 5
**AST Validator:** scripts.validators.ast_validator.validate_python
**PEP8 Implementation:** pycodestyle 2.14.0
**Provisional Token Count Method:** whitespace-based text.split(); labeled provisional because final Pythia tokenizer does not exist yet
**Exact Counts:** 
  - Think Python: examined 293, syntax-valid 287, token < 50: 293, below comment ratio 0.1: 276, PEP8 rejected: 0, exact duplicate hashes: 56, retained: 0
  - ATBS: examined 123, syntax-valid 56, token < 50: 106, below comment ratio 0.1: 107, PEP8 rejected: 13, retained: 5
**Known Limitations:** Provisional whitespace-based token counting; educational code examples often lack internal comments but have external textbook prose; code-only documentation rule may be inappropriate for tutorial/exercise data
**Interpretation:** Under current strict preliminary Stage 1 filtering, Think Python retained 0/293 records and ATBS retained 5/123 records. Outcomes may be strongly affected by provisional whitespace token counting and code-only documentation requirements.
**Follow-up:** Experiment PYT-DATA-002: Policy comparison - Policy A (strict code-only filter), Policy B (final tokenizer-based length filtering), Policy C (context-aware educational examples with preserved textbook explanation as metadata)

# Experiment Log

Use this file for human-readable experiment notes. Register reproducible run metadata in `reproducibility/run_registry.md`.

## Template

```text
Experiment ID:
Date:
Owner:
Research question(s):
Hypothesis:
Status: planned | running | completed | failed | abandoned
Code commit:
Config commit/hash:
Dataset version:
Model version:
Tokenizer version:
Command:
Hardware:
Software environment:
Metrics planned:
Result artifact paths:
Summary:
Negative/null findings:
Known limitations:
Follow-up:
```



## Entries
