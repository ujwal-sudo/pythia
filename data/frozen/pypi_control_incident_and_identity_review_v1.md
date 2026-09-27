# PYPI CONTROL INCIDENT + IDENTITY-GATE REVIEW (Session 3 — control recovery)

Status: **PYPI CONTROL RECOVERED — IDENTITY BUG INVESTIGATION COMPLETE — AWAITING NEXT AUTHORIZATION**
Date: 2026-09-25
Freeze: RESTORED. Execution: NOT AUTHORIZED.

---

## 1. Control incident

### 1.1 Observations reported by Sessions 1/2
- `.FREEZE_SENTINEL` absent, remote write mode enabled, an active PyPI scale-up process,
  `metadata/.locks/writer.lock` held, an external opencode agent involved.
- Session 2 did not launch it; Session 1 did not remove the sentinel.

### 1.2 Containment investigation (this session, read-only)
- **No PyPI writer process is currently active.** No `scripts.scrapers.pypi` / `scaleup` /
  `run_pilot` process exists in the process table.
- Active acquisition processes are Session 4 (GitHub only):
  - PID 1231797 (bash loop) + PID 1280080 (`github_acquire.py`, started 13:01) + PID 1280439
    (`rclone copy … pythia:Pythia/raw/github/.snapshots/…`) — GitHub paths only, not PyPI.
- `metadata/.locks/writer.lock` owner: **`972092-076fbad7`** — this is the lock documented in
  Session 3's pilot report as the pilot's leftover (post-batch interruption). Acquired
  2026-09-25 00:01 UTC, lease expired 00:29 UTC; **currently expired/stale**.
- The only live PyPI-touching process is PID 1283963 (an opencode session, parent PID 624354)
  running a **read-only** `rclone ls`/`hashsum`/`cat` audit — no writes.

### 1.3 Determination
- The "external PyPI writer" reported by Sessions 1/2 corresponds to **Session 3's authorized
  bounded pilot** (the lock owner matches the pilot; the sentinel was removed for the pilot; a
  scale-up process was active during the pilot). The pilot process has since terminated.
- **No unauthorized PyPI writes occurred**: checkpoint count and archive count exactly match the
  pilot's documented outputs, and both manifests are unchanged (see §2).
- No containment termination was required (nothing unauthorized is running).

## 2. Fresh read-only state reconciliation (post-pilot, post-containment)

```
Candidates:       5,000   (SHA e26e2035f67b646796a7cfa1474ae2e39fcccd14b13daa333090b2f9652532dc)
Checkpoints:      3,050   (= 3,047 baseline + 3 pilot FAILED)
ACQUIRED:         2,945   (unchanged; pilot acquired 0)
FAILED:             105   (= 102 baseline + 3 pilot identity-mismatch)
TIMEOUT:              0
Unprocessed:      1,950   (next derived rank 3051)
Acquisition manifest SHA: e081a09ef4b6f62d020789df5589db1a66af355eacc65e1b69bf275152d23c4b (UNCHANGED)
Canonical archives: 2,962  (= 2,959 + 3 pilot archives)
Recovery:            50   (48 RECOVERED_VERIFIED / 1 NO_PYTHON_CODE / 1 IDENTITY_MISMATCH) (UNCHANGED)
Quarantine:          13   (UNCHANGED)
Journal/staging:     clean (empty)
Locks:               1 stale lock (owner 972092-076fbad7, expired) — pilot leftover, preserved
Freeze:             RESTORED (this session; see §3)
```

Pilot artifacts verified: the 3 remote archives hash exactly to the SHAs recorded in their
FAILED checkpoints (readerwriterlock 4eac…, translationstring 3a15…, nvidia 483c…).

## 3. Unauthorized mutation analysis

Every change since the frozen baseline is accounted for by the **authorized pilot**:
- +3 checkpoints: readerwriterlock, nvidia-cuda-nvdisasm, translationstring (all FAILED).
- +3 archives: the three downloaded/uploaded archives.
- No other checkpoints/archives/manifests/recovery/quarantine changed.
- The `prot-a` lock incident remains historical (lock absent; evidence preserved).

