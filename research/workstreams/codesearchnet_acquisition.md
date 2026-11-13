# CodeSearchNet Acquisition — Final Report

Workstream: Pythia-160M / PYTHIA-007
Date: 2026-10-22
Final status: **`READY_FOR_NEXT_ACQUISITION_STAGE`**
Technical readiness: `READY_FOR_SCALE_UP` (full Python subset acquired, license-gated, validated)
Legal readiness: only permissive-licensed records promoted; copyleft/unknown segregated as `LICENSE_REVIEW_REQUIRED`

## 1. Candidate source comparison

| Candidate | Identity | Python records | Provenance | License evidence | Splits | Verdict |
|---|---|---|---|---|---|---|
| Original S3 (`s3.amazonaws.com/code-search-net/CodeSearchNet/v2/python.zip`) | Original CodeSearchNet data | n/a | full (repo/path/commit/url) | `python_licenses.pkl` | train/valid/test | **INACCESSIBLE** — 403 `AllAccessDisabled` |
| HF `code-search-net/code_search_net` (parquet) | Official CodeSearchNet re-host by `code-search-net` org | 412,178 train / 23,107 valid / 22,176 test | `repository_name`, `func_path_in_repository`, `func_code_url` | **none** (card states per-example license not included) | train/test/validation | Partial — no license evidence |
| HF `sentence-transformers/codesearchnet` | Derived comment/code mirror | ~1.38M comment/code rows (mixed language) | **none** (only `comment`/`code`) | none | none | Rejected — no provenance |
| **Zenodo `python.zip` (DOI 10.5281/zenodo.7908468)** | Official CodeSearchNet-team frozen re-host | 412,178 train / 23,107 valid / 22,176 test (`final/jsonl`) + undocumented superset in `python_dedupe_definitions_v2.pkl` | full (repo, path, func_name, `sha`, `url`) | `python_licenses.pkl` (17,059 repos) | train/valid/test | **SELECTED** |

## 2. Go/no-go decision

**GO** — acquire the CodeSearchNet Python subset from the official Zenodo archive
(DOI `10.5281/zenodo.7908468`, record `7908468`).

Rationale: it is the only candidate that recovers, from a single frozen and
checksummed source, (a) the original JSONL records with repository identity,
commit SHA, file path, and source URL; (b) the original train/valid/test split
assignments; and (c) per-repository license evidence (`python_licenses.pkl`).

## 3. Archive integrity

| Field | Value |
|---|---|
| URL | `https://zenodo.org/api/records/7908468/files/python.zip/content` |
| Size | 940,909,997 bytes |
| MD5 | `07b49dd01fbac894fbdae22da6462e4f` (verified) |
| SHA-256 | recorded in the acquisition manifest |

Archive members (from ZIP central directory):

- `python/final/jsonl/train/python_train_{0..13}.jsonl.gz` (14 shards)
- `python/final/jsonl/valid/python_valid_0.jsonl.gz`
- `python/final/jsonl/test/python_test_0.jsonl.gz`
- `python_licenses.pkl` (per-repository license evidence)
- `python_dedupe_definitions_v2.pkl` (undocumented-function superset; Category B, deferred)

## 4. Record schema (source)

Each JSONL record contains: `repo`, `path`, `func_name`, `original_string`,
`language`, `code`, `code_tokens`, `docstring`, `docstring_tokens`, `sha`,
`partition`, `url`.

`code` is the function body including `def` and docstring; `docstring` is the
extracted documentation; `sha` is the source commit; `url` is the GitHub blob
URL with commit and line range.

## 5. Licensing / provenance gate

- 17,059 unique repositories have license evidence in `python_licenses.pkl`.
- License text is loaded via a **restricted unpickler** (data-only builtins);
  any pickle referencing callables/globals is rejected (never executed).
