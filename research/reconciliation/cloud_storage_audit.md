# Cloud Storage Audit — Pythia-160M

**Date:** 2026-09-17
**Purpose:** Audit current local data paths and hardcoded locations in preparation for Google Drive mount configuration.

## 1. Current Local Data Paths (config.py)

All data paths are currently derived from `PROJECT_ROOT`, which is based on the location of `config.py`:

| Config Variable | Path | Description |
|---|---|---|
| `PROJECT_ROOT` | `/home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline` | Parent of `config.py` |
| `DATA_DIR` | `PROJECT_ROOT / "data"` | Local `data/` directory |
| `RAW_DATA_DIR` | `DATA_DIR / "raw"` | Local `data/raw/` directory |
| `FILTERED_DATA_DIR` | `DATA_DIR / "filtered"` | Local `data/filtered/` directory |
| `FINAL_DATA_DIR` | `DATA_DIR / "final"` | Local `data/final/` directory |
| `STAGE1_DIR` | `FILTERED_DATA_DIR / "stage1"` | Local `data/filtered/stage1/` |
| `STAGE2_DIR` | `FILTERED_DATA_DIR / "stage2"` | Local `data/filtered/stage2/` |
| `STAGE3_DIR` | `FILTERED_DATA_DIR / "stage3"` | Local `data/filtered/stage3/` |
| `STAGE4_DIR` | `FILTERED_DATA_DIR / "stage4"` | Local `data/filtered/stage4/` |
| `FINAL_CORPUS_PATH` | `FINAL_DATA_DIR / "corpus.jsonl"` | Local corpus file |

Source-specific raw directories:
- `PYTHON_DOCS_DIR` = `RAW_DATA_DIR / "python_docs"`
- `TEXTBOOKS_DIR` = `RAW_DATA_DIR / "textbooks"`
- `STACKOVERFLOW_DIR` = `RAW_DATA_DIR / "stackoverflow"`
- `JUPYTER_DIR` = `RAW_DATA_DIR / "jupyter"`
- `CODESEARCHNET_DIR` = `RAW_DATA_DIR / "codesearchnet"`
- `THE_STACK_DIR` = `RAW_DATA_DIR / "the_stack"`
- `PEP_DIR` = `RAW_DATA_DIR / "peps"`
- `GITHUB_RAW_DIR` = `RAW_DATA_DIR / "github"` (GitHub acquisition)
- `PYPI_DIR` = `RAW_DATA_DIR / "pypi"` (PyPI acquisition)

## 2. Hardcoded Paths Discovered

The following scripts construct data paths that are relative to the local repository:

### Scripts that import from config.py (implicitly via `from config import *`):
- `scripts/scrapers/python_docs.py` — uses `STAGE1_DIR`, `DEFAULT_OUTPUT_PATH`
- `scripts/scrapers/prepare_so.py` — references GitHub/Stack Overflow paths
- `scripts/validators/ast_validator.py` — uses logger, not data paths directly
- `scripts/logger.py` — logging configuration

### Scripts that directly reference `data/` paths:
- `scripts/scrapers/python_docs.py:33` — `STAGE1_DIR`
- `scripts/scrapers/python_docs.py:44` — `DEFAULT_OUTPUT_PATH = STAGE1_DIR / "python_docs.jsonl"`
- `scripts/finish_github_acquisition.py:49` — `GITHUB_RAW_DIR = BASE_DIR / "data" / "raw" / "github"`
- `scripts/finish_github_acquisition.py:50` — `GITHUB_MANIFEST_DIR = GITHUB_RAW_DIR / "manifests"`
- `scripts/finish_github_acquisition.py:384` — `repos_base = GITHUB_RAW_DIR / "repositories"`
- `scripts/finish_github_acquisition.py:473-474` — `"raw_dir": str(GITHUB_RAW_DIR)`, `"repositories": str(GITHUB_RAW_DIR / "repositories")`
- `scripts/scrapers/github.py:511` — `GITHUB_RAW_DIR.mkdir(parents=True, exist_ok=True)`
- `scripts/scrapers/github.py:551` — `sha_dir = safe_clone(full_name, GITHUB_RAW_DIR)`
- `scripts/scrapers/prepare_so.py` — references Stack Overflow data paths

### Research files that reference paths (documentation only, not code):
- `research/project_status.md` — references `data/raw/python_docs/`, `data/filtered/stage1/`, `data/final/corpus.jsonl`, `data/raw/stackoverflow/`, `data/raw/peps/`
- `research/task_registry.md` — references `data/raw/python_docs/python-3.14-docs-html.zip`, `data/filtered/stage1/python_docs_filtered_v3.jsonl`, `data/final/corpus.jsonl`
- `research/integration_issues.md` — documents `data/raw/stackoverflow/`, `data/raw/pypi/`, `data/raw/github/` as "do not modify"
- `research/reconciliation/audit.md` — classifies all data directories
- `research/source_schema_mapping.md` — maps source-specific paths

## 3. Proposed Configurable Root

The preferred solution is to introduce an environment variable `PYTHIA_DATA_ROOT` that, when set, overrides the default local data directory.

**Default behavior (no env var):**
- `DATA_ROOT` = `<project_root>/data` (current behavior)
- All paths resolve relative to `<project_root>/data`

**With env var:**
- `PYTHIA_DATA_ROOT=/mnt/pythia-cloud` → all large data resolves to the Google Drive mount
- The repository continues to work if the env var is absent (falls back to local `data/`)

**Proposed config.py changes:**
1. Add `DATA_ROOT` that checks `os.environ.get("PYTHIA_DATA_ROOT")` first
2. Derive all other paths from `DATA_ROOT` instead of `PROJECT_ROOT / "data"`
3. When `PYTHIA_DATA_ROOT` is not set, `DATA_ROOT` falls back to `PROJECT_ROOT / "data"`

This approach:
- Requires no code changes in scripts that import from config.py
- Allows gradual migration by setting the env var
- Preserves full backward compatibility
- Supports both local development and cloud storage

## 4. Scripts Affected

Scripts that import from config.py will automatically use the new `DATA_ROOT`:
- `scripts/scrapers/python_docs.py`
- `scripts/finish_github_acquisition.py`
- `scripts/scrapers/github.py`
- `scripts/scrapers/prepare_so.py`

No script modifications needed if they import config constants.

Scripts that hardcode `data/` paths directly would need updating, but current codebase uses config.py constants.

## 5. Expected Directory Layout After Config

```
# When PYTHIA_DATA_ROOT is NOT set (local development):
/home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline/
├── data/                    # LOCAL: keeps small manifests, configs
├── scripts/
├── tests/
├── research/
└── logs/

# When PYTHIA_DATA_ROOT=/mnt/pythia-cloud (cloud mode):
/mnt/pythia-cloud/
├── raw/                     # Large datasets
├── filtered/                # Large filtered corpora
├── manifests/               # Manifest files
└── snapshots/               # Snapshots

/home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline/  (local only)
├── scripts/                 # Always local
├── tests/                   # Always local
├── research/                # Always local (metadata, markdown, json)
├── data/                    # Small configs, research metadata
└── logs/                    # Pipeline logs
```

## 6. Safety Policy

- **Never** automatically relocate research metadata (markdown, json, configs)
- **Do not** move existing 60 GitHub repositories, Stack Overflow, or PyPI data in this task
- **Do not** modify Sessions 2–4 raw data directories
- **Only** establish the path abstraction; migration will be performed by coordinator later
- **Fallback:** if `PYTHIA_DATA_ROOT` is absent or invalid, fall back to local `data/` directory