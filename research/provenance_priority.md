# Provenance Priority — Pythia-160M

This document defines how identical content from multiple sources will be represented in the canonical corpus. It does not make a final source-priority decision unless already locked in the research decisions. Where the project has not decided something, it is explicitly marked: OPEN DECISION.

## Core Principle

One canonical training record + all contributing source references preserved.

No provenance is destroyed just because duplicate content is found. The final corpus keeps one version of the content but records every source that contributed it.

## Current Policy: OPEN DECISION

The project has not yet locked a source-priority policy. The following options are under consideration:

### Option A: Earliest Acquisition Wins (FIFO)
- The source that was acquired first gets to keep its version of the content.
- All other sources contributing the same content are recorded as `discarded_sources` in the provenance.
- Rationale: Simplicity; respects the order in which the project officially acquired sources.

### Option B: Highest-License-Clearity Wins
- Among duplicate contributions, the version from the source with the clearest license (e.g., `MIT` > `Apache-2.0` > `CC-BY-SA-4.0` > `RESTRICTED`) is kept.
- License clarity is determined by the `license_status` field in the data contract.
- Rationale: Reduces licensing risk in the final corpus.

### Option C: Most Authoritative Source Wins
- A project-defined hierarchy of source authority is used (e.g., official Python docs > textbooks > Stack Exchange > GitHub repos > Reddit).
- Rationale: Reflects the project's assessment of source trustworthiness.

### Option D: Community-Voted / Experiment-Generated
- Duplicate content from experiments (e.g., FIM prefixes, docstring→code, repair pairs) is kept based on the experiment that generated it, with all source references preserved.
- Rationale: Supports the neurosymbolic feedback loop where multiple versions of code may be valid.

## Provenance Preservation Contract (Mandatory, Regardless of Priority Policy)

Regardless of which source priority option is adopted, the following must always hold:

1. **One canonical record** is kept in the training corpus.
2. **All contributing source references** are preserved in the provenance, including:
   - `kept_source`: The source ID that was selected to represent the content.
   - `discarded_sources`: A list of all other source IDs that also contributed this content.
   - `content_hash`: The normalized SHA-256 hash of the content (canonical dedup key).
   - `acquisition_timestamps`: When each source was acquired (ISO date strings).
   - `record_ids`: The record IDs from each contributing source.
3. **No source is erased**. Even if a source is listed in `discarded_sources`, its record remains traceable in the experiment registry and decision log.
4. **License metadata is preserved** for every source, even discarded ones. The final corpus record includes the license of the kept source, and the discarded sources' licenses are recorded in the provenance.

## Decision Timeline

- **OPEN DECISION**: Source priority policy not yet locked.
- The policy will be decided before the final corpus assembly task (PYTHIA-010).
- Until the policy is locked, all source contributions are retained with full provenance, and the project operates in "provenance-preservation mode" where no content is silently dropped.
- The decision will be recorded in `research/dataset_versioning.md` and announced in `research/project_status.md`.

## Integration with Other Contracts

- This policy interacts with `research/data_contract.md` (via `content_hash`, `kept_source`, `discarded_sources`).
- This policy interacts with `research/dataset_versioning.md` (via `dataset_version`, `source_snapshots`).
- This policy interacts with the `GlobalDedupInterface` in `scripts/processors/global_dedup.py` (via `SourcePriority` protocol).
- Until the policy is locked, the default behavior is: **retain all content with full provenance; do not silently drop any source**.

## Current Implementation Note

The `scripts/processors/global_dedup.py` scaffold includes a `SourcePriority` protocol and a `DEFAULT_SOURCE_PRIORITY` that defaults to "earliest acquisition wins" (Option A). This default is **provisional** and will be replaced by the locked policy decision when it arrives.

Until the policy is locked, practitioners should operate under the provenance-preservation mode: add every source contributing a piece of content to the provenance, keep one canonical version, and do not silently remove any source's trace from the system.