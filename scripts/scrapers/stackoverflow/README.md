# Stack Overflow Data Acquisition Pipeline

## Overview

This pipeline acquires Stack Overflow QA data from three sources:
1. **HuggingFace datasets** — fastest, runs first
2. **Archive.org dump** — python.stackexchange.com 7z dump
3. **StackExchange API** — requires API_KEY

 followed by exact/near-dedup and quality filtering.

All output is written to Google Drive at `/mnt/pythia-cloud/Pythia`.
No data is written to local SSD except Python package imports.

---

## Directory Structure

```
scripts/scrapers/stackoverflow/
├── __init__.py          Package init + config re-exports
├── config.py            DRIVE_ROOT, paths, quality filters
├── hf_collector.py      HF dataset collector
├── archive_collector.py Archive.org 7z downloader + Posts.xml parser
├── api_collector.py     StackExchange API collector
├── deduplicator.py      Exact + near-dedup + quality filters
└── run_all.py           Pipeline orchestrator
```

---

## How to Run

```bash
# 1. Ensure Google Drive is mounted
rclone mount google-drive:/ /mnt/pythia-cloud

# 2. Set your API key (optional but recommended)
# Edit scripts/scrapers/stackoverflow/config.py and set:
#   API_KEY = "your-stackexchange-api-key"

# 3. Run the pipeline
python scripts/scrapers/stackoverflow/run_all.py
```

---

## File Descriptions

### config.py

Defines all constants used across the pipeline:

- `DRIVE_ROOT` — `/mnt/pythia-cloud/Pythia`
- `RAW_OUTPUT_DIR` — `data/raw/stackoverflow/`
- `CACHE_DIR` — `cache/stackoverflow/`
- `HF_CACHE_DIR` — `cache/huggingface/`
- `OUTPUT_FILES` — paths for hf, archive, api, deduped JSONL files
- `QUALITY_FILTERS` — min_body_length, min_code_chars, must_be_accepted
- `MIN_ANSWER_SCORE` — 10
- `CHUNK_SIZE` — 8192
- `REQUEST_DELAY` — 0.1 seconds

All output and cache directories are created on import via `os.makedirs`.

### hf_collector.py

Collects Stack Overflow Python QA pairs from HuggingFace datasets.

**Tries datasets in this order:**
1. `ArmelR/stack-exchange-instruction`
2. `HuggingFaceH4/stack-exchange-preferences`
3. `koutch/stackoverflow_python`

