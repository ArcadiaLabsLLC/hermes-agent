# R011 bounded read-epoch implementation — 2026-10-07

Base: `1655c0ab1fa437596d7aa07dcf9d9ba3a4025b40`; branch `grind/sol-runtime-20261007`; no advancing main integration.
Outcome: instance preparation and skill preparation reuse implemented; whole R011 remains pending its separate writer lease. No queue removal.

InstanceReadEpoch is explicitly owned by one message preparation. Roster ensure runs once per persona and shares one decoded PersonaInstanceScan with target projection. Before every reuse, fresh scandir fingerprints the entire canonical directory (name/device/inode/ctime/mtime/size); before/after mismatch or unknown receipt prevents caching. Mutable row containers are independently copied, unreadable counts preserved. Store writes and retirement invalidate; the epoch closes after target projection. Admission/uniqueness/binding and commit continue using fresh scan_all/get, including unchanged-directory reads and fail-closed corruption handling.
SkillPreparationEpoch belongs to the request's TurnRootRegistries. Required-preload, accessible rows and available catalog explicitly opt into one manifest snapshot; default skill_runtime_compatibility/tool authorization never uses it. The epoch closes before _run_model/provider work, so later explicit uses also fall back to fresh reads. A middle edit may leave the already assembled preparation snapshot coherent, while fresh authorization observes it immediately; invalidate/new request observes it too. Absolute candidate paths isolate roots/profiles. Existing parse_cache now includes device/inode/ctime to reject same-mtime/same-size replacement; no new cross-turn TTL cache or permission policy.

Measured same synthetic sizes (no operator data):

| two evaluations | baseline | epoch | observed local time |
|---|---|---|---|
| 256 instance rows | 512 JSON reads | 256 JSON reads, 3 fingerprints / 768 directory stat receipts / 0 pathname file-stat probes | 140.433 -> 76.994 ms |
| 186 warm skill manifests | 372 stats, 0 reads | 186 stats, 0 reads; next request checks all 186 again | 60.882 -> 36.695 ms |

The first implementation's pathname validation/deepcopy was slower (144.191 -> 248.223 ms); it was corrected before delivery using fresh DirEntry enumeration metadata and slot-aware mutable-container copies. Timings are single isolated owner samples, not end-to-end context/turn guarantees; required fingerprints and authoritative scans remain.
Focused proof: initial 35 explicit epoch/cache/record-once tests green; 20 final explicit epoch/cache tests plus one real chat success node green; after clone optimization, 19 epoch/census tests green; final real chat node 1 green; actual preload/catalog shared-epoch node 1 green; stronger unchanged-stamp write + retirement nodes 2 green; final census 2 green. Final changed-file Ruff passes (12 files). These batches overlap; do not add their counts as unique suite coverage.
Five killing controls each fail the intended assertion: disable instance memo (512 !=256 reads); disable skill memo (372 !=186 stats); route uniqueness through epoch (missing256 fresh reads); restore duplicate ensure (4 !=2 calls); restore old parse key (same-mtime replacement yields old surface). Exact production bytes restored in finally.
Cases: creation/deletion/file rename/display edit/corruption/replacement, mutable-row poison, root/profile separation, concurrent instance and skill requests, manifest denial recovery, fresh admission owner/corruption reads, actual roster/target and preload/catalog wiring, and real message terminal persistence.
Evidence copies: outputs/runtime-read-epochs-{integration,final,optimized,census-final,callers,chat-final,writes}.log; outputs/runtime-read-epochs-{instance,skill,authority,ensure,replacement}-red.log; outputs/runtime-read-epoch-census.py. Reproduction uses only those named tests in the retained worktree.
All product edits are fork-owned; no upstream hunks, footprint fixture or Job2 changes. Tracked tree will be clean after scoped push; prior untracked evidence, QA patch and new census probe retained. No full suite, root analyzer or main landing.
Next: parent batch review. Writer lease remains a local, separate lifetime slice covering turn failure/finally and off-path finalizer reference transfer; do not declare R011 DONE. No self-dispatch. Approximately 35 scoped tool calls including checkpoint publication; no agents.