## 4. Freeze restoration

- `.FREEZE_SENTINEL` restored 2026-09-25T07:35Z after containment determined no active writer.
- Reason: external-writer report + pilot completion; namespace must be guarded.
- Verified present and readable. No acquisition resumes.

## 5. Identity-gate investigation — root cause (all three pilot failures)

Observed pattern: the pipeline resolves a package's **latest** version but downloads an
**old** archive.

| Package | resolved (info.version) | selected release | archive filename | gate result |
|---|---|---|---|---|
| readerwriterlock | 1.0.9 | 1.0.0 (first non-yanked sdist) | readerwriterlock-1.0.0.tar.gz | filename_version_mismatch |
| translationstring | 1.4 | 0.1 (first non-yanked sdist) | translationstring-0.1.tar.gz | filename_version_mismatch |
| nvidia-cuda-nvdisasm | 13.4.92 | 13.2.51 (first non-yanked wheel) | nvidia_cuda_nvdisasm-13.2.51…whl | identity_unprovable_no_sha |

### Root cause (verified via PyPI JSON for all three)
`fetch_package_metadata` (pypi.py):
1. Iterates `releases` **in ascending order** and **breaks at the first non-yanked release** that
   has an sdist (or wheel fallback) — selecting the **oldest** release, not the latest.
2. PyPI release-file dicts have **no `version` field** (`sel.get("version") is None`), so
   `resolved_version = sel.get("version") or info.get("version")` falls back to **`info.version`
   (the latest)**.
3. The candidate manifest specifies **no exact version**, and the scale-up loop calls
   `fetch_package_metadata(c["package"])` **without `requested_version`**.

Result: `requested_version/resolved_version = latest`, `archive = oldest` → the identity gate
correctly rejects every such mismatch. The gate is **working as designed (fail-closed)**.

### Answers to the investigation questions
1. Source metadata resolved: PyPI JSON `info` (latest) + `releases` dict (selection).
2. Requested version selection: not supplied by candidate (manifest has no version); the loop
   determines it.
3. Archive URL selection: first non-yanked release (ascending) with sdist/wheel; break.
4. Filename version parsing: `parse_version_from_filename` (works for simple sdist names; complex
   wheel names may yield None).
5. SHA identity: `sel.digests.sha256` (expected) vs computed observed — verified equal.
6. "latest" used where exact should be: YES — `resolved_version` uses `info.version` as fallback
   while the archive is from the oldest non-yanked release.
7. Manifest exact versions: NO — the candidate manifest has no version field.
8. Mismatch class: **metadata-resolution + URL-selection error** (dominant). Not a
   candidate-manifest error, not an archive-parsing error, not an identity-gate implementation
   error.

### Required design principle (NOT implemented this mission)
Make candidate identity deterministic and prove
`candidate identity == requested version == resolved artifact identity == verified archive identity`,
or reject. Minimum changes (future authorized step):
- Anchor to an exact release version (e.g., latest non-yanked sdist RELEASE, deterministically
  chosen), set `resolved_version` to that release (not `info.version`), and verify the archive
  filename version == that release before accepting.
- The identity gate stays fail-closed; mismatches remain FAILED.

## 6. Final status

```
Freeze:             RESTORED
Execution:          NOT AUTHORIZED
93 transient recovery: NOT AUTHORIZED
3 deterministic:        NOT AUTHORIZED (manual review)
6 identity-mismatch:    NOT AUTHORIZED (quarantined)
Resume (3051):          NOT AUTHORIZED
5K scale-up / background: NOT AUTHORIZED
Final corpus:           NOT AUTHORIZED
```

> **PYPI CONTROL RECOVERED — IDENTITY BUG INVESTIGATION COMPLETE — AWAITING NEXT AUTHORIZATION**

Evidence preserved: pilot reports, freeze-removal event, this incident record, the stale pilot
lock, quarantine records, and the historical prot-a incident. No evidence deleted.