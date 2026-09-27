# SESSION 2 — FINAL CONTROL PREFLIGHT INTAKE (independent verification)

## VERIFIED FINDINGS

### 1. WriterLock
- Wired into run_pilot (line ~857), run_scaleup (~1423), recovery main (~429): acquire -> locked-runner -> release in finally. VERIFIED.
- heartbeat/renewal/protected(): PRESENT (renew at 816, protected at 859, heartbeat thread, LockNotHeldError on ownership loss). VERIFIED.
- ownership loss fails closed: VERIFIED (protected() raises LockNotHeldError -> no mutation proceeds).
- advisory limitation documented: VERIFIED (class docstring + remediation_v2 + all control docs).

### 2. Commit safety
- journal=True + find_interrupted_commits() + reconcile_startup(): PRESENT. VERIFIED (isolated tests).
- interrupted/uncommitted/promoted-unverified/ambiguous -> reconcile_startup classifies; ambiguous fails closed. VERIFIED.
- BUT: journal is OPT-IN (journal=True), not mandatory by default in all call sites -> partial-final risk remains unless enabled. PARTIALLY VERIFIED.

### 3. Remote reads/writes
- checkpoint discovery: remote_checkpoint_names() used via _iter_checkpoint_paths() in remote mode. VERIFIED.
- archive verification: _archive_sha256_value/_archive_exists route through remote_archive_sha256/remote_archive_exists. VERIFIED.
- candidate manifest reads: load_candidates_manifest remote-aware. VERIFIED.
- recovery reads/writes: load_state/save_state remote-aware. VERIFIED.
- **archive WRITE (download): BLOCKER** — TWO _download_file defs (807 remote-aware, 1024 POSIX). Python uses LAST (1024) = POSIX (part.replace). save_archive_remote unreachable. CONFIRMED POSIX dependency in live archive-download path.

### 4. Resume
- 3,047 checkpoints / 2,945 ACQUIRED / 102 FAILED / 1,953 unprocessed / boundary 3048. VERIFIED (rclone read-only).

### 5. Safety guard
- _guard_write() refuses RcloneBackend writes unless PYPI_STORAGE_ALLOW_REMOTE_WRITE=1. VERIFIED.
- Tests use LocalDirBackend; cannot mutate pythia:Pythia. VERIFIED.

### 6. Tests/evidence
- storage: 59 passed (re-run independently). VERIFIED.
- full suite: 175 passed / 1 skipped / 2 subtests (re-run). VERIFIED.
- remote-mode targeted tests + read-only live validation: claimed; read-only validation commands (lsf/cat/hashsum/about) documented. VERIFIED for read-only scope.

### 7. Immutability
- candidate SHA e26e2035... / acquisition SHA e081a09e... / recovery 50 / quarantine 13 / freeze ACTIVE / 3,047 checkpoints. VERIFIED via rclone. .staging/ absent. VERIFIED.

### 8. Writer-lock incident
- .locks/writer.lock (owner prot-a) was test residue from a flawed protected() implementation; remediation removed it; .locks/ now empty (verified via rclone). Incident documented in remediation_v2 (not erased). VERIFIED consistent.

## DECISION: BLOCKED

### Exact blocker
1. **Archive download path is POSIX-only at runtime**: pypi.py defines _download_file twice (807 remote-aware, 1024 POSIX); the LAST definition wins, so the live pilot/scaleup archive download uses `part.open("wb")`/`part.replace(dest)` even in remote mode. The remote-aware version (with save_archive_remote) is shadowed/unreachable. This is the exact remote-mode POSIX dependency Session 3 flagged, and it remains.

### Additional partial areas (not blockers, but require Session 1 to confirm)
- Commit journal is opt-in (journal=True), not mandatory by default; confirm reconcile_startup is invoked on startup in run_scaleup/recovery, else ambiguous state may not be handled automatically.
- Duplicate _download_file definitions are a code-hygiene defect that caused the shadowing; must be consolidated to one remote-aware definition.

## NEXT STEP
Session 1 must fix the _download_file shadowing (remove the POSIX duplicate / consolidate to the remote-aware definition), make journal/reconcile mandatory for remote execution, and re-provide evidence. Then Session 2 re-verifies and, only if clean, returns READY FOR SESSION 3 REVIEW.

PYPI EXECUTION NOT AUTHORIZED — FREEZE ACTIVE.
