---
type: queue
program: fork-hygiene
status: open
tags: [queue, program/fork-hygiene]
---

# Fork hygiene — open queue

## Tasks — 2026-11-09 (owner: every row belongs to a task; plan QUEUE_TASKS_AND_SUBTASKS)

- **`TASK-HERMES-TEST-ISOLATION` — Agent engine tests: a run never hangs, leaks onto your machine or breaks on Windows** · task: hermes-test-isolation · 15 subtasks on 2026-11-10 (1 ready, 14 deferred) · READY 2026-11-09 · handoff 2026-11-09: w1109a-hm-iso closed FH-LIVE-GUARD-PATH-READ-AS-SPAWN (3e0292cfe4) and FH-WORK-STORE-FIXTURE-LOST-IN-ONE-PROCESS (147d9316f6, a pytest 9.1 Dir-node conftest bug fenced by regrouping args); the two READY rows left (RT-WINDOWS-BASELINE-REGRESSIONS, FH-PYTEST-HOME-BIN-LEAKS-INTO-USER-PATH) need a Windows box, their rows carry the steps · handoff 2026-11-10 (w1110a-org): recounted — `FORK-BUNDLE-PROFILES-SDK-PACK-TEST-HANGS` (READY, filed today) was uncounted, and `FORK-NEMO-PYD-OLD-DELETE` (delete the retired shared test venv) moved in from embedded-hermes · handoff 2026-11-10 (w1110b-hm): closed FORK-BUNDLE-PROFILES-SDK-PACK-TEST-HANGS (137f34928f: nothing waited, a CPU-bound closure walk that re-parsed every installed METADATA per walk; memoized, reproduced timeout at a 1/16 core share now passes); READY left: FH-GUARD-PROBE-SCAN-RED-WINDOWS (a Windows box)
- **`TASK-PREPUSH` — Agent engine checks: pre-push, CI and the full suite run fast and alike on every machine** · task: prepush · 18 subtasks on 2026-11-10 (4 ready, 14 deferred) · READY 2026-11-09 · handoff 2026-11-10: w1110c-hmprepush closed LINE-ENDINGS-MEMO-RED-WINDOWS (7b3e61beeac) and cut the Windows gates step 98 s red -> 32 s (9d87a13109c) and made heavy files shard on Windows (60cb78a0020); the 4 READY rows left are measurement work for an idle Windows box: GATES-OVER-BUDGET (start-up cost, not a gate), TOUCHED-NAMED-HEAVY-OVER-BUDGET (one 36 s room test), and the new PREPUSH-SH-TEST-SLOW-WINDOWS and DOC-CITE-OVER-BUDGET · **TAKEN 2026-11-10 w1110c-hm2 on DESKTOP-QJ7DDV2 as nekwo in h1109-wake**
- **`TASK-UPSTREAM-FOOTPRINT-LEDGER` — Agent engine: carry as little as possible on top of upstream, fixing bugs where they live** · task: upstream-footprint-ledger · 28 subtasks on 2026-11-10 (1 blocked, 27 deferred) · BLOCKED 2026-11-10: upstream — `FORK-HERMES-GH-AUTH-STATUS` waits on an upstream issue; every other subtask is deferred · handoff 2026-11-09: FH-UP-FP-FIXTURE-LAGS-MAIN filed READY by w1109a-hm-2
- **`TASK-UPSTREAM-LOAD-FLAKES` — Agent engine tests: every test passes on main, even when the machine is busy** · task: upstream-load-flakes · 27 subtasks on 2026-11-10 (2 ready, 25 deferred) · READY 2026-11-09 · handoff 2026-11-09: w1109a-hm-2 landed the owner's ruling (room and run stores synchronous=NORMAL, attempt receipts FULL, bfabe63fb5) and a WAL keeper connection (1ebe8ba237); RT-FLAKE-NATIVE-DISCUSSION-ROOM-DB-LOCKED stays READY, 0/40 with and without the keeper at 4+4 dd writers, so the red needs reproducing on current main before it can close (its row); the rest are DEFERRED · handoff 2026-11-10 (w1110b-hm): closed RT-FLAKE-NATIVE-DISCUSSION-ROOM-DB-LOCKED (51e7acc4f5: FULL turn receipts moved off the shared state.db lock into discussion_attempts.db, old builds fenced); filed READY RT-SESSIONDB-FULL-COMMIT-HOLDS-ROOM-LOCK (SessionDB's own FULL commits on state.db, the remaining holder) and FH-E2E-KANBAN-ROUTING-RED-ON-MAIN (two e2e files red alone on main)

## Owner request — 2026-11-08 (hermes prepush: a tight cap, an overrun report, fast)


## Filed on arrival — 2026-11-09 (lane w1109a-hm-2)

