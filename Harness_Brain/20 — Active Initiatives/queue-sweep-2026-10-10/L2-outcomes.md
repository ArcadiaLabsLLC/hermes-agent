# L2 outcomes (lane-1010-L2, branch lane/1010-L2)

L2.01 · FIXED 9d8cf3492b
L2.02 · RETURNED operator live proof: not reproducible today — the managed venv (`.hermes/venvs/hermes-agent`) cannot even import `hermes_cli.gateway` (`ModuleNotFoundError: hermes_yaml`, venv package set behind the checkout); `_detect_venv_dir` returns `sys.prefix` for any venv interpreter, and the start call site (`gateway_windows._launcher_settings`) is upstream (seam); re-run `gateway start` after a venv re-sync and capture the traceback
L2.03 · RETURNED operator live proof: n=1 cold/after-idle re-takes need live turns on the operator's serve (`hermes harness observe turn-timing --check`)
L2.04 · RETURNED upstream: H2 cost is in upstream `agent/skill_commands.py::build_preloaded_skills_prompt` / `skill_view` (double frontmatter parse, usage write) — needs an upstream door; H6 measured below the bar
L2.05 · RETURNED owner decision: which skills each harness persona preloads (persona config, then body compression)
L2.06 · RETURNED too big: not reproducible off-load (6/6 green; stall_over50 4.9–7.4 s over 5.6–7.9 s windows) — the 500 ms floor fails only when the window is short under gate load; design question: gate the server's headers on K hog multiplies (fixes the window) without flipping `wait_on` to server, which needs the failing run's window numbers
L2.07 · RETURNED too big: needs a live no-credential turn through serve + Launcher feed; design question: which typed settlement a provider-unavailable turn ends with before `_cross_provider_boundary`, and who renders the recovery step (launcher half)
L2.08 · FIXED 2ff1c64b1a
L2.09 · RETURNED too big: a new capability packet (formats, limits, typed refusals, retention, recovery) on `conversations/prompt.py` + `ConversationService.send` — design first
L2.10 · RETURNED too big: moving system-prompt build/construction off `_WORKDIR_LOCK` or splitting them into yieldable steps is a prewarm redesign
L2.11 · RETURNED too big: one cross-process skill-parse cache keyed by file signature + build-scoped memos across four walkers (verdict 2026-10-06 stands)
L2.12 · RETURNED owner decision: does the volatile tail carry facts only (the trim was refused as weakening permission guidance)
L2.13 · RETURNED operator live proof: fresh prewarm kept-count / connection-reuse / title-start receipts from one live turn
L2.14 · RETURNED operator live proof: blocked on the R034 final-wire-tools capture prerequisite plus authenticated cache-token runs
L2.15 · ALREADY-DONE measured 2026-10-10 on a copy of the live base `state.db` (335 sessions, 171 prompts): the sweep is 1.6 ms cold / 0.15 ms warm; `idx_sessions_tool_names` now exists and the plan is two covering-index searches — the row's "no index, ~15 ms" premise no longer holds
L2.16 · ALREADY-DONE a317870c7f (lock, 2026-10-06 05:44Z); live re-read of `events.81417412.jsonl` 92973189–92974049: two same-fingerprint PAIRS, each ms apart (04:09:32.48/.65Z; 04:14:54.53/.52Z, out-of-order by 11 ms) — the check-then-append race, both before the lock; "5 min apart" was the two pairs conflated; zero repeated stream_watchdog fingerprints after 05:44Z through 2026-10-10T03:12Z
L2.17 · RETURNED owner decision: may per-parameter prose move behind `tool_describe`
L2.18 · RETURNED seam: an upstream-file edit (`agent/turn_api_request.py`), blocked on the A5 first-turn `build_api_request` row
L2.19 · ALREADY-DONE 1f47100d67 — `tests/tooling/test_function_legibility_floor.py` 4 passed on today's tree
L2.20 · RETURNED too big: every outliving spawn site (serve tool/MCP hosts, gateway, workers) must stamp/remove `<pid>.json`; design question: one spawn chokepoint that owns the launcher process-index entry, including the upstream-spawned gateway (seam)
L2.21 · FIXED a325b7c08e
L2.22 · RETURNED seam: upstream PR #131249 is merged into main (95db0e2ada is an ancestor via 3002eaa067, v0.21.6); the delete of the carry needs an edit to upstream `tools/tool_search.py` (the `attach_local_call_rule` call + import) alongside `tools/tool_search_downstream.py` — the merge/seam lane's
L2.23 · FIXED dd02613c2b
L2.24 · RETURNED too big: the registry's `scope` is a HERMES_HOME profile key (`current_scope_key`), not a connection; per-link scoping needs the turn's tool resolution to carry the link's scope (upstream `tools/registry.py` / model_tools seam); design question: per-connection registry scope vs memo keyed on catalog identity instead of `registry_epoch`
L2.25 · FIXED 5060f1c9ec
L2.26 · RETURNED too big: program remainder (rich input/activity, recovery, live latency) per the instance-conversations plan
L2.27 · RETURNED owner decision: does the `levels` status row fold into `store_drift` (one count) — then the per-family revert table, then the level arm with the launcher mirror
L2.28 · RETURNED too big: a new realm-sync family (publish scan, pull applier, baseline, status counts) plus the launcher binding first
L2.29 · RETURNED owner decision: parked until Hermes-as-a-service is wanted (OWNER 2026-09-29)
L2.30 · RETURNED owner decision: parked until darwin/linux builds exist (OWNER 2026-09-29)
L2.31 · RETURNED upstream: fork delete waits on upstream PR #124194 merging
L2.32 · RETURNED owner decision: watch per RULED 2026-09-25 — needs the failing case's `what=` string before any change
