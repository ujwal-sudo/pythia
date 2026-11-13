# Prose Extractor Reconciliation — `prose_docs.py` vs `prose_plus_code.py`

- **Report ID:** `RECON-PROSE-001`
- **Version:** v1
- **Date:** 2026-10-22T20:01:34Z
- **Repository:** `~/Desktop/Pythia/pythia-data-pipeline`
- **Git HEAD:** `49ad817` (working tree dirty; neither scraper is committed)
- **Phase status:** Phases 1–3 complete (read-only). Phase 4 (edits) and Phase 5 (new-source pilot) are **blocked pending explicit coordinator selection**.
- **Scope:** Resolve which prose extractor is canonical before scikit-learn/SymPy work. No acquisition, no pilot rerun, no scraper edits, no commits.

---

## 1. Executive summary

**Recommendation: adopt `scripts/scrapers/prose_docs.py` as the canonical RST/prose+code extractor, conditional on mandatory fail-closed license and schema fixes.**

`prose_docs.py` is the only implementation validated end-to-end on the real sources. It preserves ordered prose/code structure, section hierarchy, document identity, includes, tab/admonition containers, and directive options, and its outputs reconcile to immutable hashes. `prose_plus_code.py` has a better license gate and better output-contract fields, but its RST parser has disqualifying defects on real PEPs (notably `:class:` option lines and indented directives), and it discards reading-order structure.

The existing pilot (`prose-20261022T100121Z-f5fc9a3b`, **10,240 records**, 1,881,929 provisional tokens) must **not** be promoted as-is: 32 PEP documents (250 records, 54,794 tokens) are stamped `CC0-1.0` without a supporting per-document Copyright section, and 6 of those documents carry explicitly different or ambiguous terms.

The premise “10,241 records” is a superseded-run count. Verified final counts are **9,838 PEPs + 402 Devguide = 10,240**; the 10,241-record run is `prose-20261022T095601Z-f5fc9a3b`, retained as evidence only.

---

## 2. Verified state (Phase 1)

### 2.1 Running jobs and ownership

- **No prose/scraper process was running** at inspection time (`ps`/`pgrep` check; repeated twice).
- **Concurrent write observed during reconciliation:** `research/reports/prose_duplicate_analysis_v1.json` appeared at 2026-10-22T20:01:01Z (mtime 01:31 +05:30), while this report was being prepared. It was not created or modified by this session. It corroborates the duplicate and license findings below (45 groups, 94 involved records, 49 excess records, 6,586 tokens; 33 `license_review_documents`) and adds candidate policies P0–P3. Another session was therefore still writing at that time; this report does not depend on it but cites it as independent corroboration.
- `prose_docs.py` and `tests/test_prose_docs.py` were last modified 2026-10-22 15:31 +05:30 (10:01 UTC), contemporaneous with the final pilot run. They belong to the Session 6 prose pilot (`SESSION_6_PROSE_DOCS_PILOT_REPORT.md`, `DEC-20261022-005`).
- `prose_plus_code.py` and `tests/test_prose_plus_code.py` were last modified 15:23/15:25 +05:30 (09:53/09:55 UTC). They have **no** raw acquisition directory and **no** Stage 1 outputs (`data/raw/prose_plus_code` does not exist).
- Both implementations and both test files are **untracked**. No commits were made.

### 2.2 Existing pilot artifacts (all belong to `prose_docs.py`)

| Run ID | PEP records | Devguide records | Status |
|---|---:|---:|---|
| `prose-20261022T095336Z-f5fc9a3b` | 9,947 | 402 | superseded |
| `prose-20261022T095601Z-f5fc9a3b` | 9,839 | 402 | superseded (10,241 total) |
| `prose-20261022T095715Z-f5fc9a3b` | 9,839 | 402 | superseded |
| **`prose-20261022T100121Z-f5fc9a3b`** | **9,838** | **402** | **final; candidate only** |

Final outputs (SHA-256 verified, match `prose_docs_pilot_summary_v1.json`):

- `data/filtered/stage1/prose_docs_prose-20261022T100121Z-f5fc9a3b_peps.jsonl` — 9,838 records, 48,460,837 B, `ad3c63565b0b95233806e11c87849ad62ec11aae20564b8127da86e39662fcda`
- `data/filtered/stage1/prose_docs_prose-20261022T100121Z-f5fc9a3b_cpython_devguide.jsonl` — 402 records, 2,050,105 B, `3ed29176bd2205bf6ee5bfefadae05a45d93c3b5f7325992f1a0682d88452549`

