# Run Registry

This is the canonical index of reproducible runs.

## Experiment ID Format

Use `EXP-YYYYMMDD-AREA-NNN`.

Areas:

- `TOK`: tokenizer
- `DATA`: dataset and filtering
- `MODEL`: architecture/checkpoint
- `TRAIN`: training
- `EVAL`: evaluation
- `ABL`: ablation
- `NS`: neurosymbolic feedback

## Registered Runs

### EXP-20260915-DATA-001

Experiment ID: EXP-20260915-DATA-001
Date started: 2026-09-15T00:00:00+00:00
Date completed: 2026-09-15T20:25:24+00:00
Status: completed
Research question(s): Ingest and validate Python 3.14 documentation code examples for Stage 1 training candidates.
Hypothesis: Official Python docs HTML archive can be processed into 317 retained Python code examples meeting minimum token count, comment ratio, and PEP8 violation thresholds.
Code commit: UNKNOWN
Config commit/hash: UNKNOWN
Dataset version: 3.14
Model version: N/A
Tokenizer version: provisional_python_tokenize_significant_tokens_v1
Input artifact paths:
  - data/raw/python_docs/python-3.14-docs-html.zip (SHA-256: 44e94d921af3e1c4f46e6dd3a39d606e6847e37e9c3be22700a354de38a9a92f)
Output artifact paths:
  - data/filtered/stage1/python_docs.jsonl (317 records)
  - data/raw/python_docs/manifest.json
  - logs/python_docs_report.json
Command: python3 -m scripts.scrapers.python_docs --process --raw-path data/raw/python_docs/python-3.14-docs-html.zip
Random seed(s): none
Hardware record: see hardware.md
Software version record: see software_versions.md
Metrics:
  - blocks_examined: 10030
  - python_candidates: 10030
  - syntax_valid: 4512
  - syntax_invalid: 416
  - too_short: 3588
  - too_long: 0
  - low_documentation: 569
  - pep8_rejected: 38
  - exact_duplicates: 5102
  - retained: 317
Result summary: Successfully processed Python 3.14 documentation archive into 317 retained code examples. No duplicates introduced. All records syntax-valid. Provenance preserved via manifest SHA-256.
Negative/null result preserved: n/a
Notes: Processed using existing scraper and AST validator. Run was a takeover from a previous interrupted session. Original process completed with 317 retained; re-run confirmed same counts.
