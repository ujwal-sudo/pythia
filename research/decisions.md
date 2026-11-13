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

### DEC-20261022-001 — CodeSearchNet source selection: official Zenodo archive

- **Decision ID:** DEC-20261022-001
- **Decision:** Acquire the CodeSearchNet Python subset from the official frozen Zenodo archive (`python.zip`, DOI `10.5281/zenodo.7908468`) rather than the Hugging Face mirrors or the original S3 bucket.
- **Date:** 2026-10-22
- **Status:** accepted
- **Context:** The original S3 bucket (`s3.amazonaws.com/code-search-net/...`) is decommissioned (403 AllAccessDisabled). The official `code-search-net/code_search_net` Hugging Face dataset re-hosts only the documented function records and does not include per-repository license evidence; the `sentence-transformers/codesearchnet` mirror contains only `comment`/`code` pairs with no repository, commit, path, or license metadata. The Zenodo archive is the official CodeSearchNet-team re-host (DOI 10.5281/zenodo.7908468) and contains the original JSONL splits plus `python_licenses.pkl` (per-repository license text) and `python_dedupe_definitions_v2.pkl` (undocumented-function superset).
- **Options considered:** (A) S3 original (decommissioned); (B) HF `code_search_net` parquet (no license evidence); (C) HF `sentence-transformers/codesearchnet` (no provenance); (D) Zenodo official archive (license + provenance + splits).
- **Chosen approach:** Zenodo official archive.
- **Reason:** Only the Zenodo archive recovers repository identity, per-record provenance (commit SHA + URL), original train/valid/test splits, and per-repository license evidence from a single frozen, checksummed source.
- **Expected effect:** A provenance-preserving, license-auditable Python subset.
- **Actual effect:** Archive downloaded (940,909,997 bytes; MD5 `07b49dd01fbac894fbdae22da6462e4f` verified); 17,059 repositories with license evidence recovered.
- **Related experiment:** UNKNOWN
- **Related task:** PYTHIA-007

### DEC-20261022-002 — Load `_licenses.pkl` via restricted unpickler

- **Decision ID:** DEC-20261022-002
- **Decision:** Load the frozen `python_licenses.pkl` only through a restricted `pickle.Unpickler` that permits data-only builtin types, and reject any pickle that references callables/globals.
- **Date:** 2026-10-22
- **Status:** accepted
- **Context:** The license evidence is distributed as a Python pickle; loading a pickle normally executes code, which violates the project's "do not execute source" rule.
- **Options considered:** (A) `pickle.load` directly (unsafe); (B) restricted unpickler; (C) avoid the file entirely.
- **Chosen approach:** Restricted unpickler (data-only builtins).
- **Reason:** Preserves the license evidence without executing arbitrary pickle opcodes; a malicious pickle is rejected rather than run.
- **Expected effect:** Safe, deterministic loading of license evidence.
- **Actual effect:** 17,059 repositories loaded; a malicious-pickle fixture is rejected by the test suite.
- **Related experiment:** UNKNOWN
- **Related task:** PYTHIA-007

### DEC-20261022-003 — CodeSearchNet license classification policy

- **Decision ID:** DEC-20261022-003
- **Decision:** Classify per-repository license text deterministically into `LICENSE_APPROVED_FOR_INTENDED_USE` (permissive allowlist), `LICENSE_REVIEW_REQUIRED` (copyleft/unknown/ambiguous/missing), `LICENSE_INELIGIBLE` (explicit no-redistribution), or `PROVENANCE_INSUFFICIENT` (no repository identity). Only APPROVED + quality-ACCEPTED records enter the filtered corpus.
- **Date:** 2026-10-22
- **Status:** accepted
- **Context:** The CodeSearchNet dataset card explicitly states example-wise license info is not included and must be determined per repository. The project's own license policy (data_contract.md) maps to CLEAR/UNKNOWN/RESTRICTED_OR_REVIEW; this workstream adopts the more granular four-state scheme required by the acquisition plan.
- **Options considered:** (A) treat all as approved (unsafe); (B) permissive-only allowlist with review bucket for the rest.
- **Chosen approach:** Permissive allowlist (MIT, Apache-2.0, BSD-2/3-Clause, ISC, Unlicense, CC0-1.0, Python-2.0, Zlib, 0BSD, WTFPL, BlueOak-1.0.0) → APPROVED; GPL/LGPL/AGPL/MPL/EPL/unknown/missing → REVIEW_REQUIRED.
- **Reason:** Evidence-based, conservative separation of training-eligible records; does not assert legal certainty beyond the evidence.
- **Expected effect:** Deterministic, auditable license gating; unresolved/copyleft records segregated.
- **Actual effect:** See final acquisition report license counts.
- **Related experiment:** UNKNOWN
- **Related task:** PYTHIA-007

### DEC-20261022-001 — Jupyter notebook selection policy and source go/no-go

- **Decision ID:** DEC-20261022-001
- **Decision:** Acquire Jupyter notebooks for Stage 3 only from permissively licensed, authored sources with immutable-commit provenance, using a Markdown-proportion gate of strictly > 0.40 and a meaningful-Python gate.
- **Date:** 2026-10-22
- **Status:** accepted
- **Context:** Notebook acquisition workstream. Candidates: codebasics/py (no license), jdhp-docs/notebooks (MIT), COGS108/Tutorials (CC-BY-4.0), jupyter-guide/jupyter-guide (MIT), jupyter-agent/jupyter-agent-dataset (Apache-2.0, synthetic Parquet).
- **Options considered:** (a) acquire all candidates; (b) acquire only permissively licensed authored `.ipynb` sources; (c) skip notebook acquisition.
- **Chosen approach:** (b). GO for jdhp-docs/notebooks, COGS108/Tutorials, jupyter-guide/jupyter-guide. NO-GO/defer codebasics/py (no license) and jupyter-agent (synthetic, non-`.ipynb`).
- **Reason:** A public repo or license badge does not prove every notebook is reusable; synthetic non-notebook content fails the `.ipynb` criterion.
- **Expected effect:** 178 raw notebooks acquired, 73 eligible Stage 3 records, with traceable license/provenance and no overwrites.
- **Actual effect:** 178 raw / 73 eligible / 105 rejected across two versioned runs; byte-preservation and count reconciliation verified.
- **Related task:** PYTHIA Jupyter acquisition workstream (Stage 3).

