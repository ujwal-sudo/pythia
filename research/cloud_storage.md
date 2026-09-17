# Cloud Storage — Pythia-160M

This document documents the local and cloud storage roles, the Google Drive mount path, the environment variable, the expected directory layout, and the behavior when the Drive is unavailable.

## 1. Local Storage Role

**Local repository directory:** `/home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline/`

**What lives locally (under `data/`):**

- **code**: All Python scripts under `scripts/`
- **tests**: All test files under `tests/`
- **research markdown/json**: All `research/*.md`, `research/*.json`, `research/results/*.json`
- **small configuration**: `config.py` and all its constants
- **source manifests when small enough**: Stage 1 manifests, JSONL files with <10KB, experiment reports

**Purpose:** The local repository remains fully functional for development, testing, and reconciliation work without requiring cloud access. All research metadata, decision logs, experiment registries, and small manifests stay here.

## 2. Google Drive Cloud Storage

**Mount path:** `/mnt/pythia-cloud`

**Remote:** `pythia:Pythia` (via rclone)

**Available storage:** approximately 4.948 TiB free (verified 2026-09-17)

**What lives in the cloud (under `/mnt/pythia-cloud/`):**

- **raw datasets**: Large raw source datasets (e.g., GitHub repos, Stack Exchange data, PyPI snapshots)
- **large extracted datasets**: Processed corpora that exceed local storage capacity
- **repository clones**: GitHub repository checkouts used by Session 4
- **large filtered corpora**: Stage 2-4 filtered data, deduplicated corpora
- **snapshots**: Point-in-time copies of data states for rollback/reproducibility
- **archives**: Long-term storage of dataset versions (e.g., `PYTHIA-DATA-v0.1`, `PYTHIA-DATA-v0.2`)

**Directory layout in the cloud:**

```
/mnt/pythia-cloud/
├── raw/
│   ├── stackoverflow/
│   ├── pypi/
│   ├── github/
│   ├── the_stack/
│   ├── codesearchnet/
│   ├── jupyter/
│   └── peps/
├── filtered/
│   ├── stage1/
│   ├── stage2/
│   ├── stage3/
│   └── stage4/
├── manifests/
│   ├── source/
│   ├── dataset/
│   └── version/
└── snapshots/
    ├── pythia-data-v0.1/
    ├── pythia-data-v0.2/
    └── ...
```

## 3. Environment Variable

**`PYTHIA_DATA_ROOT`**

- When set (e.g., `PYTHIA_DATA_ROOT=/mnt/pythia-cloud`), all canonical paths (`RAW_DIR`, `FILTERED_DIR`, `FINAL_DIR`, `MANIFEST_DIR`, `SNAPSHOT_DIR`) resolve to the Google Drive mount.
- When **unset**, paths fall back to the local `data/` directory (`/home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline/data/`).
- The variable is optional; the repository must work without it.

**Example:**

```bash
export PYTHIA_DATA_ROOT=/mnt/pythia-cloud
python3 -c "
from config import DATA_ROOT, RAW_DIR, FILTERED_DIR
print(DATA_ROOT)  # /mnt/pythia-cloud
print(RAW_DIR)    # /mnt/pithia-cloud/raw
print(FILTERED_DIR)  # /mnt/pithia-cloud/filtered
"
```

## 4. Behavior When Drive is Unavailable

If `/mnt/pythia-cloud` is not mounted or `PYTHIA_DATA_ROOT` points to a non-existent path:

- The environment variable is still set but the path is invalid
- The config falls back gracefully: if `PYTHIA_DATA_ROOT` is set but the directory is not readable, a warning is emitted and the local `data/` directory is used instead
- No dataset acquisition or processing should fail due to cloud unavailability
- All existing local paths continue to work unchanged

**Warning example:**

```bash
export PYTHIA_DATA_ROOT=/nonexistent/path
# On next Pythia import:
# WARNING: PYTHIA_DATA_ROOT=/nonexistent/path is not a readable directory.
# Falling back to local data: /home/ujwal-mahajan/Desktop/Pythia/pythia-data-pipeline/data
```

## 5. Safety Policy

- **Do not** move the existing 60 GitHub repositories, Stack Overflow data, or PyPI data in this task
- **Do not** modify Sessions 2–4 raw data directories
- **Do not** automatically relocate research metadata (markdown, json, configs) from local to cloud
- **Do not** perform global deduplication on active datasets
- **Do** use the environment variable to direct large data to the cloud
- **Do** perform a controlled migration (planned for a later task, after configuration is verified)
- **Do** ensure the local repository remains fully functional without the cloud mount

## 6. rclone Remote Configuration

The Google Drive remote is configured as `pythia:Pythia` via rclone. Verified read/write:

```bash
rclone ls pythia:Pythia/test
/mnt/pythia-cloud/test/test.txt
```

The mount has been verified at `/mnt/pythia-cloud` with approximately 4.948 TiB free (2026-09-17).