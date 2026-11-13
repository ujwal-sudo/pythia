# Source Discovery & Corpus Reconciliation — 2026-10-22

Workstream: Pythia-160M data acquisition (license-first discovery).
Status: **DISCOVERY / REPORT ONLY.** No acquisition started; active workstreams left untouched.

---

## 0. Why this report exists

Reconcile what the corpus actually contains, identify the highest-value *missing* source family,
and queue candidates without overlapping the acquisitions currently in flight. The pipeline rule
stands: **acquire → verify → document → only then promote** into the training corpus.

Active workstreams observed at report time (do **not** start overlapping work):

| Workstream | State | Evidence |
|---|---|---|
| CodeSearchNet (`full-v3`) | Running; source fully processed | `.csn_stage/.../codesearchnet_full-v3/checkpoint.json` → 457,461 processed, 312,723 accepted, 144,738 rejected |
| PyPI remediation v2 | In progress | `raw/pypi/remediation_v2/completed/` → 3,033 packages staged |
| GitHub acquisition verification | Running (`verify_github_acquired_rclone.py --list-only`) | process list |
| rclone Drive mount | Active | `/mnt/pythia-cloud/PythiaDrive` |

---

## 1. Corpus reconciliation (actual filesystem state)

### 1.1 Promoted / staged data

| Tier | Source | Records | Provisional tokens | License state | Notes |
|---|---|---:|---:|---|---|
| Stage 2 | CodeSearchNet `full-v3` accepted | **312,723** | **82,854,131** | All `LICENSE_APPROVED_FOR_INTENDED_USE` | Active run; 1.38 GB accepted + 47 MB rejected |
| Stage 3 | Jupyter (2 runs) | **73** | **135,671** | MIT / CC-BY-4.0 | On Drive; 59 + 14 records |
| Stage 1 | Python docs | 96 | 405 | PSF | Historical v3 file; manifest differs (see below) |
| Stage 1 | Think Python | 293 | 666 | **CC BY-NC 3.0** | NC — see §4 flag |
| Stage 1 | Automate the Boring Stuff | 162 | 7,171 | **CC BY-NC-SA 4.0** | NC — see §4 flag |
| Stage 1 | NumPy / SciPy / pandas | 99 / 301 / 41 | 7,789 / 34,693 / 3,040 | BSD-3-Clause | Acquisition of this session |
| Pilot | The Stack (bigcode) | 1,000 | ~135,650 (chars/4) | UNKNOWN | **Review hold** |
| Pilot | Stack Overflow (HF niche sites) | 10,000 | not computed | UNKNOWN | **Blocked** |
| Staged | PyPI `remediation_v2` | 3,033 packages | not yet aggregated | Per-package metadata | Active; no filtered token total yet |

**Verified Stage 1 total (excluding CodeSearchNet/Jupyter/PyPI): 992 records / 53,764 tokens.**
CodeSearchNet alone is ~1,500× the Stage 1 token volume, so *code* is not the bottleneck.

### 1.2 Stale artifacts to quarantine (do not promote)

| Path | Records | Why stale |
|---|---:|---|
| `data/canonical/codesearchnet/so_codesearchnet_canonical_v1.jsonl` | 1,000 | Derived from `sentence-transformers/codesearchnet`, the candidate the current CodeSearchNet workstream **rejected** for missing provenance; license `UNKNOWN` |
| `data/canonical/the_stack/so_the_stack_canonical_v1.jsonl` | 1,000 | Old 1,000-record sample; license `UNKNOWN` |
| `data/canonical/pypi/pypi_canonical_v1_sample.jsonl` | 50 | 50-record schema sample; `license_status = UNKNOWN` |
| `data/final/corpus.jsonl` | 0 | Empty — final corpus not assembled |

### 1.3 Known count conflicts (preserved, not overwritten)

`data/filtered/stage1/stage1_manifest.json` is internally inconsistent with the v3 files:
manifest "retained" says Python docs 90 / Think Python 287 / ATBS 67, while its own `counts` block
says 0 / 5 / 1, and the v3 JSONL files hold 96 / 293 / 162. This is the documented historical
reconciliation issue; do not treat the manifest as authoritative without recomputing.

### 1.4 What is genuinely missing

- **No natural-language explanatory prose corpus.** The docs pipeline (`scientific_docs.py`) extracts
  *code blocks only*; it discards the surrounding tutorial/guide text. Jupyter captures some
  markdown (64,055 of 135,671 tokens) but is tiny.
- **No official Python prose beyond the 3.14 reference dump** (PEPs, Devguide, packaging guide).
- **PyPI token yield is unquantified** and PyPI overlaps CodeSearchNet at the package/function level.

---

## 2. Highest-value missing source family

> **Licensed explanatory prose tightly aligned with executable Python examples** —
> official project tutorials/guides plus permissively licensed educational books.

Rationale:
1. Code volume is saturated (82.9M CodeSearchNet tokens + 3k PyPI packages in flight).
2. The scarce, high-signal axis for a *Python-specialized* model is prose that explains *why* code
   works: tutorials, how-to guides, design rationale, worked examples.
3. Current prose inventory is ~54k Stage 1 tokens + 64k Jupyter markdown tokens — effectively noise.
4. This family complements (does not duplicate) CodeSearchNet docstrings and PyPI source.

Secondary (defer): canonical repository code (CPython stdlib) only if it fills a documented gap;
GitHub-Python remains rejected.

---

## 3. Prioritized candidates

Legend — Decision: **ACCEPT-READY** (permissive/clear, provenance strong), **HOLD** (license
restricts or mechanism unclear), **BLOCKED** (policy override). Yield estimates are rough and
must be confirmed at acquisition; `tokens ≈ chars/4`.

