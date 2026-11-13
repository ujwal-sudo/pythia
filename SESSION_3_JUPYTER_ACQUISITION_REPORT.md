# PYTHIA-160M — Jupyter Notebook Acquisition — Final Report

Workstream: **Jupyter notebook acquisition** (Stage 3). This workstream is complete
for all approved sources. Two discovery candidates were deferred and were **not**
promoted into the corpus.

- Final status: **`READY_FOR_NEXT_ACQUISITION_STAGE`**
- Technical readiness: `READY_FOR_SCALE_UP` (full approved inventory acquired + validated)
- Legal readiness: approved sources are permissively licensed; deferred sources remain `LICENSE_REVIEW_REQUIRED`

---

## 1. Headline results

| Metric | Value |
|---|---:|
| Raw notebooks acquired | **178** |
| Eligible (Stage 3 filtered) | **73** |
| Rejected | **105** |
| Total source bytes | 2,682,422 |
| Provisional token estimate | 218,838 (`char_count // 4`) |
| Sources acquired | 3 |
| Sources rejected / deferred | 2 |

## 2. Sources and go/no-go decisions

| Source | License | Decision | Raw notebooks | Stage 3 eligible |
|---|---|---|---:|---:|
| `jdhp-docs/notebooks` | MIT | **GO** | 154 | 59 |
| `COGS108/Tutorials` | CC-BY-4.0 (attribution required) | **GO** | 22 | 13 |
| `jupyter-guide/jupyter-guide` | MIT | **GO** | 2 | 1 |
| `codebasics/py` | **none** | NO-GO | (114 available) | 0 |
| `jupyter-agent/jupyter-agent-dataset` | Apache-2.0 (synthetic) | NO-GO | (not .ipynb) | 0 |

Deferred reasons:
- `codebasics/py` — no repository license present; default copyright applies. Not acquired.
- `jupyter-agent/jupyter-agent-dataset` — Parquet, machine-generated/synthetic QA pairs
  derived from Kaggle notebooks; not `.ipynb` documents and not authored notebooks. Not acquired.

## 3. Immutable provenance (captured)

| Source | Revision (immutable) |
|---|---|
| `jdhp-docs/notebooks` | git commit `7f375ebea5933b82d1b8e8965e4ea0f2efa3045d` |
| `COGS108/Tutorials` | git commit `d79b6169a34ad6fff2c96d4a872801182b4ff419` |
| `jupyter-guide/jupyter-guide` | git commit `18813d2aa64bdba3382087842f28a81832e7518a` |
| `codebasics/py` (deferred) | `3ee4bde332ae7a10499c2679900094fa22ae191f` |
| `jupyter-agent/jupyter-agent-dataset` (deferred) | HF revision `10a8dd461bb6c580fa25b83cd3b2f6810f1d6385` |

License files were captured and hashed for every acquired source:
- `jdhp-docs/notebooks` → `LICENSE` (MIT, sha256 `13f2f44c…830`)
- `COGS108/Tutorials` → `LICENSE.txt` (CC-BY-4.0, sha256 `9ba9550a…411`)
- `jupyter-guide/jupyter-guide` → `LICENSE` (MIT)

## 4. Artifact locations

Authoritative data root: `/mnt/pythia-cloud/PythiaDrive`

- Raw notebooks: `/mnt/pythia-cloud/PythiaDrive/raw/jupyter/github/<source>__<commit>/` (original bytes preserved exactly)
- Filtered Stage 3 outputs:
  - `/mnt/pythia-cloud/PythiaDrive/filtered/stage3/jupyter_stage3_v1_jupyter-20261022T052005Z-98b816b5.jsonl` (pilot, 59 records)
  - `/mnt/pythia-cloud/PythiaDrive/filtered/stage3/jupyter_stage3_v1_jupyter-20261022T052157Z-e17930e2.jsonl` (scale-up, 14 records)
- Run directories (manifest, quality metrics, rejection report, duplicate report, inventory):
  - `/mnt/pythia-cloud/PythiaDrive/processed/jupyter/jupyter-20261022T052005Z-98b816b5/`
  - `/mnt/pythia-cloud/PythiaDrive/processed/jupyter/jupyter-20261022T052157Z-e17930e2/`
- Research records (this repo):
  - `research/results/data/jupyter_source_inventory_v1.json`
  - `research/results/data/jupyter_license_review_v1.json`
  - `research/results/data/jupyter_acquisition_summary_v1.json`

