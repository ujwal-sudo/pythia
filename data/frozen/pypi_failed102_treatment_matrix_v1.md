# SESSION 2 — FAILED-102 TREATMENT MATRIX (read-only)

Transient (93): network errors (metadata_fetch_failed, ConnectionResetError).
  - Future: eligible for bounded SHA-anchored retry under safe pipeline (Phase D).
  - Evidence: each package's SHA-anchor availability in PyPI release history.

Deterministic (3): dbt-semantic-interfaces ("File is not a zip file"), metricflow
  ("Is a directory" extraction error), +1 structural. NOT retried.
  - Evidence: archive-format inspection; confirm usable sdist/wheel existence.
  - Treatment: manual review or exclusion.

External identity_mismatch (6): ranks 3042-3047 (moyopy, clickhouse-sqlalchemy,
  python-editor, databricks, dogpile-cache, types-pyasn1). Quarantined; NOT reprocessed.
  - Evidence: quarantine hashes verified; FAILED identity_mismatch:filename_version_mismatch.
