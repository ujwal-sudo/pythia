# Where the next 4 billion tokens come from

Current corpus: **322,507 records / 343.5 M chars ≈ 33 M whitespace tokens**
(≈ 90–100 M real BPE tokens). Target: **4 B tokens**. We are ~2.5 % of the way,
so this is a sourcing problem, not a cleaning problem.

Sizes below are measured from the Hugging Face API on 2026-11-13 unless marked
*estimate*. Every "tokens" figure is a range: bytes → chars → tokens for Python
is not exact until the tokenizer exists.

## The constraint that shapes everything

| Resource | Available |
|---|---|
| Google Drive (`pythia:`) | **4.86 TiB free** |
| Local disk | **7.9 GB free** (88 % full) |

So ingestion must stream: download a shard → filter → write to the archive →
delete the local copy. Nothing may be materialised in full on this laptop.

## Tier 1 — the backbone (one click needed)

Both are **gated=auto**: downloading requires accepting the dataset terms on the
HF page once, with the account that owns the token in `.env`
(`kn1ghtofzero`). I cannot accept a licence on your behalf — that is your click.

| Source | Python size | Licence | Est. tokens |
|---|---|---|---|
| [`bigcode/the-stack-dedup`](https://huggingface.co/datasets/bigcode/the-stack-dedup) `data/python` | **28.6 GB**, 144 parquet | permissive-only by construction + per-file `licenses.json` | 8–15 B |
| [`bigcode/starcoderdata`](https://huggingface.co/datasets/bigcode/starcoderdata) `python` | **23.2 GB**, 59 parquet | permissive-only + StarCoder quality filters | 7–12 B |

Either one alone covers the 4 B target four times over. They are whole **files**,
which is the bigger win: the current corpus is 97 % single-function
CodeSearchNet snippets with no module context.

Status right now: `403` on download until the terms are accepted.

## Tier 2 — independent, no gate, start today

| Source | Size | Licence | Why |
|---|---|---|---|
| [`codeparrot/codeparrot-clean`](https://huggingface.co/datasets/codeparrot/codeparrot-clean) | **34.3 GB**, 5.36 M files | per-file `license` field → filter with our policy | verified downloadable today (first shard 246 MB) |
| PyPI sdists, top 20 k packages | *est.* 15–30 GB | per-package metadata, mostly MIT/BSD/Apache | real packaging, setup.py, CLI, tests — a distribution CodeSearchNet doesn't have |
| CPython stdlib + `Lib/test` + `typeshed` | ~300 MB | PSF-2.0 / Apache-2.0 | canonical style, 100 % clean licence, test-heavy |
| Read the Docs / Sphinx `docs/` sources | *est.* 2–5 GB | per-project, mostly permissive | prose + code blocks, the "explanation" signal |
| [Exercism python](https://github.com/exercism/python) | ~50 MB | MIT | exercise + exemplar solutions, high pedagogical density |
| [TheAlgorithms/Python](https://github.com/TheAlgorithms/Python) | ~10 MB | MIT | textbook-style algorithms, heavily commented |

## Tier 3 — collect now, use for SFT/repair later

| Source | Size | Licence | Use |
|---|---|---|---|
| [`bigcode/commitpackft`](https://huggingface.co/datasets/bigcode/commitpackft) | 1.6 GB data | permissive repos | commit → patch pairs, repair training |
| [`nvidia/OpenCodeReasoning`](https://huggingface.co/datasets/nvidia/OpenCodeReasoning) | 13.3 GB | CC-BY-4.0 | Python solutions with reasoning traces |
| [`google-deepmind/code_contests`](https://huggingface.co/datasets/google-deepmind/code_contests) | small | Apache-2.0 | competitive programming, eval-safe |

## Held or excluded — and why

- **The Stack v2 (Python, 13.9 GB)**: metadata only (`blob_id`); content lives on
  S3 behind requester-pays. Not worth the plumbing while v1 dedup exists.
- **Stack Exchange dump**: CC-BY-SA — share-alike on the corpus. Policy says HOLD.
- **Raw GitHub scraping**: no per-file licence metadata. The Stack already did
  this correctly; re-scraping would be worse and slower.
- **Think Python / Automate the Boring Stuff**: non-commercial, already archived.
- **MBPP / HumanEval / BigCodeBench**: evaluation sets. Training on them
  contaminates every later number. Keep them out of the corpus permanently.
- **Rosetta Code, A Byte of Python, Dive Into Python**: CC-BY-SA — HOLD for now.

## Diversity target (this matters more than volume)

At 4 B tokens the failure mode is not "too little data", it is "one source ate
the corpus". Current mix is 96.7 % CodeSearchNet. Proposed budget:

| Slice | Share | Tokens |
|---|---|---|
| file-level code (Stack / CodeParrot) | 55 % | 2.2 B |
| function-level code (CodeSearchNet) | 15 % | 0.6 B |
| docs + prose (PEPs, Sphinx, tutorials) | 20 % | 0.8 B |
| tests + packaging (PyPI, stdlib tests) | 5 % | 0.2 B |
| educational (Exercism, algorithms) | 5 % | 0.2 B |

Cap any single source at ~1.5 B tokens so the mix survives sampling.

## Week plan

| Day | Work | Output |
|---|---|---|
| 1 | Accept terms (you) → install `pyarrow` into the repo's 3.12 env → build streaming HF-parquet ingest → 1 % sample run | `batch-002` sample, pipeline validated |
| 2 | Full `the-stack-dedup` python ingest (28.6 GB streamed) | `batch-002`, ~10 B raw tokens |
| 3 | `codeparrot-clean` + PyPI top 20 k | `batch-003`, `batch-004` |
| 4 | Docs/prose wave (Read the Docs, stdlib/tests, Exercism, algorithms) | `batch-005` |
| 5 | Diversity rebalance, dedup audit, freeze `corpus-v2`, report | training-ready text corpus |

## Two things only you can do

1. **Accept the terms** on `bigcode/the-stack-dedup` and `bigcode/starcoderdata`
   (one click each, same account as the token). Until then I start on Tier 2.
2. **Confirm the licence stance on share-alike**: CC-BY-SA sources (Stack
   Exchange, Rosetta Code, Dive Into Python) stay excluded unless you say
   otherwise. That decision changes how much prose we can add.
