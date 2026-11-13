# Diversity plan — closing the prose gap

## Where we are

| Slice | Chars | Share |
|---|---:|---:|
| File-level code (The Stack) | 12.83 B | 97.4 % |
| Everything else (CodeSearchNet, PEPs, devguide, scientific docs, Python docs) | 0.34 B | 2.6 % |
| **Total** | **13.17 B** | 100 % |

The volume target (4 B tokens) is met. The mix is not: a Python model trained
on this will write code but will be weak at explaining it, following
instructions, or reasoning about a problem before writing the solution.

## Target mix (v2 ≈ 20 B chars ≈ 6 B tokens)

| Slice | Target | Chars to add |
|---|---:|---:|
| File-level code | 60 % | 0 (Stack covers it) |
| Docs + prose | 20 % | +3.7 B |
| Tests + packaging | 5 % | +0.7 B |
| Educational / Q&A / repair | 8 % | +1.6 B |
| General text + reasoning | 7 % | +1.4 B |

20 B chars ≈ 6 B tokens, or ~37 tokens per parameter for a 160 M model —
comfortably past compute-optimal, which is what you want if "more doesn't hurt".

## Sources, by batch

### batch-007 — docs and prose (~3.4 B chars) ← the important one

| Source | Est. chars | Licence | Access |
|---|---:|---|---|
| Read the Docs, top ~1 000 Python projects (`docs/` from each repo) | 2.5 B | per project, mostly MIT/BSD/PSF | RTD API + git |
| PyPI `long_description` / README for top 20 k packages | 0.8 B | per package | PyPI JSON API |
| CPython `Doc/` (tutorial, library, C API, howto) | 0.1 B | PSF-2.0 | git |

This is the single highest-value wave: explanatory prose interleaved with code
blocks is exactly what teaches "explain this function".

### batch-008 — tests and packaging (~0.7 B chars)

| Source | Est. chars | Licence |
|---|---:|---|
| `tests/` directories from PyPI top 20 k sdists | 0.5 B | per package |
| CPython `Lib/test` | 0.08 B | PSF-2.0 |
| typeshed | 0.03 B | Apache-2.0 |

Tests teach assertions, fixtures and edge cases — a distinct distribution from
application code.

### batch-009 — educational / repair (~1.6 B chars)

| Source | Est. chars | Licence | Use |
|---|---:|---|---|
| CommitPackFT (permissive repos) | 0.4 B | permissive | repair / edit pairs |
| NVIDIA OpenCodeReasoning | 1.0 B | CC-BY-4.0 | reasoning traces |
| Exercism + TheAlgorithms + CodeContests | 0.1 B | MIT / Apache | pedagogy |

CommitPackFT and OpenCodeReasoning are SFT-leaning; keep them in separate
batches so pretraining can exclude or down-weight them.

### batch-010 — general text (~1.4 B chars)

| Source | Est. chars | Licence |
|---|---:|---|
| FineWeb-Edu sample | 1.2 B | ODC-By |
| OpenWebMath | 0.2 B | Apache-2.0 |

Enough general English to keep the model literate without turning it into a
general-purpose model.

## Held back until you decide

- **Stack Exchange Python dump** (~1.5 B chars): CC-BY-SA 4.0. Share-alike is
  the question, not availability.
- **A Byte of Python, Dive Into Python, Rosetta Code**: CC-BY-SA, small but good.
- **Think Python / ATBS**: non-commercial, already archived.

If you accept share-alike for a *research* corpus, Stack Exchange alone covers
most of the remaining prose gap and is cleaner than crawling 1 000 doc sites.

## Order of work

1. **batch-007 docs** — biggest quality gain per byte.
2. **batch-008 tests** — cheap, reuses the PyPI crawl.
3. **batch-009 educational** — needed for the SFT stage.
4. **batch-010 general** — last; it is the least Python-specific.

## Tokenizer interaction

The BPE is being trained now on a sample weighted 20 % prose — more than the
current corpus share — so English subwords are already covered. If docs push
prose above ~25 % of the corpus, retraining the tokenizer costs ~30 minutes and
a re-tokenisation pass; otherwise the existing vocab is fine.

## What this changes for training

- Pretraining (stage A): batches 001–008, minus the SFT-leaning ones.
- SFT (stage B): batch-009 (CommitPackFT, OpenCodeReasoning, Exercism).
- Stage C (neurosymbolic): unchanged by data work.

Keeping these as separate batches is the point of the batch design: the
training recipe chooses batches, so no re-cleaning is needed when the mix
changes.
