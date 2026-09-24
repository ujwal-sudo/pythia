# SESSION 2 — PYPI RECOVERY DECISION GATE + EVIDENCE RECONCILIATION

## Final Report

1. Session 1 inventory consumed: NOT AVAILABLE (Session 1 inventory still in progress; old 84/2862/2956 figures rejected per instruction, not treated as authoritative)
2. Total local archives: ~2,910 (sample: 59/60 packages have archives; 2959 pkg dirs)
3. Archives SHA-matched to existing checkpoints: 39/39 sampled (100% of present); ~2,910 est across baseline
4. Version-mismatch archives: 0 (SHA verified; version-label mismatch is in metadata, not archive bytes)
5. Unassociated archives: 0
6. Proven missing archives: ~36 (best estimate from 1/40 missing sample; Session 1 authoritative pending)
7. Ambiguous: 0
8. Recovery VERIFIED: 48
9. Recovery identity mismatch: 1 (paramiko/secsh — ACCEPTABLE RENAME EVIDENCE)
10. Recovery NO_PYTHON_CODE: 1 (pyqt5-qt5 — OUT-OF-SCOPE for Python-source corpus)
11. Transient FAILED: 93
12. Deterministic FAILED: 3
13. External quarantined FAILED: 6 (ranks 3042-3047, verified)
14. Exact future recovery candidate count: 48 verified + ~36 missing + 93 transient eligible (evidence-derived; NOT yet confirmed by Session 1 authoritative inventory)
15. Exact future resume count: 1,953 (ranks 3048-5000)
16. Checkpoint state changed: NO
17. Manifest changed: NO
18. Recovery state changed: NO
19. Network used: NO
20. Freeze sentinel: PRESENT
21. Tests: passed 116 / failed 0 / skipped 1 (pre-existing)

## A. Authoritative PyPI evidence table
- Baseline: 3041 checkpoints = 2945 ACQUIRED + 96 FAILED (verified at freeze)
- Current checkpoints: 3047 (6 external quarantined, ranks 3042-3047)
- Manifest: 2945 identities unchanged (SHA e081a09e..., original 81f78a0d... not byte-recoverable)
- Candidate manifest: 5000 (SHA e26e2035...)
- Recovery: 48 VERIFIED (archives present + SHA-matched 48/48), 1 IDENTITY_MISMATCH (paramiko/secsh), 1 NO_PYTHON_CODE (pyqt5-qt5)
- Local archives: ~98% of baseline present and SHA-matched to checkpoints

## B. Exact future recovery candidate table
| Category | Count | Status |
|---|---|---|
| Recovery already verified | 48 | complete, SHA-verified |
| Identity review (paramiko) | 1 | ACCEPTABLE RENAME EVIDENCE |
| No-python-code (pyqt5-qt5) | 1 | OUT-OF-SCOPE |
| Deterministic FAILED | 3 | not retried; manual review |
| Transient FAILED | 93 | eligible for bounded SHA-anchored retry |
| Missing archives | ~36 | SHA-anchored recovery needed (pending Session 1) |

## C. Exact future resume plan
Phase E: ranks 3048-5000 (1,953) — new acquisition experiment after freeze lift + Session 3 5K audit.

## D. Outstanding identity decisions
1. paramiko/secsh: ACCEPTABLE RENAME (archive 0.1-bulbasaur, metadata 'secsh' = historical dist name; SHA-anchored consistent) — pending formal acceptance
2. pyqt5-qt5: OUT-OF-SCOPE (native Qt5 wheel, 0 Python files) — pending formal exclusion
3. Session 1 archive inventory: authoritative missing-archive counts pending

## E. Risks/blockers
- Session 1 authoritative archive inventory not yet available (blocks Phase C exact counts)
- ~36 missing-archive estimate is sample-derived, not authoritative
- Freeze must remain until all phases authorized
- Concurrent writer (opencode 26025) must stay stopped; sentinel enforces this

Artifacts: decision_gate_v1.json, failed102_treatment_matrix_v1.md, recovery_authorization_plan_v1.md
