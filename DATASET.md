# Dataset

The corpus lives on the archive, not on this laptop. This file is the contract
for where data is, how it is selected, and what the current snapshot contains.

## One rule

> Every path goes through `scripts.storage`. There is one root, and it is
> `pythia:Pythia`.

```bash
PYTHIA_STORE=rclone PYTHIA_STORE_ROOT=pythia:Pythia   # the default
PYTHIA_STORE=file   PYTHIA_STORE_ROOT=/tmp/scratch    # tests only
```

`/mnt/pythia-cloud` is **not** used and should not be recreated. It was a plain
directory on the root disk while the real archive was on Drive; the pipeline
"wrote to cloud" onto a partition that now has 8 GB free.

## Layout

```
raw/<source>/…                     as acquired, immutable
filtered/stage1/…                  curated prose + docs
filtered/stage2/<run>/…            CodeSearchNet full-v3
filtered/stage3/…                  notebooks
final/corpus-<snapshot>.jsonl      curated corpus: {"text", "meta"}
manifests/<snapshot>.json          sha256 + counts + policy per input file
reports/curation-<snapshot>.json   what was dropped and why
```

## Commands

```bash
python -m scripts.corpus.doctor                    # read-only health report
python -m scripts.corpus.sync                      # plan uploads (no writes)
python -m scripts.corpus.sync --apply              # publish canonical stage1
python -m scripts.corpus.batch status              # what batches exist
python -m scripts.corpus.batch clean               # clean new files into a batch
python -m scripts.corpus.batch verify --id batch-001
python -m scripts.corpus.build                     # one-shot rebuild from raw
python -m scripts.corpus.quarantine --plan         # local cleanup (no moves)
python -m scripts.corpus.quarantine --apply
```

`batch` is the normal path. `build` is only for rebuilding everything from raw
sources; it re-reads the whole archive and writes one monolithic file.

`doctor` exits non-zero when a file is graded ERROR. It grades what a file
*contains*: records with no text, unparseable lines, unlicensable records, and
identical reruns.

## Batches

Collection arrives in waves. Each wave is cleaned exactly once into an
immutable batch; later waves deduplicate against every earlier one. Training
consumes the union in registry order, so it never has to wait for the last
acquisition.

```
batches/REGISTRY.json                 ordered list + totals (the dataset version)
batches/batch-001/shard-0000.jsonl    ~200 MB, frozen, sha256 recorded
batches/batch-001/hashes.txt          one normalised hash per line
batches/batch-001/stats.json          inputs, counts, every drop reason
```

```bash
python -m scripts.corpus.batch adopt --snapshot corpus-v1-20261110   # existing corpus -> batch
python -m scripts.corpus.batch clean --stages 1,2,3 --only numpy     # next wave
python -m scripts.corpus.batch verify --id batch-001 [--quick]
```

Rules the code enforces:

- A batch is written once. Re-adopting a snapshot or re-cleaning identical
  input files raises `FileExistsError` instead of silently doubling the corpus.
- `clean` downloads every earlier batch's `hashes.txt` into a local SQLite
  index **before** reading new data, so duplicates are dropped and counted
  (`dedup_seeded_from_prior_batches`).
- Normalisation is fixed: CRLF→LF, trailing whitespace stripped, runs of blank
  lines collapsed. Two records differing only in that whitespace are one record.
- `verify` recomputes each shard's sha256 and record count from the archive.
- Code records pass `scripts/corpus/quality.py` (syntax, size, line length,
  generated/migration files, secrets). New batches apply it while cleaning;
  batch-001..006 predate it, so `tokenize_corpus` applies it to them. Shards
  record `quality_filter`, and `finalize` refuses mixed versions.

**Current state: 2,947,277 records / 13.17 B chars / ~3.57 B tokens (estimated, before the q1 quality filter).**

| Batch | Source | Records | Chars | Dedup vs earlier | Licence held |
|---|---|---:|---:|---:|---:|
| batch-001 | CodeSearchNet + prose/docs | 322,507 | 343.5 M | — | 0 |
| batch-002 | The Stack, shards 0–5 | 524,920 | 2.556 B | 26 | 15,150 |
| batch-003 | The Stack, shards 6–11 | 524,964 | 2.547 B | 85 | 15,047 |
| batch-004 | The Stack, shards 12–17 | 525,064 | 2.563 B | 125 | 14,907 |
| batch-005 | The Stack, shards 18–23 | 524,874 | 2.598 B | 173 | 15,049 |
| batch-006 | The Stack, shards 24–29 | 524,948 | 2.564 B | 198 | 14,950 |

The token figure is an estimate from a clean held-out set: the frozen tokenizer
`pythia-bpe-32k-v2` encodes `.tokenizer/holdout.jsonl` (8,721 records, 25.1 M
chars, disjoint from the tokenizer sample) at **3.689 chars/token**, so 13.17 B
chars is **~3.57 B tokens**; the q1 quality filter will lower it, and the exact
figure comes from `tokenize_corpus finalize`. (The earlier 3.687 for v0 was
measured on `holdout.txt`, which is contained in the training sample, so it was
inflated; v1 measures 3.323 on the clean set.) Dedup against earlier batches is low
(26–198 records) because The Stack is already deduplicated and each chunk sees
distinct shards.

