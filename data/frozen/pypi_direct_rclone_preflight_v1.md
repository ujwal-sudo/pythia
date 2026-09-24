# SESSION 2 — FINAL PYPI EXECUTION PREFLIGHT USING DIRECT RCLONE REMOTE

## DECISION: B. DIRECT-RCLONE EXECUTION NOT SUPPORTED

## Check 1 — Storage access compatibility
The existing PyPI pipeline (scripts/scrapers/pypi.py, pypi_sha_recovery.py) uses
PURE POSIX filesystem semantics throughout:
- pathlib.Path.write_text/.read_text/.replace/.exists/.mkdir/.stat (atomic write via tmp+replace)
- tarfile.open / zipfile.ZipFile (archive read)
- os.walk / .glob (directory traversal)
- Python built-in open() (file I/O)

The pipeline contains ZERO rclone integration (no 'rclone' and no 'subprocess' in either module).
The direct remote 'pythia:Pythia' is accessed via the rclone CLI (cat/lsf/copy), which is a
completely different interface from POSIX file paths. pathlib cannot open 'pythia:Pythia/...'.

Therefore the pipeline CANNOT read or write checkpoints/archives/manifests directly against
the rclone remote without code changes.

## Check 2 — Write safety
The freeze guard (PYPI_FREEZE_SENTINEL.exists() in _save_checkpoint, run_scaleup, run_pilot)
uses POSIX .exists() on a path. Under direct rclone (no mount), the sentinel path is not
POSIX-resolvable, so the guard would not be enforced by pathlib. The sentinel check must use
rclone lsf. Write safety is only guaranteed when the path is POSIX-resolvable (mounted).

## Check 3 — State consistency (authoritative remote, read-only)
- Checkpoint count: 3047 MATCH
- Candidate SHA: e26e2035f67b6467... MATCH
- Recovery: 50 records MATCH
- Quarantine: 6 MATCH
- Ranks 3048-5000: no checkpoints (unprocessed 1953) MATCH

## Check 4 — Execution plan compatibility
Phase C (93 transient) and Phase D (1953, ranks 3048-5000) both require POSIX checkpoint reads,
archive writes, manifest reads, and per-record writes. These CANNOT safely execute against the
direct rclone remote with the existing implementation.

## Check 5 — Concurrency
- No PyPI writer/pilot/scaleup/recovery process running MATCH
- No rclone copy process targeting PyPI
- Session 4's GitHub rclone process writes only github paths (not PyPI)
- Single-writer control achievable once execution is authorized

## Blockers preventing direct-rclone execution
1. POSIX/FUSE dependency: pipeline uses pathlib.open()/tarfile/zipfile/os.walk which require a
   mounted filesystem path. 'pythia:Pythia' is an rclone remote name, not a POSIX path.
2. Freeze-sentinel guard relies on POSIX .exists(); needs rclone-aware check.
3. Atomic writes (tmp+replace) require a real filesystem; rclone CLI writes are not atomic in-place.

## Minimum infrastructure change required
1. Restore a FUSE mount of pythia:Pythia (blocked in this sandbox) - OR
2. Add an rclone I/O adapter to the pipeline: replace pathlib/tarfile/zipfile/os.walk with
   rclone subprocess calls (cat/lsf/copyto/moveto) + a sentinel check via rclone lsf.
Neither is present today. Direct-rclone execution is NOT supported by the current implementation.

## Note
The working rclone remote does NOT make the Python pipeline write-compatible. Proven from
implementation: zero rclone integration + POSIX-only I/O.

Execution NOT authorized. Freeze remains active.