## 5. Selection policy applied

Eligibility requires, for every notebook:
1. Parses as a valid `.ipynb` JSON document (`nbformat >= 4`, `cells` list).
2. Markdown proportion `markdown_cells / total_cells` **strictly greater than 0.40**.
3. Contains meaningful Python (not merely imports / placeholders / empty cells / boilerplate).
4. Non-zero cell count.

Rejection reasons observed (105 notebooks, 116 reasons):
- `markdown_proportion_not_gt_0.4` — 63
- `no_meaningful_python` — 53

## 6. Quality metrics produced (per notebook)

For every acquired notebook: markdown/code/raw/total cell counts, markdown proportion,
AST-valid/invalid cell counts (authoritative `scripts.validators.ast_validator.validate_python`,
per-cell, never concatenated into a fake script), IPython magic/shell separation, real
PEP8 violations (pycodestyle), comment/docstring lines, provisional token estimate
(`char_count // 4`), subject category, output-size inspection, secret screen, and
rejection reasons. Static analysis only — **no cell was ever executed**.

Subject distribution (eligible):
`python_fundamentals` 22, `numpy_pandas_scientific` 17, `statistics_visualization` 11,
`uncategorized` 11, `reproducible_research_advanced` 4, `machine_learning_deep_learning` 4,
`data_engineering_analysis` 3, `algorithms_data_structures` 1.

## 7. Deduplication (audit-first, non-destructive)

- Exact SHA-256 duplicates: 6 groups / 23 records
- Normalized-content duplicates: 4 groups / 24 records
- Same path+revision duplicates: 0
- Destructive deduplication performed: **false** (no raw artifacts deleted)

Near-duplicate similarity was not resolved in this workstream; exact and
normalized-content duplicates are reported as evidence.

## 8. Tests

New automated tests (synthetic fixtures only, no execution, no network):

- `tests/test_notebook_policy.py` — parsing, markdown-proportion boundary (exactly 40%
  is ineligible), zero-cell/empty notebooks, meaningful-Python vs import-only, magics,
  classification, secrets, outputs, deterministic hashes, eligibility.
- `tests/test_jupyter_acquire.py` — evaluation, duplicate audit, write-refusal, count
  reconciliation, Stage 3 output, report generation, refuse-to-overwrite run directory.

Result: **47/47 passed** (`python -m pytest tests/test_notebook_policy.py tests/test_jupyter_acquire.py`).

Full existing suite: `331 passed, 5 failed, 1 skipped`. The 5 failures are pre-existing
and unrelated to this workstream (PyPI/path-config tests: `test_path_config.py::test_with_pythia_data_root_cloud`
and 4 in `test_pypi_remote_wiring.py`, all tied to the already-modified `pypi_storage.py` /
`PYTHIA_DATA_ROOT` mount-path convention).

## 9. Reproducibility

- Every run records `run_id`, UTC timestamp, pipeline version (`1.0.0`), schema version
  (`jupyter.stage3.v1`), source revisions, output SHA-256 hashes, counts, filtering rules,
  token-estimation method, license status, dependency versions, and git metadata.
- Raw artifacts are versioned by immutable commit; a destination that already exists is
  refused (never overwritten).
- Notebook source bytes are preserved exactly (verified: raw file SHA-256 equals the
  manifest entry).

## 10. Git changes (this workstream)

New files (untracked):
- `scripts/processors/notebook_policy.py`
- `scripts/scrapers/jupyter_acquire.py`
- `tests/test_notebook_policy.py`
- `tests/test_jupyter_acquire.py`
- `research/results/data/jupyter_source_inventory_v1.json`
- `research/results/data/jupyter_license_review_v1.json`
- `research/results/data/jupyter_acquisition_summary_v1.json`

Pre-existing modified/untracked files (PyPI, Stack Overflow, `models/`, `grep`, etc.)
were left untouched.

## 11. Next recommended action

The notebook acquisition workstream is complete for all approved sources. Recommended next
steps, in order:
1. Decide (with legal review) whether `codebasics/py` can be licensed; it is the largest
   untapped notebook source (~114 notebooks) but has no license today.
2. Treat `jupyter-agent/jupyter-agent-dataset` as a separate synthetic/agent-training
   workstream, not notebook acquisition.
3. Proceed to the next unrelated acquisition family (e.g. The Stack / CodeSearchNet) as a
   separate workstream — not started here.
