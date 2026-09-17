# Knowledge Graph Placeholder — Pythia-160M

This directory serves as the structural location and documentation foundation for the later Knowledge Graph task. No full KG is built or downloaded in this reconciliation task.

## Intended KG Entities

The Knowledge Graph will ultimately capture structured relationships among Python code elements mined from the validated corpus. The following entity types are intended:

- **modules**: Top-level Python modules and their docstrings
- **functions**: Function definitions including signatures, parameters, return types, and docstrings
- **classes**: Class definitions including inheritance, methods, and docstrings
- **signatures**: Call signatures (function/method parameters and return annotations)
- **types**: Type annotations and type information across the corpus
- **relationships**: Dependencies and references between entities (e.g., import relationships, method-call relationships)
- **patterns**: Recurring code patterns (e.g., common idioms, anti-patterns, utility patterns)
- **error/fix relationships**: Mappings between code errors/bugs and their fixes, where appropriate, supporting the neurosymbolic feedback loop

## Scope and Scaling

- The KG will be populated from the validated Python corpus (after Stage A-E pretraining data is finalized).
- Entity extraction will use the AST validator (`scripts.validators.ast_validator.validate_python`) as the syntax gate, ensuring only syntactically valid Python is processed.
- Relationship extraction will build on top of function/class boundaries identified during AST analysis.
- The KG is intended to support the Stage C neurosymbolic training loop: Generate -> AST -> Knowledge Graph -> Feedback/Regeneration.

## Current State

- `research/knowledge_graph/` directory exists as an empty placeholder.
- No KG data, graphs, or implementation artifacts exist yet.
- Entity and relationship schemas are documented in this README for future implementation.
- The KG will be developed in a later task after the corpus, tokenizer, and model architecture are verified.

## Planned Future Work

- Implement KG entity extraction from validated Python corpus.
- Implement relationship extraction between KG entities.
- Populate a working Knowledge Graph with modules, functions, classes, and signatures from the Pythia-160M corpus.
- Integrate KG feedback into the neurosymbolic training loop (Stage C).
- Expose KG queries/queries for the evaluation harness (e.g., repair suggestions, pattern lookup).