# Dataset Versioning Contract — Pythia-160M

This document formalizes the versioning scheme for Pythia data releases. It defines when a new dataset version is created, what metadata identifies it, how source snapshots are linked, how hashes are recorded, and how historical versions are preserved.

## Version Scheme

| Version | When Created | Corresponding Artifacts |
|---|---|---|
| **PYTHIA-DATA-v0.1** | Initial release after Stage 1 reconciliation | Canonical data contract, source schema mapping, experiment registry, run registry, all scaffolding directories |
| **PYTHIA-DATA-v0.2** | After first blocked data task completes (e.g., Stack Overflow source acquisition) | New experiment entries, updated readiness checklist, resolved provenance gaps |
| **PYTHIA-DATA-v0.3** | After deduplication scaffold is populated | Global dedup schema, normalized hashing contract, source-priority rules |
| **PYTHIA-DATA-v0.4** | After final corpus readiness check passes | `READY` status, train/validation/holdout policy, all quality metadata verified |
| **PYTHIA-DATA-v0.5** | After custom tokenizer version `PYTHIA-TOK-v0.1` is available | All `token_count` values updated to `FINAL` status, tokenizer version recorded per record |

## Version Identification Metadata

Every dataset version must carry the following metadata, recorded in `research/dataset_versioning.md` and propagated into every contributing record:

- **version_string**: `PYTHIA-DATA-v0.x`
- **date_released**: ISO date (`YYYY-MM-DD`)
- **dataset_keeper**: Owner responsible (OP/CD/Lead)
- **parent_version**: The prior `PYTHIA-DATA-v0.y` from which this version diverges
- **release_notes**: Summary of what changed, what was added, what was resolved
- **experiment_ids**: List of experiment IDs included in this version, e.g., `PYT-DATA-SO-001`, `PYT-DATA-GH-001`
- **source_snapshots**: Mapping of source name → SHA-256 of the immutable raw snapshot used
- **validator_version**: The `scripts.validators.ast_validator` version used for syntax gating
- **tokenizer_version**: The `PYTHIA-TOK-v0.x` version used for token counting (if `FINAL`)
- **blockers_resolved**: List of known blockers that were resolved to reach this version
- **blockers_remaining**: List of known blockers that persist into this version

## Source Snapshot Linking

When a new dataset version is created, every source contributing to that version must have an immutable snapshot recorded:

- **raw_path**: Absolute filesystem path to the raw source archive/directory
- **sha256**: SHA-256 checksum of the raw snapshot, recorded at acquisition time
- **acquisition_date**: Date the snapshot was taken/immutable copy was created
- **session_owner**: Which session (OP/CD/Lead/Session2/3/4) acquired the source
- **notes**: Any relevant provenance notes

The SHA-256 of the raw snapshot must **never** be recomputed or overwritten for a given version. If the source needs to be re-acquired, a new version (e.g., `v0.2` → `v0.3`) is created.

## Hash Recording Contract

Every record in the canonical corpus must carry:

- **content_hash**: SHA-256 of the normalized content string. This is the canonical dedup key.
- **normalized_hash** (optional): SHA-256 after normalization (e.g., whitespace stripping, comment removal). Used for near-deduplication.

The `content_hash` must be computed deterministically:

1. Normalize the source code/text (normalize line endings `\r\n` → `\n`, strip trailing whitespace)
2. Run through `hashlib.sha256(normalized.encode("utf-8")).hexdigest()`

If a record passes through the AST validator, the `validator_version` must also be recorded.

## Historical Version Preservation

- **Never retroactively rename** historical runs. `PYT-DATA-001` remains as evidence of the reconciliation run even after `PYTHIA-DATA-v0.1` is introduced.
- When a new version is created, the prior version is **preserved intact** and marked `superseded` in `research/dataset_versioning.md`.
- New versions may **reference** prior versions for provenance, but must not modify their contents.
- All historical experiment logs, run registries, and decision logs are preserved as-is.

## When a New Dataset Version Is Created

A new `PYTHIA-DATA-v0.x` is created when **any** of the following conditions are met:

1. A new source is acquired (e.g., Stack Overflow, PyPI, GitHub) and added to the corpus.
2. A major pipeline change is made (e.g., new validator version, new preprocessing stage).
3. The tokenizer becomes available and token counts are updated from `PROVISIONAL` to `FINAL`.
4. A significant blocker is resolved that changes the dataset composition.
5. The Lead explicitly requests a version bump for coordination purposes.

The version bump is recorded in `research/dataset_versioning.md`, and a new entry is added to `research/experiment_registry.md` for each experiment included in the new version.

## Example: v0.1 to v0.2 Transition

If Session 2 acquires a Stack Overflow source snapshot:

- **v0.1** (existing): No SO data. All records from Python docs, textbooks only.
- **v0.2** (new): SO snapshot acquired, SHA-256 `abc123...`, acquisition date `2026-09-17`, session `Session 2`.
  - New `research/dataset_versioning.md` entry records the transition.
  - Every SO record inherits `dataset_version: PYTHIA-DATA-v0.2`.
  - All pre-existing records keep `dataset_version: PYTHIA-DATA-v0.1` (unchanged).
  - `content_hash` values are unchanged; only the new records have `content_hash` computed from SO source.
  - `token_count_status` remains `PROVISIONAL` for all records until `PYTHIA-TOK-v0.1` exists.

## Compliance

- No record may carry `token_count_status: FINAL` before `PYTHIA-TOK-v0.1` exists.
- Every record's `dataset_version` must match a recorded version in `research/dataset_versioning.md`.
- Source snapshots' SHA-256 checksums must be immutable; any change increments the dataset version.