- **`FH-PREPUSH-TOUCHED-NAMED-HEAVY-OVER-BUDGET` — The pre-push check runs over its time budget when a lane names the slow discussion-room test files, so the budget no longer says how long a normal push takes** · group: prepush · `scripts/prepush.sh` · found 2026-11-09 by w1109a-hm-2: step `touched` 85.0 s against its 60 s budget (deadline 120 s, exit 0, load 11.08, head 9bdfccafe0, `_lane_logs/prepush_overruns.jsonl`) with 1 touched file plus 4 named (`tests/agent_runtime/test_native_discussion_room.py`, `test_discussion_runtime.py`, `tests/gateway/test_hosted_room_driver.py`, `tests/hermes_cli/test_sqlite_util_canonical.py`); budget the named files apart or speed those room tests, never a raised budget without an idle-box measurement · READY 2026-11-09 · handoff 2026-11-10: w1110c-hmprepush fixed the Windows half — `_last_seconds` missed the runner's backslash-keyed `test_durations.json`, so no file ever sharded on Windows (60cb78a0020); on DESKTOP-QJ7DDV2 the four files ran 73 s wall unsharded and now shard 4 ways, the slowest shard 56.5 s at load 11.7. The floor is one test, `test_discussion_runtime.py::test_twelve_same_profile_instances_run_distinct_sessions_and_end_retains_history` (36.4 s call: twelve member turns serialized on state.db in DELETE journal mode), which no shard splits; the Linux 85 s (load 11) is not re-measured here. Likely fix: speed that one test, or budget a named file apart from the touched lane
- **`FH-PREPUSH-SH-TEST-SLOW-WINDOWS` — The pre-push check's own test file takes two minutes on Windows, so a lane that touches the pre-push script pays it on every push** · group: prepush · `tests/scripts/test_prepush_sh.py` · found 2026-11-10 by w1110c-hmprepush on DESKTOP-QJ7DDV2: 21 passed in 121.2 s under the venv's pytest (each test drives `scripts/prepush.sh` through bash with a fake runner; bash and process start dominate on Windows); measure per test on an idle box, then cut the bash round trips per test · REQUIRES windows · READY 2026-11-10
- **`FH-PREPUSH-DOC-CITE-OVER-BUDGET` — The doc-cite pre-push step runs just over its four-second budget on a loaded Windows box** · group: prepush · `scripts/doc_cite_adjacency.py` · found 2026-11-10 by w1110c-hmprepush: 4.6 s against 4 s (deadline 10 s, load 15.55, DESKTOP-QJ7DDV2, head 60cb78a0020, `_lane_logs/prepush_overruns.jsonl`); re-measure on an idle box before any change · REQUIRES windows · READY 2026-11-10

## Filed on arrival — 2026-11-09 (lane w1109a-hm-iso)


## Filed on arrival — 2026-11-09 (stale-headers lane)


## Filed on arrival — 2026-11-08 (lane w1108c-hm-reds-upstream)

