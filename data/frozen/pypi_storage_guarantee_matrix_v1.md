# SESSION 2 — PYPI STORAGE ABSTRACTION GUARANTEE MATRIX + FAILURE-MODE TABLE

## 13. GUARANTEE MATRIX
Classification: A = proven by code/tests · B = dependent on rclone behavior ·
C = dependent on Google Drive behavior · D = dependent on external coordination ·
E = not guaranteed

| Guarantee | Class | Notes |
|---|---|---|
| Logical path model (no hardcoded /mnt) | A | PathRegistry; must be implemented + tested |
| Backend abstraction (POSIX+remote) | A | injectable backend interface |
| Freeze enforcement (fail-closed) | A | storage-abstraction check; unreachable => refuse |
| POSIX atomic rename (local) | A | tmp+replace on real FS |
| Remote atomic rename | E | GDrive/rclone has NO POSIX atomic rename; copy->move != rename |
| Remote conditional no-overwrite create | E | GDrive lacks atomic conditional create; must be emulated + verified |
| Checkpoint crash-safety (temp+verify+promote+RAW) | B | depends on rclone upload/hash reliability |
| Archive immutability (no silent replace) | B | enforced by no-overwrite promotion |
| Manifest torn/concurrent protection | B | temp+verify+promote; NOT truly atomic on GDrive |
| Recovery state isolation | A | separate namespace + skip-existing |
| Writer lease atomicity | E | lock file NOT atomic on GDrive; advisory only |
| Lease expiry/heartbeat/stale detection | D | needs clock + external coordination; best-effort |
| Read-after-write consistency | B | depends on GDrive eventual consistency + rclone read-back |
| Resume boundary preservation | B | derived from committed objects only |
| Remote headroom determination | B | depends on rclone/Drive quota API; fail-closed fallback |
| Historical immutability (ACQUIRED/FAILED preserved) | A | freeze + no-overwrite + separate namespaces |
| Session 4 isolation (no PyPI writes by GitHub process) | A | GitHub writes only github paths; must be tested |

## FAILURE-MODE TABLE
| Failure | Detection | Containment |
|---|---|---|
| Partial/torn upload | size+hash verify on temp before promote | temp never promoted; orphan cleanup |
| Interrupted upload | temp present, final absent | retry from temp or discard; final never partial |
| Duplicate checkpoint | conditional no-overwrite on final | reject if final exists |
| Stale temp object | temp age/owner | garbage-collect with lease window |
| SHA mismatch | hash of read-back vs expected | refuse commit; mark failed |
| Missing remote object | existence check post-write | retry; fail closed if unverifiable |
| Freeze sentinel unreachable | backend probe fails | FAIL CLOSED (no writes) |
| Two writers | lease conflict + freeze check | second writer refused |
| Expired/stale lease | lease expiry + heartbeat | safe takeover with owner verification |
| Concurrent manifest update | no-overwrite promote | last-writer-not-atomic; refuse overlap |
| Archive/checkpoint mismatch | checkpoint references archive SHA | verify before commit; mismatch => reject |
| Resume-boundary corruption | derive from committed checkpoints only | never from partial objects |
| Remote capacity unknown | headroom probe fails | fail closed |