### 3.1 Official / readily verifiable documentation

| # | Source | Version | License | Access | Est. prose tokens | Est. retained code blocks | Cost | Provenance |
|---|---|---|---|---|---|---|---|---|
| 1 | **scikit-learn docs** | 1.9.1 | BSD-3-Clause | versioned HTML **ZIP 99.8 MB** (`scikit-learn.org/dev/versions.html`) | ~5–10M | ~400–700 | Low (1 download) | **High** (ZIP + `COPYING`) |
| 2 | **SymPy docs** | 1.14.0 | BSD-3-Clause | `sympy/sympy_doc` `latest/` at pinned commit (no monolithic zip) | ~3–5M | ~200–400 | Medium (archive dir / build) | **High** (tag + `LICENSE`) |
| 3 | **PEPs** | repo commit | Public domain / **CC0-1.0** | `python/peps` git clone | ~3–5M | low | Low | **High** (per-PEP license header) |
| 4 | **CPython Developer's Guide** | repo commit | **CC0-1.0** | `python/devguide` | ~0.3–0.5M | low | Low | **High** (`LICENSE`) |
| 5 | **Python Packaging User Guide** | repo commit | **CC BY-SA 3.0** | `pypa/packaging.python.org` | ~0.4–0.6M | moderate | Low–Medium | **High** (README license) |
| 6 | Matplotlib docs | 3.11.2 | PSF-derived | no HTML zip (PDF only) | ~2–4M | moderate | Medium | High but mechanism unclear → **HOLD** |

### 3.2 Licensed educational material (prose + worked examples)

| # | Source | License | Access | Est. tokens | Decision | Note |
|---|---|---|---:|---|---|---|
| 1 | **A Byte of Python** | **CC BY-SA 4.0**; code BSD-3-Clause | `github.com/swaroopch/byte-of-python` | ~60–90k | **ACCEPT-READY** | Commercial use allowed; SA attribution |
| 2 | Composing Programs 3e | CC BY-NC-SA 4.0 | composingprograms.com/3ed | ~120–200k | **HOLD** | Non-commercial |
| 3 | Think Python 2e (already acquired) | CC BY-NC 3.0 | — | 666 (code only) | **PROMOTION HOLD** | NC conflicts with commercial/weight release |
| 4 | Automate the Boring Stuff 3e (already acquired) | CC BY-NC-SA 4.0 | — | 7,171 (code only) | **PROMOTION HOLD** | Non-commercial |
| 5 | Invent with Python / Big Book of Small Python Projects | CC BY-NC-SA | inventwithpython.com | ~0.5–1M | **HOLD** | Non-commercial |
| 6 | Python for Everybody / Full Stack Python | CC BY-NC-SA | — | ~1–2M | **HOLD** | Non-commercial |

### 3.3 Repository-level licensed code (complements, does not duplicate)

| # | Source | License | Access | Est. tokens | Decision | Rationale |
|---|---|---|---:|---|---|---|
| 1 | **CPython standard library** | PSF-2.0 | release tarball, pinned version | ~3–5M | **DEFER (P3)** | Canonical, heavily documented code; not represented in CodeSearchNet/PyPI overlap analysis yet |
| 2 | pip / setuptools / wheel | MIT / PSF | PyPI sdists (already in PyPI flow) | small | **DEFER** | Covered by PyPI workstream; do not duplicate |
| 3 | GitHub-Python scrape | varies | — | — | **REJECTED** | Policy override |
| 4 | Stack Exchange | varies | — | — | **BLOCKED** | Pending licensing review |
| 5 | The Stack | UNKNOWN | — | 135,650 (pilot) | **REVIEW HOLD** | License unresolved |

---

## 4. Licensing flags raised by reconciliation

- **Think Python 2e = CC BY-NC 3.0** and **ATBS 3e = CC BY-NC-SA 4.0** are already in Stage 1.
  "Non-commercial" conflicts with the project's stated intent to release dataset/model weights.
  Recommendation: **keep raw, hold promotion**, and record the decision. Do not silently delete.
- `python_docs` is PSF-licensed (fine). Scientific docs are BSD-3-Clause (fine).
- Stale canonical samples carry `license = UNKNOWN`; quarantine them from any future assembly.

## 5. Recommended sequence (respect active workstreams)

1. **Wait** for CodeSearchNet `full-v3` and PyPI `remediation_v2` to finish and be verified.
2. **P1 prose (official):** PEPs + CPython Devguide (CC0, tiny, highest provenance certainty),
   then scikit-learn docs (BSD-3, single ZIP), then SymPy, then Packaging guide (CC BY-SA).
3. **P1 prose (educational):** A Byte of Python (CC BY-SA 4.0 + BSD-3 code).
4. **New capability required:** a prose extractor (HTML/Markdown → clean text) — the current docs
   pipeline only keeps code blocks, so prose yield cannot be realized without it.
5. **P3 (defer):** CPython stdlib only after an overlap analysis against CodeSearchNet/PyPI.
6. **Never** promote NC material without an explicit licensing decision.

## 6. Bottom line

- Current verified corpus is **code-heavy and prose-poor**: ~82.9M CodeSearchNet tokens vs ~54k
  Stage 1 tokens (plus 136k Jupyter).
- The highest-value missing family is **licensed explanatory prose**.
- Readiest, lowest-risk next sources: **PEPs + Devguide (CC0)**, **scikit-learn (BSD-3)**,
  **A Byte of Python (CC BY-SA 4.0)**.
- Keep **Stack Exchange blocked**, **The Stack on review hold**, **GitHub-Python rejected**.
- No acquisition was started by this report.
