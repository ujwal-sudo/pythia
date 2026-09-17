import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent

# Configurable data root — falls back to local data directory when unset.
DATA_ROOT = Path(os.environ.get("PYTHIA_DATA_ROOT", str(PROJECT_ROOT / "data")))

# Canonical path layout
RAW_DIR = DATA_ROOT / "raw"
FILTERED_DIR = DATA_ROOT / "filtered"
FINAL_DIR = DATA_ROOT / "final"
MANIFEST_DIR = DATA_ROOT / "manifests"
SNAPSHOT_DIR = DATA_ROOT / "snapshots"

RAW_DATA_DIR = RAW_DIR
PYTHON_DOCS_DIR = RAW_DIR / "python_docs"
TEXTBOOKS_DIR = RAW_DIR / "textbooks"
STACKOVERFLOW_DIR = RAW_DIR / "stackoverflow"
JUPYTER_DIR = RAW_DIR / "jupyter"
CODESEARCHNET_DIR = RAW_DIR / "codesearchnet"
THE_STACK_DIR = RAW_DIR / "the_stack"
PEP_DIR = RAW_DIR / "peps"

# GitHub acquisition configuration
GITHUB_RAW_DIR = RAW_DIR / "github"
GITHUB_MANIFEST_DIR = GITHUB_RAW_DIR / "manifests"
GITHUB_PILOT_SIZE = 150  # target number of repositories for the pilot
GITHUB_MIN_STARS = 100   # initial discovery filter
GITHUB_API_RATE_LIMIT_PER_MIN = 30  # conservative unauthenticated limit
GITHUB_API_BACKOFF_SECONDS = 7      # sleep between requests to stay within limits
GITHUB_PAGINATION_PER_PAGE = 30     # items per search page
GITHUB_PAGINATION_MAX_PAGES = 5     # max pages to fetch (≈GITHUB_PILOT_SIZE)

FILTERED_DATA_DIR = FILTERED_DIR
STAGE1_DIR = FILTERED_DIR / "stage1"
STAGE2_DIR = FILTERED_DIR / "stage2"
STAGE3_DIR = FILTERED_DIR / "stage3"
STAGE4_DIR = FILTERED_DIR / "stage4"
FINAL_DATA_DIR = FINAL_DIR
FINAL_CORPUS_PATH = FINAL_DIR / "corpus.jsonl"

SCRIPTS_DIR = PROJECT_ROOT / "scripts"
VALIDATORS_DIR = SCRIPTS_DIR / "validators"
SCRAPERS_DIR = SCRIPTS_DIR / "scrapers"
PROCESSORS_DIR = SCRIPTS_DIR / "processors"
LOGS_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOGS_DIR / "pipeline.log"

MIN_TOKEN_LENGTH = 50
MAX_TOKEN_LENGTH = 2048
MIN_COMMENT_RATIO = 0.1
PEP8_MAX_VIOLATIONS = 5
DEDUP_SIMILARITY_THRESHOLD = 0.85

# PyPI acquisition
PYPI_DIR = RAW_DIR / "pypi"
PYPI_PACKAGES_DIR = PYPI_DIR / "packages"
PYPI_METADATA_DIR = PYPI_DIR / "metadata"
PYPI_MANIFESTS_DIR = PYPI_DIR / "manifests"
PYPI_LICENSES_DIR = PYPI_DIR / "licenses"
PYPI_REPORTS_DIR = PYPI_DIR / "reports"
PYPI_TOP_PACKAGES_URL = "https://hugovk.github.io/top-pypi-packages/top-pypi-packages-30-days.min.json"
PYPI_TOP_PACKAGES_PATH = PYPI_METADATA_DIR / "top_pypi_packages_30_days.json"
PYPI_CANDIDATES_MANIFEST_PATH = PYPI_MANIFESTS_DIR / "pypi_candidates_v1.jsonl"
PYPI_ACQUISITION_MANIFEST_PATH = PYPI_MANIFESTS_DIR / "pypi_acquisition_v1.json"
PYPI_PILOT_REPORT_PATH = PYPI_REPORTS_DIR / "pypi_pilot_report_v1.json"
PYPI_SELECTION_REPORT_PATH = PYPI_REPORTS_DIR / "pypi_selection_report_v1.json"
PYPI_CANDIDATE_POOL_SIZE = 5000
PYPI_DOCSTRING_THRESHOLD_HIGH = 0.60
PYPI_DOCSTRING_THRESHOLD_MEDIUM = 0.30

# Curriculum learning stages
CURRICULUM_STAGES = ("A", "B", "C")
CURRICULUM_STAGE_A = "A"  # clean curated Python base pretraining
CURRICULUM_STAGE_B = "B"  # SFT (repair, docstring2code, instruction, reasoning)
CURRICULUM_STAGE_C = "C"  # neurosymbolic training (AST + KG + feedback)

# Tokenizer target vocabulary
TOKENIZER_TARGET_VOCAB = 32_000

# Target corpus token count (validated Python tokens)
TARGET_CORPUS_TOKEN_COUNT = 4_000_000_000

# FIM ratio (fill-in-the-middle)
FIM_RATIO = 0.5  # 50% FIM, 50% next-token prediction

# Model architectural constants
ARCH_HIDDEN_SIZE = 768
ARCH_NUM_LAYERS = 12
ARCH_NUM_HEADS = 12
ARCH_ROPE_THETA = 1_000_000
ARCH_ACTIVATION = "swiGLU"
ARCH_GQA_HEADS = 4  # GQA: grouped-query attention heads

# Backward-compatible alias: DATA_DIR resolves to DATA_ROOT (configurable) or
# PROJECT_ROOT / "data" when the environment variable is absent.
DATA_DIR = DATA_ROOT