### DEC-20261022-002 — License-first scientific documentation acquisition

- **Decision ID:** DEC-20261022-002
- **Decision:** Acquire official scientific Python documentation (NumPy, SciPy, pandas) under a license-first Accept/Hold/Reject policy, from pinned versioned HTML archives, reusing the authoritative AST validator and pycodestyle tooling. Hold Matplotlib until an immutable acquisition path is chosen.
- **Date:** 2026-10-22
- **Status:** accepted
- **Context:** Extension of Stage 1 official documentation. License of the documentation content (not just the repo) was verified per source.
- **Options considered:** (a) blanket-accept all four; (b) accept BSD-3-Clause docs with versioned HTML archives, hold Matplotlib; (c) skip.
- **Chosen approach:** (b). ACCEPT NumPy 2.5, SciPy 1.18.0, pandas 2.3.3 (BSD-3-Clause, versioned HTML archives). HOLD Matplotlib (PSF-derived license is clear, but only a PDF is published).
- **Reason:** Minimize legal risk by using clearly licensed, provenance-verifiable sources and excluding anything ambiguous until reviewed.
- **Expected effect:** A small, defensible Stage 1 documentation pilot (NumPy).
- **Actual effect:** NumPy 2.5 acquired (4,736 blocks -> 99 retained, sha256 verified); SciPy and pandas ready for scale-up; Matplotlib held.
- **Related task:** Stage 1 documentation acquisition (scientific docs).

### DEC-20261022-003 — Discovery priority and corpus reconciliation

- **Decision ID:** DEC-20261022-003
- **Decision:** Prioritize licensed explanatory prose (official guides + permissively licensed educational books) as the next source family; defer repository-level code; keep Stack Exchange blocked, The Stack on review hold, and GitHub-Python rejected. Do not start overlapping acquisition while CodeSearchNet `full-v3` and PyPI `remediation_v2` are active.
- **Date:** 2026-10-22
- **Status:** accepted
- **Context:** Corpus is code-heavy (CodeSearchNet 82.9M tokens) and prose-poor (Stage 1 ~54k tokens; Jupyter ~136k). The docs pipeline extracts code blocks only.
- **Options considered:** (a) more repository code; (b) explanatory prose/tutorials; (c) Stack Exchange/The Stack.
- **Chosen approach:** (b), with a required new prose extractor; queue acquisition until active runs finish.
- **Reason:** Explanatory prose is the scarce high-signal axis for a Python-specialized model and avoids duplicating CodeSearchNet/PyPI.
- **Expected effect:** A prose corpus from CC0/BSD/CC-BY-SA sources with strong provenance.
- **Actual effect:** Report + priorities written (`SESSION_5_SOURCE_DISCOVERY_REPORT.md`, `source_discovery_priorities_v1.json`); no acquisition started.
- **Related task:** Stage 1 documentation / educational prose.

### DEC-20261022-005 — Structure-preserving prose+code documentation pilot

- **Decision ID:** DEC-20261022-005
- **Decision:** Adopt a structure-preserving prose-plus-code extractor for Stage 1 documentation and accept the CC0-1.0 PEP + CPython Developer's Guide pilot outputs as candidate records. Keep them out of `data/final/` until a corpus-wide exact-hash dedupe policy and a single canonical extractor are chosen.
- **Date:** 2026-10-22
- **Status:** accepted
- **Context:** Verified corpus is code-heavy and prose-poor (Session 5). The previous docs pipeline discarded prose and kept only code blocks. A pilot was requested that keeps each example attached to its explanation, without disturbing CodeSearchNet `full-v3` or PyPI `remediation_v2`.
- **Options considered:** (a) keep the block-only docs pipeline; (b) add a prose+code extractor and pilot CC0 sources first; (c) acquire more code.
- **Chosen approach:** (b). Custom lightweight RST parser (no `docutils`); ordered prose/code segments; AST-only validation; commit-pinned shallow clones; versioned, refuse-overwrite outputs. Use PEPs and the CPython Developer's Guide (both CC0-1.0) as the pilot.
- **Reason:** Explanatory prose with adjacent executable examples is the scarce high-signal axis and avoids duplicating CodeSearchNet/PyPI. CC0 sources minimize legal risk.
- **Expected effect:** A small, auditable Stage 1 prose pilot with full section/document provenance.
- **Actual effect:** Run `prose-20261022T100121Z-f5fc9a3b`: 808 documents examined, 15,059 sections, **10,240 records retained** (9,838 PEPs / 402 Devguide), 6,542 code blocks (2,994 AST-valid, 146 invalid fragments), **1,881,929 provisional tokens** (1,675,740 prose + 206,189 code). 49 PEP records repeat an exact hash across documents (identical governance text; distinct provenance). Earlier in-session runs are retained but superseded. The untracked concurrent `scripts/scrapers/prose_plus_code.py` was not used.
- **Related task:** Stage 1 documentation / educational prose (Session 6).

**Numbering note:** `DEC-20261022-004` is already used in `research/decision_registry.md` for the CodeSearchNet `record_id` decision; `DEC-20261022-005` avoids a cross-file ID collision.
