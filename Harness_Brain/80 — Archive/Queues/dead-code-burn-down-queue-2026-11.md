---
type: queue-archive
queue: dead-code-burn-down-queue.md
program: downstream-refactor
month: 2026-11
---

Closed rows of `dead-code-burn-down-queue.md` for 2026-11; appended by the close commits, never edited.

- **`FORK-BUNDLE-PROFILES-SDK-PACK-TEST-HANGS` — The bundle-profiles check that each provider SDK left out of the wheel ships as its own pack finishes instead of hanging** · group: hermes-test-isolation · `tests/…/test_bundle_profiles.py::test_each_provider_sdk_the_wheel_omits_ships_as_its_own_pack` · seen 2026-11-10 on Linux by w1110a-hm2 in a 2231-test persona/profile/snapshot/sync run (after fc61452c9a): the test hung and was skipped to finish the run; find what it waits on (a subprocess, a network fetch, a lock) and bound it · DONE 2026-11-10 137f34928f · result: nothing waited: CPU re-parse of every installed METADATA per closure walk; reproduced timeout at 1/16 core share, now 19 s < 30 s; requires/_req/uv.lock memoized, mapping lazy
