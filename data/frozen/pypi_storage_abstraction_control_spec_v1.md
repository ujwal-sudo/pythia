# SESSION 2 — PYPI STORAGE ABSTRACTION CONTROL SPECIFICATION (v1)
Status: AUTHORITATIVE CONTROL SPEC — for Session 1 implementation, Session 3 review.
Scope: storage abstraction for PyPI acquisition/recovery. NO real PyPI writes authorized.

## 0. Current-state evidence (Session 2)
- Pipeline is POSIX-only: pathlib/.open()/tarfile/zipfile/os.walk/glob/stat/.replace/.exists/.mkdir.
- Zero rclone integration (no 'rclone', no 'subprocess' in pypi.py or pypi_sha_recovery.py).
- Scattered hardcoded paths:
  * pypi.py: "/mnt/pythia-cloud/Pythia/raw/pypi/packages/"
  * pypi_sha_recovery.py: "/mnt/pythia-cloud/Pythia/recovery",
    "/mnt/pythia-cloud/Pythia/raw/pypi/manifests/pypi_acquisition_v1.json",
    "/mnt/pythia-cloud/Pythia/raw/pypi/metadata"
  * config.py: DATA_ROOT (env PYTHIA_DATA_ROOT or local data/), PYPI_DIR derived from DATA_ROOT.
- Conclusion: DIRECT-RCLONE EXECUTION NOT SUPPORTED by current implementation.

## 1. CANONICAL PATH MODEL
One canonical logical path model. No scattered hardcoded /mnt paths.

Logical namespaces (single source of truth, e.g. a PathRegistry keyed by logical name):
  raw/pypi/                     -> pypi root
  raw/pypi/metadata/             -> checkpoints
  raw/pypi/packages/             -> canonical archives
  raw/pypi/recovery/             -> recovery state + recovery archives
  raw/pypi/quarantine/           -> external/quarantined artifacts
  raw/pypi/manifests/            -> candidate/acquisition manifests
  raw/pypi/.FREEZE_SENTINEL      -> freeze marker

Mapping:
  A. POSIX backend (FUSE restored): each logical name -> absolute Path under the mounted root.
     e.g. root/mnt/pythia-cloud/Pythia -> raw/pypi/metadata/...
  B. Remote backend (direct rclone): each logical name -> remote object path (pythia:Pythia/raw/pypi/...).
The acquisition/recovery logic MUST address logical names only; backend mapping is injectable.

## 2. FREEZE PROTOCOL
- Every PyPI mutation MUST verify authoritative remote freeze state through the storage abstraction
  (rclone lsf / backend-specific check), NEVER pathlib on a possibly-stale local path.
- Freeze check order: backend probe -> remote object existence. A stale local copy is NEVER authoritative.
- Missing/unreachable freeze state => FAIL CLOSED (refuse all writes).
- Freeze removal requires explicit authorization (a second actor, not the writer itself).
- Sentinel content must include: creation timestamp, creator, reason, expected hash.

## 3. CHECKPOINT COMMIT PROTOCOL (crash-safe)
Prevent: partial/torn checkpoint, silent overwrite, duplicate, stale, commit-before-verify,
archive/checkpoint mismatch, incorrect resume boundary.

Steps (each step must be idempotent or resumable):
  1. Generate unique temp object id (checkpoint_uuid + nonce) under a temp namespace.
  2. Upload temp object (complete bytes; never stream partial as final).
  3. Remote existence verification (rclone lsf / stat on temp path).
  4. Size verification (temp object size == expected).
  5. SHA/hash verification (backend hashsum or local hash of read-back bytes).
  6. Commit/promotion: conditional no-overwrite move temp -> final (only if final absent).
  7. Read-after-write verification (read final back, verify size+hash+identity).
  8. Record explicit committed state (committed marker / journal entry).
Atomicity determination: Google Drive + rclone does NOT provide POSIX atomic rename.
rclone copy -> rclone move is NOT equivalent to atomic rename. State this limitation explicitly.
Required mitigation: unique nonce temp objects + conditional no-overwrite promotion + read-after-write;
accept that promotion is at-least-once with explicit verification, never blindly assumed atomic.

## 4. ARCHIVE COMMIT PROTOCOL
- Archives (.tar.gz/.tgz/.zip/.tar.bz2) immutable once committed.
- Commit via temp upload + size + SHA verify + conditional no-overwrite promotion.
- If final canonical archive already exists: REJECT (never silently replace).
- Checkpoint MUST reference the committed archive path + archive SHA (verified before commit).

## 5. MANIFEST COMMIT PROTOCOL
- candidate manifest, acquisition manifest, frozen manifest references.
- Same temp+verify+promote pattern; protect against torn/concurrent/stale/lost-update.
- Manifest writes MUST include: generated_at, record_count, packages (identity), sha of source inputs.
- Resume boundary derived ONLY from committed checkpoints, never from a partially uploaded manifest.
- If Google Drive/rclone cannot guarantee atomic manifest update, state so explicitly.