Reports: `data/raw/prose_docs/reports/prose-20261022T100121Z-f5fc9a3b/{report,source_inventory,acquisition_manifests}.json`.
Machine summary: `research/results/data/prose_docs_pilot_summary_v1.json`.

Raw clones and pinning (verified with `git rev-parse HEAD`):

| Source | Clone | Commit | License evidence |
|---|---|---|---|
| `peps` | `data/raw/peps/repo` | `3b0eaa2021d57747ab83b9356eefe597c5745dde` | per-PEP Copyright sections (no repo LICENSE) |
| `cpython_devguide` | `data/raw/devguide/repo` | `ff9af798f7c216406da7699a46ac6b9052711745` | `LICENSE` = CC0 1.0, SHA-256 `bf474cdf…6af0c` |

**Durability gap:** the final outputs and reports are **local only**. The Drive root `/mnt/pythia-cloud/PythiaDrive/filtered/` contains only `stage2` and `stage3`; there is no `filtered/stage1` and no `raw/prose_docs` or `raw/prose_plus_code`. `data/filtered/stage1/stage1_manifest.json` is stale (2026-09-15) and does not list either prose output.

**Independent duplicate/license analysis (concurrent session):** `research/reports/prose_duplicate_analysis_v1.json` (generated 2026-10-22T20:01:01Z) reports the same 33-document license-review set and the same 45 exact-hash groups / 49 excess records / 6,586 duplicate tokens. Its candidate policies reconcile as follows: P0 keep-all 10,240 records / 1,881,929 tokens; P1 exact-dedupe 10,191 / 1,875,343; P2 license-filter 9,990 / 1,827,135; P3 license-filter + exact-dedupe 9,941 / 1,820,549. This is read-only corroboration, not an authorization to apply a policy.

### 2.3 Tests run (read-only, no repo writes)

| Suite | Result |
|---|---|
| `python -m pytest tests/test_prose_docs.py -q` | **29 passed** |
| `python -m pytest tests/test_prose_plus_code.py -q` | **38 passed** |

Both suites use synthetic fixtures/temporary directories. Neither suite tests a real PEP containing `:class:` directive options, a real indented directive, or the PEP `Title:` metadata. `prose_docs` tests do not test license classification at all.

---

## 3. Comparison matrix (Phase 2)

Legend: **Docs** = `prose_docs.py`; **Plus** = `prose_plus_code.py`. “Winner” is relative to the stated objective (training-ready explanatory prose with code, license-first).

