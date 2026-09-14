# Pythia-160M Data Pipeline

This repository contains the data-engineering foundation for **Pythia-160M**, a compact 160M-parameter Python code language model trained from scratch under the C3AN framework.

Research questions, hypotheses, experiment records, reproducibility requirements, and paper-oriented artifacts are maintained under `research/`.

## C3AN

C3AN stands for:

- **Custom**: Python-only, domain-specific, curated training data.
- **Compact**: The model is intentionally designed around 160M parameters rather than simply scaling parameters.
- **Composite**: The system combines a neural language model, a Python Knowledge Graph, and AST-based validation.
- **Neurosymbolic**: Neural generation is paired with symbolic validation and feedback.

The intended inference pipeline is:

```text
Generate
   ↓
AST Validation
   ↓
Knowledge Graph Validation
   ↓
Feedback / Regeneration
```

## Data Pipeline

The high-level data pipeline is:

```text
Raw Sources
     ↓
AST Validation
     ↓
Quality Filtering
     ↓
PEP8 Validation
     ↓
Knowledge Graph Validation
     ↓
Deduplication
     ↓
Final Corpus
```

The pipeline is designed around a **quality-over-quantity** philosophy inspired by Phi-1. The intended corpus target is approximately **5–6 GB of filtered, validated Python**, but quality and validation take precedence over simply reaching a size target.

## Curriculum Stages

### Stage 1 — Highest-quality sources

- Official Python documentation
- Think Python
- Automate the Boring Stuff
- Composing Programs

### Stage 2

- High-quality StackOverflow Python answers
- CodeSearchNet Python subset

### Stage 3

- High-quality Jupyter notebooks
- Heavily filtered subset of The Stack

## Filtering Configuration

Current filtering thresholds are:

```text
Minimum tokens: 50
Maximum tokens: 2048
Minimum comment/docstring ratio: 10%
Maximum PEP8 violations: 5
Deduplication similarity threshold: 0.85
```

## Project Layout

- `data/raw/`: source-specific raw data locations.
- `data/filtered/`: staged, filtered data locations.
- `data/final/corpus.jsonl`: final corpus destination.
- `scripts/validators/`: future validation components.
- `scripts/scrapers/`: future source collection components.
- `scripts/processors/`: future processing components.
- `logs/`: pipeline logs.
- `config.py`: centralized project paths and filtering constants.

The project is being built incrementally. Validators, scrapers, processors, the Knowledge Graph, and the eventual training pipeline will be added in later stages.

## AST Validation

The authoritative validator is available through `scripts.validators.ast_validator.validate_python`. It uses Python's standard-library `ast.parse()` as the syntax gate and returns structured results containing syntax diagnostics, AST node counts, functions, classes, imports, loops, conditionals, returns, comments, docstrings, and a documentation ratio.

AST validation does not execute submitted code and does not establish semantic correctness, executability, API correctness, PEP8 compliance, or Knowledge Graph validity. Those concerns remain separate pipeline components. Comment and docstring measurements are reported rather than filtered automatically; syntax support depends on the Python interpreter version running the validator.

## Official Python Documentation Ingestion

Stage 1 includes a source-specific official Python documentation component runnable with `python -m scripts.scrapers.python_docs`. The flow is:

```text
Official Python documentation
→ extraction
→ conservative Python detection
→ AST validation
→ preliminary quality filtering
→ normalized Stage 1 candidates
```

Raw archives stay in `data/raw/python_docs/`; normalized retained examples are written to `data/filtered/stage1/python_docs.jsonl`. The component records source/version/license provenance, provisional token counts, AST metadata, PEP8 counts, exact hashes, a source manifest, and `logs/python_docs_report.json`. Knowledge Graph validation is marked as pending for later stages.