**For each dataset, filters rows where:**
- Tags contain "python" (case-insensitive)
- Score >= MIN_ANSWER_SCORE (10 if field exists)
- Body length >= 200 characters
- Body contains a code block (` ``` ` or `<code>`)

**Writes to** `so_huggingface.jsonl` with fields:
```json
{
  "source": "huggingface",
  "dataset_name": "<name>",
  "question": "<question text>",
  "answer": "<answer body>",
  "score": <int>,
  "tags": "<tags string>",
  "has_code": true/false,
  "char_count": <int>,
  "collected_at": "<ISO timestamp>"
}
```

**Progress:** printed/logged every 10,000 rows.

**Summary:** total processed, kept, output file size, estimated tokens (char_count / 4.5).

### archive_collector.py

Downloads and processes the Archive.org Python StackExchange dump.

**Steps:**
1. Downloads `python.stackexchange.com.7z` streaming directly to Drive
   - URL: `https://archive.org/download/stackexchange/python.stackexchange.com.7z`
   - Chunk size: 8192 bytes
   - If cached dump > 100 MB, skips download
2. Extracts 7z using `py7zr` to `cache/stackoverflow/python_stackexchange_extracted/`
3. Parses `Posts.xml` using `ET.iterparse` — **never loads full XML into memory**
   - `PostTypeId == "1"` → question, stored temporarily by Id
   - `PostTypeId == "2"` → answer, paired with parent question
   - Filters: score >= MIN_ANSWER_SCORE, parent question available
4. Writes to `so_archive.jsonl` with fields:
```json
{
  "source": "python_stackexchange_dump",
  "question_id": <int>,
  "answer_id": <int>,
  "question_title": "<title>",
  "question_body": "<body>",
  "answer_body": "<body>",
  "score": <int>,
  "is_accepted": true/false,
  "tags": "<tags>",
  "has_code": true/false,
  "char_count": <int>,
  "collected_at": "<ISO timestamp>"
}
```
5. Clears each XML element after processing (`post.clear()`) to keep memory low.
6. After successful completion, **deletes extracted XML files** from Drive cache
   (keeps the `.7z` file in case reprocessing is needed).

### api_collector.py

Collects from the public StackExchange API.

**Endpoint:** `https://api.stackexchange.com/2.3/questions`
**Params:** `site=stackoverflow`, `tagged=python`, `sort=votes`, `order=desc`,
 `filter=withbody`, `pagesize=100`, `min=MIN_ANSWER_SCORE`, `key=API_KEY`

**For each question fetched, immediately fetches its accepted answer:**
`https://api.stackexchange.com/2.3/answers/{answer_id}` with `filter=withbody`

**Resumable pagination:**
- Saves current page to `cache/api_checkpoint.json`
- On startup, reads checkpoint and resumes from last page
- Updates checkpoint after every page written

**Stops when:**
- `has_more == False`
- OR 500,000 pairs collected
- OR API returns `backoff` field (sleeps that many seconds)

**Rate limit handling:**
- `REQUEST_DELAY` (0.1s) between requests
- If `backoff` in response, sleeps that many seconds
- If `quota_remaining < 100`, prints warning and stops gracefully

**Error handling** (log and continue, don't crash):
- `requests.Timeout`
- `requests.ConnectionError`
- `JSONDecodeError`
- Missing fields in response

**Writes to** `so_api.jsonl` with same schema as archive_collector.

### deduplicator.py

Deduplicates and filters records from all three sources.

**Steps:**
1. Reads all three source files: `so_huggingface.jsonl`, `so_archive.jsonl`, `so_api.jsonl`
2. **Exact dedup:** hash of `answer_body.strip().lower()` (SHA-256); drop duplicates
3. **Near-dedup:** if two answers share >85% trigram similarity, keep higher-score one
4. **Quality filters:**
   - body length >= 200 chars
   - contains at least one code block (` ``` ` or `<code>` tag)
   - score >= MIN_ANSWER_SCORE (10)
   - not empty
5. Writes final output to `so_final_deduped.jsonl`
6. Prints final report:
   ```
   Total from HuggingFace:      X
   Total from Archive:          X
   Total from API:              X
   Before dedup:                X
   After exact dedup:           X
   After near dedup:            X
   After quality filter:        X
   ─────────────────────────────
   Final pairs:                 X
   Estimated tokens:            X (pairs × ~550)
   Output size on Drive:        X MB
   ```

### run_all.py

Pipeline orchestrator that runs collectors in order:

1. **Checks Drive is mounted:** `/mnt/pythia-cloud` — raises `RuntimeError` if not
2. **Step 1:** `hf_collector.py` (fastest, run first)
3. **Step 2:** `archive_collector.py`
4. **Step 3:** `api_collector.py` — **skips with warning if API_KEY not set**
5. **Step 4:** `deduplicator.py`

**Each step:**
- Prints `"Starting Step X: <name>"`
- Times the step
- Prints `"Step X complete in X minutes. Output: X rows, X MB"`
- Logs to `logs/pipeline.log`

**If any step fails:**
- Logs the error
- Continues to next step (doesn't abort the whole pipeline)
- Notes which steps failed in final summary

**Final summary printed to console and logged:**
```
══════════════════════════════════════
STACK OVERFLOW PIPELINE COMPLETE
══════════════════════════════════════
HuggingFace     → X pairs (X MB)
Archive         → X pairs (X MB)
API             → X pairs (X MB)
After dedup     → X pairs (X MB)
Estimated tokens → ~XM tokens
All data at: /mnt/pythia-cloud/Pythia/data/raw/stackoverflow/
══════════════════════════════════════
```

### requirements.txt

Add these packages:

```
py7zr
requests
datasets
huggingface_hub
jsonlines
tqdm
```

---

## Drive Mount Requirement

All output must go to `/mnt/pythia-cloud/Pythia`. Before running the pipeline:

```bash
rclone mount google-drive:/ /mnt/pythia-cloud
```

If Drive is not mounted, all scripts raise a clear `RuntimeError` explaining
the mount issue.

---

## Expected Output Sizes

- **HF collector:** ~10k–100k pairs depending on dataset availability
- **Archive collector:** ~10k–50k pairs from the 7z dump
- **API collector:** variable, depends on API key and rate limits
- **After dedup:** typically 30–50% reduction from before-dedup count
- **Estimated tokens:** pairs × ~550 (provisional; final count needs Pythia tokenizer)