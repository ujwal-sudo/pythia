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

### CSN-DATA-001 — CodeSearchNet Python subset acquisition

- **Run/Experiment ID:** codesearchnet-full-v3
- **Date:** 2026-10-22T13:10:00+05:30 to 2026-10-22T13:32:00+05:30 (UTC 07:40–08:02)
- **Owner:** OP
- **Git commit:** `49ad817` (working tree dirty: acquisition module + tests uncommitted)
- **Dataset version:** `codesearchnet_full-v3` (raw = Zenodo DOI `10.5281/zenodo.7908468`)
- **Tokenizer version:** `provisional_char_count_div_4`
- **Model version:** N/A
- **Hardware:** local NVMe (staging) + Google Drive via rclone mount `pythia:Pythia`
- **Software environment:** Python 3.12.11
- **Random seed:** none (deterministic)
- **Command:** `python -m scripts.scrapers.codesearchnet_acquire --raw-dir /mnt/pythia-cloud/PythiaDrive/raw/codesearchnet --filtered-dir /mnt/pythia-cloud/PythiaDrive/filtered/stage2 --manifest-dir /mnt/pythia-cloud/PythiaDrive/manifests --skip-download --skip-extract --run-id full-v3`
- **Input artifacts:** `raw/codesearchnet/python.zip` (940,909,997 bytes, MD5 `07b49dd01fbac894fbdae22da6462e4f`); extracted `python/final/jsonl/{train,valid,test}/*.jsonl.gz`; `raw/codesearchnet/python_licenses.pkl`
- **Output artifacts:** `filtered/stage2/codesearchnet_full-v3/codesearchnet_canonical_accepted.jsonl` (1,376,283,223 bytes, SHA-256 `420c36b2…bf318`); `.../codesearchnet_rejected.jsonl` (46,709,966 bytes, SHA-256 `d7f4f3f1…4d289`); `manifests/codesearchnet_acquisition_full-v3.json`
- **Result:** processed 457,461; accepted 312,723; rejected 144,738 (134,996 license-review + 9,742 quality-on-approved); splits train 412,178 / valid 23,107 / test 22,176; 82,854,131 provisional tokens; 0 exact content duplicates; 457,461 unique record IDs.
- **Notes:** `full-v2` (first complete cloud run) was superseded because `record_id` omitted a content discriminator (148 colliding accepted groups) and was purged after `full-v3` upload. A transient rclone FUSE `os.replace` I/O error had aborted `full-v1`; checkpoint retry + resume-tail repair were added. Upload verified with `rclone check` (0 differences).

### PROSE-DATA-001 — Structure-preserving prose+code documentation pilot

- **Run/Experiment ID:** prose-20261022T100121Z-f5fc9a3b
- **Date:** 2026-10-22T10:01:21Z (final run)
- **Owner:** OP
- **Git commit:** `49ad817` (working tree dirty: `prose_docs.py` + tests uncommitted)
- **Dataset version:** `prose_docs_v1` (PEPs commit `3b0eaa2021d57747ab83b9356eefe597c5745dde`; CPython Devguide commit `ff9af798f7c216406da7699a46ac6b9052711745`)
- **Tokenizer version:** `provisional_char_count_div_4` / `whitespace_prose_plus_code_tokens_v1`
- **Model version:** N/A
- **Hardware:** local filesystem (raw + Stage 1)
- **Software environment:** Python 3.12.11; no `docutils` (custom RST parser)
- **Random seed:** none (deterministic)
- **Command:** `python -m scripts.scrapers.prose_docs --sources peps cpython_devguide`
- **Input artifacts:** `data/raw/peps/repo` (28 MB, CC0-1.0); `data/raw/devguide/repo` (3.1 MB, CC0-1.0); acquisition manifests under each `data/raw/<source>/ACQUISITION_MANIFEST.json`
- **Output artifacts:** `data/filtered/stage1/prose_docs_prose-20261022T100121Z-f5fc9a3b_peps.jsonl` (9,838 records, 48,460,837 B, SHA-256 `ad3c6356…62fcda`); `..._cpython_devguide.jsonl` (402 records, 2,050,105 B, SHA-256 `3ed29176…452549`); `data/raw/prose_docs/reports/prose-20261022T100121Z-f5fc9a3b/`
- **Result:** 808 documents examined (789 with records), 15,059 sections seen, 10,240 retained (9,838 + 402), 6,542 code blocks (2,994 AST-valid, 146 invalid fragments), 1,675,740 prose tokens + 206,189 code tokens = 1,881,929 provisional tokens; 0 within-document duplicates; 49 cross-document exact-hash repeats in PEPs (identical governance text, distinct provenance); max record 2,025 tokens.
- **Notes:** Superseded in-session runs `prose-20261022T095336Z-f5fc9a3b`, `prose-20261022T095601Z-f5fc9a3b`, and `prose-20261022T095715Z-f5fc9a3b` are retained as evidence. No writes to CodeSearchNet/PyPI outputs. Untracked concurrent `scripts/scrapers/prose_plus_code.py` was not used. Not promoted to `data/final/`.
