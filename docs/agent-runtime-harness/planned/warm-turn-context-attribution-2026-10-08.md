# Warm turn-context attribution — 2026-10-08

## Evidence and scope

Current base `633fdda0fe`; attribution claim `61ab9bd5aa` precedes implementation. This lane depends on PR #4's home-key seam (`4c4ab83d2d` after its refresh). It adds measurement, not a latency-saving claim. Neither lane is integrated.

Newer existing receipts, 17:49–18:17 UTC: warm n=3, accept→request_sent median 388 ms, range 301–400 ms; after-idle n=3, median 755 ms, range 621–907 ms (one classification provisional); cold n=1, 956 ms. The earlier nine-turn warm sample is retained separately. No post-patch live measurement or new operator turn was generated.

| warm wall interval | n | median / range, ms |
|---|---:|---|
| turn-context | 3 | 111 / 90–123 |
| request-build | 3 | 71 / 55–95 |
| context | 3 | 67 / 50–71 |
| observability | 3 | 20 / 19–20 |
| agent-ready | 3 | 29 / 26–33 |

Warm turn IDs: `2c612665-04ac-42c9-b89b-1443f889b4f7`, `1c4004d0-e45a-4a20-b674-310bcd7e96b7`, `6720f666-efc1-49b2-9757-711a4918211a` (all `agent-chat-send-` prefixed). Source/line receipts and physical request IDs are in the execution artifacts. Medians are not additive; current evidence still does not identify the internal expensive operation.

`24b96aad` has stale thread-local bracket context (`2012029ef087`) while its explicit `chat_turn_effort root=...2cb4a622c117 turn=...24b96aad` and the physical request prefix agree. Treat the bracket-derived checker chat/group as provisional for that turn. This is not proof of a rotation event or wrong request. Physical-window binding is still contextual (unique same-log window before next prep); no new Launcher/journal revalidation.

## Minimal instrument

`agent_runtime/turn_context_timing.py` owns the collector/decorator; `agent/turn_context.py::build_turn_context` receives 13 additive lines (import, decorator, 10 boundaries and one blank). One log-only `turn_context_receipt` per persona-chat build; no per-lap callbacks, durable writes, new parity keys or expanded budgets. This avoids displacing fields under the existing 64-key durable timing cap.

The exclusive parts are `runtime_restore` (stdio/recovery/bind/restore), `mcp_refresh`, `state_history_prompt` (turn identity/state/history/user/prompt/tool injection), `session_row` (ensure plus carried admission-row flush), `compaction`, `hooks` (including gateway notes), `memory` (interrupt binding/prefetch), `title`, `sidecar`, `persist`, `return`.

`total_ms` ends before logging; parts telescope to that total on success. Failed builds retain only closed parts plus `unfinished_ms`; unexecuted work is absent. Clock/logger faults cannot fail the build. Missing/invalid outer turn IDs produce no receipt. Every wrapper invocation masks its context, so observed and unobserved nested builds cannot consume a parent's laps; reused actors have fresh collectors. Use the lap function only at these synchronous build boundaries.

The existing outer `conversation_started→turn_context_built` includes fast-mode/credential work before the new timer; existing `profile_conversation_turn_context_ms` starts after it. Reconcile those scopes before attributing a residual. Title measures foreground checks/spawn, not background generation. Preserve all current durability, prompt, tool, credential and compaction work.

## Characterization and verification

Isolated true legacy / instrumented / restored source, 100 history messages, n=50 each: median 3.763 / 3.820 / 3.789 ms. Instrumented adds about 0.057 ms versus first legacy arm; ranges overlap. Real scratch FileHandler flush included; full production-store overhead remains unknown. Messages/system prompt match and persistence occurs once per build. Fixture in-flight markers are cleared outside the measured setup window.

Deterministic real-build regressions cover exclusive partition, durable ordering, failure/unfinished work, returned messages/system prompt, reused IDs, clock/logger failure, invalid identity invoking the body exactly once, nested observed/unobserved builds, signature preservation and bounded labels/duplicate/finished laps. Characterization: 11 passed. Positive control removes MCP boundary: partition guard fails `KeyError: mcp_refresh_ms`. Killing mutation closes failed builds as success: guard fails `completed != failed`.

Touched-module ruff: PASS. Required shared-interpreter invocation over 45 named importing files exited 1 after 183.7 s: pytest-timeout aborted during plugin-loader setup of `test_compression_lock_defer`, before a summary. Same-scope per-file authority then passed all 45 files / 485 tests, exit 0 in 131.5 s. The shared-run abort is unresolved, not proved pre-existing; no whole-tree landing gate has run for this batch.

PR #4 refresh: packaging/regressions 35 passed. CI history gate is independently red on lane and untouched `633fdda0fe`: same `test_round4_deleted_tests_left_no_live_production_subject_uncovered`, same violation `test_status_fn_empty_selection` deleted the last direct reference to `hermes_cli.tools_config._estimate_tool_tokens`; each local file run 1 failed / 26 passed. Filed separately in fork-hygiene; do not weaken the gate or fix unrelated production code in passing.

## Next measured decision

The 250 ms target remains unmet. After approved integration/rebuild and real turns, join each new receipt by its explicit turn ID to admission/prep and then its physical request. Optimize only a demonstrated redundant expensive part. H4 tool writers and H11 prewarm remain sol-runtime-owned; measure without changing their scheduling/policy. Conditional hook-spill config loading is an unmeasured candidate, not a confirmed saving. H1–H13 baseline dispositions remain in the earlier note.