| Dimension | Docs | Plus | Winner / note |
|---|---|---|---|
| **License verification / fail-closed** | Source-level CC0 for all PEPs; no per-document check; Copyright sections skipped (`prose_docs.py:603`). **Defect:** 32 PEP docs / 250 records / 54,794 tokens lack supporting evidence. | Per-document `classify_pep_license`; gate before build (`prose_plus_code.py:1000`); rejects non-approved docs. Fails closed on 33 PEPs. | **Plus** — but its RST parser is broken (below). |
| **Source attribution / version pinning** | `document_id`, `document_path`, `document_url`, `source_revision`, per-document identity; commit recorded at acquisition. | GitHub blob URL with commit per page; `source_version`, `provenance{repository,commit,path,section}`, `source_url`; fresh clone per run. | **Docs** for per-document identity; **Plus** for pinning discipline. |
| **Provenance integrity on rerun** | Reuses an existing clone read-only and does **not** verify `HEAD == manifest.commit` (`prose_docs.py:715-721`); manifest is created once. A moved branch can be processed under a stale manifest. | Clones into staging, resolves commit, then refuses to overwrite an existing commit-specific directory. | **Plus** |
| **Prose extraction** | Custom RST parser: headings, reflowed paragraphs, lists, definition terms, links/roles/footnotes; resolves `.. include::` (`prose_docs.py:454`); handles tabs/admonitions/versions. | Custom RST parser: headings, inline cleanup, notes, literal blocks; **does not resolve includes**; nested/indented directives are missed because directive regex is applied to the raw line, not `stripped` (`prose_plus_code.py:357`). | **Docs** |
| **Code-block extraction** | Strips directive options (`_strip_code_options`, `prose_docs.py:323`); handles `code-block`, `code`, `sourcecode`, `parsed-literal`, `doctest`; preserves relative indentation; keeps ordered segments. | Handles top-level `code-block`/`code`/`doctest`/literal blocks, but does **not** strip option lines. On real PEP 8, all 17 parsed blocks began with `:class:` and failed AST validation → **0 valid code blocks**. Across 745 PEPs: 5,765 parsed vs 2,877 AST-valid (Docs: 6,131 blocks / 2,984 valid). | **Docs** |
| **PEP metadata / page title** | Removes PEP header fields from `Preamble`; uses `Title:` metadata for `document_title` (`prose_docs.py:805-810`). | Skips PEP metadata but derives page title from the first heading. **Defect:** 743/744 PEP documents got the wrong page title (e.g. PEP 8 → “Introduction”, not “Style Guide for Python Code”). | **Docs** |
| **Duplicate HTML code suppression** | N/A (no HTML support). | Fixed: outermost `div.highlight` only; nested `pre` skipped; test asserts one extraction per block. Unverified on real scikit-learn/SymPy HTML. | **Plus** (feature), Docs (coverage) |
| **Indentation preservation** | `_dedent` + `_strip_code_options`; verified on real PEP 8 good/bad examples. | `_dedent` preserves relative indentation, but option lines contaminate code; indented directives are lost. | **Docs** |
| **Chunk-boundary correctness** | Splits only at segment boundaries; keeps each code example adjacent to its prose. **Edge defect:** a single oversized segment is never split (`_split_segments`, `prose_docs.py:540`); synthetic 5,000-token segment produced one 5,000-token record. Observed pilot max was 2,025, so no current violation. | Hard-splits long prose/words and guarantees prose budget; code attached only to first chunk, losing reading order. Can slightly exceed `MAX_UNIT_TOKENS` when `code_tokens` is near the cap. | **Docs** for observed data; **Plus** for hard-cap behavior. |
| **Truncation / record completeness** | No silent truncation; every record has ordered segments and non-empty `content` (verified 0 empty). Invalid Python retained in `content` (93 PEP records) but flagged only inside `code_blocks`, not in the fenced `content`. | Rejects code blocks ≥ cap (`code_too_long`); drops invalid code entirely; no `content` or `segments`, so interleaving is lost. | Mixed; requires policy decision. |
| **Deduplication / stable IDs** | Within-document content-hash dedupe (`prose_docs.py:600-642`); cross-document repeats retained (45 groups / 49 PEP records). IDs `source:doc:ordinal:part:hash8` are deterministic but parser-version-dependent. | Global per-source content-hash dedupe; ID `prose_<hash24>`; content includes prose + attached code; deterministic. | **Plus** for uniqueness; **Docs** for preserving distinct provenance. Needs a corpus-level policy. |
| **Download retries / safe resume** | No HTTP download path; `git clone` with no retry; duplicate run IDs refused. | `_download_resumable` with `Range`, 3 attempts, atomic move (`prose_plus_code.py:831`); git clone no retry. | **Plus** |
| **Output schema / downstream compatibility** | Legacy Stage 1-ish: `id`, `exact_hash`, `provisional_token_count`, `content`, `segments`, `document_url`, `retrieved_at`. **Missing contract fields:** `source_type`, `source_url`, `record_id`, `content_hash`, `acquisition_date`, `license_status`, `token_count_status`. | **Has** `source_type`, `source_url`, `record_id`, `content_hash`, `acquisition_date`, `license_status`, `token_count_status`, `validator_version`; missing `content`/`segments` and legacy `id`/`exact_hash`. | **Plus** for `research/data_contract.md`; **Docs** for existing Stage 1 conventions. Best answer is dual fields. |
| **Manifest / rejected-record accounting** | Report + source inventory + acquisition manifests; aggregate rejection counts only (`no_prose`, `too_short`); **no rejected-record file**. | Report + inventory + acquisition manifests; per-source rejected JSONL with reasons; invalid/skipped code counters. | **Plus** |
| **Reproducibility evidence** | Complete run registry entry (`PROSE-DATA-001`), hashes verified, 4 runs retained, final run identified. | No run, no outputs, no registry entry. | **Docs** |
| **Test coverage / regressions** | 29 tests: headings, ordering, literals, directives, doctest, tabs, admonitions, include cycles, cleanup, filters, splits, dedupe, discovery, acquisition, end-to-end, refusal, dry-run. No license/schema/cap tests. | 38 tests: RST synthetic, HTML duplicates/noise, license classification, chunking, dedupe, schema, writers, dry-run. **Misses** real-PEP option lines, indented directives, PEP `Title:` metadata, includes. | **Docs** for realistic parser coverage; **Plus** for license/HTML/schema tests. |

