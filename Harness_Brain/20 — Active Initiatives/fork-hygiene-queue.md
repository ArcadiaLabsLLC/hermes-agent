---
type: queue
program: fork-hygiene
status: open
tags: [queue, program/fork-hygiene]
---

# Fork hygiene — open queue

## Tasks — 2026-11-09 (owner: every row belongs to a task; plan QUEUE_TASKS_AND_SUBTASKS)

- **`TASK-HERMES-TEST-ISOLATION` — Agent engine tests: a run never hangs, leaks onto your machine or breaks on Windows** · task: hermes-test-isolation · 8 subtasks on 2026-11-10 (4 ready, 4 deferred) · DEFERRED 2026-11-10: every subtask is deferred  · unblocked 2026-11-10: owner deferral triage ("rest of the triage is good") reopened `RT-WRITING-COMMAND-HOME-SKELETON`; 9 deferred rows archived · handoff 2026-11-09: w1109a-hm-iso closed FH-LIVE-GUARD-PATH-READ-AS-SPAWN (3e0292cfe4) and FH-WORK-STORE-FIXTURE-LOST-IN-ONE-PROCESS (147d9316f6, a pytest 9.1 Dir-node conftest bug fenced by regrouping args); the two READY rows left (RT-WINDOWS-BASELINE-REGRESSIONS, FH-PYTEST-HOME-BIN-LEAKS-INTO-USER-PATH) need a Windows box, their rows carry the steps · handoff 2026-11-10 (w1110a-org): recounted — `FORK-BUNDLE-PROFILES-SDK-PACK-TEST-HANGS` (READY, filed today) was uncounted, and `FORK-NEMO-PYD-OLD-DELETE` (delete the retired shared test venv) moved in from embedded-hermes · handoff 2026-11-10 (w1110b-hm): closed FORK-BUNDLE-PROFILES-SDK-PACK-TEST-HANGS (137f34928f: nothing waited, a CPU-bound closure walk that re-parsed every installed METADATA per walk; memoized, reproduced timeout at a 1/16 core share now passes); READY left: FH-GUARD-PROBE-SCAN-RED-WINDOWS (a Windows box) · handoff 2026-11-10 (w1110d-hm2): closed RT-WRITING-COMMAND-HOME-SKELETON (2a10c0de0c: the control's SOUL.md expectation was stale on a box whose git reads no checkout identity; qualified both ways); no READY subtask left — every remaining subtask is DEFERRED
- **`TASK-PREPUSH` — Agent engine checks: pre-push, CI and the full suite run fast and alike on every machine** · task: prepush · 12 subtasks on 2026-11-10 (8 ready, 1 blocked, 3 deferred) · READY 2026-11-09 · handoff 2026-11-10: w1110c-hmprepush closed LINE-ENDINGS-MEMO-RED-WINDOWS (7b3e61beeac) and cut the Windows gates step 98 s red -> 32 s (9d87a13109c) and made heavy files shard on Windows (60cb78a0020); the 4 READY rows left are measurement work for an idle Windows box: GATES-OVER-BUDGET (start-up cost, not a gate), TOUCHED-NAMED-HEAVY-OVER-BUDGET (one 36 s room test), and the new PREPUSH-SH-TEST-SLOW-WINDOWS and DOC-CITE-OVER-BUDGET · handoff 2026-11-10 (w1110c-hm2): closed HELPER-NAME-ANSWER-TWO-OWNERS (ca01c1e694e) and DOC-CITE-OVER-BUDGET (23b58f843ce, a suffix index; idle 1.9 -> 1.5 s), refuted PREPUSH-SH-TEST-SLOW-WINDOWS (designed waits, already sharded by 60cb78a0020), cut the row guard 3.75 -> 1.63 s toward GATES-OVER-BUDGET (92d119a3f68; gates 16.2 s at load 3, still over its 10 s budget on Windows start-up), filed CENSUS-OVER-BUDGET (36.3 s at load 14); READY left: GATES-OVER-BUDGET and CENSUS-OVER-BUDGET (need an idle Windows box, load < 2), TOUCHED-NAMED-HEAVY-OVER-BUDGET (untouched: speed the 36 s twelve-member room test) · handoff 2026-11-10 (w1110c-hm3): closed TOUCHED-NAMED-HEAVY-OVER-BUDGET (5cd83a166db: twelve-member test 35-38 s -> 23-25 s at CPU ~95 %) and verified WINDOWS-EOL-COLD-ARGV cold (e40ba3032b); filed EOL-GATE-COLD-TIMEOUT; READY left need an idle Windows box: GATES-OVER-BUDGET, CENSUS-OVER-BUDGET, WORK-V1-CLAIM-GATES-WINDOWS-BUDGET, plus EOL-GATE-COLD-TIMEOUT · handoff 2026-11-10 round 2 (w1110c-hm3, box at CPU 100 %): 8 -> 5 python starts before the first test (60ae94b5331) and imports found once per tree (11e28051026, no measured win); prepush on 11e28051026 still kills gates at 22.0 s (load 101) — the rest waits on `FH-UPSTREAM-RUNNER-ONE-PROCESS-GROUP` (owner decision) and idle-box readings; filed `FH-UPSTREAM-RUNNER-ONE-PROCESS-GROUP`; touched step 85.3 s (load 64) and 68.5 s (load 61) here, all `tests/agent_runtime/test_discussion_runtime.py` (41-59 s alone) — belongs on w1110c-hmssh's `FH-PREPUSH-TOUCHED-OVER-BUDGET` once it lands; claim released · handoff 2026-11-10 (w1110c-hm3b): `FH-UPSTREAM-RUNNER-ONE-PROCESS-GROUP` ruled fork-side and worked — the bundled runner's leftovers scan 37.5 s -> 3 s (a4c298593b4); the gates stay per-file until the bundled runner has a small-run path (~20 s of landing-gate work); claim released
- **`TASK-UPSTREAM-FOOTPRINT-LEDGER` — Agent engine: carry as little as possible on top of upstream, fixing bugs where they live** · task: upstream-footprint-ledger · 40 subtasks on 2026-11-10 (14 ready, 3 blocked, 23 deferred) · READY 2026-11-10 · handoff 2026-11-09: FH-UP-FP-FIXTURE-LAGS-MAIN filed READY by w1109a-hm-2 · handoff 2026-11-10 (hm-release): the v0.23.1 release merge (branch `merge/upstream-v0.23.1`) closed four upstream-settled rows and refuted UP-TOOL-REQUEST-MIDDLEWARE-ORIGINAL-ARGS; filed eleven READY rows (the stale sync-gate script, footprint moves the merge measured, main reds it met, the PR rebase list) and two owner decisions · **TAKEN 2026-11-10 w1110d-foot on nekwo-ubuntu24 as nekwo in hm-w1109a-misc**
- **`TASK-UPSTREAM-LOAD-FLAKES` — Agent engine tests: every test passes on main, even when the machine is busy** · task: upstream-load-flakes · 26 subtasks on 2026-11-10 (3 ready, 23 deferred) · DEFERRED 2026-11-10: every subtask is deferred; owner kept SessionDB at FULL ("keep it durable") and RT-SESSIONDB-FULL-COMMIT-HOLDS-ROOM-LOCK closed as accepted · handoff 2026-11-09: w1109a-hm-2 landed the owner's ruling (room and run stores synchronous=NORMAL, attempt receipts FULL, bfabe63fb5) and a WAL keeper connection (1ebe8ba237); RT-FLAKE-NATIVE-DISCUSSION-ROOM-DB-LOCKED stays READY, 0/40 with and without the keeper at 4+4 dd writers, so the red needs reproducing on current main before it can close (its row); the rest are DEFERRED · handoff 2026-11-10 (w1110b-hm): closed RT-FLAKE-NATIVE-DISCUSSION-ROOM-DB-LOCKED (51e7acc4f5: FULL turn receipts moved off the shared state.db lock into discussion_attempts.db, old builds fenced); filed READY RT-SESSIONDB-FULL-COMMIT-HOLDS-ROOM-LOCK (SessionDB's own FULL commits on state.db, the remaining holder) and FH-E2E-KANBAN-ROUTING-RED-ON-MAIN (two e2e files red alone on main) · handoff 2026-11-10 (w1110d-hm): closed FH-E2E-KANBAN-ROUTING-RED-ON-MAIN (79187696dc: no hang, both files' fixtures run real hermes children past the 30 s cap; per-file timeout marks); RT-SESSIONDB-FULL-COMMIT-HOLDS-ROOM-LOCK set to an owner decision (every fix that frees the room flow lowers chat durability or leaves it waiting on state.db)

## Owner request — 2026-11-08 (hermes prepush: a tight cap, an overrun report, fast)


## Filed on arrival — 2026-11-10 (lane w1110c-hm3)

- **`FH-UPSTREAM-RUNNER-ONE-PROCESS-GROUP` — The pre-push gates run in one test process instead of one per file, cutting Windows start-up cost** · group: prepush · `scripts/prepush.sh` gates step, `scripts/run_tests_bundled.py` · found 2026-11-10 by w1110c-hm3 on DESKTOP-QJ7DDV2: the 9 gate files in one pytest process took 34.7 s vs a 92 s runner wall at load 99 (~2.8 CPU-s per pytest start); the fork never edits upstream, so this is an upstream issue or PR for a 'one process for these files' option, then a fork call site in `scripts/prepush.sh` · READY 2026-11-10 · RULED 2026-11-10: owner — no upstream PRs/issues (owner at the PR limit); do it in fork-owned files · handoff 2026-11-10 (w1110c-hm3b, CPU 65-99 %): the fork's own multi-file runner `scripts/run_tests_bundled.sh` runs the 9 gates as 3 bundles in 12-17 s against 21-27 s per-file, keeping the isolation re-run (a red member re-runs alone, a red-bundled-green-alone is named a leak), but its whole wall was 139 s and 300 s+ (it waits for the machine-wide heavy-run slot; `ETERNIA_HEAVY_SLOTS=off` fixes that), then 49-52 s with `--no-cache` — 37.5 s of it the end-of-run leftovers scan, now 3 s (a4c298593b4) — and still 30-41 s against per-file 20-32 s: ~20 s of landing-gate work stays (fork scope ~3.5 s, skip list and solo plan ~5.7 s, run tail and record ~10 s), so the gates were NOT moved; the routing (gates runner, slot off, 2 tests, 3 mutations red) is kept off-tree by the lane; next: a small-run path in `run_tests_bundled.py` that skips scope, plan and record for named files, then re-route
- **`FH-EOL-GATE-COLD-TIMEOUT` — On a fresh clone or a new machine the first run of the line-endings check is killed for time, so a first push reds until someone re-runs it** · group: prepush · `tests/test_line_endings.py::endings` · found 2026-11-10 by w1110c-hm3 on DESKTOP-QJ7DDV2: with no `hermes-eol-memo.json` the module fixture classifies all 24,366 blobs with `git ls-files --eol` in ~49 chunks of 500 literal pathspecs; the run took 62.7 s (load ~45) and under the default `--timeout=30` the fixture is killed (40 s wall, exit 1); warm it is 6.5 s; measure one pathspec-free `git ls-files --eol` census against the chunks cold before choosing (the docstring's 87 s whole-tree number is from load ~50), never a raised timeout without an idle measurement · REQUIRES windows · READY 2026-11-10
- **`FH-GROUP-COMPUTE-QUESTION-RED-WINDOWS` — On a busy Windows box the group-compute discussion test fails because the agent's question never shows up in the room within 30 seconds** · group: hermes-test-isolation · `tests/agent_runtime/test_discussion_group_compute.py::test_compute_question_lost_answer_ack_and_confirmed_stop` · found 2026-11-10 by w1110c-hm3 on DESKTOP-QJ7DDV2 (CPU 96-100 %, msys load ~85): red 3 of 3 alone (37.7 s, 108 s, and 79.8 s on HEAD 03d778447a1 without 5cd83a166db), so pre-existing; the view shows the task `running` with no question when `until` (30 s) expires; re-run on an idle box first, then trace whether ProfileTurns' observe ever reports the request · REQUIRES windows · READY 2026-11-10

## Filed on arrival — 2026-11-09 (lane w1109a-hm-2)

- **`FH-PREPUSH-CENSUS-OVER-BUDGET` — On a busy Windows box the pre-push name census runs past its thirty-second budget, so a lane touching Python waits longer than the check says** · group: prepush · `tests/tooling/test_no_ladder_routing.py` · found 2026-11-10 by w1110c-hm2 on DESKTOP-QJ7DDV2: step `census` 36.3 s against 30 s (deadline 60 s, exit 0, load 13.94, head 92d119a3f68, `_lane_logs/prepush_overruns.jsonl`); `test_no_ladder_routing.py` 28.75 s and `test_duplicate_helper_bodies.py` 12.71 s in the runner (12.8 s alone at lower load); measure the ladder census alone on an idle box, then profile its walk (`scripts/census_pool.py` chunks) before any change · REQUIRES windows · READY 2026-11-10 · handoff 2026-11-10 (w1110c-hm3): the box never went idle in this lane's window (msys load 18-87, CPU 82-100 %); no idle reading taken, nothing changed — still needs load < 2 · handoff 2026-11-10 round 2 (w1110c-hm3, CPU 100 % throughout): the census finds each file's imports by walking statements only, once per tree (11e28051026, equal to `ast.walk` order over 12,833 files) — serial `ladder_census` A/B 41.2 s before vs 40.9 s after on a warm cache, so no measured win; a pool kept across the census passes measured 42.0/39.0 s vs 42.2/70.2 s but moved ~20 s into process exit, inconclusive and NOT landed (patch kept off-tree by the lane); `test_no_ladder_routing.py` also hit its 30 s per-test limit at load 23-88 (42-54 s), so the step is red under load, not only slow — still needs an idle-box reading

## Filed on arrival — 2026-11-09 (lane w1109a-hm-iso)


## Filed on arrival — 2026-11-09 (stale-headers lane)


## Filed on arrival — 2026-11-08 (lane w1108c-hm-reds-upstream)

- **`FH-FLAKE-API-ADMISSION-OFF-LOOP-UNDER-LOAD` — `tests/gateway/test_api_admission_off_loop.py::test_admission_waits_for_the_writer_off_the_owner_loop[chat]` is a load flake — red in the w1108c verification daily run on hermes main 3615f904bc (quiet box, suite at -j 24), green alone on the same commit; find what it waits on under -j 24 and wait on that event, never a bare retry** · group: upstream-load-flakes · `tests/gateway/test_api_admission_off_loop.py` · found 2026-11-08 by the w1108c orchestrator (FH-W1108C-WAVE-END-REDS verification run) · DEFERRED 2026-11-09: owner triage — Test-only timing flake; the product itself is not shown broken; until the owner reopens it
- **`FH-FLAKE-SESSION-AUTHORITY-OWNER-KILL-UNDER-LOAD` — `tests/gateway/test_session_authority.py::test_native_queue_survives_owner_kill_without_replaying_unknown` is a load flake — red in the w1108c verification daily run on hermes main 3615f904bc (quiet box, suite at -j 24), green alone on the same commit; find what it waits on under -j 24 and wait on that event, never a bare retry** · group: upstream-load-flakes · `tests/gateway/test_session_authority.py` · found 2026-11-08 by the w1108c orchestrator (FH-W1108C-WAVE-END-REDS verification run) · DEFERRED 2026-11-09: owner triage — Test-only timing flake; the product itself is not shown broken; until the owner reopens it
- **`FH-FLAKE-BROWSE-SCHEMA-DRIFT-CONCURRENT-UNDER-LOAD` — `tests/hermes_cli/test_browse_schema_drift.py::test_concurrent_browses_from_processes_all_succeed` is a load flake — red in the w1108c verification daily run on hermes main 3615f904bc (quiet box, suite at -j 24), green alone on the same commit; find what it waits on under -j 24 and wait on that event, never a bare retry** · group: upstream-load-flakes · `tests/hermes_cli/test_browse_schema_drift.py` · found 2026-11-08 by the w1108c orchestrator (FH-W1108C-WAVE-END-REDS verification run) · DEFERRED 2026-11-09: owner triage — Test-only timing flake; the product itself is not shown broken; until the owner reopens it
- **`FH-LINUX-BOX-NO-NODE-UPSTREAM-REDS` — nekwo-ubuntu24 has no `node`/`npm` on PATH, so three upstream-manifest files are red alone on main 95ca419262 (`scripts/run_tests.sh <file>`): `tests/hermes_cli/test_tui_npm_install.py` (2 failed 7 errors: `os.symlink(None, …)` from `shutil.which("node")`), `tests/hermes_cli/test_web_ui_build.py` (2 failed 6 errors, same None), `tests/plugins/platforms/photon/test_spectrum_patch.py` (2 failed: `FileNotFoundError: 'node'`); the skip-listed `test_source_build.py` / `test_desktop_update_verify.py` fail the same way when named; either provision node on the box (PM's pinned node, or a system package) or skip-list each file `env: no node on the Linux box` after one bare red, never both** · group: prepush.linux-box-env · `tests/fixtures/upstream_skip_list.txt` · found 2026-11-08 by w1108c-hm-reds-upstream (FH-W1108C-WAVE-END-REDS) · READY 2026-11-10 · RULED 2026-11-10: owner approved reopening it ("approved all of em") · unblocked 2026-11-10: owner reopened it · handoff 2026-11-10: reopened for the Linux box (w1110c triage); the Windows box does not take it 
- **`FH-LINUX-BOX-NO-RIPGREP-SEARCH-REDS` — nekwo-ubuntu24 has no `rg`, so the search tool falls back to grep and two upstream files are red alone on main: `tests/tools/test_search_auto_multiline.py::TestAutoMultiline::test_newline_regex_matches_across_lines` (grep cannot match across lines: total_count 0) and four `TestZeroMatchProbe` nodes of `tests/tools/test_search_zero_match_and_multipath.py` (`_zero_match_probe` returns None without rg, so no hint); install ripgrep on the box or skip-list the nodes `env: missing ripgrep`** · group: prepush.linux-box-env · `tools/file_operations_search.py` · found 2026-11-08 by w1108c-hm-reds-upstream (FH-W1108C-WAVE-END-REDS) · READY 2026-11-10 · RULED 2026-11-10: owner approved reopening it ("approved all of em") · unblocked 2026-11-10: owner reopened it · handoff 2026-11-10: reopened for the Linux box (w1110c triage); the Windows box does not take it 
- **`FH-FLAKE-SCHEDULER-PROVIDER-RECOVERY-THREAD` — `tests/cron/test_scheduler_provider.py::test_multiplex_recovery_isolates_profile_failures` is a load flake: red in the w1108c wave-end daily run on main f353a2a4ed (run beside Eternia's full fake tier) — the recovery thread was still alive at the assert (`assert not True`, `is_alive()`, line 837; log: `unable to open database file` for the failing profile) — yet green alone 3 of 3 and once under `-j 24` on main 95ca419262; join the recovery thread on its own completion event, not a fixed wait, never a bare retry** · group: upstream-load-flakes · `tests/cron/test_scheduler_provider.py` · found 2026-11-08 by w1108c-hm-reds-upstream (FH-W1108C-WAVE-END-REDS) · DEFERRED 2026-11-09: owner triage — Test-only timing flake; the product itself is not shown broken; until the owner reopens it
- **`FH-FLAKE-API-PENDING-DAEMON-DEADLINE` — `tests/gateway/test_api_pending_daemon.py::test_api_and_ws_pending_controls_share_identity` is a load flake: red in the w1108c wave-end daily run on main f353a2a4ed (run beside Eternia's full fake tier) — a loop-time deadline passed (`assert loop.time() < deadline`, line 94) — yet green alone 3 of 3 and once under `-j 24` on main 95ca419262; make the wait event-driven or its budget load-proof, never a bare retry** · group: upstream-load-flakes · `tests/gateway/test_api_pending_daemon.py` · found 2026-11-08 by w1108c-hm-reds-upstream (FH-W1108C-WAVE-END-REDS) · DEFERRED 2026-11-09: owner triage — Test-only timing flake; the product itself is not shown broken; until the owner reopens it
- **`FH-FLAKE-EXECUTE-CODE-GATE-LOOP-TICK` — `tests/gateway/test_local_turn_origin_execute_code_gate.py::test_only_the_viewers_own_turn_skips_the_whole_script_gate` is a load flake: red in the w1108c wave-end daily run on main f353a2a4ed (run beside Eternia's full fake tier) — `timed out after 10s waiting for the /loop tick` (`tests/waiting.py:75`) — yet green alone 3 of 3 and once under `-j 24` on main 95ca419262; wait on the tick event, not a 10 s budget, never a bare retry** · group: upstream-load-flakes · `tests/gateway/test_local_turn_origin_execute_code_gate.py` · found 2026-11-08 by w1108c-hm-reds-upstream (FH-W1108C-WAVE-END-REDS) · DEFERRED 2026-11-09: owner triage — Test-only timing flake; the product itself is not shown broken; until the owner reopens it
- **`FH-FLAKE-LOCAL-SESSION-APPROVAL-CHILD` — `tests/gateway/test_local_session.py::test_fresh_local_session_owns_execution_across_viewers[approval]` is a load flake: red in the w1108c wave-end daily run on main f353a2a4ed (run beside Eternia's full fake tier) — its child probe exited 1 with an asyncio timeout (`assert 1 == 0`, line 22) — yet green alone 3 of 3 and once under `-j 24` on main 95ca419262; give the child's waits a load-proof budget or an event, never a bare retry** · group: upstream-load-flakes · `tests/gateway/test_local_session.py` · found 2026-11-08 by w1108c-hm-reds-upstream (FH-W1108C-WAVE-END-REDS) · DEFERRED 2026-11-09: owner triage — Test-only timing flake; the product itself is not shown broken; until the owner reopens it
- **`FH-FLAKE-SHARED-BUSY-RECEIVE-DEADLINE` — `tests/gateway/test_shared_busy_receive_loop.py::test_busy_follow_up_returns_after_commit_and_is_answered_once` is a load flake: red in the w1108c wave-end daily run on main f353a2a4ed (run beside Eternia's full fake tier) — a loop-time deadline passed (line 70) — yet green alone 3 of 3 and once under `-j 24` on main 95ca419262; make the wait event-driven or load-proof, never a bare retry** · group: upstream-load-flakes · `tests/gateway/test_shared_busy_receive_loop.py` · found 2026-11-08 by w1108c-hm-reds-upstream (FH-W1108C-WAVE-END-REDS) · DEFERRED 2026-11-09: owner triage — Test-only timing flake; the product itself is not shown broken; until the owner reopens it
- **`FH-FLAKE-WEBHOOK-AUTHORITY-CHILD` — `tests/gateway/test_webhook_authority.py::test_signed_webhook_storage_failure_is_retryable` is a load flake: red in the w1108c wave-end daily run on main f353a2a4ed (run beside Eternia's full fake tier) — its child exited 1 inside `asyncio.to_thread(peer.blocked.wait, 10)` (`assert 1 == 0`, line 15) — yet green alone 3 of 3 and once under `-j 24` on main 95ca419262; make the child's 10 s wait load-proof or event-driven, never a bare retry** · group: upstream-load-flakes · `tests/gateway/test_webhook_authority.py` · found 2026-11-08 by w1108c-hm-reds-upstream (FH-W1108C-WAVE-END-REDS) · DEFERRED 2026-11-09: owner triage — Test-only timing flake; the product itself is not shown broken; until the owner reopens it
- **`FH-FLAKE-SESSION-CONFIG-PROJECTION-PROVIDERS` — `tests/gateway/test_session_config_projection.py::test_model_options_uses_frozen_selection_without_composer_global_writes` is a load flake: red in the w1108c wave-end daily run on main f353a2a4ed (run beside Eternia's full fake tier) — the providers list differed (line 86): a non-timing diff, so suspect a catalog/auth read that races under load — yet green alone 3 of 3 and once under `-j 24` on main 95ca419262; find which provider read differs before any budget change, never a bare retry** · group: upstream-load-flakes · `tests/gateway/test_session_config_projection.py` · found 2026-11-08 by w1108c-hm-reds-upstream (FH-W1108C-WAVE-END-REDS) · DEFERRED 2026-11-09: owner triage — Only seen under heavy test load; no user report; until the owner reopens it
- **`FH-FLAKE-CONNECTOR-OPERATION-RPC-NO-REPLY` — `tests/tui_gateway/test_connector_operation_rpc.py::test_panel_connect_reissues_only_a_dead_link` is a load flake: red in the w1108c wave-end daily run on main f353a2a4ed (run beside Eternia's full fake tier) — `AssertionError: no reply` from `_connect_rpc` (line 85) — yet green alone 3 of 3 and once under `-j 24` on main 95ca419262; make the RPC wait load-proof or event-driven, never a bare retry** · group: upstream-load-flakes · `tests/tui_gateway/test_connector_operation_rpc.py` · found 2026-11-08 by w1108c-hm-reds-upstream (FH-W1108C-WAVE-END-REDS) · DEFERRED 2026-11-09: owner triage — Test-only timing flake; the product itself is not shown broken; until the owner reopens it
- **`FH-FLAKE-PM-STREAMING-DEADLINE-UNDER-LOAD` — `tests/pm/test_environment_build.py::test_streaming_deadline_includes_inherited_stdout[environment-True]` asserts the build's stdout drain ends within `timeout + 2` s and was red at `-j 6` beside other lanes (`assert (… - …) < (2 + 2)`: 11 s), green in 3 of 3 alone runs; a wall-clock margin of 2 s cannot hold on a loaded 52-core box — measure the drain against the child's own exit instead** · group: upstream-load-flakes · `tests/pm/test_environment_build.py` · found 2026-11-08 by w1108c-hm-reds-upstream (FH-W1108C-WAVE-END-REDS) · DEFERRED 2026-11-09: owner triage — Test-only timing flake; the product itself is not shown broken; until the owner reopens it

## Filed on arrival — 2026-11-08 (lane w1108a-hm-reds)

- **`FH-REPLICA-TRAVEL-ALLOWLIST-TWO-COPIES` — the persona-instance travel allowlist is applied twice on the adopt arm: `agent_runtime/persona_assignments/replicate.py::replicate_instance` copies `PERSONA_INSTANCE_TRAVEL_FIELDS` from the body, then `PersonaInstanceStore._write`'s `CharacterAssignmentReplication` branch re-reads the stored row and copies the same allowlist again, so mutating either copy alone is invisible on adopt (claim `ir-h3-the-store-door-writes-the-whole-remote-body` had to move to a mint-arm test); decide the one owner (the store write, which also covers freshness) and make the door hand it the body, or name why both stay** · group: agent-config-cleanup · `agent_runtime/persona_assignments/replicate.py` · `agent_runtime/persona_assignments/store.py::_write` · found 2026-11-08 by w1108a-hm-reds while closing FH-MUTATION-CLAIM-IR-H3-UNANCHORED · DEFERRED 2026-11-09: owner triage — Code tidiness; behaviour is correct today; until the owner reopens it
- **`FH-RUF022-UNSORTED-ALL-ON-MAIN` — `ruff check` (repo config) reds RUF022 `__all__` is not sorted on origin/main in `agent_runtime/mission_chat_outcome.py` and `agent_runtime/call_authorization.py`; sort both (`ruff check --fix --select RUF022`) in a commit of their own** · group: upstream-load-flakes · `agent_runtime/mission_chat_outcome.py` · `agent_runtime/call_authorization.py` · found 2026-11-08 by w1108a-hm-reds (origin/main 8f09900cd3) · DEFERRED 2026-11-09: owner triage — Pure style nit, one-minute fix whenever convenient; until the owner reopens it

## Filed on arrival — 2026-11-08 (lane w1108a-land-hm)


## Filed on arrival — 2026-11-06 (lane w1106b-hm)


## Filed on arrival — 2026-11-06 (lane w1106a-hm)


## Filed on arrival — 2026-11-05 (lane w1105h-hm)

- **`FH-LINUX-SOURCE-UPDATE-FILES-RED-ON-MAIN` — five source/update test files are red ALONE on `origin/main` 2f5f1a9079 on the Linux box (nekwo-ubuntu24, run under `unshare --user --pid`): `tests/hermes_cli/test_source_build.py` (13, setup: `source-build integration requires node and npm` — no node on the scrubbed PATH), `tests/scripts/test_source_driver.py` (7, `assert node`), `tests/hermes_cli/test_update_finish.py` (13, `Update completion failed: No module named 'agent_runtime'` from the minted update tree), `tests/pm/test_environment_build.py::test_first_bundle_extension_preserves_shipped_extras` (pm worker `sync_venv` readline timeout) and `tests/e2e/core/upgrade/test_upgrade_path.py` (`template_home` seed run timeout); either provision/skip by name what the host lacks or fix the minted tree, so a lane's blast-radius run reads green** · group: prepush · fork / the suite · `--confirm-red` verdict pre-existing for each (lane w1105h-hm) · filed by lane w1105h-hm 2026-11-05 · READY 2026-11-10 · RULED 2026-11-10: owner approved reopening it ("approved all of em") · unblocked 2026-11-10: owner reopened it · handoff 2026-11-10: reopened for the Linux box (w1110c triage); the Windows box does not take it 

## Filed on arrival — 2026-11-02 (appearance acceptance)


## Filed on arrival — 2026-11-02 (landing w1101e, hermes)


## Filed on arrival — 2026-11-01 (profile artwork qualification)


## Filed on arrival — 2026-10-30 (owner: push checks hang)


## Filed on arrival — 2026-10-29 (land w1029a-h)


## Filed on arrival — 2026-10-29 (lane w1029a-h-fork)


## Filed on arrival — 2026-10-27 (lane w1027k-plan-misc, launcher)


## Filed on arrival — 2026-10-27 (lane w1027j-h-tri-b, planned/ triage)

- **`FH-SEAMS-PLAN-STAGE-3-AND-7` — the seams plan's Stages 0, 1, 4, 5 and 6 are on main and Stage 2's leftovers are `RT-NINE-STAGE-2-ROWS`; left are Stage 3 (upstream PRs P1–P5, each with its pre-decided fallback) and Stage 7 (the detach read, when `[up-fp]` reads zero or only carry-permanent rows)** · group: upstream-footprint-ledger.harness-plugin-and-upstream-seams · fork / upstream sync · plan `docs/agent-runtime-harness/planned/harness-plugin-and-upstream-seams.md` §2 Stage 3, Stage 7 · DEFERRED 2026-10-27: owner 2026-10-24 — "defer prs but make sure the code needed is on our main"; until the owner opens the PRs
- **`FH-RECORDED-PARALLELS-PAR-2-6` — the recorded-parallels sheet's PAR-1 landed (`10446d5e43` and the tool-search spellings); PAR-2..PAR-6 each wait on one of seven held upstream PRs (`store-home-override`, `persisted-row-hooks`, `skills-extra-dirs`, `tool-search-never-defer`, `credential-pool-pick-and-rotate`, `public-drain-fd`, `local-runtime-knobs`), and row 9 closes when the launcher installs from pm bundles** · group: upstream-footprint-ledger.recorded-parallels · fork / upstream sync · plan `docs/agent-runtime-harness/planned/recorded-parallels-2026-09-26.md` §3 · DEFERRED 2026-10-27: owner 2026-10-24 — "defer prs but make sure the code needed is on our main"; until the owner opens the PRs
- **`FH-DEFER-PR-REGISTRY-SNAPSHOT-RESTORE` — S5 of the process-global reset (an upstream `tools/registry.py` snapshot/restore door) is drafted as a PR body and not posted; the fork's fixture `tests/_downstream/tool_registry_scope.py` switches to the door when it merges** · group: upstream-footprint-ledger · fork / upstream PR branches · `docs/agent-runtime-harness/upstream-prs/registry-snapshot-restore-body.md` · DEFERRED 2026-10-27: owner 2026-10-24 — "defer prs"; until the owner opens the PR

## Filed on arrival — 2026-10-27 (lane w1027i-h-fork)


## Filed on arrival — 2026-10-27 (lane w1027h-h-reds)


## Filed on arrival — 2026-10-27 (lane w1027a-h-fork)


## Filed on arrival — 2026-10-26 (lane w1026c-h-rt-b)


## Filed on arrival — 2026-10-26 (lane w1026c-h-fork)


## Filed on arrival — 2026-10-26 (lane poller-requeue)


## Filed on arrival — 2026-10-26 (next-prompt implementation)






















## Filed on arrival — 2026-10-25 (lane w1025a-hermes)

- **`FH-UPSTREAM-TESTS-STRIP-SYSTEMROOT` — four upstream tests red on Windows `main`: `tests/hermes_cli/test_update_restore_authority.py` (2) and `tests/hermes_cli/test_runtime_maintenance_exclusion.py` (2) spawn `gateway/run.py` with an env of only `PATH`/`LANG`/`TZ`/`TIRITH_ENABLED`, and without `SYSTEMROOT` `import asyncio` dies `OSError: [WinError 10106]` (`_overlapped`); upstream-owned (Teknium `b8f1548c08`), so an upstream PR in the Windows-env fix class, never a carry** · group: upstream-load-flakes · `tests/hermes_cli/test_update_restore_authority.py:35` · evidence: lane w1025a-hermes, red with and without its change on `79e006e701` · DEFERRED 2026-11-09: owner triage — Upstream test bug; product unaffected; until the owner reopens it

## Filed on arrival — 2026-10-22 (release merge rel-v0224)


## Filed on arrival — 2026-10-22 (land w1022d)


## Filed on arrival — 2026-10-22 (land w1022a)

- **`FH-DEFER-PR-128649-SHARED-TLS` — upstream PR #128649 (shared TLS platform context) is deferred; its code rides our `main` as a carry in `agent/ssl_verify.py::resolve_httpx_verify` (under truststore one shared context, certifi bundle on the platform store, certifi re-resolved first) + `tests/agent/test_ssl_verify.py`; retire both ledger rows when the PR lands upstream** · group: upstream-footprint-ledger · fork / upstream PR branches · evidence: lane w1024t-hermes2 · RULED 2026-10-24: owner — "defer prs but make sure the code needed is on our main" · DEFERRED 2026-10-24: owner — "defer prs"; until the owner opens the PR (branch `up/tls-shared-platform-context` still needs the same rework before it can go)
- **`FH-DEFER-PR-J2A-HOSTED-ROOM-LIMITS` — upstream PR J2a (Group Chat limits, active members, conclusion, checkpoint budget) is deferred; the code already rides our `main` as the carry `gateway/hosted_room_limits.py` + the A3 hunk in `gateway/hosted_room_policy_checkpoint.py`; retire both (and their S3 ledger rows) when J2a lands upstream** · group: upstream-footprint-ledger.hosted-room-j2-limits · fork / upstream PR branches · plan `docs/agent-runtime-harness/planned/hosted-room-j2-limits-2026-10-16.md` § Half B · RULED 2026-10-24: owner — "defer prs but make sure the code needed is on our main" · DEFERRED 2026-10-24: owner — "defer prs"; until the owner opens it · v0.23.1: upstream's per-instance `max_active_events` and derived transcript bound now cover the A3 hunk in `gateway/hosted_room_policy_checkpoint.py` (dropped at the merge, c042b98019); `gateway/hosted_room_limits.py` stays as the fork's superset `DiscussionLimits`, so the row stays for it
- **`FH-DEFER-PR-J2B-HOSTED-ROOM-PINS` — upstream PR J2b (Group Chat history pin/unpin) is deferred; the code already rides our `main` as `gateway/hosted_room_history_pins.py` + the pinned-set prune hunk in `gateway/hosted_rooms.py`; retire both when J2b lands upstream** · group: upstream-footprint-ledger.hosted-room-j2-limits · fork / upstream PR branches · plan `docs/agent-runtime-harness/planned/hosted-room-j2-limits-2026-10-16.md` § Half B · RULED 2026-10-24: owner — "defer prs but make sure the code needed is on our main" · DEFERRED 2026-10-24: owner — "defer prs"; until the owner opens it
- **`FH-DEFER-PR-J2-B0-OMISSION-RESERVE` — upstream PR B0 (reserve the omission notice inside the Discussion prompt budget) is deferred; the fix already rides our `main` in `gateway/hosted_room_discussion.py::_build_prompt` (`reserved = len(omission…) + 2`); retire that hunk's ledger row when B0 lands upstream** · group: upstream-footprint-ledger.hosted-room-j2-limits · fork / upstream PR branches · plan `docs/agent-runtime-harness/planned/hosted-room-j2-limits-2026-10-16.md` § Half B · RULED 2026-10-24: owner — "defer prs but make sure the code needed is on our main" · DEFERRED 2026-10-24: owner — "defer prs"; until the owner opens it
- **`FH-DEFER-PR-SELF-REPO-GUARD-VARS` — the upstream PR for the self-repo guard's `$VAR` / `${VAR}` targets is deferred; the code rides our `main` as the fork seam `tools/self_repo_guard_vars.py` (scoped shell variables, expansion, the UNRESOLVED refusal) + its hook lines in upstream `tools/self_repo_guard.py` (import, `_find_mutation` bind, the cd / `-C` / `--work-tree` `expand_target` calls) + `tests/tools/test_self_repo_guard_vars.py`; retire the seam and that ledger row's VAR clause when the PR lands upstream** · group: upstream-footprint-ledger · fork / upstream PR branches · evidence: `tools/self_repo_guard_vars.py::ShellVars` · RULED 2026-10-24: owner — "defer prs but make sure the code needed is on our main" · DEFERRED 2026-10-24: owner — "defer prs"; until the owner opens the PR (no `up/` branch cut yet: inline the seam into `tools/self_repo_guard.py` when it is)

## Filed on arrival — 2026-10-21 (lane w1021h-tooling, branch `w1021h/tooling`)

- **`FH-CI-MAIN-LARGE-RUNNER-QUEUE` — hermes CI on `main` never finishes: upstream's jobs ask for runner labels ArcadiaLabsLLC lacks; run 39494050964 (`79d3fa5754`) queued since 2026-10-20 holds `ci-refs/heads/main`, every later push pending → cancelled; 0 green in the last 200 runs** · group: prepush · fork CI · evidence `306a622a64` (branch `w1021h/tooling`) · RULED 2026-10-22: owner — no larger runners; a fork seam maps upstream's large-runner labels to standard runners through a repository variable whose default is upstream's label · RULED 2026-10-25: owner — zero upstream footprint: one fork-owned workflow on `ubuntu-latest` / `windows-latest` running `scripts/run_tests.sh` over the validated lanes on `main` pushes, then the owner disables upstream's `ci.yaml` for the fork in the repository's Actions settings (one click, after the fork workflow lands); supersedes the 2026-10-22 per-label seam · BUILT 2026-10-25 lane w1025a-hermes: `.github/workflows/fork-gates.yml` job `validated-suite` (ubuntu-latest + windows-latest, the validated scope then `tests/tooling tests/scripts`, push to `main`), pinned by `tests/ci/test_fork_suite_on_standard_runners.py` · DEFERRED 2026-11-09: owner — owner sittings parked for now ("those owner sitting rows should be deffered for now"); the sitting it waits on: in GitHub, ArcadiaLabsLLC/hermes-agent → Actions → "CI" (`ci.yaml`) → Disable workflow, and cancel queued run 39494050964 if it still holds `ci-refs/heads/main`; then read the first `Fork gates` run on `main` for the two `Validated suite` jobs

## Filed on arrival — 2026-10-20 (launcher orchestrator w1020r)

- **`FORK-PARALLEL-MESSAGING-GATEWAY` — recorded parallel: the fork's persona messaging gateway (`agent_runtime/messaging/`, own Telegram transport over httpx) shadows upstream's `plugins/platforms/telegram/` + `gateway/platforms/base.py::BasePlatformAdapter` + `gateway/run.py::GatewayRunner`/`gateway/session.py::SessionStore`; not adopted because wrapping brings upstream's second session store and runner-private coupling, and re-admits 71 upstream test files (plan §2.2); retires if upstream exposes a session-store-free transport hook a persona turn can sit behind** · group: remote-parity-and-two-machine-proof.p10-messaging · `docs/agent-runtime-harness/planned/p10-messaging-2026-10-19.md` §2.2 · `Harness_Brain/30 — Decisions/0015 — Upstream features the fork does not ship leave the suite and the boot path.md` · DEFERRED 2026-10-20: owner "sounds good persona system for our custom gateway is the way" — kept until upstream ships a transport-only hook; re-check at each upstream merge's supersession pass

## Filed on arrival — 2026-10-18 (land w4)


## Filed on arrival — 2026-10-16 (landing land-h5, reds proven on `origin/main` `b11585e6424` by `scripts/run_tests.sh` alone)


## Filed on arrival — 2026-10-16 (build lane h-bundle-speed, reds proven on `origin/main` `aba5fec098c`)


## Filed on arrival — 2026-10-16 (build lane h3-runser)

- **`FORK-CHECK-HEALTH-BLE001` — `scripts/check --only health` reds every pre-existing BLE001 in a file the change touches, so a docstring-only edit to `agent_runtime/mcp_admission/registration.py` fails the ratchet on 9 old hits** · group: prepush · fork / tooling · `scripts/code_health/compare.py::_hit_findings` (credit from `_owned_base_hits`) · measured 2026-10-16: a detached worktree at `origin/main` `ab6956f11826` plus one docstring word in `release_mcp_admission` reported all 9 `except Exception` hits in that file as new; the pinned ruff finds the same 9 on both sides · find why the base hits are not credited (owner/rename resolution of the base file?) and add the docstring-only case as a fixture · cause found 2026-10-16 (r-isolation): `scripts/code_health/measure.py::Measurer.measure` runs ruff on the base in a bare temp tree with no `__init__.py`, so a relatively imported `logger` reads as a bare name and BLE001 accepts its `exc_info=True` there but not in place (same bytes: 10 hits in the checkout, 1 outside); the measurer is upstream-owned, so the fix and its fixture test are drafted in `docs/agent-runtime-harness/upstream-prs/code-health-package-markers-body.md` (patched: 0 blocking, killing mutation recorded) · DEFERRED 2026-11-09: owner triage — Developer tooling annoyance; fix already drafted upstream; until the owner reopens it

## Filed on arrival — 2026-10-15 (audit lane a1015-hfh)


## Filed on arrival — 2026-10-15 (audit lane a1015-hrt)


## Filed on arrival — 2026-10-15 (lane w1015h-rt-h)


## Filed on arrival — 2026-10-15 (landing land-w1015j-h, reds proven on `origin/main` `88414c8d13e`)


## Filed on arrival — 2026-10-15 (landing land-w1015e, pre-existing reds proven on `origin/main` `ef2a4492272`)


## Filed on arrival — 2026-10-15 (lane w1015b-fh-a)


## Filed on arrival — 2026-10-13 (upstream merge v0.21.7)


## Filed on arrival — 2026-10-09 (final gates)


## Filed on arrival — 2026-10-08 (lane opus-w1-hermes)


## Filed on arrival — 2026-10-08 GenUI qualification

- **`FORK-RUNNING-TURN-STREAM` — Diagnose the running-turn stream intermittent remaining after the HTTPS-scanning control.** After the operator disabled scanning, the ten H01 files pass across controls (96 distinct passes / one existing skip), with certificate and permission assertions unchanged. On `f6c27f4d0b`, `tests/agent_runtime/test_serve_gateway_chat_reply_lanes.py::test_a_running_turn_publishes_its_own_start_and_end_on_the_stream_lane` fails its six-second start-frame wait under eight-worker load, then both file tests pass serially. The two-roots file also passes all nine when allowed its declared duration; its earlier 120-second cap was a command choice. Trace the start-event publication/fixture boundary before changing behavior or deadlines. The former certificate blocker is qualified; the parallel failure remains evidence. Separate from H03 commentary. · group: upstream-load-flakes · fork / suite · [H01 control and log digests](../../docs/downstream/history-red-triage-2026-10-12.md#https-scanning-control-after-the-operators-setting-change), [H01 diagnosis](../../docs/downstream/stream-delivery-diagnosis-2026-10-12.md#h01-still-open-no-speculative-runtime-change) · no reproduction since `f6c27f4d0b`: the ten-file control passed 96 / one skip three times, the presence repair `911275e641` landed, and the test recorder keeps its reader exception + last 32 frame summaries on a failed wait; keep it as a watch and do not touch deadlines · DEFERRED 2026-10-18: a watch, not lane work — reopen when a landing gate's log reds this node, with the recorder's frame timeline

## Filed on arrival — 2026-10-06 (lane console-generated-content)



The repository AS A FORK: upstream sync and the boundary, CI, the suite and its gates, the god-file refactor, this vault. Runtime and Mission Control rows do NOT go here — the hermes half is [[runtime-queue]], the launcher half is `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`. Rows: one line + a pointer, never a restatement; claim with `**TAKEN <date> <who>**` before starting; a landing deletes its row.

## Filed on arrival — 2026-10-06 (lane h-prereq-window)


## Filed on arrival — 2026-10-05 (owner ask: a usable suite)


## Filed on arrival — 2026-10-05 (lane h-turn1-title)


## Filed on arrival — 2026-10-05 (lane h-turnws, the workstation freeze)

- **`FORK-P0-VALIDATED-SUITE-FROZE` — P0 — the validated suite froze the operator's workstation twice on 2026-10-05 (hard freeze, reboot both times), and both times the same four files were in flight: `tests/hermes_cli/test_source_check.py`, `test_source_launcher_publication.py`, `test_source_release_channels.py`, `test_source_release_probe.py`. Run 1: `scripts/run_tests.sh tests/agent_runtime tests/hermes_cli tests/hermes_state`, 8 workers, frozen at 82.5% immediately after `test_source_stamp.py` and `test_spawn_gateway_restart_cooldown.py` reported. Run 2: only the 453 files run 1 never finished, 4 workers, nothing else heavy running, frozen within about a minute, right after `test_source_channel_integration.py` reported (so the in-flight set was a subset of those four). Both runs printed `real store root handed to the gateway fence`, and the operator's own gateway (`hermes_cli.main gateway run`) was up during run 2. NOT reproduced a third time, on purpose. Find which file does it — one at a time, under a watchdog or in a VM, never on the operator's desktop — and until then no lane runs the validated suite on a workstation with these four in scope** · group: hermes-test-isolation · `fork / suite` · the two interrupted run logs are not in the repo; the facts above are their last lines · the 311 `tests/hermes_cli` and 142 `tests/hermes_state` files after that point have NOT run for lane h-turnws · **Added the same day (owner's question):** all four files are UPSTREAM's (listed in `tests/fixtures/upstream_manifest.txt`), so the fork's own landing gate (`scripts/run_tests_bundled.sh …`, `--scope fork`, `docs/downstream-development.md` § "The fork landing gate") would not have run them; the lane ran `scripts/run_tests.sh` over the three directories because `CLAUDE.md` § Commands calls that "THE suite" and its landing discipline says "the validated suite". The two documents disagree about what a landing runs — make `CLAUDE.md` name the fork gate for a landing and keep the full scope for the weekly upstream merge lane · the FOLLOW-UP half landed: `docs/downstream-development.md` names `scripts/run_tests_bundled.sh tests` as the landing gate · DEFERRED 2026-11-09: owner — owner sittings parked for now ("those owner sitting rows should be deffered for now"); the sitting it waits on: a watchdog box or disposable VM off the operator's desktop for the one-file-at-a-time freeze bisect
## Filed on arrival — 2026-10-05 (lane h-turnws)


## Filed on arrival — 2026-10-04 (lane hb-a)


## Filed on arrival — 2026-10-03 (resident identity verification)


## Filed on arrival — 2026-10-02 (lane h-rows)


## Filed on arrival — 2026-10-02 (instance foundation)


## Filed on arrival — 2026-10-02 (lane w13-hm, filed by the orchestrator)


## Filed on arrival — 2026-10-02 (lane w10-s7h)


## Filed on arrival — 2026-10-02 (lane w5-fh)


## Filed on arrival — 2026-09-30 (GenUI invocation)


## Filed on arrival — 2026-10-01 (lane w3-turn)


## Filed on arrival — 2026-10-01 (lane w3-perf)


## Release validation — 2026-09-23


**Provider-boundary qualification, October 1:** the existing TLS setup stall and duplicate-name/routing-ladder gate failures were reproduced, not waived; [evidence](../../docs/downstream/provider-access-boundary-2026-10-01.md#qualification). Native provider, plugin and execution checks pass; this does not certify a whole-repository green run.




**Additional evidence for the claimed validated-suite residuals:** 68 gateway/TLS failures reproduce on clean primary with Python 3.13.15; this does not supersede the separate Python 3.12 green receipt. [Comparison](../../docs/downstream/chat-first-group-qualification-2026-09-29.md#baseline-comparison). Filed 2026-09-29 chat-first-groups.





- **`FORK-WRAPPER-PUBLICATION-TESTS` — Isolate wrapper-publication tests before resuming interrupted desktop qualification.** · group: hermes-test-isolation · Whole-PC freeze during the single-worker continuation; running-wrapper publication is the last surviving fixture, not a proven cause. Preserve evidence; use contained off-desktop reproduction, not an unbounded rerun. [Incident boundary](../../docs/downstream/discussion-qualification-2026-09-28.md#host-freeze--qualification-interrupted). Filed 2026-09-28 Discussion qualification. · static read 2026-09-29: `tests/hermes_cli/test_source_launcher_publication.py::test_running_source_launcher_can_republish_itself` is bounded, a candidate trigger only through the OS/driver side of self-overwrite; the updater-retarget half is fenced by `319c6ff69d` · DEFERRED 2026-10-16: owner 2026-09-29 "park, low priority; needs a disposable VM" — until a disposable Windows VM exists or the next clean desktop qualification



### Filed on arrival — 2026-10-15 (owner screenshot during land-w1015h)


### Filed on arrival — 2026-09-29 (h11-mcp landing)


### Filed on arrival — 2026-09-29 (lane h10-fhrest)


### Filed on arrival — 2026-09-29 (lane h7-phone)


### Filed on arrival — 2026-09-28 (lane w5-hstt)

### Filed on arrival — 2026-09-29 (lane h10b-triage — the three-directory triage, one row per class)


### Filed on arrival — 2026-09-28 (lane w4-hfix2)

### Filed on arrival — 2026-09-27 (Windows console signal safety)

- **`FORK-WINDOWS-SIGNAL-SAFETY-CARRY` — Retire the Windows signal-safety carry when upstream adopts an equivalent fix.** · group: upstream-footprint-ledger · [[Windows console signal safety]]; held upstream candidate recorded in `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md`; no parallel supervisor or PID helper added, no PR submitted. · RULED 2026-10-10 (owner): carry stays; re-check at the next release merge · re-checked 2026-10-16: upstream `v0.22.2` `tui_gateway/host_supervisor.py::_pid_alive` still calls `os.kill(pid, 0)` · DEFERRED 2026-11-09: owner triage — Reminder only; nothing to do until upstream changes; until the owner reopens it · re-checked 2026-11-10: upstream `v0.23.1` `tui_gateway/host_supervisor.py::_pid_alive` still calls `os.kill(pid, 0)`

### Filed on arrival — 2026-09-26 (native Hermes qualification)


  EVIDENCE 2026-10-06 console-generated-content: the 895-file fork gate's exact
  115 failure/error nodes in 33 files reproduce on unchanged `5c0f130723`;
  the 35 unique helper/legibility/citation violation lines also match.
  [Receipt and remaining native acceptance](../../docs/downstream/console-generated-content-2026-10-06.md).

### Filed on arrival — 2026-09-26 (lane FIX-TRIAGE, filed by the orchestrator)





## Filed on arrival — 2026-09-30 (Stage 2 G4 landing, filed by the orchestrator)




## Filed on arrival — 2026-09-30 (launcher engine-build diagnosis, filed by the launcher orchestrator)


## Filed on arrival — 2026-09-29 (footprint attribution, filed by the orchestrator)


## Filed on arrival — 2026-09-29 (lane h10-fhrel, filed by the orchestrator)


## Filed on the move — 2026-09-22 (fork rows the launcher queue had carried since 2026-09-02)

Moved verbatim from `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`; they are about the repository as a fork, not about the surface. Upstream-owned ones are tagged so: never patched here, a marker or an upstream issue.

- **`FORK-HERMES-GH-AUTH-STATUS` — hermes `gh_auth_status_route` caches a stale logged-out answer on a coarse clock — upstream race, report upstream** · group: upstream-footprint-ledger · `hermes` · the stale-probe guard compares two `time.monotonic()` reads with `>=`; Windows resolution is 15.625 ms (10000/10000 back-to-back reads identical, deterministic failure of upstream's own `test_gh_auth_refresh_waits_out_a_probe_started_before_it`), Linux still ties 1009/10000. Operator symptom: dashboard says "not signed in to GitHub" for the 5-minute TTL right after signing in. File is byte-identical to upstream — the fork does not patch it. Ruling 3. · BLOCKED 2026-10-16: upstream — an upstream issue on `gh_auth_status_route`'s `>=` monotonic guard; none filed

- The unrun-gate class on hermes `main`: nothing on any push lane runs the full suites, so reds accumulate silently. Two instances measured and FIXED 2026-08-30 (hermes `00fa94dd75` (pre-rewrite)): `tests/scripts/test_run_tests_script.py` (pins now follow `$RUNNER_PATH` and the import-pytest venv probe) and `tests/hermes_cli/test_error_exit_code_producers.py` (`runtime_unavailable` left `_KEPT_UNSPENDABLE` — the gateway lane mints it at five sites). The CLASS is NARROWED 2026-09-02: hermes' push gate now exists (`fc2e16349e` (pre-rewrite) — Lane B runs the validated 4-dir lane on `main` pushes), so what stays open is only the dirs outside that lane, e.g. `tests/scripts`, home of the first instance. Evidence: the misc-batch landing report (hermes `5fa9000b2`), both fixes `00fa94dd75` (pre-rewrite); hermes `AGENTS.md` §Testing. · moved from the launcher queue 2026-09-22 (wave 8 sheet) · READY 2026-10-16
- Hermes's focused suites cannot be trusted under multi-agent load: the named instance is RETIRED by suite-perf Stage 6 — `test_realm_sync.py` now drives `run_harness_in_process` (`tests/agent_runtime/_harness_cli`) and carries no `timeout` at all (verified 2026-09-01). The CLASS survives: an in-test subprocess cap `--timeout` cannot raise is invisible to the runner. Original filing: it timed out at load average ~400 on a command the diff never touched; fifteen failures across two suites on 2026-08-30 were all this class. Either the in-test cap becomes environment-scalable or the wave serializes pytest across agents. Evidence: the misc-batch landing report. **RULED 2026-09-04 evening (operator, recommended answer adopted):** Option 1. There is no scaling helper anywhere today — a repo-wide grep for `HERMES_TEST_SUBPROCESS_TIMEOUT` / `timeout_scale` finds only an unrelated audio test — while 474 test files carry a `timeout=`, so the class is broad and nothing currently absorbs load. Option 2 needs exactly the cross-agent orchestrator the shared-index row above says does not exist, and serializing test runs is a direct tax on the multi-agent workflow this house runs by default. Next: hermes: add the scaled-timeout helper plus its env knob, convert the subprocess caps in the test tree to use it, and add a gate refusing a bare numeric subprocess `timeout=` in `tests/`. · moved from the launcher queue 2026-09-22 (wave 8 sheet) · READY 2026-10-16

## Filed on arrival — 2026-09-24 (lane CARRY2A)



## Filed on arrival — 2026-09-24 (lanes UPPR2, REDS)


### Filed on arrival — 2026-09-29 (lane h12-upnew)


## Filed on arrival — 2026-09-24 (disposition wave)


## Filed on arrival — 2026-09-23 (seam Stage 0 lanes)


## Filed on arrival — 2026-09-21 (upstream sync assessment)

- **`FORK-PR-RUN-TESTS-PARALLEL` — PR candidate: run_tests_parallel amortised start-up** · group: prepush.suite-cost-centres · `fork / upstream` · after `76e6fb0dc8` the per-file floor is upstream's own (~1.1 s to session start, ~2.6 s to collected, × every file); the five would-be upstream commits (phase timings, LPT order, small-file batching, POSIX fork workers, lazy root-conftest hooks) are outlined one per bullet with saving and isolation trade; the lane that builds it re-takes the upstream full-suite wall IDLE first (lane SPEED's was loaded) · evidence: `docs/agent-runtime-harness/planned/suite-cost-centres-2026-09-24.md` §8–§9 · fork after-fix baseline 40.7 min idle (2026-09-24) · 2026-09-24 (lane SUITE2): the measured PROTOTYPE of the batching bullet is the fork-only `scripts/run_tests_bundled.py` (+ `.sh`, plugin in `scripts/_bundle_plugin/`), core free of fork paths; first idle validated-scope run 1,802 s (30.0 min) vs 2,442.7 s per-file, 91 bundles, reds unchanged — the wall is held up by known-red files whose pytest-timeout kills a whole bundle (see the row below and the cost note §10). Owner decides when the upstream PR series is cut; the lane that cuts it takes the upstream idle wall first. · 2026-09-29 h12-upnew: LEFT, not opened — the series needs the upstream idle full-suite wall first (an exclusive ~40 min box) and our open runner PR #125263 on the same file is unreviewed with a body that describes fork-only code (h10b note 1); fix that body before a second runner PR goes up · RULED 2026-10-10: owner — "parked stays parked" · DEFERRED 2026-10-18: parked until the owner opens the upstream series; the lane that cuts it first re-takes the upstream idle full-suite wall and fixes PR #125263's body (owner 2026-10-10 "parked stays parked") — `docs/agent-runtime-harness/planned/suite-cost-centres-2026-09-24.md` §8–§9

## Filed on arrival — 2026-09-21 (god-file refactor plan)


## Filed on arrival — 2026-09-21 (brain)


## Filed on arrival — 2026-09-24 (lane CARRY2B)


## Filed on arrival — 2026-09-24 (lane REDS2)


## Filed on arrival — 2026-09-24 (lane CARRY3)


## Filed on arrival — 2026-09-24 (lane TESTS)


## Filed on arrival — 2026-09-24 (lane REDS3)


## Filed on arrival — 2026-09-24 (lane CLOSE)


## Filed on arrival — 2026-09-24 (program-end gate on `c7652475cd`)


## Filed on arrival — 2026-09-24 (lane LEDGER-DOCS)



## Filed on arrival — 2026-09-24 (lane DOORS-A)


## Filed on arrival — 2026-09-24 (lane W0)


## Filed on arrival — 2026-09-24 (lane MERGE)


## Filed on arrival — 2026-09-24 (lane H1)
## Filed on arrival — 2026-09-25 (lane R4)


## Filed on arrival — 2026-09-25 (lane S2B)


## Filed on arrival — 2026-09-25 (lane S2A)


## Filed on arrival — 2026-09-25 (lane 2B-A)


## Filed on arrival — 2026-09-25 (lane Q-DEAD-A)

## Filed on arrival — 2026-09-25 (lane B2)

- **`FORK-TEST-STAGE42-GLOBAL-FLAG` — `test_every_stage42_global_flag_is_honored` is a source walk keyed on the name `args`: a flag read through `self.args` or a renamed parameter reads as unhonoured, so phase objects must read flags in the handler** · group: upstream-load-flakes · `fork / gates` · a source walk certifying a POSITIVE guarantee ("this flag is honoured") by spelling — the fork CLAUDE.md gate rule says ask the runtime or the element model; re-key it on the parser's `set_defaults` targets and the attribute reads they reach · evidence: B2 gateway_commands CHANGE body · filed by lane B2 2026-09-25 · widening the visitor to `self.args` is another spelling; the re-key is a runtime probe (each `set_defaults(func=…)` handler driven with a recording Namespace under a side-effect fence), which needs the handler fence picked first · RULED 2026-10-10: owner — "parked stays parked" · DEFERRED 2026-10-18: the walk fails CLOSED on an unknown spelling (a `self.args` read reds as unhonoured, never passes) and a recording-Namespace probe reads only the path it drives, so the re-key waits on the owner's handler-fence pick — owner 2026-10-10 "parked stays parked"

## Filed on arrival — 2026-09-25 (lane Q-GATES)

## Filed on arrival — 2026-09-25 (lane B3)


## Filed on arrival — 2026-09-30 (lane h13-test)


## Filed on arrival — 2026-09-26 (lane TRIAGE)


## Filed on arrival — 2026-09-26 (lane ACP-DROP, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (program-end suite on `7df3bee189`, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (batch gates on `6bae3f2484`, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (lane LAYERS-DESIGN, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (lane LLAMA-ALIAS, filed by the orchestrator)


## Filed on arrival — 2026-09-25 (lane W3-A)

## Filed on arrival — 2026-09-25 (round-2 gate pass)


## Filed on arrival — 2026-09-25 (lane W3-C)


## Filed on arrival — 2026-09-27 (lane MERGE-0927)

## Filed on arrival — 2026-09-30 (lane h12-upfix)



## Filed on arrival — 2026-10-04 (lane h-qaeff)


## Filed on arrival — 2026-10-05 (lane upstream-PR review replies)


## Filed on arrival — 2026-10-06 (turn-latency session)

- **`FORK-LANE-HOMES-REAL-PATH` — Test and lane homes still land their `bin` on the operator's real user `Path` after the 2026-10-03 PATH fence: 14 of 30 leaked entries were created 2026-10-05 (`stage2-serve-*`, `stage4-gateway-*`, `rb7-identity-flip-*`, `ro9-boot-sweep-*`, `rs7-restart-fence-*`, `p-l-longrun-*`, a lane's `scratchpad/live`); the first one shadowed `hermes` and the operator's `hermes harness observe` died on a deleted interpreter** · group: hermes-test-isolation.design-sweep-d3 · fork hygiene / test isolation · evidence: `[Environment]::GetEnvironmentVariable('Path','User')` read 2026-10-06 00:35, dated by each dir's CreationTime; writers are `hermes_cli/_launchers.py` (user-Path merge) and `windows_env.py`, fence `hermes_cli/_registry_write_fence.py` · lane: find the writer the fence misses (a subprocess outside `install_path_fence`, or a root the fence counts as owned), make the gate a positive test, then a one-time cleanup verb the operator runs · designed in `docs/agent-runtime-harness/planned/design-sweep-d3-2026-10-10.md` § D3.15; stages 1–2 built (`805f8293c9` `4045fa25c8` `811fc986e7`) · DEFERRED 2026-11-09: owner — owner sittings parked for now ("those owner sitting rows should be deffered for now"); the sitting it waits on: on the workstation: stage 0 (Process Monitor on a launcher real-serve sandbox run) and `scripts/prune_user_path.ps1 -Apply` after reading its list; stage 3's -SkipUserPath upstream PR waits with the idle PR branches

## Filed on arrival — 2026-10-06 (lane h-turn1-conn)


## Filed on arrival — 2026-10-07 (owner: upstream integration jobs)


## Filed on arrival — 2026-10-06 (upstream PR triage)


## Filed on arrival — 2026-10-06 (landing w16)


## Filed on arrival — 2026-10-07 (upstream PR lanes up-drafts / up-door-*)


## Filed on arrival — 2026-10-07 (landing prep/hermes-waves-reviewed)


## Found fixing main's reds — 2026-10-07 (lanes h-red-cli/-runtime/-gates/-inherited)


## Filed by isolated lifecycle fixture — 2026-10-07


## Filed on arrival — 2026-10-08 final GenUI gate


Process-dock product-half recurrence, 2026-10-08 GenUI qualification: `tests/gateway/test_abandoned_turn_process_cleanup.py` times out in `test_timed_out_turn_reaps_only_its_own_job_on_a_shared_container_key`, at `tools/process_registry.py::_release_finished_handles` → `stream.close()`. The candidate full gate and isolated run hang; untouched `7ea1c17366` first passes all 15 tests, then an isolated repeat hangs at the identical site. This is additional evidence for the existing process-dock/upstream-PR row above. No timeout, environment fence or production cleanup code was changed.

## Filed on arrival — 2026-10-08 (release merge v0.21.6)


## Filed on arrival — 2026-10-09 (lane opus-fix-toolsets-refusal)


## Filed on arrival — 2026-10-09 (perf programme close-out sweep)


## Filed on arrival — 2026-10-09 (landing lane land-h-toolvis; red on detached origin/main 440cba12ce, after the upstream v0.21.6 merge)


## Filed on arrival — 2026-10-10 (release merge v0.21.6 reds, branch `fix/v0216-fork-reds`)


## Filed on arrival — 2026-10-10 (chat content integrity)


## Filed on arrival — 2026-10-10 (chat-content boundary qualification)




## Filed on arrival — 2026-10-10 (queue sweep lane-1010, filed by the orchestrator)


## Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)


## Filed on arrival — 2026-10-10 (build batch 1, build-1011-B1..B5, filed by the orchestrator)


## Filed on arrival — 2026-10-10 (fast-gate design, guard fix, build batch 2 C1–C4, filed by the orchestrator)


## Filed on arrival — 2026-10-10 (fast gate FG1, filed by the orchestrator)


## Filed on arrival — 2026-10-11 (fast-gate landing, whole-tree gate, filed by the orchestrator)



## Filed on arrival — 2026-10-11 (Console history final qualification)







## Filed on arrival — 2026-10-13 shutdown-test repair

- **`FORK-QUALIFY-NATIVE-WINDOWS-MSYS` — Qualify native Windows MSYS foreground-child ownership and cleanup.** Three `sleep.exe 3518` children survived the failing inherited shutdown-test setup; adding the executable suffix did not make the ancestry scan find them. They were explicitly reaped. The repaired test owns its Python child by a ready PID receipt, which does not prove MSYS tree cleanup. Reproduce through the existing local-environment process owner before attributing a production defect or proposing a fix; no broad process-name kill or new process registry. · group: hermes-test-isolation · fork / native process qualification · [evidence](../../docs/downstream/shutdown-test-repair-2026-10-13.md) · reproduced 2026-10-16 (r-isolation) through the owner: after `kill_live_foreground_processes(now=True)` (signalled 1, rc 1) the MSYS `usr\bin\sleep.exe` survived with a dead Windows parent, because `_kill_process_windows` -> `terminate_pid` -> `taskkill /T` walks parent links the MSYS spawn already broke; the graceful path signalled 0 (evidence appended to the doc above); both files are upstream-owned · DEFERRED 2026-11-09: owner triage — Rare leftover processes; upstream-owned; needs report first; until the owner reopens it



## Filed on arrival — 2026-10-15 (land-w1015b)


## Filed on arrival — 2026-10-15 (owner: "testing commands should be optimised")


## Filed on arrival — 2026-10-15 (lane w1015h-fh-h)


## Filed on arrival — 2026-10-15 (upstream PR sync lanes up-sync-1015-*)


## Filed on arrival — 2026-10-15 (owner: the footprint ratchet only goes up)

### Filed on arrival — 2026-10-16 (Phase B lanes pb-*, release gate triage rel-0222-reds)

- **`FORK-CHECKPOINT-MANAGER-TIMEOUT` — `tests/tools/test_checkpoint_manager.py` times out in the 2026-10-17 `--scope features` run (first: `no result before the cap`); fix whether or not it was red before (owner)** · group: upstream-load-flakes · fork / suite · features run 2026-10-17 (gate store runs.jsonl, `features-1`) · DEFERRED 2026-11-09: owner triage — Test speed issue in upstream code; until the owner reopens it · r-state 2026-10-18: green alone twice on an idle box (run_tests.sh 68.7 s on origin/main, 62.5 s on `q/r-state`; bare 56.9 s, slowest test 4.1 s); the cost is 1,190 git spawns (~47 ms each: `git init --bare` + five `git config` per store, 44 stores) inside upstream `tools/checkpoint_manager.py`, so a loaded box reaches the cap; no fork-only fix (the store init is the subject) — next: an upstream PR folding the five configs into `git init -c`/one `config` call, or a skip-list call by the owner
- **`FORK-24-UPSTREAM-PR-BRANCHES` — 24 upstream PR branches are prepared and idle (16 splits, 7 doors, the phone fix `fix/connectors-files-lazy-wire`); the account cannot open PRs upstream** · group: upstream-footprint-ledger · fork / upstream · bodies kept beside the clone in `worktrees/pr-bodies/`; owner 2026-10-16 "pr branches should remain idle" · owner opens them when upstream accepts PRs again; re-check each against the next release first · RULED 2026-10-16: owner — "pr branches should remain idle" while upstream is not taking the owner's PRs · DEFERRED 2026-10-18: when upstream takes the owner's PRs again, re-check each against the newest release tag and re-run `check_carried_prs.py` before opening — `worktrees/pr-bodies/`
- **`FORK-18-CARRIED-PR-PAIRS` — 18 carried-PR pairs stopped matching after the 2026-10-15 sync (8 hunk/line DRIFT: #119069 gateway.py, #121226 ×2, #121642 auth_nous.py, #123892 shell_hooks.py, #128652 hermes_state_messages.py, #129414 resolution_allowlist.json, #125261 environments/local.py; 9 fragments the PR branches rewrote: #125259, #125263 ×2, #125264, #128648 ×2, #128651, #128654, #128843): per PR re-cut the branch to the fork's text or adopt the PR's text in the fork, then re-pin** · group: upstream-footprint-ledger · fork / upstream PR tooling · q/carried `5692a35290f` check run · re-anchored 2026-10-18 on q/q-sync (fork adopts the PR's spelling where only spelling differed; #129414 deferred as a fork relocation): 17 → 9 pairs, `check_carried_prs.py` 4 drift + 5 errors; the nine left differ in logic, not spelling (#119069 gateway.py, #121642 auth_nous.py, #125259 config.py, #125261 local.py, #125263 run_tests_parallel.py, #125264 base.py, #128648 main.py + plugins.py, #128652 hermes_state_messages.py) · RULED 2026-10-16: owner — "pr branches should remain idle" while upstream is not taking the owner's PRs · DEFERRED 2026-10-18: re-cut those eight PR branches to the fork's text when upstream takes the owner's PRs again; adopting the PR's logic in the fork needs a per-PR review lane



- **`FORK-FULL-RE-AUDIT-FOUND` — The full re-audit found nine fork fixes that have no upstream PR yet (`_codex_pool_row_refused`, the system_prompt anchor repair, the `_sanitize_client_source` NameError, `terminal_tool_result.timed_out`, the tts piper download switch, the live-guard console-event refusal, the relay optional binding, the runtime_provider `auto` re-check, the pyproject F821): give each a prepared branch and a PR body in `pr-bodies`** · group: upstream-footprint-ledger · fork / upstream PRs · same doc §4 · RULED 2026-10-16: owner — "pr branches should remain idle" while upstream is not taking the owner's PRs · DEFERRED 2026-10-18: cut the nine branches from the then-current release tag only when upstream takes the owner's PRs again (a branch cut now drifts before it can open) — owner 2026-10-16 deferral



## Filed on arrival — 2026-10-15 (lane w1015j-hermes)


## Filed on arrival — 2026-10-16 (h2-redact)


## Filed on arrival — 2026-10-16 (land-h234)



## Filed on arrival — 2026-10-16 (lane h5-deadcode)


## Filed on arrival — 2026-10-17 (footprint audit)


## Filed on arrival — 2026-10-17 (lane r-plugins)


## Filed on arrival — 2026-10-18 land/q6




## Filed on arrival — 2026-10-18 (lane r-quiet)

## Filed on arrival — 2026-10-18 (lane q-gates)

## Filed on arrival — 2026-10-18 (lane q-stale)

## Filed on arrival — 2026-10-18 (lane r-turn)

## Filed on arrival — 2026-10-18 (lane h1-setup)

## Filed on arrival — 2026-10-18 (lane h2-sleep)

## Filed on arrival — 2026-10-18 (lane h3-plugins)

## Filed on arrival — 2026-10-18 (lane h6-collect)

## Filed on arrival — 2026-10-18 (land h1018)

## Filed on arrival — 2026-10-18 (lane w2-reds)

## Filed on arrival — 2026-10-18 (lane w2-speed-b)

## Filed on arrival — 2026-10-18 (landing land-w2)

## Filed on arrival — 2026-10-18 (landing land-ww2)

## Filed on arrival — 2026-10-18 (landing land-w3)

## Filed on arrival — 2026-10-18 (land w6)

## Filed on arrival — 2026-10-18 (session r-perf close-out)


## Filed on arrival — 2026-10-19 (land w10, b05ccafe29)


## Filed on arrival — 2026-10-19 (ns + rt-model landing ab8578f8f5: reds on main after land w10)


## Filed on arrival — 2026-10-19 (lane rt-ns-seed)


## Filed on arrival — 2026-10-20 (parent session)

## Filed on arrival — 2026-10-25 (lane w1024t-hermes2)



## Filed on arrival — 2026-10-26 (next-prompt landing baseline)

## Filed on arrival — 2026-10-27 (owner: triage every plan in planned/)

- **`FH-AUTH-TRANSPORT-PRS` — the auth-transport plugin's L2/L3 are unlanded: the on_verification kwargs are still fork-carried in the auth_* modules and there is no register_cli_command(parent=), because both upstream PR branches are held** · group: upstream-footprint-ledger.auth-transport-plugin · fork hygiene / upstream footprint · plan `docs/agent-runtime-harness/planned/auth-transport-plugin-2026-09-26.md` (L1 built e5e7a3a057) · `hermes_cli/auth_codex.py`, `hermes_cli/auth_xai.py`, `hermes_cli/auth_minimax.py`, `hermes_cli/plugins.py`; held branches feat/auth-on-verification and feat/plugin-cli-commands in `Harness_Brain/10 — Programs/Upstream Sync.md` § Held branches · RULED 2026-10-27: owner "the rest of the reccomendations sound good too" — open the two held auth PRs upstream; on merge delete the four kwarg hunks and register the auth parsers from plugins/eternia-harness · DEFERRED 2026-11-09: owner triage — Waiting on upstream; nothing broken meanwhile; until the owner reopens it


## Filed on arrival — 2026-10-28 (lane w1028a-h-persona)


## Windows baseline qualification — 2026-10-27


## Filed on arrival — 2026-10-28 (lane w1028a-h-rt)



## Filed on arrival — 2026-10-28 (lane w1028a-h-triage)


## Filed on arrival — 2026-10-29 (orchestrator, found running the CLAUDE.md-reading tests)



## Filed on arrival — 2026-10-30 (character migration validation)




## Character completion qualification findings — 2026-10-31


## Filed on arrival — 2026-11-01 (owner ruling, launcher ADR 0038 amendment)

## Filed on arrival — 2026-11-01 (release merge lane, branch `merge/upstream-v0.22.5`)

- **`FH-MAIN-RED-LAUNCHER-ENTRY-ID-WORLD-LEVEL` — `tests/tooling/test_no_launcher_entry_id_literals.py` is red on main since `28975f9023` (RT-LEVEL-SKILL-PRELOAD): `agent_runtime/mcp_admission/vocabulary.py` names `launcher.world.level` outside the listed catalog (R10); read it from `launcher.app_functions.list` or add it to ALLOWED with its reason** · group: upstream-load-flakes · fork / suite · `agent_runtime/mcp_admission/vocabulary.py` · `--confirm-red` on origin/main `f6ac4265f4`: pre-existing · READY 2026-11-01 · handoff 2026-11-10 (w1110d-foot): fixed on main b24af51bb2, its gate green; `work_row.py close` refuses only because the row's task is DEFERRED — close DONE b24af51bb2 when the owner reopens it
- **`FH-MAIN-RED-COMMAND-DISCOVERY-SERVE-GUARD` — upstream `tests/gateway/test_command_discovery.py::test_ordinary_daemon_discovery_matches_legacy_extensions` is red on main on nekwo-ubuntu24: the fork's live-system guard (`tests/_fixtures/live_system_guard.py`) blocks its `python -m hermes_cli.main serve --isolated` spawn; classify it on the pure tag (`scripts/classify_reds_on_tag.py --tag v0.22.5 --nodeid …`) and give it a skip/up-red row or a guard exemption for `--isolated`** · group: upstream-load-flakes · fork / suite · `tests/_fixtures/live_system_guard.py` · `--confirm-red` on origin/main `f6ac4265f4`: pre-existing · READY 2026-11-01

## Profile artwork qualification findings — 2026-11-01


## Filed on arrival — 2026-11-02 (landing w1101f)

## Filed on arrival — 2026-11-03 (lane w1103a-h1)


## Windows cold EOL census — 2026-11-03


## Baseline gates observed during suggestion modes — 2026-11-03


- **`FH-WORK-V1-CLAIM-GATES-WINDOWS-BUDGET` — Measure the cold Windows prepush queue/text gate batch and remove startup overhead without raising the budget** · group: prepush · `scripts/prepush.sh` · work-v1-intelligence claim 54f3445bd9: gates 14.3s against 10s budget, doc-cite 1.2s, freshly prepared Python 3.14 test environment; no other test process launched by this lane · READY 2026-11-10 · RULED 2026-11-10: owner approved reopening it ("approved all of em") · unblocked 2026-11-10: owner reopened it · REQUIRES windows · handoff 2026-11-10 (w1110c-hm3): the box never went idle in this lane's window (msys load 18-87, CPU 82-100 %); no idle reading taken, nothing changed — still needs load < 2 · handoff 2026-11-10 round 2 (w1110c-hm3): start-up overhead cut 8 -> 5 python starts before the first test (60ae94b5331); no idle reading yet

## Filed on arrival — 2026-11-04 (landing hm-land-w1104a)



## Filed on arrival — 2026-11-08 (lane w1108b-hfh)

- **`FH-PREPUSH-GATES-OVER-BUDGET` — On Windows the pre-push check fails on time alone, so a correct change cannot be pushed without overriding its limit** · group: prepush · `scripts/prepush.sh` · measured 2026-11-09 on DESKTOP-QJ7DDV2 (load 0.06-0.72): the gates step took 20.5 s against its 20 s deadline and was killed, and at PREPUSH_GATES_DEADLINE=120 it took 106 s with `tests/test_line_endings.py` and `tests/tooling/test_gate_directory_current.py` each killed by the runner before collecting (both finish in ~25 s run alone); the budgets were measured on the Linux box · REQUIRES windows · host 2026-11-10 (w1110a orchestrator): Windows-only — the red and the budgets reproduce only on Windows; Linux budgets fit · READY 2026-11-09 · handoff 2026-11-10: w1110c-hmprepush (DESKTOP-QJ7DDV2, 16 cores) removed both kills — `test_gate_directory_current.py` opened ~8,000 test files from Python (>30 s, killed twice) and now uses one `git grep` (`scripts/gate_mark.gate_marked_files`, 9d87a13109c); `test_line_endings.py` decoded git's paths as cp1252 and re-classified 83 blobs each run (7b3e61beeac); gates step 98 s red -> 25.6 s runner / 32 s wall green at low load, killed at 20.4 s under load 15.6 in `prepush.sh`. What is left is Windows start-up, not a gate: ~3 s per pytest process alone (pytest import 0.7 s), 7-12 s each with 8 starting at once, ~4 s of per-test setup over 132 tests; the gates' own call time is ~13.5 s summed. Likely fix: one process per gate group on Windows, or a Windows deadline set from an idle-box measurement (never this loaded one) · handoff 2026-11-10 (w1110c-hm2, DESKTOP-QJ7DDV2): cut the gates' own cost — the row guard read its base vault with a git process per note and split segments per character (guard.run 3.75 s -> 1.63 s, 92d119a3f68); the gates step measured 19.4 s (load ~19) and 16.2 s (load 3.1) after, runner 12.2-14.3 s, so it still overruns its 10 s budget but no longer nears the 20 s deadline. What is left is start-up under concurrency, not any gate: each of the 9 files runs 4-8 s in its own pytest process (1.6 s alone), the runner shell adds ~2.5 s (three upstream `_has_pytest` probes are 1.4 s of it, `scripts/run_tests.sh`, upstream-owned), and the 9 files serial in ONE pytest process take 16 s (14.3 s of tests), while `scripts/run_tests_bundled.sh` with 3-file bundles runs the tests in 9.8 s but costs 28.7 s wall. Next: an idle-box measurement (load < 2) before any budget talk; the per-file floor is `FORK-PR-RUN-TESTS-PARALLEL` · handoff 2026-11-10 (w1110c-hm3): the box never went idle in this lane's window (msys load 18-87, CPU 82-100 %); no idle reading taken, nothing changed — still needs load < 2 · handoff 2026-11-10 round 2 (w1110c-hm3): `run_tests.sh` starts 5 pythons before the first test, not 8 — the pytest probe is remembered per interpreter and the root fence is one start (60ae94b5331); prepush on 11e28051026 still killed gates at 22.0 s at load 101; the 9 gate files in ONE pytest process took 34.7 s vs a 92 s runner wall at load 99, so the remaining cost is a pytest process per file — waits on `FH-UPSTREAM-RUNNER-ONE-PROCESS-GROUP`

## Filed on arrival — 2026-11-09 (lane queue-tasks-s2)


## Filed on arrival — 2026-11-10 (lane hm-rel-fix-a, v0.23.1 release gate)

- **`FH-MAIN-RED-LAUNCHER-ENTRY-ID-AGENT-CHAT-LIST` — The Launcher entry-id check passes on main again: the chat parser and turn message stop naming `launcher.agent_chat.list` outside the listed catalog** · group: upstream-load-flakes · `tests/tooling/test_no_launcher_entry_id_literals.py` · `hermes_cli/harness_parts/parser/persona.py` · `hermes_cli/harness_parts/persona/chat_turn_message.py` · red on origin/main `0338812f8b` since `b49ae82006` (RT-CHAT-MESSAGE-MINT-UNSCOPED); `FH-MAIN-RED-LAUNCHER-ENTRY-ID-WORLD-LEVEL` names `launcher.world.level`, which `vocabulary.py` no longer carries; read the intent from `launcher.app_functions.list` or add it to ALLOWED with its reason · READY 2026-11-10 · handoff 2026-11-10 (w1110d-foot): fixed on main b24af51bb2, its gate green; `work_row.py close` refuses only because the row's task is DEFERRED — close DONE b24af51bb2 when the owner reopens it

## Filed on arrival — 2026-11-10 (lane hm-release, branch `merge/upstream-v0.23.1`)

- **`FH-MAIN-RED-SPAWN-FENCE-TOOL-NOT-ARGV0` — The store-write fence check passes on a machine that has a real Hermes home** · group: hermes-test-isolation · `tests/hermes_cli/test_gateway_spawn_fence.py::test_a_pm_tool_still_cannot_write_the_store[tool-not-argv0]` · red alone on main 0338812f8b and on the v0.23.1 merge tip: `tests/_downstream/live_guard_classify._names_an_existing_path` checks whether a token with a space is a real path and trips the home-I/O guard when `~/.hermes` exists · READY 2026-11-10 · handoff 2026-11-10 (w1110d-foot): fixed on main 366fc0773d, its gate green; `work_row.py close` refuses only because the row's task is DEFERRED — close DONE 366fc0773d when the owner reopens it
- **`FH-MAIN-RED-SILENT-PACKAGE-PATCHES-THREE` — The silent-package-patch check passes again for two runtime test files** · group: hermes-test-isolation · `tests/agent_runtime/test_provider_agent_scope.py`, `tests/agent_runtime/test_runtime_notice_transcript.py` · `tests/tooling/test_no_silent_package_patches.py` 3 NEW (`agent_runtime.config:ensure_persisted_personas`, `load_agent_runtime_config`, …), red on main 0338812f8b and on the merge tip · READY 2026-11-10 · handoff 2026-11-10 (w1110d-foot): fixed on main 71d93d0079, its gate green; `work_row.py close` refuses only because the row's task is DEFERRED — close DONE 71d93d0079 when the owner reopens it
- **`FH-HARNESS-CORE-BROWSER-AFTER-V0231` — Mission personas can drive a browser again after upstream removed the per-action browser tools** · group: upstream-footprint-ledger · `agent_runtime` harness_core toolsets · upstream v0.23.1 deleted the ten `browser_*` action tools (68500d9ff9); their successor `browser_exec` registers under `browser-use`, which harness_core does not name, so harness_core counts 34 tools (was 44; the merge re-pinned 34 at 617eb2abc3). Add `browser-use` to harness_core (as `browser-cdp` is), or keep 34; the generated harness SKILL.md still describes the `browser` toolset as navigate/click · BLOCKED 2026-11-10: owner decision — product call on the persona tool surface · Recommend: add `browser-use` to harness_core so personas keep a browser, and re-pin the count
- **`FH-CARRIED-PRS-WEB-OAUTH-STALE` — The carried-PR record for the dashboard login catalog matches the code again** · group: upstream-footprint-ledger · `tests/fixtures/carried_prs.json` (PR #128654 entry, `hermes_cli/web_server_oauth.py`) · still quotes `_OAUTH_STATUS_FNS` with the copilot-acp line the v0.23.1 merge removed; the `hermes_cli/gateway.py` ledger row and `recorded-parallels-2026-09-26.md` still describe the deleted `_pm_runtime_venv_dir` (text) · READY 2026-11-10
- **`FH-UPSTREAM-PRS-REBASE-V0231` — Our open upstream fixes apply to the current upstream release again** · group: upstream-footprint-ledger · NousResearch/hermes-agent PRs · triage 2026-11-10 against v0.23.1: 62 open, 0 merged, 0 overtaken; 39 still apply (32 clean, 7 by 3-way); 22 conflict — simple rebases #121640 #124191 #124194 #125259 #125260 #125262 #125265 #128649 #128653 #128840 #129414 #131903 #131904 #132423, moderate #123978 #123979 #124190 #124210 #128648 #128654, non-trivial #125263 (drop the dead browser/service_manager hunks in #121640 #125262 #131903); #128841 unclear (upstream b9e983665c bounds grace re-probes for built lists; re-run the PR's repro) · READY 2026-11-10
- **`FH-FOOTPRINT-PDF-ATTACH-UPSTREAM-BYTES` — The prompt methods file goes back to upstream's bytes, the phone dropping pdf.attach at registration** · group: upstream-footprint-ledger · `tui_gateway/methods_prompt.py` 40 added / 110 deleted · restore upstream's `pdf.attach` and helpers and have the phone profile drop the method at registration instead of relocating it to `agent_runtime/gateway/methods_pdf.py` (−110 deleted, the largest single win; touches the phone bundle and carried_prs.json) · READY 2026-11-10
- **`FH-FOOTPRINT-VENV-SYNC-RELAUNCH` — The bootstrap relaunch leaves an upstream file for a fork module** · group: upstream-footprint-ledger · `hermes_cli/venv_sync.py` 62 added / 0 · move `relaunch_if_needed`/`_relaunch` into a fork module (hermes_bootstrap's guarded import already falls back); boot path and phone-profile switch (PR #129413) · READY 2026-11-10
- **`FH-FOOTPRINT-PROVIDER-UA-LAZY` — Five provider plugins go back to upstream bytes now that their User-Agent is built lazily** · group: upstream-footprint-ledger · `plugins/model-providers/{fireworks,gmi,kimi-coding,opencode-zen,xai}/__init__.py` 10 added / 10 deleted · rebind `hermes_user_agent` to `release_version` in the fork block of `hermes_cli/version_info.py`; changes every caller's User-Agent in the unknown-version case · BLOCKED 2026-11-10: owner decision — User-Agent for every caller · Recommend: yes, release_version is the same value whenever a version is known
- **`FH-FOOTPRINT-UPDATE-INVENTORY-HISTORY` — The update inventory's fork-history block moves to a fork module** · group: upstream-footprint-ledger · `hermes_cli/update_inventory.py` 22 added / 0 · leave ~3 lines; tied to PR #125265 and its carried_prs.json hunks · READY 2026-11-10
- **`FH-FOOTPRINT-FORK-TEST-HUNKS-OUT` — Five upstream test files lose their fork hunks to fork test files or id markers** · group: upstream-footprint-ledger · `tests/hermes_cli/test_doctor.py` 19/19 (PR #125260), `tests/gateway/test_api_server_active_work_drain.py` 2/0 (fixture shortening `_cron_drain_timeout`), `tests/tools/test_windows_agent_loop_papercuts.py` 23/0 and `tests/hermes_cli/test_uninstall_dry_run.py` 1/0 (carried-PR hunks → `_downstream` files + carried_prs.json), `tests/tools/test_execution_flag_detection.py` 11/2, `tests/hermes_cli/test_setup_hermes_script.py` 19/1, `tests/hermes_cli/test_deleted_profile_tombstone.py` 4/1 (Windows-only fixes → win32 id markers; PRs #121226 #121224) · REQUIRES windows, linux · READY 2026-11-10
- **`FH-FOOTPRINT-PHONE-PSUTIL-STUB` — The phone bundle gets a psutil stand-in instead of per-call-site import guards in upstream files** · group: upstream-footprint-ledger · `hermes_cli/process_identity.py` 20/5 (the v0.23.1 merge added 12/3 at its psutil guards), `hermes_constants_scratch.py` 16/4 · one fork-owned stub module the phone wheel ships, upstream files back to their bytes · READY 2026-11-10
- **`FH-FOOTPRINT-WOVEN-CHECKPOINT-RPC` — Checkpoint restore and RPC dispatch carry their fork behaviour through doors instead of woven hunks** · group: upstream-footprint-ledger · `tools/checkpoint_manager.py` 34/34, `tui_gateway/rpc_dispatch.py` 35/25 · behaviour woven into upstream code (held PR / native recovery); each needs its own lane and a door ask · DEFERRED 2026-11-10: each is its own lane
- **`FH-MAIN-RED-SAFE-MODE-TIMEOUT` — The safe-mode CLI tests finish inside their time limit** · group: hermes-test-isolation · `tests/hermes_cli/test_safe_mode.py` · times out under `scripts/run_tests.sh` alone on main 0338812f8b and on the v0.23.1 merge tip (2026-11-10) · READY 2026-11-10 · handoff 2026-11-10 (w1110d-foot): fixed on main f562dfe61c, its gate green; `work_row.py close` refuses only because the row's task is DEFERRED — close DONE f562dfe61c when the owner reopens it
- **`FH-PREPUSH-TOUCHED-OVER-BUDGET` — On a heavily loaded Windows box two small touched test files took longer than the pre-push touched-step budget** · group: prepush · `scripts/prepush.sh` touched step · found 2026-11-10 by w1110c-hmssh on DESKTOP-QJ7DDV2: step `touched` 61.8 s against budget 60 s (deadline 120 s, exit 0, load 95.28, head 67c69755448): `tests/tui_gateway/test_ssh_remote_cwd_downstream.py` 20.9 s and `test_gateway_extension_registration_downstream.py` 22.5 s, both importing `tui_gateway.server`; measure on an idle box (load < 2) before any change · REQUIRES windows · READY 2026-11-10
