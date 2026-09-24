# SESSION 2 — PYPI STORAGE ABSTRACTION POST-IMPLEMENTATION ACCEPTANCE PROCEDURE (v1)

Status: PROCEDURE FOR SESSION 1 IMPLEMENTATION REVIEW. No PyPI execution authorized.
Controlling contract: data/frozen/pypi_storage_abstraction_control_spec_v1.md
                        + pypi_storage_guarantee_matrix_v1.md
Authoritative state (unchanged): 5,000 candidates (SHA e26e2035...); 3,047 checkpoints;
2,945 ACQUIRED; 102 FAILED; 1,953 unprocessed; resume boundary 3048; 2,954 canonical archives;
recovery 50 (48/1/1); quarantine 6; freeze ACTIVE; no execution.

==================================================
1. IMPLEMENTATION INTAKE
==================================================
Session 1 MUST deliver, before review begins:
  - changed-file list (diff vs current repo)
  - architecture summary
  - backend interface/API (abstract storage interface; methods + signatures)
  - path registry (logical namespace -> backend path map)
  - POSIX backend implementation
  - remote/rclone backend implementation
  - freeze implementation
  - checkpoint commit implementation
  - archive commit implementation
  - manifest commit implementation
  - recovery commit implementation
  - lock/lease implementation
  - read-after-write verification implementation
  - remote headroom implementation
  - tests + test output (isolated local/mock infra; NO real PyPI writes)
  - guarantee matrix (honest classification)
  - known limitations
  - explicit list of behavior intentionally NOT changed
REJECT if Session 1 provides only a conceptual design without implementation evidence
(no runnable code, no tests, no diff).

==================================================
2. CODE-LEVEL ACCEPTANCE
==================================================
Checks (objective, evidence-based):
A. No scattered PyPI filesystem roots — single PathRegistry; grep must find no hardcoded
   /mnt/pythia-cloud/Pythia/... in acquisition/recovery logic (only in registry mapping).
B. No acquisition logic directly calling pathlib/.open()/os.replace/tarfile/zipfile/os.walk
   for storage ops where the abstraction should be used. Storage ops go through the backend.
C. Backend selection is explicit and deterministic (config/env; never inferred at runtime
   from path strings).
D. POSIX backend retains required local atomic behavior (tmp+rename where appropriate).
E. Remote backend does NOT pretend rclone move/copy is POSIX atomic rename; code must
   treat promotion as non-atomic + verify.
F. Freeze checking occurs through the storage abstraction (not pathlib on local copy).
G. Missing/unreachable freeze state fails closed (all writes refused).
H. Existing committed objects cannot be silently overwritten (conditional no-overwrite).
I. Checkpoint identity cannot be changed after commit (immutable committed record).
J. Archive identity cannot be changed after commit (immutable canonical archive).
K. Existing historical state remains immutable (ACQUIRED/FAILED checkpoints, manifests).

==================================================
3. REMOTE COMMIT ACCEPTANCE
==================================================
For each remote write class (checkpoint, archive, manifest, recovery state, metadata),
verify the explicit lifecycle:
  UNCOMMITTED -> temporary object -> upload -> remote verification -> commit/promotion
               -> read-after-write verification -> COMMITTED
Determine whether each transition is enforceable (code exists, is reachable, is tested).
Do NOT mark a protocol safe merely because the sequence exists.
Specifically test the claim "upload temporary object -> rclone move -> committed":
  - Is promotion atomic on Google Drive? (NO by default)
  - Is promotion conditional on absence of final? (must be verified, not assumed)
If final promotion is not atomic/conditional on GDrive, classify honestly as a limitation
(do not upgrade to "safe").

==================================================
4. FREEZE ACCEPTANCE
==================================================
Verify:
  - freeze is authoritative (remote pythia:Pythia/raw/pypi/.FREEZE_SENTINEL)
  - freeze is checked remotely via storage abstraction (rclone lsf)
  - freeze check happens before EVERY mutation
  - inaccessible freeze state => fail-closed (refuse writes)
  - local stale sentinel cannot override remote state
  - freeze removal is not possible through normal acquisition code
  - execution remains blocked while sentinel exists
The test suite must demonstrate each of the above (isolated mock).

==================================================
5. SINGLE-WRITER ACCEPTANCE
==================================================
Review lease/lock: owner identity, acquisition time, expiry, heartbeat, stale detection,
takeover, release, failure handling.
HARD QUESTION: Can this lock provide mutual exclusion on Google Drive + rclone?
  - Google Drive does NOT provide atomic conditional create.
  - A lock file is advisory; two writers CAN both think they hold it.
