# PYTHIA-160M — Scientific Python Documentation — License-First Audit + Pilot

Workstream: **official scientific Python documentation** (Stage 1 extension). License-first audit completed;
small pilot acquired from approved sources only.

- Final status: **`READY_FOR_NEXT_ACQUISITION_STAGE`**
- Technical readiness: `READY_FOR_SCALE_UP` (audit + pipeline + pilot validated); scale-up to all three approved sources completed.
- Legal readiness: acquired sources are BSD-3-Clause with recorded evidence; Matplotlib held pending an acquisition-mechanism decision.

---

## 1. License-first audit (source-by-source)

| Project | Doc license | Decision | Immutable archive | Version |
|---|---|---|---|---|
| NumPy | BSD-3-Clause | **ACCEPT** | `numpy-html.zip` | 2.5 |
| SciPy | BSD-3-Clause | **ACCEPT** | `scipy-html-1.18.0.zip` | 1.18.0 |
| pandas | BSD-3-Clause | **ACCEPT** | `pandas.zip` | 2.3.3 |
| Matplotlib | Matplotlib (PSF-derived) | **HOLD** | none (PDF only) | 3.11.2 |

License evidence (documentation content, not just the repo):
- **NumPy** — docs license page carries the full BSD 3-Clause text (`https://numpy.org/doc/stable/license.html`).
- **SciPy** — developer guide: "All code, **documentation** and other files added to SciPy by contributors is licensed under [the 3-clause BSD] license."
- **pandas** — docs describe the project as "an open source, BSD-licensed library"; overview page carries the BSD 3-Clause text.
- **Matplotlib** — license is PSF-based and explicitly covers "associated documentation," but no immutable HTML archive is published (PDF only), so acquisition is deferred pending a mechanism decision.

Assessed **training / dataset redistribution / model-weight release** separately. A license permitting one does not settle the others; BSD-3-Clause and the Matplotlib/PSF license are permissive on all three, but the Matplotlib acquisition path remains undecided.

## 2. Acquisition results (all three approved sources)

| Source | Version | Archive bytes | Blocks examined | AST-valid | Retained |
|---|---|---:|---:|---:|---:|
| NumPy | 2.5 | 36,455,676 | 4,736 | 3,265 | **99** |
| SciPy | 1.18.0 | 76,758,514 | 7,779 | 5,940 | **301** |
| pandas | 2.3.3 | 40,509,391 | 8,973 | 3,824 | **41** |
| **Total** | | 153,723,581 | **21,488** | 13,029 | **441** |

Filter outcomes:
- **NumPy:** 2,628 too short, 1,063 exact duplicates, 516 low documentation, 408 syntax invalid, 22 PEP8-rejected, 99 retained.
- **SciPy:** 4,227 too short, 1,132 exact duplicates, 1,385 low documentation, 707 syntax invalid, 27 PEP8-rejected, 301 retained.
- **pandas:** 3,149 too short, 2,461 exact duplicates, 620 low documentation, 2,688 syntax invalid, 14 PEP8-rejected, 41 retained.

Filter thresholds reused from `config.py` (`MIN_TOKEN_LENGTH=50`, `MAX_TOKEN_LENGTH=2048`, `MIN_COMMENT_RATIO=0.1`, `PEP8_MAX_VIOLATIONS=5`).

## 3. Artifacts

- Raw archives + manifests: `data/raw/scientific_docs/{numpy_docs__2.5,scipy_docs__1.18.0,pandas_docs__2.3.3}/` (local, alongside the existing `data/raw/python_docs/`)
- Stage 1 output:
  - `data/filtered/stage1/scientific_docs_scidocs-20261022T053610Z-ea912df1_numpy_docs.jsonl` (99)
  - `data/filtered/stage1/scientific_docs_scidocs-20261022T063330Z-29c8f7b5_scipy_docs.jsonl` (301)
  - `data/filtered/stage1/scientific_docs_scidocs-20261022T064353Z-91b4855a_pandas_docs.jsonl` (41)
- Run reports: `data/raw/scientific_docs/reports/{scidocs-20261022T053610Z-ea912df1,scidocs-20261022T063330Z-29c8f7b5,scidocs-20261022T064353Z-91b4855a}/`
- Reports: `research/results/data/scientific_docs_license_audit_v1.json`, `research/results/data/scientific_docs_acquisition_summary_v1.json`

## 4. Implementation and tests

- New module: `scripts/scrapers/scientific_docs.py` (pinned download with SHA-256 + last-modified + refuse-overwrite; Sphinx/PyData code-block extraction; reuses the authoritative `validate_python`, the in-memory `pycodestyle` checker, and token-count helpers from `scripts.scrapers.python_docs`).
- New tests: `tests/test_scientific_docs.py` — **15/15 pass** (inventory decisions, python/default/pycon/bash detection, extraction without duplicate `<pre>` matches, retention + schema, refuse-overwrite, dry-run with no network/no write).
- No downloaded code was executed.

Full existing suite (context from prior step): `331 passed, 5 failed, 1 skipped` — the 5 failures are pre-existing and unrelated (PyPI/path-config tests).

## 5. Provenance and integrity

- Raw archive bytes preserved exactly; each SHA-256 verified against its manifest:
  - NumPy `42fe2b5d…a15bb`
  - SciPy `104a6fb2…3c4400`
  - pandas `851b0af5…02ae91`
- Records carry `source`, `documentation_version`, `license`, `license_spdx`, `license_url`, `source_url`, `exact_hash`, AST metadata, PEP8, comment ratio, and provisional token count.
- No existing artifact was overwritten (versioned directories + refuse-overwrite).

## 6. Next recommended actions

1. Decide the Matplotlib acquisition mechanism (source-repo `examples/` at a tagged release, or the PDF) before promoting it off HOLD.
2. Individually review **Automate the Boring Stuff** and **Composing Programs** for the foundation sources.
3. Keep Stack Overflow / CodeSearchNet on HOLD until licensing/provenance checks pass.
4. Optionally expand the scientific-docs corpus (e.g. scikit-learn, SymPy) under the same Accept/Hold/Reject policy.
