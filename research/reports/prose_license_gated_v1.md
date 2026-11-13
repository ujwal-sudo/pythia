# Prose License-Gated Pilot — v1

- **Report ID:** `PROSE-LICENSE-GATED-001`
- **Version:** v1
- **Date:** 2026-10-23T00:11:26Z
- **Canonical extractor:** `scripts/scrapers/prose_docs.py`
- **Final run:** `prose-license-gated-v2`
- **Superseded run:** `prose-license-gated-v1` (retained; its rejected file double-counted parser rejects from license-quarantined documents)
- **Status:** license-gated, schema-compatible candidate; **not promoted**, no Drive copy, no Stage 1 manifest update, no commit.

---

## 1. What changed

`prose_docs.py` now implements the P0 fixes ratified after `RECON-PROSE-001`:

1. **Fail-closed per-document PEP licensing.** New `scripts/scrapers/pep_license.py` classifies each PEP from its own Copyright section. Only explicit public-domain/CC0 text is accepted. All other PEPs are quarantined with `license_status="RESTRICTED_OR_REVIEW"` and a detailed `license_status_detail="LICENSE_REVIEW_REQUIRED"`.
2. **Contract aliases.** Every record now carries `record_id`, `content_hash`, `source_type`, `source_url`, `acquisition_date`, `token_count`, `token_count_status`, `source_version`, `validator_version`, `provenance`, `license_status`, `license_status_detail`, and `license_evidence`, without removing legacy fields (`id`, `exact_hash`, `source_revision`, `provisional_token_count`).
3. **Rejected-record JSONL.** Each source writes `<output_stem>_rejected.jsonl` with `reason` codes (`license_not_approved`, `no_prose`, `too_short`, `duplicate`, `no_prose_chunk`, `oversized_code_segment`) and candidate-record IDs for license quarantines.
4. **Acquisition drift check.** An existing clone is processed only if `git rev-parse HEAD` equals `ACQUISITION_MANIFEST.json` `commit`. Missing/unpinned manifests and HEAD drift fail closed.
5. **Oversized-segment handling.** Oversized prose is split on word boundaries; oversized code is quarantined with `oversized_code_segment` rather than emitting an over-cap record.
6. **Devguide titles.** Empty titles fall back to the first heading, then the filename. `document_title` is non-empty for all 402 accepted Devguide records.
7. **License-file evidence.** New manifests record `LICENSE` SHA-256 when present; the run report records the observed Devguide license-file hash without mutating existing manifests.

---

## 2. Final run

Command (existing clones only; no acquisition):

```bash
python -m scripts.scrapers.prose_docs \
  --sources peps cpython_devguide \
  --run-id prose-license-gated-v2
```

| Metric | Value |
|---|---:|
| Accepted records | **9,990** |
| PEP records | 9,588 |
| Devguide records | 402 |
| Accepted provisional tokens | **1,827,135** |
| Candidate records before license gate | 10,240 |
| License-rejected candidate records | 250 |
| License-rejected tokens | 54,794 |
| Parser rejection entries | 3,040 |
| Total rejection entries | 3,290 |
| Max accepted record tokens | 2,025 |
| Accepted records over 2,048 tokens | 0 |
| Empty `document_title` | 0 |
| Missing required contract fields | 0 |

Rejected entries reconcile as:

- 250 `license_not_approved`
- 1,557 PEP + 36 Devguide `no_prose`
- 1,379 PEP + 68 Devguide `too_short`
- 0 `duplicate` (the pilot has no within-document duplicates)
- 0 `oversized_code_segment`

`accepted (9,990) + license-rejected (250) = 10,240`, matching the original pilot candidate count.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `data/filtered/stage1/prose_docs_prose-license-gated-v2_peps.jsonl` | 55,106,524 | `3e432ba1dee2b78beb8121d696e5872a4093b3778d8c63f1977a447a05cd2c29` |
| `data/filtered/stage1/prose_docs_prose-license-gated-v2_peps_rejected.jsonl` | 1,817,287 | `c8b7001e678385bf75060a3352870f8f53c04b410e94cf9806927d925037f5f0` |
| `data/filtered/stage1/prose_docs_prose-license-gated-v2_cpython_devguide.jsonl` | 2,400,454 | `ec713e7db9b6b2e5f6398369c1e9a6b26d5cd040b295a9f40a9830341b6eec04` |
| `data/filtered/stage1/prose_docs_prose-license-gated-v2_cpython_devguide_rejected.jsonl` | 65,809 | `cb5c657038ec0f990aa81f3ce90ad7d2c4528b4c6d72b458a0379f0a3b44d9ad` |

Run report: `data/raw/prose_docs/reports/prose-license-gated-v2/{report,source_inventory,acquisition_manifests}.json`.

---

## 3. License accounting

Applied `pep_license.classify_pep_license` to all 745 PEP `.rst` files (excluding `pep-0000`):

