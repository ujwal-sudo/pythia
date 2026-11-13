# Session 6 — Structure-Preserving Prose + Code Documentation Pilot

**Date:** 2026-10-22
**Status:** COMPLETE — pilot artifacts ready for review; not yet promoted to `data/final/`.
**Scope:** Implement a prose-plus-code extractor and run it on two CC0-1.0 sources
(PEPs, CPython Developer's Guide) without touching the active CodeSearchNet
`full-v3` or PyPI `remediation_v2` workstreams.

## 1. Objective

The corpus is code-heavy (CodeSearchNet `full-v3`: 312,723 accepted records /
82,854,131 provisional tokens) and prose-poor (Stage 1: 992 records / 53,764
tokens). The existing docs pipeline kept code blocks and discarded the narrative
that explains them. This pilot builds **training-ready explanatory records** that
keep each code example attached to the prose that introduces it.

## 2. Extractor design (`scripts/scrapers/prose_docs.py`)

- **Structure preserved.** A document is split into ordered `prose`/`code`
  segments. Nothing is flattened: records carry `section_path` (heading
  hierarchy), `document_*` identity, and the exact source revision.
- **Code stays attached.** Segments are serialized in reading order into
  `content` (Markdown) and the structured `segments` array. Literal blocks
  (`::`), `code-block`/`code`/`sourcecode`/`parsed-literal`, `doctest`, and code
  nested in `tab`/`tab-item`/admonition containers are all retained.
- **Safe.** Python examples are only AST-parsed with the authoritative
  `validate_python`; nothing is executed. `SyntaxWarning` noise from examples is
  suppressed without changing validation results.
- **No overwrites.** Stage 1 files and report directories use a versioned run id
  and fail if the destination exists. Acquisition reuses an existing clone
  read-only and never rewrites its manifest.
- **Clean text.** Inline RST roles/markup and footnote references are reduced to
  plain text; wrapped paragraph lines are reflowed; list/table line structure is
  preserved; heading reference suffixes (`Git_`) are cleaned; PEP header
  metadata (including author e-mail fields) is removed from `Preamble` records
  while genuine preamble prose is kept.
- **Filters.** Sections need ≥ 20 prose tokens and ≥ 40 total tokens; records are
  split at 2,048 tokens (whole segments only) with `part`/`part_count`.
- **Sources.** Both sources are `CC0-1.0`; acquisition is a shallow, commit-pinned
  clone of the official repository.

## 3. Acquisition provenance

| Source | Repo | Ref | Commit | License |
|---|---|---|---|---|
| `peps` | `https://github.com/python/peps` | `main` | `3b0eaa2021d57747ab83b9356eefe597c5745dde` | CC0-1.0 |
| `cpython_devguide` | `https://github.com/python/devguide` | `main` | `ff9af798f7c216406da7699a46ac6b9052711745` | CC0-1.0 |

- Raw clones: `data/raw/peps/repo` (28 MB), `data/raw/devguide/repo` (3.1 MB).
- Manifests: `data/raw/peps/ACQUISITION_MANIFEST.json`,
  `data/raw/devguide/ACQUISITION_MANIFEST.json` (created once, never overwritten).

## 4. Run

**Final run id:** `prose-20261022T100121Z-f5fc9a3b`

```
python -m scripts.scrapers.prose_docs --sources peps cpython_devguide
```

Earlier in-session runs were development iterations:
`prose-20261022T095336Z-f5fc9a3b` (first pass), `prose-20261022T095601Z-f5fc9a3b`
(prose reflow + preamble cleanup), `prose-20261022T095715Z-f5fc9a3b` (warning
suppression). They are retained as evidence; **only the final run should be
consumed.** The final run differs from the previous run only by footnote-reference
removal (one PEP section fell below threshold).

### Results

| Metric | PEPs | Devguide | Total |
|---|---:|---:|---:|
| Documents examined | 745 | 63 | 808 |
| Documents with records | 740 | 49 | 789 |
| Sections seen | 14,521 | 538 | 15,059 |
| Rejected: no prose | 1,611 | 36 | 1,647 |
| Rejected: too short | 1,425 | 68 | 1,493 |
| Within-document duplicates | 0 | 0 | 0 |
| **Records retained** | **9,838** | **402** | **10,240** |
| Code blocks | 6,131 | 411 | 6,542 |
| AST-valid Python blocks | 2,984 | 10 | 2,994 |
| AST-invalid Python blocks | 145 | 1 | 146 |
| Records with code | 2,836 | 119 | 2,955 |
| Prose tokens | 1,608,939 | 66,801 | 1,675,740 |
| Code tokens | 201,121 | 5,068 | 206,189 |
| **Provisional tokens** | **1,810,060** | **71,869** | **1,881,929** |

The invalid Python blocks are documentation fragments (snippets, pseudo-code,
deliberately incomplete examples); they are retained as `text`-adjacent content
only when the source declared them Python, and are flagged `syntax_valid=false`.

### Outputs

| File | Records | Bytes | SHA-256 |
|---|---:|---:|---|
| `data/filtered/stage1/prose_docs_prose-20261022T100121Z-f5fc9a3b_peps.jsonl` | 9,838 | 48,460,837 | `ad3c63565b0b95233806e11c87849ad62ec11aae20564b8127da86e39662fcda` |
| `data/filtered/stage1/prose_docs_prose-20261022T100121Z-f5fc9a3b_cpython_devguide.jsonl` | 402 | 2,050,105 | `3ed29176bd2205bf6ee5bfefadae05a45d93c3b5f7325992f1a0682d88452549` |

Reports: `data/raw/prose_docs/reports/prose-20261022T100121Z-f5fc9a3b/`
(`report.json`, `source_inventory.json`, `acquisition_manifests.json`).
Machine-readable summary: `research/results/data/prose_docs_pilot_summary_v1.json`.

## 5. Validation performed

- 29/29 unit tests pass (`tests/test_prose_docs.py`), covering heading
  hierarchy, prose/code ordering, literal blocks, directives, doctest, nested
  tabs, admonition/version labels, include resolution (relative, absolute,
  cycles), footnote/markup cleanup, list-preserving reflow, filters, splitting,
  dedupe, discovery/exclusions, manifest refuse-overwrite, dry-run, end-to-end
  writes, and non-ACCEPT rejection.
- Every record has non-empty ordered segments; every code block kept in the same
  record as its introducing prose.
- All record ids unique within each output; 0 within-document duplicates.
- `part`/`part_count` used for 4 long PEP sections; maximum record is 2,025
  tokens (cap 2,048, whole-segment granularity).
- No code executed; removal of prose before token accounting is the only
  content-affecting change from the previous run.
- 49 PEP records repeat an earlier `exact_hash` **across documents** (identical
  governance/policy text, e.g. PEP 13 vs PEP 8016). They are kept because each
  carries distinct `document_id` provenance; a corpus-wide dedupe policy is still
  required at assembly time.
- No writes outside `data/raw/peps/`, `data/raw/devguide/`,
  `data/raw/prose_docs/`, and `data/filtered/stage1/prose_docs_*.jsonl`.

## 6. Sample record (PEP 8, `Code Lay-out > Indentation`)

`content` preserves the explanation, then the fenced example:

````markdown
## Code Lay-out > Indentation

Use 4 spaces per indentation level.

Continuation lines should align wrapped elements ...

```python
# Correct:
foo = long_function_name(var_one, var_two,
                         var_three, var_four)
...
```
````

Segments: `prose → code → prose → code ...`; 418 provisional tokens; 6 code
blocks; AST-valid.

## 7. Limitations / open items

- Not promoted: `data/final/corpus.jsonl` remains empty by design.
- Cross-document duplicate policy (exact-hash) is unresolved.
- Headings/roles are handled with a lightweight custom RST parser (no
  `docutils`/Sphinx dependency); unusual constructs fall back to prose.
- Code language for unnamed literal blocks is inferred (AST-valid → `python`,
  otherwise `text`); explicitly declared languages are trusted.
- Untracked `scripts/scrapers/prose_plus_code.py` + `tests/test_prose_plus_code.py`
  appeared concurrently in the working tree; they were **not** modified or used.
  A decision is needed on which extractor is canonical before scale-up.

## 8. Recommended next steps

1. Resolve the extractor fork (`prose_docs.py` vs concurrent `prose_plus_code.py`)
   and adopt one canonical implementation.
2. Approve a corpus-wide exact-hash dedupe policy for repeated boilerplate.
3. Scale to the remaining approved prose sources: scikit-learn 1.9.1 (BSD-3),
   SymPy 1.14.0 (BSD-3), packaging guide (CC BY-SA 3.0), A Byte of Python
   (CC BY-SA 4.0). Keep Composing Programs (CC BY-NC-SA 4.0) on hold and keep
   Think Python / ATBS promotion held for non-commercial terms.
4. Run promotion/assembly only after the above and after CodeSearchNet/PyPI runs
   are finalized.
