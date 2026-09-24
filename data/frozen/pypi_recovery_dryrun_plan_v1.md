# SESSION 2 — PYPI RECOVERY DRY-RUN PLAN (NOT EXECUTED)

Status: DRY-RUN ONLY — freeze remains active. No network, no writes, no retries.

## Recovery categories and evidence requirements

1. EXISTING VERIFIED RECOVERY (48 RECOVERED_VERIFIED)
   - Status: complete, isolated under /mnt/pythia-cloud/Pythia/recovery/pypi/
   - Evidence already present: content_hash, normalized_hash, SHA, provenance, resolved identity
   - Before use: reconcile against baseline 2945; confirm no double-counting; confirm recovery records
     are treated as NEW (never merged into historical checkpoints)

2. IDENTITY-MISMATCH RECOVERY (1: paramiko)
   - historical 5.0.0, resolved 0.1-bulbasaur, internal metadata package 'secsh' != 'paramiko' (package rename)
   - Evidence required before execution: confirm whether the package was renamed (secsh -> paramiko) and
     whether the historical archive is the intended distribution; decide accept-as-rename vs reject

3. NO-PYTHON-CODE RECOVERY (1: pyqt5-qt5)
   - wheel PyQt5_Qt5-5.15.11 (native Qt5 libs, no .py). Identity established (5.15.11) but no Python code.
   - Evidence required: decide whether native-only wheels are in scope for the corpus (likely exclude;
     preserve as non-code artifact)

4. TRANSIENT FAILED RECORDS (93, network errors: metadata_fetch_failed / ConnectionResetError)
   - Evidence required before execution: confirm archive availability in PyPI release history (SHA-anchor);
     retry under safe pipeline with identity gate. No new data needed beyond PyPI metadata.

5. DETERMINISTIC FAILED RECORDS (3: dbt-semantic-interfaces, metricflow, +1 structural)
   - Structural failures (archive format / extraction). Evidence required: inspect archive type, confirm
     whether a usable sdist/wheel exists; may require manual handling or exclusion.

6. FUTURE UNPROCESSED RANKS 3048-5000 (~1,953 candidates)
   - Not yet attempted. Evidence required before execution: full SHA-anchored resolution + identity gate;
     must be a NEW acquisition phase (distinct experiment) after freeze is lifted and Session 3 authorizes 5K scale-up.

## Guardrails for ANY future execution
- Freeze sentinel must be explicitly lifted by an authorized session before writes.
- Every record must pass identity gate (requested==resolved==filename==metadata==SHA) before RECOVERED_VERIFIED.
- No record may become ACQUIRED before full identity verification.
- Recovery writes ONLY under /mnt/pythia-cloud/Pythia/recovery/pypi/.
- Historical 3041 checkpoints and 2945 manifest never modified.
