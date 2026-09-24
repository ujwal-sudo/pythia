## Near-Duplicate Detection — Technical Specification (Design Only)

**Do not run** global deduplication.  This section documents the technical
specification for future implementation.  The decision and rationale are
recorded in the research decision registry.

### Goals

1. Detect near-duplicate Python code across sources (GitHub, Stack Overflow,
   PyPI, Python documentation).
2. Preserve source provenance — retain all records with different source
   identifiers, even when their code is similar.
3. Provide a deterministic fingerprinting and similarity calculation.
4. Configure a similarity threshold that can be versioned and reviewed.
5. Record near-duplicate clusters without deleting any data.

### Design Constraints

- **No data deletion** — near-duplicate flags are metadata only.
- **Deterministic** — same input always produces same fingerprint/clustering.
- **Source-aware** — identical code from different sources should be flagged
  as similar but retained with distinct source metadata.
- **Configurable** — threshold and normalization are versioned in the dataset
  versioning scheme.
- **Non-destructive** — no raw records are modified; flags are additive metadata.

### Approaches Considered

| Approach | Normalization | Fingerprint | Similarity Calculation | Threshold | Notes |
|---|---|---|---|---|---|
| **SimHash** | Whitespace/stripping, comment removal, \r\n→\n | SimHash 64-bit vector | Jaccard on bitwise overlap | ~0.85 (configurable) | Fast, incremental updates possible; well-established for doc dedup |
| **MinHash** | Same as SimHash | MinHash signatures (k-min-wise independent hashes) | Jaccard estimate on signature similarity | ~0.85 (configurable) | Standard for set similarity; larger memory than SimHash if k is big |
| **Locality-Sensitive Hashing (LSH)** | Same as above | LSH bands/buckets | Band collision probability | ~0.85 (configurable) | Good for very large datasets; adds complexity of band parameters |

**Selected approach: SimHash** — simplest implementation, sufficient for the
expected data volumes, and supports incremental updates.  The threshold of
0.85 aligns with the existing `DEDUP_SIMILARITY_THRESHOLD` in `config.py`.

### Normalization Pipeline (applied before fingerprinting)

1. **Line ending normalisation**: `\r\n` → `\n`
2. **Trailing whitespace strip** per line
3. **Comment removal**: strip lines that are solely comments; strip `# ` prefixes
   from remaining lines
4. **Docstring removal**: strip `"""..."""` blocks (preserve content if needed
   for other purposes, but exclude from fingerprint)
5. **Whitespace collapse**: convert sequences of horizontal whitespace to a
   single space (optional — depends on whether code structure should be
   preserved at fingerprint level)
6. **Unicode normalisation**: NFKC canonical decomposition (Python source is
   typically ASCII, but this handles edge cases)

After normalization, the code string is passed to the SimHash pipeline.

### SimHash Pipeline

1. **Tokenise**: split normalized code on whitespace and punctuation to produce
   a bag of tokens (lower‑cased).
2. **Token weighting**: each token gets a weight based on its document frequency
   (rare tokens get higher weight).  For simplicity, start with uniform weight
   (all tokens weight = 1).
3. **Bitwise iteration**: for each bit position `i` (0 … 63):
   - Sum the weights of tokens where bit `i` of the token's hash is 1.
   - Sum the weights of tokens where bit `i` of the token's hash is 0.
   - If the weight-for-1 > weight-for-0, set bit `i` of the SimHash fingerprint to 1; otherwise set it to 0.
4. **Fingerprint**: 64-bit integer representing the SimHash vector.

### Similarity Calculation

Given two SimHash fingerprints `A` and `B` (64-bit integers):

- Compute `diff = A XOR B` (bits that differ).
- Count the number of differing bits: `popcount(diff)`.
- Similarity `s = 1 - (popcount(diff) / 64)`.
- If `s >= THRESHOLD` (configured as `DEDUP_SIMILARITY_THRESHOLD = 0.85`),
  the items are flagged as near-duplicates.

### Clustering and Recording

- **No deletion**: When code from source A and source B have `sim >= 0.85`,
  both records are retained.  Each record gets a `near_duplicate_status`
  field set to `"similar_to_<source_id>_<record_id>"`.
- **Provenance preservation**: The `near_duplicate_status` field is stored in
  the record's metadata alongside the existing `exact_hash` and
  `content_hash`.  No records are removed or modified.
- **Cluster ID**: An optional cluster identifier can be assigned (e.g.,
  `near_dup_cluster_<hash>`) to group records that form a transitive chain
  of similarity (A similar to B, B similar to C, but A not similar to C).
  This is *optional* for the initial implementation; the first phase only
  records pairwise similarity flags.
- **Versioning**: The similarity threshold and normalization parameters are
  recorded in the dataset version entry (`research/dataset_versioning.md`).
  If the threshold changes, a new dataset version is created.

### Implementation Phasing

| Phase | Action |
|---|---|
| **Phase 1** (research) | Implement SimHash fingerprint generation and similarity
  calculation as a standalone function.  Test on small synthetic datasets.
  Record design and rationale in the decision registry. |
| **Phase 2** (integration) | Integrate the SimHash pipeline into the quality-gate
  infrastructure.  Add `near_duplicate_status` field to the record schema.
  Do not modify any raw data or candidate manifests. |
| **Phase 3** (deferred) | Run the near-dedup pipeline on acquired datasets.
  Resolve any provenance or cluster-ID assignments.  Update the dataset
  version as needed. |

### Decision Rationale (recorded in research/decision_registry.md)

- **SimHash over MinHash/LSH**: SimHash requires less memory (64 bits per
  document) and is easier to implement correctly without external
  dependencies.  The data volumes expected (tens of thousands of Python
  files) do not justify the added complexity of MinHash or LSH at this
  stage.
- **Threshold 0.85 aligns with existing config**: The existing
  `DEDUP_SIMILARITY_THRESHOLD = 0.85` in `config.py` provides a consistent
  anchor; changing it would fragment the project's quality-gate semantics.
- **Provenance preservation is non-negotiable**: The project's core principle
  is that source-specific metadata must never be silently discarded.  The
  design ensures that similar code from different sources is flagged but
  retained with full source identity.
- **Implementation deferred**: Until sufficient source data has been acquired
  (GitHub pilot, SO profiling complete, PyPI snapshot), the algorithm is
  specified and tested on synthetic data.  No data is processed until the
  implementation is verified on real records.

### Rationale Summary

The design preserves the project's core principles: no data deletion, full
source provenance, deterministic behavior, and versioned configuration.  The
SimHash approach provides a practical, efficient mechanism for near-duplicate
detection that can be integrated into the quality-gate infrastructure when
the time comes.

---
*Decision recorded in research/decision_registry.md under "Near-duplicate
detection design".  Implementation deferred until Phase 2 conditions are met.*