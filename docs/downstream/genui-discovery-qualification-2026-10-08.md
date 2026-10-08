# GenUI discovery qualification 8 October 2026

The Launcher now declares eager discovery on its generated list/create entry points. Hermes honors that declaration for the bound connection and origin, preserves the brief/full-manual split, and keeps the native worker's relay on its owning agent. The runtime contract is [Chat Turn Lane](../agent-runtime-harness/05-chat-turn-lane.md). Luau, streaming previews and changing the creation argument format are outside this change.

## Runtime verification

| Check | Result |
| --- | --- |
| Initial focused catalog, discovery, prewarm and tool-search tests | 89 passed |
| Extended native-worker discovery tests | 14 passed |
| Extended prewarm tests using real search assembly | 5 passed |
| Final discovery + prewarm checks after the catalog-lifetime fix | 20 passed |
| Full sanctioned landing gate over `tests` | 993 files; 13,338 passed, 70 failed, 64 skipped; 822 seconds, 8 workers |
| Same 12 failing files on untouched base `7ea1c17366` | 58 passed, the identical 70 nodes failed, 3 skipped; 199 seconds |
| Repeated full sanctioned landing gate, final runtime | 993 files; 13,323 passed, 71 failed, 64 skipped; one additional file times out; 631 seconds, 8 workers |
| Additional failing files on unchanged base | Stream-gap assertion matches; cleanup first passes all 15 tests, then an isolated repeat hangs at the identical `stream.close()` site |
| Documentation adjacency gate | No unwaived failures or stale waivers |
| Changed-line mutation inventory | Exit 0 |

The full gate is **red**. The initial 70-node comparison and the final 71-node comparison against the combined base receipts each have zero candidate-only or base-only assertion failures. The final gate also has an unqualified process-cleanup file: its child times out while closing a subprocess pipe, so its 15 tests are not counted as passes. An isolated base repeat hangs in the same test and at the same close site. The runner's `0 errors` statistic does not turn that file into a pass. The footprint violation also matches exactly: measured `files=184 deleted_lines=959 heavy=4`, fixture `files=176 deleted_lines=883 heavy=4`. The new cache-context seam is two additive lines in an already-carried upstream file; it changes none of these ratchet metrics. The fixture was not raised.

| Inherited failing file under `tests/` | Failed nodes |
| --- | ---: |
| `agent_runtime/test_gateway_media_fetch_e2e.py` | 5 |
| `agent_runtime/test_gateway_peer_cross_install_chat_e2e.py` | 3 |
| `agent_runtime/test_gateway_peer_cross_install_media_e2e.py` | 2 |
| `agent_runtime/test_gateway_peer_two_roots_e2e.py` | 9 |
| `agent_runtime/test_gateway_tls.py` | 1 |
| `agent_runtime/test_local_llama_adapter_gateway.py` | 2 |
| `agent_runtime/test_scope_use_serve_acceptance.py` | 3 |
| `agent_runtime/test_serve_gateway_chat_reply_lanes.py` | 2 |
| `agent_runtime/test_serve_gateway_lane.py` | 17 |
| `agent_runtime/test_serve_gateway_peer_lane.py` | 24 |
| `scripts/test_upstream_footprint.py` | 1 |
| `tools/test_modal_sandbox_fixes.py` | 1 |
| `agent_runtime/test_stream_gap_receipt.py` (final gate) | 1 |
| `gateway/test_abandoned_turn_process_cleanup.py` (final gate) | File timeout; unqualified |

The gateway failures include certificate-pin mismatch and unsuccessful peer setup. Their shared cause is not established by the node comparison. Modal's inherited failure is `TestHostPrefixList::test_all_common_host_paths_flagged_unusable`. The footprint finding already has an owner row; the other findings are recorded in the [fork hygiene queue](../../Harness_Brain/20%20%E2%80%94%20Active%20Initiatives/fork-hygiene-queue.md).

The stream-gap fixture fails `max_lag_ms >= 150` (candidate 91.4 ms, base 75.0 ms). Cleanup hangs in `test_timed_out_turn_reaps_only_its_own_job_on_a_shared_container_key` at `_release_finished_handles` → `stream.close()`, including during its own final cleanup. Its intermittency is observed on the base, not inferred solely from unchanged source. Neither timing floors nor process cleanup were edited.

## Killing controls

Detached copies of runtime `b958a18747` and Launcher `8ead9b6ad` carried each planted defect, then reverted it. Commit `ab60947cf5` records the controls.

| Planted defect | Observed red |
| --- | --- |
| Drop host promotions from search classification | 13 discovery tests and the prewarm reuse test fail |
| Remove the connection/origin element from the definitions memo | Linked-to-unlinked cache isolation fails |
| Discard the native worker's owning relay | Continued-turn relay identity fails |
| Force the Launcher projection's eager mark to false | Per-entry metadata parity and the two-entry-point check fail |

The tests exercise boolean opt-in, legacy omission, an arbitrary future app-function name, persona deferral, admission, reach, connection teardown, warm memo hits, old session-prefix restoration, all three provider payload forms, full manual retention and refusal through the existing dispatcher.

A further red-first regression fails on the previous candidate when the same sink redeclares after another link already synced replacement registry entries. The fixed catalog lifetime token makes it green; 82 focused catalog/discovery/search tests pass, followed by the final 20 discovery/prewarm checks. Warm hits retain the token without another wire request.

The actual shipped Launcher projection measured through the parser, assembly and briefing middleware carries 1,189 characters for the eager pair (list 398, create 791); net surface growth is 1,014 characters after removing their deferred listing entries. Chars/4 estimates 297 tokens for the pair and 254 net; these are controlled-subset estimates, not live provider token counts. Full component schemas remain behind `generated.list`, and full descriptions remain behind `tool_describe`.

## Product acceptance

These deterministic checks prove delivery and boundaries. First-response selection from ordinary language, visible rendering and live latency still require the built Launcher and actual provider turns. The product qualification is recorded in `EterniaLauncher/docs/mission_control/evidence/genui-discovery-qualification-2026-10-08.md`; fixture calls alone do not close the GenUI selection queue row.

The isolated Launcher QA build succeeded (147 seconds), stamped `7f0d5c3c26346ce63b9cd9b23a6971aed79f734b`. Its source MCP eventually attached through this run's supported direct-control files, confirmed the full QA lane and populated registry, and drove dev login, Mission Control, Base selection and an ordinary side-by-side comparison without naming generated-content tools. Turn `agent-chat-send-a5a157f9-a62c-4755-bd0d-be2c51daa082` ended `outcome_unknown` with no rendered elements. The profile model receipt had `provider=- model=-`, and the runtime logged no available provider. The record's submission flag and fingerprint do not establish a successful HTTP/model request; no provider-first-byte phase was recorded. The inspected in-app screenshot shows an empty console with “Response status needs checking.”

Live acceptance remains **incomplete**, pending an authenticated QA model/profile. Provider credentials were neither copied nor changed. First-response selection across agents/providers, output rendering, follow-up edit/reopen, restart, actual provider token counts/cache hits and latency are unqualified. Launcher QA refusal/timeout/escaped-child findings are filed in its QA tooling queue. Raw safe receipts are retained in the Launcher's ignored `docs/stages/qa-reboot/qa-artifacts/genui-discovery-2026-10-08/` folder.