If mutual exclusion is unavailable, state so explicitly and identify the missing primitive
(e.g., true conditional-create / compare-and-swap) and the consequence for execution
authorization (Phase C/D remain blocked).

==================================================
6. CRASH / FAILURE ACCEPTANCE
==================================================
Require tests/evidence for: process killed during upload; killed after upload before commit;
killed during promotion; partial remote object; missing remote object; SHA mismatch;
size mismatch; stale temporary object; duplicate commit attempt; existing object collision;
manifest update interrupted; recovery write interrupted.
For each: (1) what remains remotely? (2) can it be mistaken for committed state?
(3) can the process safely resume? (4) can historical state be overwritten?
(5) can resume boundary become incorrect?

==================================================
7. READ-AFTER-WRITE ACCEPTANCE
==================================================
Require actual verification that a committed object can be: found remotely; read remotely;
hashed; compared against expected hash; compared against expected size; matched to expected
identity. If backend cannot guarantee immediate consistency, document retry/verification
behavior and the consistency window.

==================================================
8. RESUME SAFETY ACCEPTANCE
==================================================
Verify the implementation preserves: 3,047 checkpoints; 2,945 ACQUIRED; 102 FAILED;
resume boundary 3048; skip-existing; immutable historical records.
No new real checkpoint may be created during acceptance. Tests use isolated mock/local state.

==================================================
9. MANIFEST SAFETY ACCEPTANCE
==================================================
Review candidate/acquisition/frozen manifest handling. Determine whether concurrent update,
interrupted write, stale copy, lost update, partial object, or conflicting writer can corrupt
the authoritative manifest. If backend cannot provide safe conditional replacement, mark as
an execution blocker (do not invent a guarantee).

==================================================
10. HEADROOM ACCEPTANCE
==================================================
Verify the old local shutil.disk_usage() assumption is NOT silently used for remote execution.
Remote capacity/headroom must either be reliably measured or cause fail-closed behavior.

==================================================
11. TEST QUALITY REVIEW
==================================================
Classify each important guarantee as:
  A = directly proven by implementation + meaningful test
  B = tested only against a mock
  C = dependent on rclone
  D = dependent on Google Drive
  E = not actually guaranteed
A mock passing must NOT upgrade a GDrive-dependent guarantee to A.

==================================================
12. ADVERSARIAL QUESTIONS
==================================================
Before accepting Session 1, explicitly answer:
1. Can Google Drive provide atomic conditional object creation here?
2. Can rclone provide atomic rename/replace semantics here?
3. Can two independent writers be prevented from both acquiring the same logical lock?
4. Can a crashed writer leave state indistinguishable from committed state?
5. Can a stale remote object be mistaken for a committed checkpoint?
6. Can a manifest update be lost or overwritten?
7. Can read-after-write verification prove the object actually persisted?
8. Can the system recover safely after process termination at every commit stage?
9. Can the implementation guarantee historical immutability remotely?
10. What guarantees exist ONLY because the current freeze prevents execution?
    Do NOT mistake "safe while frozen" for "safe during execution."

==================================================
13. ACCEPTANCE RESULT
==================================================
Produce exactly one of: PASS | PASS WITH EXPLICIT LIMITATIONS | FAIL
No subjective scoring.
- If any missing primitive means execution cannot be made safe -> FAIL + identify blocker.
- If the abstraction works but some guarantees remain backend-dependent -> PASS WITH
  EXPLICIT LIMITATIONS only if those limitations do not undermine required execution safety.

==================================================
14. EXECUTION AUTHORIZATION BOUNDARY
==================================================
Even if this acceptance passes:
  - DO NOT authorize execution yet.
  - Session 3 must independently perform the adversarial storage-abstraction review.
  - Only after Session 3 review passes should Session 2 perform the final PyPI execution preflight.
  - Only after that can a separate explicit authorization remove the freeze.
Phase C and Phase D remain blocked until all gates pass.

==================================================
15. SESSION 3 HANDOFF REQUIREMENTS
==================================================
Deliver to Session 3: acceptance result + classification, all adversarial answers,
test evidence, guarantee matrix, known limitations, and the exact primitive gaps
(atomic conditional create, lock atomicity, consistency window) that Session 3 must
independently attack. Session 3 must challenge claimed atomicity, lock safety, GDrive
consistency, rclone semantics, crash recovery, concurrent writers, manifest integrity,
historical immutability.
