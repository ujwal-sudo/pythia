# Hypotheses

## H1: Python-Specialized Tokenizer

A tokenizer trained or adapted for Python will reduce token counts for common Python constructs and identifiers compared with appropriate general-purpose baselines, while preserving or improving downstream code quality.

## H2: Quality-Over-Quantity Data

AST-validated, documented, and source-curated Python examples will improve model behavior per training token compared with less selective Python data.

## H3: Compact Model Competitiveness

A Python-specialized model near 160M parameters can achieve useful competitiveness on Python-focused tasks when paired with high-quality data and reproducible training.

## H4: Neurosymbolic Feedback

AST and later Knowledge Graph/tooling feedback will reduce invalid or low-quality Python outputs and improve repair loops without executing untrusted generated code.

## Null And Negative Results

Each hypothesis may be disproven. Negative, null, mixed, or failed results must be preserved in the experiment log, run registry, and relevant results folder.