- **`FH-FLAKE-API-ADMISSION-OFF-LOOP-UNDER-LOAD` — `tests/gateway/test_api_admission_off_loop.py::test_admission_waits_for_the_writer_off_the_owner_loop[chat]` is a load flake — red in the w1108c verification daily run on hermes main 3615f904bc (quiet box, suite at -j 24), green alone on the same commit; find what it waits on under -j 24 and wait on that event, never a bare retry** · group: upstream-load-flakes · `tests/gateway/test_api_admission_off_loop.py` · found 2026-11-08 by the w1108c orchestrator (FH-W1108C-WAVE-END-REDS verification run) · DEFERRED 2026-11-09: owner triage — Test-only timing flake; the product itself is not shown broken; until the owner reopens it
- **`FH-FLAKE-SESSION-AUTHORITY-OWNER-KILL-UNDER-LOAD` — `tests/gateway/test_session_authority.py::test_native_queue_survives_owner_kill_without_replaying_unknown` is a load flake — red in the w1108c verification daily run on hermes main 3615f904bc (quiet box, suite at -j 24), green alone on the same commit; find what it waits on under -j 24 and wait on that event, never a bare retry** · group: upstream-load-flakes · `tests/gateway/test_session_authority.py` · found 2026-11-08 by the w1108c orchestrator (FH-W1108C-WAVE-END-REDS verification run) · DEFERRED 2026-11-09: owner triage — Test-only timing flake; the product itself is not shown broken; until the owner reopens it
- **`FH-FLAKE-BROWSE-SCHEMA-DRIFT-CONCURRENT-UNDER-LOAD` — `tests/hermes_cli/test_browse_schema_drift.py::test_concurrent_browses_from_processes_all_succeed` is a load flake — red in the w1108c verification daily run on hermes main 3615f904bc (quiet box, suite at -j 24), green alone on the same commit; find what it waits on under -j 24 and wait on that event, never a bare retry** · group: upstream-load-flakes · `tests/hermes_cli/test_browse_schema_drift.py` · found 2026-11-08 by the w1108c orchestrator (FH-W1108C-WAVE-END-REDS verification run) · DEFERRED 2026-11-09: owner triage — Test-only timing flake; the product itself is not shown broken; until the owner reopens it
- **`FH-LINUX-BOX-NO-NODE-UPSTREAM-REDS` — nekwo-ubuntu24 has no `node`/`npm` on PATH, so three upstream-manifest files are red alone on main 95ca419262 (`scripts/run_tests.sh <file>`): `tests/hermes_cli/test_tui_npm_install.py` (2 failed 7 errors: `os.symlink(None, …)` from `shutil.which("node")`), `tests/hermes_cli/test_web_ui_build.py` (2 failed 6 errors, same None), `tests/plugins/platforms/photon/test_spectrum_patch.py` (2 failed: `FileNotFoundError: 'node'`); the skip-listed `test_source_build.py` / `test_desktop_update_verify.py` fail the same way when named; either provision node on the box (PM's pinned node, or a system package) or skip-list each file `env: no node on the Linux box` after one bare red, never both** · group: prepush.linux-box-env · `tests/fixtures/upstream_skip_list.txt` · found 2026-11-08 by w1108c-hm-reds-upstream (FH-W1108C-WAVE-END-REDS) · DEFERRED 2026-11-09: owner triage — Test machine setup, not a product defect; until the owner reopens it
- **`FH-LINUX-BOX-NO-RIPGREP-SEARCH-REDS` — nekwo-ubuntu24 has no `rg`, so the search tool falls back to grep and two upstream files are red alone on main: `tests/tools/test_search_auto_multiline.py::TestAutoMultiline::test_newline_regex_matches_across_lines` (grep cannot match across lines: total_count 0) and four `TestZeroMatchProbe` nodes of `tests/tools/test_search_zero_match_and_multipath.py` (`_zero_match_probe` returns None without rg, so no hint); install ripgrep on the box or skip-list the nodes `env: missing ripgrep`** · group: prepush.linux-box-env · `tools/file_operations_search.py` · found 2026-11-08 by w1108c-hm-reds-upstream (FH-W1108C-WAVE-END-REDS) · DEFERRED 2026-11-09: owner triage — Test machine setup, not a product defect; until the owner reopens it
- **`FH-LINUX-BOX-GIT-ISO-UTC-SPELLING` — `tests/website/test_extract_plugins.py::test_git_dates_added_is_first_commit_updated_is_last_and_renames_keep_added` is red alone on main: it expects `git log --format=%cI` to spell a UTC commit `2026-01-01T00:00:00Z`; this box's git 2.43.0 prints `2026-01-01T00:00:00+00:00` (seen by hand); either upgrade git on the box or make `website/scripts/extract-plugins.py::load_git_dates` normalise the offset (an upstream PR, not a fork edit)** · group: prepush.linux-box-env · `website/scripts/extract-plugins.py` · found 2026-11-08 by w1108c-hm-reds-upstream (FH-W1108C-WAVE-END-REDS) · DEFERRED 2026-11-09: owner triage — Cosmetic date format difference in a test on one machine; until the owner reopens it
- **`FH-USERNS-CHOWN-SERVICE-MANAGER` — three nodes of `tests/hermes_cli/test_service_manager.py` (`test_seed_supervise_skeleton_creates_expected_layout`, `…_sets_setgid_on_event_dirs`, `test_s6_log_run_creates_leaf_as_hermes_without_chown`) are red ONLY under `unshare --user --map-current-user` (the lane and daily-run PID namespace): `os.chown(path, _HERMES_UID, _HERMES_GID)` raises `OSError [Errno 22] Invalid argument` for an unmapped uid, where the code expects the non-root `PermissionError`; green without unshare (18 passed); decide whether `hermes_cli/service_manager` should treat EINVAL like EPERM (containers hit it too: upstream PR) or the run harness should name this file outside the namespace** · group: prepush.linux-box-env · `hermes_cli/service_manager.py` · found 2026-11-08 by w1108c-hm-reds-upstream (FH-W1108C-WAVE-END-REDS) · DEFERRED 2026-11-09: owner triage — Already fixed upstream; closes itself at the next merge; until the owner reopens it
- **`FH-UPSTREAM-OPENROUTER-IMAGE-CATALOG-LIVE` — `tests/plugins/image_gen/test_openrouter_compat_provider.py::TestImageApiSurface::test_catalog_models_are_offered_only_by_openrouter` reads OpenRouter's LIVE image catalog (`list_models` → `_image_api_live_models`) and reds when it lacks `x-ai/grok-imagine-image-quality`; green with the network removed (`unshare --net`: 53 passed); make the test hermetic (upstream PR) or skip-list the node `upstream: live catalog` after one bare red** · group: upstream-load-flakes.upstream-reds · `plugins/image_gen/openrouter/__init__.py` · found 2026-11-08 by w1108c-hm-reds-upstream (FH-W1108C-WAVE-END-REDS) · DEFERRED 2026-11-09: owner triage — Already fixed upstream; closes itself at the next merge; until the owner reopens it
- **`FH-FTS-CJK-OPTIMIZE-RED-UNDER-PYTEST` — `tests/hermes_state/test_fts_cjk_bigram.py::test_existing_v23_db_gains_cjk_via_optimize` is red alone on main (3 of 3 runs: `fts_cjk_rebuild_status()` is None right after the capable reopen), yet the same steps as a plain script against the same checkout leave `fts_cjk_rebuild_high_water`/`_progress` and report pending (seen by hand); the fork code on the path is only `hermes_state.py`'s two seams, so suspect a test-environment fixture (`tests/_downstream`) that touches the state store between the two opens; bisect the conftest plugins, then fix there or id-mark** · group: upstream-load-flakes.upstream-reds · `hermes_state_fts.py` · `tests/_downstream/` · found 2026-11-08 by w1108c-hm-reds-upstream (FH-W1108C-WAVE-END-REDS) · DEFERRED 2026-11-09: owner triage — Goes away with the next upstream merge; until the owner reopens it
- **`FH-PM-UNSEALED-BUILD-NO-VIRTUALENV-PTH` — `tests/pm/test_build_operations.py::test_requirements_build_installs_offline_markers_and_seals_only_build_pth[False]` and `tests/pm/test_environment_build.py::test_public_build_installs_all_extras_at_explicit_destination[False]` are red on main (the first alone 3 of 3, the second in the `-j 6` run): an UNSEALED build has no `_virtualenv.pth` in site-packages (`assert False is not False`); PM builds with its pinned uv 0.12.3, so not the host uv 0.13.5; find what strips it (`pm/environment.py::prune_site_pth` or a fork `pm/_fork_*` path) or why uv no longer writes it, then fix or id-mark with the cause** · group: upstream-load-flakes.upstream-reds · `pm/environment.py` · found 2026-11-08 by w1108c-hm-reds-upstream (FH-W1108C-WAVE-END-REDS) · DEFERRED 2026-11-09: owner triage — Already fixed upstream; closes itself at the next merge; until the owner reopens it
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

- **`FH-LINUX-SOURCE-UPDATE-FILES-RED-ON-MAIN` — five source/update test files are red ALONE on `origin/main` 2f5f1a9079 on the Linux box (nekwo-ubuntu24, run under `unshare --user --pid`): `tests/hermes_cli/test_source_build.py` (13, setup: `source-build integration requires node and npm` — no node on the scrubbed PATH), `tests/scripts/test_source_driver.py` (7, `assert node`), `tests/hermes_cli/test_update_finish.py` (13, `Update completion failed: No module named 'agent_runtime'` from the minted update tree), `tests/pm/test_environment_build.py::test_first_bundle_extension_preserves_shipped_extras` (pm worker `sync_venv` readline timeout) and `tests/e2e/core/upgrade/test_upgrade_path.py` (`template_home` seed run timeout); either provision/skip by name what the host lacks or fix the minted tree, so a lane's blast-radius run reads green** · group: prepush · fork / the suite · `--confirm-red` verdict pre-existing for each (lane w1105h-hm) · filed by lane w1105h-hm 2026-11-05 · DEFERRED 2026-11-09: owner triage — Test noise on one machine; product unaffected; until the owner reopens it

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

- **`FORK-PYTEST-EXIT-HANG-LOOP-THREAD` — A pytest run printed `4 passed` and then never exited, held by a non-daemon thread named `Thread-1 (_loop)`** · group: hermes-test-isolation · `fork / suite` · seen once 2026-10-26 on Linux, the first (cold-bytecode) run of `tests/tui_gateway/test_prompt_turn_reaper_downstream.py` in a fresh `~/.venvs/hermes-test`; the next three runs of the same file and a 351-file `tests/tui_gateway` run exited normally, and no `Thread(target=_loop` without `daemon=True` exists in the fork's own code, so it is likely a dependency's. If it recurs, dump the thread's stack (`py-spy dump` or `faulthandler.dump_traceback_later`) before killing it · DEFERRED 2026-10-26: a watch until it recurs

## Filed on arrival — 2026-10-26 (next-prompt implementation)






- **`FORK-MACOS-CI-TRIAGE` — Triage upstream/macOS jobs exposed by the subagent-history PR's broader CI matrix.** Run `38832830663`, macOS shards `116755299378` / `116755299386`, fails in update/PM/source-stamp/MCP subprocess fixtures: copied update trees lack `agent_runtime`, import probes hit the live-system guard, and PM/tool fixtures touch the setup environment. These files are outside Step 5's changed paths; Windows fork-scope qualification does not establish a macOS baseline. Reproduce on the same native CI host against the base before attributing or exempting them. Preserve the run logs; do not weaken live-system guards or grow the skip list from this report. · group: prepush · fork / CI · read 2026-10-16 (r-sync, `gh run view --log`): shard 1 = 17 reds in 6 files (update_missing_configured_deps, sessions_held_store_gate, update_import_guard, update_posix_pause, source_build_env, mcp_death_supervisor), shard 2 = 8 errors + ~20 failed (doctor_pm_store_probe, doctor_command_install, update_finish "No module named 'agent_runtime'" from the copied tree, update_pause_step_interruptions, update_post_commit_safety, update_recovery_closure, pm runtime_bootstrap_tls / update_dependency_legs); no `main` push runs the macOS matrix (runs 38884451206, 38976202285 carry no macOS job), so no base exists to compare · DEFERRED 2026-11-09: owner triage — Mac is not a current target platform; until the owner reopens it


- **`FORK-SECOND-WORKSTATION-ENV` — Qualify the canonical shared test environment on the second Windows workstation before treating the PM slow-exit check as covered there.** Baseline re-audit on `5fc3c617df` (2026-10-15): with no explicit `HERMES_PYTHON`, `scripts/run_tests.sh tests/pm/test_worker_slow_exit_downstream.py` refuses before collection because this Windows account has no shared environment with pytest at `~/.venvs/hermes-test`. Explicitly selecting this clone's Python 3.13.15 reproduces the PM fixture's Python 3.14 requirement error; no worker assertion runs. Commit `646acfb921` established a genuine 1/1 pass on another account's shared Python 3.14.5 environment, not this workstation. Use the existing shared-environment setup and runner, then rerun the single file; do not change upstream's fixture, relax the Python requirement, or add another runner. Evidence: `scripts/run_tests.sh`, `tests/pm/_fixtures.py::isolated_python`, `pm/pyproject.toml`; local re-audit receipts retained. Environment setup, not a demonstrated PM or Eternia runtime defect. · group: prepush · DEFERRED 2026-11-09: owner triage — Machine setup for one test; no product defect; until the owner reopens it














## Filed on arrival — 2026-10-25 (lane w1025a-hermes)

- **`FH-UPSTREAM-TESTS-STRIP-SYSTEMROOT` — four upstream tests red on Windows `main`: `tests/hermes_cli/test_update_restore_authority.py` (2) and `tests/hermes_cli/test_runtime_maintenance_exclusion.py` (2) spawn `gateway/run.py` with an env of only `PATH`/`LANG`/`TZ`/`TIRITH_ENABLED`, and without `SYSTEMROOT` `import asyncio` dies `OSError: [WinError 10106]` (`_overlapped`); upstream-owned (Teknium `b8f1548c08`), so an upstream PR in the Windows-env fix class, never a carry** · group: upstream-load-flakes · `tests/hermes_cli/test_update_restore_authority.py:35` · evidence: lane w1025a-hermes, red with and without its change on `79e006e701` · DEFERRED 2026-11-09: owner triage — Upstream test bug; product unaffected; until the owner reopens it

## Filed on arrival — 2026-10-22 (release merge rel-v0224)


## Filed on arrival — 2026-10-22 (land w1022d)


## Filed on arrival — 2026-10-22 (land w1022a)

- **`FH-DEFER-PR-128649-SHARED-TLS` — upstream PR #128649 (shared TLS platform context) is deferred; its code rides our `main` as a carry in `agent/ssl_verify.py::resolve_httpx_verify` (under truststore one shared context, certifi bundle on the platform store, certifi re-resolved first) + `tests/agent/test_ssl_verify.py`; retire both ledger rows when the PR lands upstream** · group: upstream-footprint-ledger · fork / upstream PR branches · evidence: lane w1024t-hermes2 · RULED 2026-10-24: owner — "defer prs but make sure the code needed is on our main" · DEFERRED 2026-10-24: owner — "defer prs"; until the owner opens the PR (branch `up/tls-shared-platform-context` still needs the same rework before it can go)
- **`FH-DEFER-PR-J2A-HOSTED-ROOM-LIMITS` — upstream PR J2a (Group Chat limits, active members, conclusion, checkpoint budget) is deferred; the code already rides our `main` as the carry `gateway/hosted_room_limits.py` + the A3 hunk in `gateway/hosted_room_policy_checkpoint.py`; retire both (and their S3 ledger rows) when J2a lands upstream** · group: upstream-footprint-ledger.hosted-room-j2-limits · fork / upstream PR branches · plan `docs/agent-runtime-harness/planned/hosted-room-j2-limits-2026-10-16.md` § Half B · RULED 2026-10-24: owner — "defer prs but make sure the code needed is on our main" · DEFERRED 2026-10-24: owner — "defer prs"; until the owner opens it
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

- **`FORK-BARE-PYTEST-FILES-SEVERAL` — A bare pytest over files from several test directories hangs `test_gateway_spawn_fence::test_subprocess_run_refuses_the_measured_argv` (the fence is not armed; a real `gateway run` starts) and reddens `test_conftest_isolation_downstream` test_2/test_4; red on main `71079deb70`** · group: hermes-test-isolation · `fork / suite` · evidence: lane h-suite-hermetic report · reproducing it starts a real gateway on the operator's machine · DEFERRED 2026-11-09: owner triage — Only hit by an unusual test invocation the team avoids; until the owner reopens it

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

- **`FORK-WINDOWS-SIGNAL-SAFETY-CARRY` — Retire the Windows signal-safety carry when upstream adopts an equivalent fix.** · group: upstream-footprint-ledger · [[Windows console signal safety]]; held upstream candidate recorded in `docs/agent-runtime-harness/planned/upstream-footprint-ledger.md`; no parallel supervisor or PID helper added, no PR submitted. · RULED 2026-10-10 (owner): carry stays; re-check at the next release merge · re-checked 2026-10-16: upstream `v0.22.2` `tui_gateway/host_supervisor.py::_pid_alive` still calls `os.kill(pid, 0)` · DEFERRED 2026-11-09: owner triage — Reminder only; nothing to do until upstream changes; until the owner reopens it

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

- **`FORK-HERMES-PACK-MAINTENANCE` — hermes pack maintenance is a SILENT no-op on git < 2.32** · group: embedded-hermes · `hermes` · `_run_bounded_repack` issues `git repack -d --geometric=2 --write-midx`, which exits 129 on older git; the runner sends both streams to DEVNULL and never reads the return code, then `_claim_repack_slot` suppresses retries for 6 hours. Measured on git 2.31.1.windows.1 — this box. Upstream-owned; decide: warn, fall back to `repack -a -d`, or require 2.32. Ruling 1. · `hermes_cli/worktree_ops.py`, upstream-owned · DEFERRED 2026-11-09: owner triage — Only disk tidiness on old git; low user impact; until the owner reopens it
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

- **`FORK-HERMETIC-DEFAULT-DB-PATH` — The hermetic `DEFAULT_DB_PATH` pin depends on import order: `tests/conftest.py` pins it only if `hermes_state` is already imported, so profile-scoped store tests pass alone and red after any importer** · group: hermes-test-isolation · fork / suite · `queue-sweep-2026-10-10/L7-outcomes.md` L7.01 · lane: suite · upstream-owned on both sides (`tests/conftest.py` step 3b, `tests/gateway/test_multiplex_routing_authz.py`), so the answer is an upstream issue/PR · RULED 2026-10-15 (owner, decision sheet w1015i #2): post the upstream ones together in one sitting · DEFERRED 2026-11-09: owner triage — Test isolation quirk; known failures already worked around; until the owner reopens it

## Filed on arrival — 2026-10-10 (fork-fixable sweep lane-1011, filed by the orchestrator)


## Filed on arrival — 2026-10-10 (build batch 1, build-1011-B1..B5, filed by the orchestrator)


## Filed on arrival — 2026-10-10 (fast-gate design, guard fix, build batch 2 C1–C4, filed by the orchestrator)


## Filed on arrival — 2026-10-10 (fast gate FG1, filed by the orchestrator)


## Filed on arrival — 2026-10-11 (fast-gate landing, whole-tree gate, filed by the orchestrator)



## Filed on arrival — 2026-10-11 (Console history final qualification)







## Filed on arrival — 2026-10-13 shutdown-test repair

- **`FORK-QUALIFY-NATIVE-WINDOWS-MSYS` — Qualify native Windows MSYS foreground-child ownership and cleanup.** Three `sleep.exe 3518` children survived the failing inherited shutdown-test setup; adding the executable suffix did not make the ancestry scan find them. They were explicitly reaped. The repaired test owns its Python child by a ready PID receipt, which does not prove MSYS tree cleanup. Reproduce through the existing local-environment process owner before attributing a production defect or proposing a fix; no broad process-name kill or new process registry. · group: hermes-test-isolation · fork / native process qualification · [evidence](../../docs/downstream/shutdown-test-repair-2026-10-13.md) · reproduced 2026-10-16 (r-isolation) through the owner: after `kill_live_foreground_processes(now=True)` (signalled 1, rc 1) the MSYS `usr\bin\sleep.exe` survived with a dead Windows parent, because `_kill_process_windows` -> `terminate_pid` -> `taskkill /T` walks parent links the MSYS spawn already broke; the graceful path signalled 0 (evidence appended to the doc above); both files are upstream-owned · DEFERRED 2026-11-09: owner triage — Rare leftover processes; upstream-owned; needs report first; until the owner reopens it

- **`FORK-QUALIFY-POSIX-EXIT-FLUSH` — Qualify POSIX exit-flush test signal-state restoration.** The unchanged SIGTERM test saves only SIGTERM, while `install_exit_flush_signal_handlers` also replaces SIGINT; `_restore_signal_state` clears the handler map after restoring the supplied entries. Baseline and candidate Linux tests pass but do not inspect the next test's handler state. Use a bounded native before/after probe and repair the existing fixture if confirmed; no runtime redesign or shared fixture duplication. · group: hermes-test-isolation · fork / native test isolation · [source finding](../../docs/downstream/shutdown-test-repair-2026-10-13.md) · confirmed 2026-10-16 (r-isolation) by a before/after probe: SIGTERM restored, SIGINT left as `_handle_exit_flush_signal` with an empty chain map; the test file is upstream-owned, fix drafted in `docs/agent-runtime-harness/upstream-prs/serve-exit-flush-signal-restore-body.md` · DEFERRED 2026-11-09: owner triage — Test hygiene only; fix drafted upstream; until the owner reopens it


## Filed on arrival — 2026-10-15 (land-w1015b)


## Filed on arrival — 2026-10-15 (owner: "testing commands should be optimised")


## Filed on arrival — 2026-10-15 (lane w1015h-fh-h)


## Filed on arrival — 2026-10-15 (upstream PR sync lanes up-sync-1015-*)


## Filed on arrival — 2026-10-15 (owner: the footprint ratchet only goes up)

### Filed on arrival — 2026-10-16 (Phase B lanes pb-*, release gate triage rel-0222-reds)

- **`FORK-CHECKPOINT-MANAGER-TIMEOUT` — `tests/tools/test_checkpoint_manager.py` times out in the 2026-10-17 `--scope features` run (first: `no result before the cap`); fix whether or not it was red before (owner)** · group: upstream-load-flakes · fork / suite · features run 2026-10-17 (gate store runs.jsonl, `features-1`) · DEFERRED 2026-11-09: owner triage — Test speed issue in upstream code; until the owner reopens it · r-state 2026-10-18: green alone twice on an idle box (run_tests.sh 68.7 s on origin/main, 62.5 s on `q/r-state`; bare 56.9 s, slowest test 4.1 s); the cost is 1,190 git spawns (~47 ms each: `git init --bare` + five `git config` per store, 44 stores) inside upstream `tools/checkpoint_manager.py`, so a loaded box reaches the cap; no fork-only fix (the store init is the subject) — next: an upstream PR folding the five configs into `git init -c`/one `config` call, or a skip-list call by the owner
- **`FORK-NEMO-PYD-OLD-DELETE` — Owner, after a reboot: delete the retired shared test venv `~/.venvs/hermes-test-3145-retired` (Python 3.14.5 / SQLite 3.50.4; it still holds the held `nemo_relay/_native.pyd.old-0.8.4`)** · group: hermes-test-isolation · moved 2026-11-10 (w1110a-org): from embedded-hermes · fork / box · the shared venv was rebuilt on Python 3.14.7 / SQLite 3.53.1 on 2026-10-19 (same 146 pins, WAL on; `FORK-SHARED-TEST-VENV-SQLITE` closed); the retired folder is the rollback until one landing gate has run on the new venv · DEFERRED 2026-11-09: owner triage — Disk housekeeping whenever the owner reboots; until the owner reopens it
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
- **`FORK-STATE-SCHEMA-AUTOCOMMIT` — a fresh `state.db` build autocommits ~100 DDL statements (`hermes_state_schema._init_schema` on the `isolation_level=None` writer): in `journal_mode=DELETE` each is a rollback-journal create+delete+fsync, 87-110 ms CPU per store even at `synchronous=OFF` (100 statements: 105 ms autocommitted vs 6 ms in one transaction); the fork's tests now dodge it with a stripped template, production first-runs and every DELETE-mode install still pay it** · group: prepush · upstream-owned / hermes_state · lane h1-setup measurement (`tests/_downstream/session_db_template.py` docstring) · DEFERRED 2026-11-09: owner triage — One-time 100 ms cost users will not notice; until the owner reopens it

## Filed on arrival — 2026-10-18 (lane h2-sleep)
- **`FORK-TEST-UPSTREAM-FIXED-WAITS` — The largest suite sleeps left are upstream constants a test cannot shorten: `tools/terminal_tool.py::_run_foreground` retries any backend exception at 2+4+8 s (the five `_LIFECYCLE_SCAN` strict-xfail rows in `test_gateway_restart_loop.py` reach the test double's `execute` on Windows, so each pays 14 s: 70 s per run), `hermes_cli/local_runtime/supervisor.py::unload_model`'s 15 s / 0.3 s poll (44 s in `test_local_runtime.py`), `cron/scheduler.py::_launch_external_cron_worker` (18 s in `test_restart_safe_worker_death_evidence.py`) and `hermes_state._sleep_before_write_retry` (15 s in `test_compression_watermark_commit.py`)** · group: prepush · fork / suite (upstream code) · probe 2026-10-18 lane h2-sleep (main-thread sleep per call site, top 44 files) · DEFERRED 2026-11-09: owner triage — Test speed only; upstream change needed; until the owner reopens it

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

- **`FORK-ORPHAN-INSTALL-LEFTOVERS` — the 335 owner-approved orphan pm install states under `X:\Eternia\.hermes\installs` each keep ~82 locked files (~36 MB, hardlinked native modules such as aiohttp `.pyd` held by live Pythons; the whole folder is 5.1 GB), and `uv cache prune` failed on a held temp dir (os error 32); rerun `delete_orphans.py` (skip-and-continue) and `uv cache prune` after a reboot** · group: embedded-hermes · fork / workstation · deleter run 2026-10-18 `deleted=0 skipped=0 failed=335` (all PARTIAL) · DEFERRED 2026-11-09: owner triage — Disk clean-up on the owner's PC, no urgency; until the owner reopens it
- **`FORK-STALE-PR-BRANCH-LAZY-HTTPS` — remote branch `upstream-pr/lazy-https-opener` (`95b3221fbec`) is dead: its SSLKEYLOGFILE cause is fixed by the launcher strip (`1616c349cc`) and FORK-DIAGNOSE-LOCAL-CLI-STARTUP is closed; delete it (`git push origin --delete upstream-pr/lazy-https-opener`), a remote-ref delete the owner runs** · group: upstream-footprint-ledger · fork / git · w4-misc `317dc4779c` · DEFERRED 2026-11-09: owner triage — Harmless leftover; one-command tidy-up anytime; until the owner reopens it

## Filed on arrival — 2026-10-19 (land w10, b05ccafe29)


## Filed on arrival — 2026-10-19 (ns + rt-model landing ab8578f8f5: reds on main after land w10)

- **`FORK-LENS-PULL-DOOR-BUNDLE-DEATH` — `tests/agent_runtime/lens/test_lens_pull_door.py` killed its bundle once in the lint landing gate (passed alone, 12 later members re-bundled)** · group: hermes-test-isolation · fork / suite · gate log of land/lint 2026-10-19 · DEFERRED 2026-10-19: a watch — reopen with the hang stack when a second gate sees it

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

## Profile artwork qualification findings — 2026-11-01


## Filed on arrival — 2026-11-02 (landing w1101f)

## Filed on arrival — 2026-11-03 (lane w1103a-h1)


## Windows cold EOL census — 2026-11-03

- **`FH-WINDOWS-EOL-COLD-ARGV` — Bound the cold EOL classifier batch by the native Windows command-line limit** · group: prepush · `tests/test_line_endings.py::_eol_states` · 500 literal paths exceed CreateProcess limits on Windows and all five EOL gates error with WinError 206; use a bounded argv or smaller cross-platform batch, retain git classification and all assertions; warming the existing blob memo with one git ls-files --eol census lets the unchanged gate run · built 2026-11-06 w1106b-hm e40ba3032b: `_argv_chunks` cuts the unseen batch by a 16,000-character command-line budget and 500 paths (pure unit tests, every host) · left: the native Windows cold run — with the blob memo empty (`hermes-eol-memo.json` beside the git common dir removed), `tests/test_line_endings.py` passes with no WinError 206 · DEFERRED 2026-11-09: owner triage — Developer check; fix built, only verification left; until the owner reopens it · REQUIRES windows

## Baseline gates observed during suggestion modes — 2026-11-03


- **`FH-WORK-V1-CLAIM-GATES-WINDOWS-BUDGET` — Measure the cold Windows prepush queue/text gate batch and remove startup overhead without raising the budget** · group: prepush · `scripts/prepush.sh` · work-v1-intelligence claim 54f3445bd9: gates 14.3s against 10s budget, doc-cite 1.2s, freshly prepared Python 3.14 test environment; no other test process launched by this lane · DEFERRED 2026-11-09: owner triage — Four seconds of developer wait; no user impact; until the owner reopens it · REQUIRES windows

## Filed on arrival — 2026-11-04 (landing hm-land-w1104a)



## Filed on arrival — 2026-11-08 (lane w1108b-hfh)

- **`FH-PREPUSH-GATES-OVER-BUDGET` — On Windows the pre-push check fails on time alone, so a correct change cannot be pushed without overriding its limit** · group: prepush · `scripts/prepush.sh` · measured 2026-11-09 on DESKTOP-QJ7DDV2 (load 0.06-0.72): the gates step took 20.5 s against its 20 s deadline and was killed, and at PREPUSH_GATES_DEADLINE=120 it took 106 s with `tests/test_line_endings.py` and `tests/tooling/test_gate_directory_current.py` each killed by the runner before collecting (both finish in ~25 s run alone); the budgets were measured on the Linux box · REQUIRES windows · host 2026-11-10 (w1110a orchestrator): Windows-only — the red and the budgets reproduce only on Windows; Linux budgets fit · READY 2026-11-09 · handoff 2026-11-10: w1110c-hmprepush (DESKTOP-QJ7DDV2, 16 cores) removed both kills — `test_gate_directory_current.py` opened ~8,000 test files from Python (>30 s, killed twice) and now uses one `git grep` (`scripts/gate_mark.gate_marked_files`, 9d87a13109c); `test_line_endings.py` decoded git's paths as cp1252 and re-classified 83 blobs each run (7b3e61beeac); gates step 98 s red -> 25.6 s runner / 32 s wall green at low load, killed at 20.4 s under load 15.6 in `prepush.sh`. What is left is Windows start-up, not a gate: ~3 s per pytest process alone (pytest import 0.7 s), 7-12 s each with 8 starting at once, ~4 s of per-test setup over 132 tests; the gates' own call time is ~13.5 s summed. Likely fix: one process per gate group on Windows, or a Windows deadline set from an idle-box measurement (never this loaded one)

## Filed on arrival — 2026-11-09 (lane queue-tasks-s2)

- **`FH-E2E-KANBAN-ROUTING-RED-ON-MAIN` — Two end-to-end checks (kanban rate-limit review, routing truth table) pass on main again** · group: upstream-load-flakes · `tests/e2e/core/kanban/test_kanban_rate_limit_review.py` · `tests/e2e/core/tenancy/test_routing_truth_table.py` · found 2026-11-10 by w1110b-hm: both time out at 1 worker (31-35 s, a `wait_until(not pid_alive)` and a thread join), and `--confirm-red` on test_routing_truth_table: red alone on HEAD and on origin/main ba0b5e8d11 (pre-existing) · handoff 2026-11-10 (w1110b-hm): not chased; next: run each alone with the timeout stack and name the child process or thread that does not exit · READY 2026-11-10