- Per-repository license text is classified deterministically into:
  - `LICENSE_APPROVED_FOR_INTENDED_USE` — permissive allowlist (MIT, Apache-2.0,
    BSD-2/3-Clause, ISC, Unlicense, CC0-1.0, Python-2.0, Zlib, 0BSD, WTFPL,
    BlueOak-1.0.0).
  - `LICENSE_REVIEW_REQUIRED` — GPL/LGPL/AGPL/MPL/EPL, unknown, ambiguous,
    multiple-with-copyleft, or missing license text.
  - `LICENSE_INELIGIBLE` — explicit no-redistribution (none observed in this
    corpus so far).
  - `PROVENANCE_INSUFFICIENT` — no repository identity recoverable.

Only records that are both quality-ACCEPTED and license-APPROVED are promoted
to the filtered corpus. Review-required and ineligible records are preserved in
the rejected/audit output, never merged into approved training data.

This classification is evidence-based and deterministic; it is **not** a legal
determination. Final counts are recorded in the acquisition manifest and the
closing report.

## 6. Reference sample (license distribution over all 17,059 repos)

| Identifier | Repositories |
|---|---|
| MIT | 8,490 |
| Apache-2.0 | 2,211 |
| BSD-3-Clause | 1,666 |
| GPL-3.0 | 1,323 |
| UNKNOWN | 843 |
| BSD-2-Clause | 730 |
| GPL-2.0 | 452 |
| LGPL-3.0 | 338 |
| AGPL-3.0 | 246 |
| MPL-2.0 | 135 |
| (others / combinations) | remainder |

Approved: 13,354 repos; Review-required: 3,705 repos (78.3% / 21.7%).

## 7. Infrastructure incident and remediation (2026-10-22)

The first full run (`full-v1`) aborted after 4 source shards with:

```
OSError: [Errno 5] Input/output error:
  '/mnt/pythia-cloud/PythiaDrive/filtered/stage2/codesearchnet_full-v1/checkpoint.json.tmp'
```

The failure occurred on the checkpoint's atomic `os.replace` over the rclone
FUSE mount (a known instability, also recorded in `SESSION1_FINAL_REPORT.md`).
Sequential appends to the accepted/rejected files had succeeded; only the
rename-based checkpoint write failed. Because the abort happened after the
current shard's records were flushed but before its checkpoint entry was
persisted, the output held one uncheckpointed shard (`full-v2` restarts clean;
`full-v1` output was deleted).

Remediation (implemented in `scripts/scrapers/codesearchnet_acquire.py`):

1. `_write_checkpoint` now retries up to 6 times with exponential backoff and
   cleans up the `.tmp` file between attempts.
2. On resume, `_repair_output_tail` truncates any uncheckpointed trailing
   records back to the checkpointed accepted/rejected counts, so the
   interrupted shard is reprocessed without duplication.
3. Unit + integration coverage added (`TestResumeRepair`, `TestAcquireResume`).

The full run resumes/writes directly to the authoritative cloud root (no local
corpus staging), preserving the plan's "authoritative storage root" requirement.


## 8. Final acquisition results (run `full-v3`)

Authoritative run: `codesearchnet_full-v3` (manifest
`/mnt/pythia-cloud/PythiaDrive/manifests/codesearchnet_acquisition_full-v3.json`).

| Metric | Value |
|---|---:|
| Source records processed | **457,461** |
| Accepted (license + quality eligible) | **312,723** (68.4%) |
| Rejected | **144,738** (31.6%) |
| — `LICENSE_REVIEW_REQUIRED` | 134,996 |
| — quality-rejected on approved license | 9,742 |
| Distinct repositories (processed) | 13,590 |
| Archive MD5 | `07b49dd01fbac894fbdae22da6462e4f` (verified) |

Split preservation is exact and matches the official CodeSearchNet/HF counts:

| Split | Records |
|---|---:|
| train | 412,178 |
| valid | 23,107 |
| test | 22,176 |
| total | 457,461 |