---

## 4. Concrete defects and strengths

### 4.1 `prose_docs.py`

**Strengths**

1. Structure-preserving output: ordered `segments` plus rendered `content`; code examples remain adjacent to the prose that explains them.
2. Handles real-world RST features the other parser misses: `:class:` options, indented directives, `include` resolution, tab containers, admonitions/version labels.
3. End-to-end validated: 808 documents, 15,059 sections, 10,240 records, hashes reconcile; deterministic reruns (report documents repeated-run equality).
4. Correct PEP title metadata and section hierarchy; 0 empty `content`; 0 within-document duplicate IDs.
5. Atomic, refuse-overwrite writers; no code execution (AST-only).

**Defects (all verified)**

1. **License fail-closed is absent (critical).** The inventory stamps all PEPs `CC0-1.0`; `build_records` skips Copyright sections. `prose_plus_code.classify_pep_license` applied to the same 745 PEP files gives 712 approved, 26 with no Copyright section, and 7 with a Copyright section that is not CC0/public-domain:
   - `pep-0401` (explicit “don't quote, copy, modify, or distribute”),
   - `pep-0437`, `pep-0483`, `pep-3145` (Open Publication License),
   - `pep-0551`, `pep-0578` (Microsoft terms referencing Open Publication License),
   - `pep-0227` (Copyright heading with no statement).
   Output impact: **32 documents / 250 records / 54,794 tokens**; 6 explicitly non-CC0/ambiguous docs account for 51 records / 13,173 tokens.
2. **Contract/schema gaps.** Missing `source_type`, `source_url`, `record_id`, `content_hash`, `acquisition_date`, `license_status`, `token_count_status`; `reproducibility_manifest.py` expects `record_id`/`content_hash`/`acquisition_date`/`license_status`.
3. **No rejected-record artifact.** Only aggregate counts; rejection reasons are not reconstructible per record.
4. **Acquisition drift risk.** Existing clone is reused without checking it against the acquisition manifest commit.
5. **Soft token cap.** A single segment larger than 2,048 tokens is emitted unsplit (synthetic 5,000-token case). Not observed in the pilot (`max = 2,025`).
6. **Devguide titles.** 111/402 Devguide records have `document_title == ""` (no overline title and no `Title:` metadata).
7. **Invalid code in `content`.** 93 PEP records include AST-invalid fragments inside `python` fences; the flag exists only in `code_blocks`.
8. **Cross-document duplicates.** 45 exact-hash groups / 49 excess PEP records retained with distinct provenance; no corpus-level dedupe policy. Independently corroborated by `research/reports/prose_duplicate_analysis_v1.json`; exact dedupe would remove 49 records / 6,586 tokens (P1), and 55 near-duplicate proxy groups / 60 extra records are noted but not applied.
9. **Token method divergence.** Prose tokens use whitespace split; CodeSearchNet uses `char/4`; method is `whitespace_prose_plus_code_tokens_v1`.
10. **RST-only.** No HTML source path, so scikit-learn/SymPy need a new front-end.
11. **Local-only outputs and stale Stage 1 manifest** (see §2.2).

### 4.2 `prose_plus_code.py`

**Strengths**

1. Per-document license gate with fail-closed statuses; would reject the 33 unsupported PEPs (subject to classifier review).
2. Contract-oriented schema: required `source_type`, `source_url`, `record_id`, `content_hash`, `acquisition_date`, `license_status`, `token_count_status`, `validator_version`.
3. Rejected-record JSONL with reasons and invalid/skipped code accounting.
4. Resumable HTTP download with retries; fresh commit-pinned clones with refuse-overwrite.
5. HTML duplicate-code suppression (outermost highlight only) and noise stripping; test-covered.
6. Atomic writers; 38 passing tests.

**Defects (verified on real data)**

1. **Directive options are treated as code.** All 17 parsed blocks in PEP 8 began with `:class:` and failed AST validation → **0 valid code blocks** for the most important style guide.
2. **Indented/nested directives are not recognized** because the regex runs on the raw line rather than `stripped`; listed examples are lost.
3. **Wrong PEP page titles:** 743/744 PEP documents use the first heading instead of the `Title:` metadata.
4. **No structure preservation:** no `content`/`segments`; code is appended to the first prose chunk, losing reading order.
5. **No include resolution**; admonition bodies contribute prose but nested code inside admonitions is dropped.
6. **No real-data validation:** no raw acquisition, no outputs, no run-registry entry; HTML path untested on scikit-learn/SymPy.
7. **Global dedupe per source** drops cross-document repeated text rather than preserving distinct provenance (policy difference, not strictly a bug).
8. **No retry for git clone**, only HTTP.

---

## 5. Compatibility risks

1. **Two competing schema conventions.** Existing Stage 1 files use `id`/`exact_hash`/`provisional_token_count`; `research/data_contract.md` requires `record_id`/`content_hash`/`acquisition_date`. Neither scraper satisfies both. Adding aliases is low-risk; choosing one exclusive schema is not.
2. **No downstream consumer.** No canonicalization/assembly script currently reads `prose_docs_*` or `prose_plus_code_*`; `stage1_manifest.json` is stale. `quality_gate.evaluate_record` expects a top-level `code` field, which neither prose schema provides.
3. **Promotion hazard.** `DEC-20261022-005` accepts the pilot as “candidate records”; it must remain non-promotable until the license gate and schema aliases land.
4. **Durability.** The only verified pilot outputs are on local disk (93% full). Drive has no Stage 1 copy.
5. **Token-count comparability.** Mixing `char/4`, whitespace prose, and tokenizer code counts makes cross-source token totals non-additive without a documented conversion.
6. **Identification of “the 10,241-record pilot.”** That count is superseded; using it in reports would misstate the corpus by one record and by a different parser revision.

---

## 6. Recommendation (Phase 3)

### 6.1 Canonical choice

**Adopt `scripts/scrapers/prose_docs.py` as the canonical RST/prose+code extractor.** Rationale:

- It is the only implementation with real-source, end-to-end evidence and reproducible hashes.
- It preserves ordered prose/code structure, which is the entire point of the prose-plus-code workstream; `prose_plus_code.py` flattens that structure.
- Its parser handles the real RST constructs that `prose_plus_code.py` fails on.
- Its weaknesses are localized and fixable (license gate, schema aliases, rejection artifact, drift check); `prose_plus_code.py` would require replacing its core RST parser and adding structure preservation, with less evidence.

**Do not use `prose_plus_code.py`'s RST path.** Keep the file and its tests as prior art/reference, and preserve both implementations until the canonical path passes regression tests. Its HTML extraction, resumable download, and contract-field work are useful inputs for a future HTML front-end.

### 6.2 Mandatory minimal changes before new sources (P0)

1. **Add per-document license verification for PEPs.** Reuse the fail-closed logic already proven in `prose_plus_code.classify_pep_license` (prefer extracting it to a shared helper). Emit `license_status`; classify the 32 unsupported documents as `LICENSE_REVIEW_REQUIRED` (or `LICENSE_INELIGIBLE` for `pep-0401` if the coordinator treats its wording literally). Only approved records enter the accepted output.
2. **Add compatibility aliases** without removing existing fields: `record_id` (= `id`), `content_hash` (= `exact_hash`), `source_type="raw"`, `source_url` (= `document_url`), `acquisition_date` (= run/acquisition timestamp), `token_count` (= `provisional_token_count`), `token_count_status="PROVISIONAL"`, `source_version` (= `source_revision`).
3. **Write a rejected-record JSONL** per source with reason codes (`license_not_approved`, `no_prose`, `too_short`, `duplicate`) and reconcile counts to the accepted file.
4. **Verify acquisition integrity:** before processing, assert `git rev-parse HEAD == manifest.commit` (or explicitly re-pin and rewrite a new manifest); record the license-file hash for sources that have one.
5. **Fix the token cap edge case:** split a single oversized segment deterministically, or reject it with a recorded reason; add a regression test.
6. **Derive Devguide titles** from the first heading/filename when no title metadata exists; add a test.

### 6.3 Deferred (P1, not blocking the RST pilot)

- Decide whether AST-invalid examples stay in `content`; if yes, mark them in the rendered fence or exclude them from training text.
- Set a corpus-level exact-hash dedupe policy for the 45 cross-document groups.
- Unify or explicitly document token-count conversion.
- Add `include`/tab/admonition cases already covered by tests to a real-source fixture.

### 6.4 Scikit-learn / SymPy (Phase 5 proposal only — do not execute)

`prose_docs.py` has no HTML path. Before scikit-learn/SymPy:

1. Confirm the source-specific license/version evidence again (scikit-learn 1.9.1 BSD-3-Clause docs zip; SymPy 1.14.0 BSD-3-Clause `gh-pages` sparse checkout).
2. Build a separate HTML front-end that emits the **same canonical prose schema**; reuse `prose_plus_code._download_resumable` and a corrected `html_units` rather than its RST parser.
3. Run each source with a separate versioned run ID and a new output destination; do not overwrite the PEP/Devguide pilot.
4. Report actual validated token counts separately from estimates, and keep rejected records.

---

## 7. Test and acceptance checklist

### For the reconciling/canonical session

- [ ] Coordinator explicitly selects `prose_docs.py` (or documents an alternative) and authorizes Phase 4.
- [ ] License gate implemented; all 32 unsupported PEP docs excluded/quarantined; accepted output contains only `LICENSE_APPROVED_FOR_INTENDED_USE`.
- [ ] License count reconciliation: 745 PEPs → 712 approved / 26 missing / 7 other; accepted record count drops by 250 from the current pilot unless review decisions restore some.
- [ ] Contract aliases present on every accepted record; legacy fields preserved.
- [ ] Rejected JSONL exists and its counts reconcile to the accepted file and `report.json`.
- [ ] Acquisition HEAD matches manifest commit; drift test fails closed.
- [ ] Determinism: two runs to separate destinations produce identical record content/hashes (ignoring timestamps) and unique IDs.
- [ ] No record exceeds 2,048 tokens, or oversized-segment handling is documented and tested.
- [ ] `document_title` non-empty for all accepted Devguide records.
- [ ] Targeted tests: existing 29 + new license/schema/cap/drift tests; full suite run with pre-existing failures reported separately.
- [ ] Outputs copied to Drive and `stage1_manifest.json` updated only after acceptance (separate authorization).
- [ ] Decode/quality dry-run with the downstream consumer proves schema compatibility before promotion.

### For scikit-learn / SymPy (later)

- [ ] Source license and documentation version re-verified at acquisition time.
- [ ] HTML front-end emits the canonical schema; raw archives preserved and checksummed.
- [ ] Separate run ID and output destination; PEP/Devguide artifacts untouched.
- [ ] Actual validated token counts reported separately from estimates; rejected records preserved.

---

## 8. Final status

- **Chosen implementation (recommended, not yet ratified):** `scripts/scrapers/prose_docs.py`, conditional on the P0 fixes in §6.2.
- **Evidence:** real pilot outputs and hashes (§2.2), real-PEP license scan (§4.1), real-PEP parser comparison (§4.2), both test suites passing (§2.3).
- **Tests run:** `test_prose_docs.py` 29 passed; `test_prose_plus_code.py` 38 passed. No acquisition or pilot rerun.
- **Changes made by this reconciliation:** this report only. **No scraper edits, no data writes, no deletions, no commits.**
- **Untouched artifacts:** CodeSearchNet `full-v3` accepted/rejected/manifest; PyPI `remediation_v2` outputs and code; both prose scrapers and tests; all raw clones and pilot outputs/reports.
- **Unresolved risks:** license classification policy for the 7 non-CC0/ambiguous PEPs and 26 missing-Copyright PEPs; schema convention choice; cross-document dedupe (P1/P3); invalid-code policy; local-only artifacts; no downstream consumer; `prose_plus_code` HTML path unvalidated; concurrent-session ownership of the just-written duplicate analysis.
- **Exact next action requiring coordination:** the coordinating session must (a) confirm ownership/status of the concurrent `research/reports/prose_duplicate_analysis_v1.json` writer, (b) ratify `prose_docs.py` as canonical (or choose an alternative), and (c) authorize the §6.2 P0 edits. After that, Phase 4 should make only those edits, add regression tests, and—only if explicitly authorized—run a license-gated pilot to a **new** versioned destination (e.g. `prose-license-gated-v1`) without overwriting `prose-20261022T100121Z-f5fc9a3b`. Do not start scikit-learn/SymPy until the canonical path passes acceptance.