| Class | Documents | Records | Tokens |
|---|---:|---:|---:|
| Approved | 712 | 9,588 | 1,755,266 |
| Review required | **33** | 250 | 54,794 |
| — no Copyright heading | 26 | 187 | 38,591 |
| — Copyright heading, not approved | 7 | 63 | 16,203 |

Of the 33 review-required documents, **32 produce candidate records**; `pep-0210` produces none. This is why earlier notes may show “32 documents / 250 records” alongside “26 missing + 7 other = 33”: the former counts documents with records, the latter counts all review-required documents.

Explicit non-CC0/restrictive documents (6; 51 records / 13,173 tokens):

- `pep-0401` — restrictive “property of the Python Steering Union … don't even think about quoting, copying, modifying, or distributing it.”
- `pep-0437`, `pep-0483`, `pep-3145` — Open Publication License.
- `pep-0551`, `pep-0578` — Microsoft copyright plus Open Publication License terms.

`pep-0227` has an empty Copyright heading (12 records / 3,030 tokens). PEP 1’s dual-license rule applies to new PEPs; the PEPs clone has no repository-wide `LICENSE`. All 33 remain quarantined pending an explicit policy decision.

The accepted PEP output contains only `license_status="CLEAR"`; all 9,588 PEP records carry non-empty per-document `license_evidence`. Devguide records remain source-level CC0-1.0 with `license_file_sha256 = bf474cdfd02e162603358e4e3615182018cad27593d2bf5e75ca13e4a5a6af0c`.

---

## 4. Contract and reproducibility

Required fields from `research/data_contract.md` are present on every accepted record: `source`, `source_type`, `source_url`, `acquisition_date`, `license`, `record_id`, `content_hash`. Recommended fields `license_status`, `token_count_status`, `provenance`, and `validator_version` are also present.

Caveats that remain:

- `content_hash` is an alias of `exact_hash`, which hashes the rendered content including the `## section_path` header and `(part i/n)` marker; it is not the code-only `global_dedup.normalized_hash` contract.
- Token counts remain `PROVISIONAL` and mix whitespace prose counts with tokenizer-based Python code counts.
- `quality_gate.py` expects a top-level `code` field; prose records expose `code_blocks`.
- Cross-document duplicates are not removed in this run; the 49-record mapping is in `research/reports/prose_duplicate_analysis_v1.json`.
- No canonical assembly consumer exists yet.

Reproducibility was verified independently: a temporary rerun of the original pilot reproduced all 10,240 records with zero field differences excluding `retrieved_at`, matching stats and source revisions. The original pilot outputs remain byte-identical to their recorded hashes. Evidence: `research/reports/prose_pilot_reproducibility_v1.json`.

---

## 5. Tests

| Suite | Result |
|---|---:|
| `tests/test_prose_docs.py` | **35 passed** |
| `tests/test_pep_license.py` | **4 passed** |
| `tests/test_prose_plus_code.py` | 38 passed |
| `tests/test_scientific_docs.py` + `tests/test_python_docs_scraper.py` | included in 99-pass combined run |
| Combined targeted run | **99 passed** |

New regression coverage: per-document license quarantine, license-rejected candidate accounting, parser rejection output, contract aliases, oversized prose split, oversized code quarantine, filename title fallback, clone drift failure, and license-file hashing.

No full-suite run was attempted. Pre-existing failures remain as previously recorded: `tests/test_path_config.py::TestPathsWithPYTHIA_DATA_ROOT::test_with_pythia_data_root_cloud` and four `tests/test_pypi_remote_wiring.py` failures.

---

## 6. Preserved state

- Original pilot outputs `prose-20261022T100121Z-f5fc9a3b` are unchanged (both SHA-256 values re-verified).
- `prose-license-gated-v1` is retained as a superseded run; do not use its rejected counts for accounting.
- No new acquisition, no overwrite of raw clones or manifests, no CSN/PyPI changes, no commits.
- `data/filtered/stage1/stage1_manifest.json` was **not** updated; Drive was **not** written.
- Concurrent reconciliation report `research/workstreams/prose_extractor_reconciliation_v1.md` was not modified. Its “32 documents / 250 records” statement is a documents-with-records count; the total review-required document count is 33.

---

## 7. Next action

Review `prose-license-gated-v2` and decide the policy for the 33 quarantined PEPs:

- If public-domain/CC0 by historical practice is accepted for the 26 missing-Copyright PEPs, document that decision and rerun with an explicit allowlist.
- Keep `pep-0401`, the Open Publication License PEPs, and the Microsoft-terms PEPs excluded unless the coordinator obtains separate permission.
- Only after that decision: copy accepted outputs to Drive, update the Stage 1 manifest, or begin the HTML front-end for scikit-learn/SymPy. Do not promote the legacy 10,240-record pilot.