Quality rejection reasons on approved-license records (a record may carry more
than one reason): `trivial_stub` 6,516; `ast_invalid` 2,387;
`generated_or_boilerplate` 860.

Accepted-license composition (top identifiers): MIT 139,548; Apache-2.0 96,216;
BSD-3-Clause 42,729; BSD-2-Clause 13,564; dual/triple permissive combinations
the remainder.

## 9. Artifacts and integrity

| Artifact | Path | Bytes | SHA-256 |
|---|---|---:|---|
| Accepted canonical JSONL | `/mnt/pythia-cloud/PythiaDrive/filtered/stage2/codesearchnet_full-v3/codesearchnet_canonical_accepted.jsonl` | 1,376,283,223 | `420c36b20ffcfd318f993df4c5e05b06d07fae3893cdf38982d5e867ab8bf318` |
| Rejected / audit JSONL | `/mnt/pythia-cloud/PythiaDrive/filtered/stage2/codesearchnet_full-v3/codesearchnet_rejected.jsonl` | 46,709,966 | `d7f4f3f1f3477cce0563f417ea1091dc73d8e826bde8844e0b5467faa014d289` |
| Acquisition manifest | `/mnt/pythia-cloud/PythiaDrive/manifests/codesearchnet_acquisition_full-v3.json` | 30,873 | — |
| Raw archive | `/mnt/pythia-cloud/PythiaDrive/raw/codesearchnet/python.zip` | 940,909,997 | MD5 verified |
| Raw extraction | `/mnt/pythia-cloud/PythiaDrive/raw/codesearchnet/python/final/jsonl/**` + `python_licenses.pkl` | — | — |

The uploaded files were verified with `rclone check` (size + hash): 0
differences, 2 matching files.

## 10. Validation performed

- All 16 source shards processed; checkpoint completed for every shard.
- Line counts reconcile exactly: 312,723 accepted + 144,738 rejected = 457,461
  processed = 412,178 train + 23,107 valid + 22,176 test.
- Every accepted record has `license_status = LICENSE_APPROVED_FOR_INTENDED_USE`
  and `quality_status = ACCEPTED` (verified across the full accepted file).
- Identifier uniqueness: 457,461 distinct `record_id`; 457,461 distinct
  `content_hash`; **0 exact-duplicate content records**.
- Non-destructive dedup audit retained: 218 source-identity groups
  (`repo::path::func_name::sha`) map to multiple distinct code bodies (e.g.
  same-named nested functions / getter-setter pairs on adjacent lines). These
  are documented, not removed.

## 11. Known limitations / notes

- `record_id` folds the normalized-content digest into the source-identity tuple.
  The source identity alone is not unique in CodeSearchNet; without the digest,
  148 accepted-record groups (177 records) collided. `full-v3` is the canonical
  run with globally unique IDs.
- License classification is deterministic and evidence-based, not a legal
  opinion. Copyleft/unknown/missing licenses are conservatively held in
  `LICENSE_REVIEW_REQUIRED` and never merged into the accepted corpus.
- Token counts remain provisional (`char_count // 4`) until the custom tokenizer
  exists (DEC-20260915-003).
- The undocumented `python_dedupe_definitions_v2.pkl` superset (~2.9 GB
  uncompressed) was intentionally **not** extracted; it is Category B material
  requiring separate governance.

## 12. Reproducibility

Command (from the repo root), reusing the verified raw archive/extraction:

```
python -m scripts.scrapers.codesearchnet_acquire \
  --raw-dir /mnt/pythia-cloud/PythiaDrive/raw/codesearchnet \
  --filtered-dir /mnt/pythia-cloud/PythiaDrive/filtered/stage2 \
  --manifest-dir /mnt/pythia-cloud/PythiaDrive/manifests \
  --skip-download --skip-extract --run-id full-v3
```

Tests: `python -m pytest tests/test_codesearchnet_acquire.py` (39 passing).
