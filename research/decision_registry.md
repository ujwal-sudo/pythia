# Decision Registry — Pythia-160M

This is the canonical decision registry for the Pythia-160M project. It consolidates all locked research decisions and serves as the authoritative source for experiment design and policy. Historical decisions are preserved in `research/decisions.md`; this registry contains the final plan.

## Architecture

| Decision | Value |
|---|---|
| Parameter count | ~160M |
| Layers | 12 |
| Hidden size | 768 |
| Attention heads | 12 |
| RoPE theta | 1,000,000 |
| Normalization | RMSNorm pre-norm |
| Activation | SwiGLU |
| Grouped Query Attention | GQA |
| Flash Attention | supported |
| Token prediction mix | 50% NTP, 50% FIM |

## Tokenizer

| Decision | Value |
|---|---|
| Tokenization method | BPE |
| Vocabulary size | ~32k |
| Python-specialized | Yes |
| Special tokens | <|endoftext|>, <|code|>, <|docstring|>, <|comment|>, <|INDENT|>, <|DEDENT|>, <|fim_prefix|>, <|fim_middle|>, <|fim_suffix|> |

## Data

| Decision | Value |
|---|---|
| Corpus language | Python-only |
| AST gate | Yes (syntax validity, not semantic correctness) |
| Quality-first | Yes (over quantity) |
| Target token count | ~4B validated Python tokens |
| Curriculum learning | Yes (across stages) |
| Dedup | Exact + near (threshold 0.85) |
| PEP8 ceiling | 5 violations |
| Min token length | 50 |
| Max token length | 2048 |
| Min comment ratio | 0.10 |
| Comment/docstring ratio target | 0.10 |
| Near-duplicate threshold | 0.85 |
| AST parse failure | Automatic rejection |

## Training

| Decision | Value |
|---|---|
| Stage A | Clean curated Python base pretraining (50% NTP, 50% FIM, curriculum learning) |
| Stage B | SFT (repair, docstring→code, instruction, reasoning) |
| Stage C | Neurosymbolic training (AST + Knowledge Graph + feedback/regeneration) |

## Reasoning

| Decision | Value |
|---|---|
| Reasoning data collection | Separate, must NOT silently become part of clean base-pretraining |
| Inclusion in pretraining | Only as explicit ablation/experiment |

## Evaluation

| Decision | Value |
|---|---|
| HumanEval+ | Yes |
| MBPP+ | Yes |
| LiveCodeBench | Yes |
| Perplexity | Yes |
| AST validity | Yes |
| Execution correctness | Yes |
| Repair | Yes |
| Docstring→code | Yes |
| Pythia-specific suite | Yes |
| Efficiency | Yes |
| Tokenizer evaluation | Yes |
| Data ablations | Yes |
| Neurosymbolic ablations | Yes |
| Baseline comparisons | Yes |
| Contamination check | Yes |

## Versioning

| Artifact | Version |
|---|---|
| Data | PYTHIA-DATA-v0.1 |
| Tokenizer | PYTHIA-TOK-v0.1 |
| Model | Pythia-160M-v0.1 |

## Consolidated Decisions (from `decisions.md`)

All original decisions from `DEC-20260915-001` through `DEC-20260915-004` are preserved here as the foundation. No decisions have been rejected or superseded; they are incorporated into the canonical registry.

### DEC-20260915-001 — Use a staged quality-over-quantity data pipeline
- **Status:** accepted — incorporated into Architecture > Data section
- **Reason:** Quality and validation take precedence over raw size

### DEC-20260915-002 — Use the non-executing AST validator as the syntax gate
- **Status:** accepted — incorporated into Data > AST gate section
- **Reason:** Safe syntax gate; separates syntax from semantic/PEP8/Knowledge Graph validity

### DEC-20260915-003 — Keep token counts provisional until a custom tokenizer exists
- **Status:** accepted — incorporated into Versioning section
- **Reason:** Prevent provisional counts from being mistaken for final results

### DEC-20260915-004 — Use persistent Lead coordination files
- **Status:** accepted — incorporated into Versioning section
- **Reason:** Cross-session reproducibility and coordination