## How training consumes this

```python
registry = json.load(open("REGISTRY.json"))
for batch in registry["batches"]:            # registry order == training order
    for shard in batch["shards"]:
        assert sha256(shard["rel"]) == shard["sha256"]   # verify once
        for line in open(shard["rel"]):
            record = json.loads(line)        # {"text": str, "meta": {...}}
```

## Remaining gate before tokens

Batches are tokenizer-agnostic text with a fixed schema, deliberately: the
tokenizer should be trained on the *accumulated* corpus, not on batch-001.
The last step is therefore one command that trains a 32 K BPE over the union
and streams `{"input_ids": uint16}` shards. No part of the batch layout changes
when that lands — the answer to "can training start" is "after one tokenize
pass", not "after re-collecting data".

## Canonical selection

`scripts/corpus/canonical.py` is the only answer to "which files are the
corpus". Adding a fifth prose run to `stage1/` no longer changes anything until
this file changes.

Two files are deliberately excluded despite being present: `thinkpython`
(CC-BY-NC-SA) and `atbs` (CC-BY-NC) are non-commercial. They are archived, not
corpus.

## License policy

The decision comes from the license value. The upstream `license_status` field
(`APPROVED`, `LICENSE_APPROVED_FOR_INTENDED_USE`) is recorded but never trusted.

| Decision | Examples | Enters corpus |
|---|---|---|
| ALLOW | CC0-1.0, MIT, BSD-2/3, Apache-2.0, PSF-2.0, CC-BY-4.0 | yes, attribution noted |
| HOLD | UNKNOWN, CLEAR, RESTRICTED_OR_REVIEW, GPL, CC-BY-SA, WTFPL | no |
| DENY | CC-BY-NC, CC-BY-NC-SA | no |

`CC-BY-4.0` and the permissive code licenses require attribution; the count is
in `totals.attribution_required`.

## Snapshot `corpus-v1-20261110`

`final/corpus-v1-20261110.jsonl` — 516 MB, 322,507 records, one JSON object per
line: `{"text": ..., "meta": {record_id, source, license_spdx, normalized_sha256, …}}`.

| source | records | kept | chars | dropped |
|---|---:|---:|---:|---:|
| peps | 9,588 | 9,539 | 11,911,243 | 49 exact duplicates |
| devguide | 402 | 402 | 509,894 | — |
| python_docs | 96 | 83 | 1,546 | 13 duplicates |
| scientific_docs (numpy/scipy/pandas) | 441 | 441 | 184,273 | — |
| codesearchnet full-v3 | 312,723 | 312,042 | 330,928,362 | 681 license HOLD |
| codesearchnet pilot-v1 | 4,212 | 0 | 0 | **all 4,212 were duplicates of full-v3** |
| jupyter stage3 | 73 | 0 | 0 | **records contain no code text** |
| **total** | **327,535** | **322,507** | **343,535,318** | |

Deduplicated: 4,274 (4,212 across sources). Parse errors: 0. Text missing: 73.

### Token honesty

- 343.5 M characters
- 33.3 M whitespace-split tokens (`build` total)
- 85.9 M if you divide characters by 4

The old reports' "82.85 M tokens" is the last number — characters ÷ 4, not a
tokenizer. Against the configured 4 B target the corpus is **~2–3 %**, and the
real figure will only be known once a BPE tokenizer exists.

## Open decisions

1. **WTFPL** — 681 CodeSearchNet records held because the license is not in the
   allowlist. It is permissive; add it in `license.py` or leave it out.
2. **Jupyter** — 73 stage-3 records carry 50 metadata keys and no code. Either
   re-extract from the notebooks in `raw/jupyter/` or drop stage 3.
3. **`codesearchnet_pilot-v1`** — 100 % redundant. Quarantine it on the
   archive like the local reruns.
4. **Raw archives** — `raw/scientific_docs`, `raw/peps`, `raw/python_docs` and
   `raw/devguide` still exist only on local disk. Push them, or record that the
   pinned URLs are the source of truth.
5. **Stale monolith** — `final/corpus-v1-20261110.jsonl` (516 MB) is now
   duplicated by `batch-001`. Keep it as provenance or delete it; training
   should read batches only.

## Local changes (2026-11-10)

`data/archive/` (gitignored, never deleted) — see `ARCHIVE_MANIFEST.json`:

- `stage1-superseded/` — 12 files, 251 MB: four 2026-10-22 prose runs and
  `license-gated-v1`, all superseded by v2.
- `stage1-license-excluded/` — atbs, thinkpython (non-commercial).
- `stray-github-clones/` — 866 MB / 16 repos that a path bug had written into
  `scripts/data/raw/`. Reconstructible from `manifests/github_candidates_v1.jsonl`.