## 6. RECOVERY WRITE PROTOCOL
- Recovery state and recovery archives use the SAME commit protocol.
- Recovery writes must never overwrite historical evidence; recovery dir is a separate namespace
  (raw/pypi/recovery/). No second conflicting state.
- Recovery records keyed by recovery_id (pypi:{pkg}:{ver}); skip-existing; never re-key.

## 7. SINGLE-WRITER / DISTRIBUTED LOCK
Session 1 must implement a PyPI writer lock with:
  owner identity, acquisition timestamp, lease expiry, heartbeat, stale-lock detection,
  safe takeover, explicit release, protection against Session 2/3/other writer overlap.
CRITICAL: Determine whether the mechanism is genuinely atomic on Google Drive.
Google Drive/rclone does NOT provide atomic conditional create. A lock file is NOT safe by itself;
it is a best-effort advisory lease. State this limitation explicitly. Enforce single-writer by
(1) freeze sentinel + (2) advisory lease + (3) write-path checks that refuse on any overlap +
(4) external coordination at execution time.

## 8. READ-AFTER-WRITE CONSISTENCY
After every remote commit verify: object exists; expected size; expected hash; expected
metadata/identity; object readable back; checkpoint references expected archive;
archive references expected package/version/distribution.

## 9. RESUME SAFETY
- Preserve existing ACQUIRED (2,945) and FAILED (102) checkpoints, resume boundary 3048,
  skip-existing semantics, no checkpoint rewriting, no historical mutation.
- Abstraction must NEVER infer resume state from a partially uploaded object
  (only committed objects count).

## 10. HEADROOM / STORAGE CHECKS
- Replace local shutil.disk_usage() with remote-aware capacity check.
- Fail closed if capacity cannot be determined reliably.

## 11. BACKEND SEPARATION
Two backends behind a common interface:
  POSIX backend: normal pathlib/tarfile/zipfile; atomic local rename where applicable.
  Remote backend: rclone-mediated object ops + explicit verification; NO assumption of
                 POSIX rename semantics.
Acquisition logic must not know which backend is active (backend injected by config).

## 12. TEST REQUIREMENTS (Session 1; isolated local/mock infra; NO real PyPI writes)
Mandatory tests: logical path mapping; wrong-root rejection; freeze active; freeze unreachable;
freeze removal protection; existing-object overwrite rejection; temporary-object collision;
interrupted upload; partial object; SHA mismatch; missing remote object; successful commit;
read-after-write verification; stale temporary object; duplicate writer; active lease;
expired lease; heartbeat failure; stale-lock recovery; concurrent manifest update; torn manifest;
archive/checkpoint mismatch; recovery-state failure; resume boundary preservation;
historical immutability; remote headroom failure; Session 4 isolation.

## 13. GUARANTEE MATRIX (see table in separate section below)

## 14. SESSION 1 ACCEPTANCE GATE
Session 1 is NOT complete merely because tests pass. Must demonstrate:
  1. Canonical logical path model (PathRegistry; no hardcoded /mnt paths).
  2. Backend abstraction (POSIX + remote; acquisition logic backend-agnostic).
  3. Freeze enforcement via storage abstraction (fail closed on unreachable).
  4. Checkpoint commit protocol (temp+verify+promote+read-after-write).
  5. Archive commit protocol (immutable; no overwrite).
  6. Manifest protocol (torn/concurrent/stale/lost-update protection).
  7. Recovery protocol (no historical overwrite).
  8. Writer coordination (lease with expiry/heartbeat/stale detection).
  9. Read-after-write verification.
  10. Resume safety (boundary 3048; skip-existing; no inference from partial objects).
  11. Remote headroom strategy (fail closed).
  12. Honest backend guarantee matrix (never label B/C as A).
  13. No real PyPI state modification during implementation/testing.

## 15. SESSION 3 REVIEW HANDOFF CHECKLIST
Session 3 must challenge:
  - claimed atomicity (is temp+promote truly atomic on GDrive?)
  - claimed lock safety (is a lock file safe on GDrive? conditional create? lease expiry?)
  - Google Drive consistency assumptions (eventual consistency? read-after-write?)
  - rclone semantics (copy vs move; hashsum reliability; partial upload)
  - crash recovery (temp objects left behind; orphan cleanup; idempotency)
  - concurrent writers (two leases; stale takeover)
  - manifest integrity (torn manifest; concurrent update)
  - historical immutability (can any path rewrite ACQUIRED/FAILED checkpoints?)

## Execution authorization (Session 2 will consider ONLY after):
  1. Session 1 storage abstraction implemented + acceptance gate passed.
  2. FUSE mount OR working remote backend demonstrated with full read-after-write verification.
  3. Freeze protocol proven fail-closed.
  4. Session 3 independent review passes.
  5. Explicit freeze removal authorized by a separate authority.
  6. No competing writer.
Phase C (93) and Phase D (1,953) remain BLOCKED until then.
