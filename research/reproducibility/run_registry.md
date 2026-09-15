# Run Registry

Canonical registry for meaningful runs. `UNKNOWN` is used when a field is not recoverable. Historical run details are preserved and discrepancies are explicit.

## Canonical format

```text
Run/Experiment ID:
Date:
Owner:
Git commit:
Dataset version:
Tokenizer version:
Model version:
Hardware:
Software environment:
Random seed:
Command:
Input artifacts:
Output artifacts:
Result:
Notes:
```

## Registered runs

### EXP-20260915-DATA-001 — Python documentation processing

- **Run/Experiment ID:** EXP-20260915-DATA-001
- **Date:** 2026-09-15T00:00:00+00:00 to 2026-09-15T20:25:24+00:00 (historical record)
- **Owner:** UNKNOWN
- **Git commit:** UNKNOWN
- **Dataset version:** UNKNOWN (documentation version recorded as 3.14)
- **Tokenizer version:** `provisional_python_tokenize_significant_tokens_v1`
- **Model version:** N/A
- **Hardware:** UNKNOWN
- **Software environment:** UNKNOWN (no experiment-specific snapshot in `research/reproducibility/software_versions.md`)
- **Random seed:** none
- **Command:** `python3 -m scripts.scrapers.python_docs --process --raw-path data/raw/python_docs/python-3.14-docs-html.zip`
- **Input artifacts:** `data/raw/python_docs/python-3.14-docs-html.zip` (SHA-256 `44e94d921af3e1c4f46e6dd3a39d606e6847e37e9c3be22700a354de38a9a92f`)
- **Output artifacts:** Recorded: `data/filtered/stage1/python_docs.jsonl` (317 records), `data/raw/python_docs/manifest.json`, `logs/python_docs_report.json`. Current filesystem: manifest and report exist; recorded JSONL output is absent; `data/filtered/stage1/python_docs_filtered_v3.jsonl` exists with 96 records.
- **Result:** Historical metrics: blocks_examined 10030; python_candidates 10030; syntax_valid 4512; syntax_invalid 416; too_short 3588; too_long 0; low_documentation 569; pep8_rejected 38; exact_duplicates 5102; retained 317.
- **Notes:** Historical record says the run was a takeover from a previous interrupted session and that a rerun confirmed the same counts. The output-path mismatch is a current blocker; do not silently replace the v3 artifact or historical report.

### PYT-DATA-001 — Textbook filtering baseline

- **Run/Experiment ID:** PYT-DATA-001
- **Date:** 2026-09-15
- **Owner:** OP
- **Git commit:** `42e2f53d09fbec4f38a8a4aa994d9da171bd1cfc`
- **Dataset version:** UNKNOWN (Think Python 2nd Edition and ATBS 3rd Edition are recorded; no formal `data-v...` version exists)
- **Tokenizer version:** UNKNOWN (provisional whitespace-based `text.split()` count)
- **Model version:** N/A
- **Hardware:** UNKNOWN
- **Software environment:** Python version UNKNOWN; pycodestyle 2.14.0 recorded; full environment UNKNOWN
- **Random seed:** UNKNOWN
- **Command:** UNKNOWN
- **Input artifacts:** `data/raw/textbooks/thinkpython_code.jsonl` (SHA-256 `6a59f9584dd38a36ac26f2a76885708a0298be33de21e299315c586c293b2118`); `data/raw/textbooks/atbs3e_code.jsonl` (SHA-256 `3011f35cfe1f93813f658d01b65aae85b65d1f4a114745fbe52aa476c5983414`)
- **Output artifacts:** Recorded legacy paths in `research/results/data/pyt-data-001.json` are absent. Current artifacts: `data/filtered/stage1/thinkpython_filtered_v3.jsonl` (293 records), `data/filtered/stage1/atbs_filtered_v3.jsonl` (162 records), `data/filtered/stage1/stage1_manifest.json`, and `research/results/data/pyt-data-001.json`.
- **Result:** Think Python retained 0/293; ATBS retained 5/123 under the recorded strict baseline. The v3 files contain candidate records and are not verified strict filtered outputs.
- **Notes:** Historical result JSON records the command-independent counts and planned follow-up `PYT-DATA-002`. Counts conflict with parts of `stage1_manifest.json`; reconciliation is required before reuse.
