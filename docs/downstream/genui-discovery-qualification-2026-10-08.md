# GenUI discovery qualification 8 October 2026

The Launcher now declares eager discovery on its generated list/create entry points. Hermes honors that declaration for the bound connection and origin, preserves the brief/full-manual split, and keeps the native worker's relay on its owning agent. The runtime contract is [Chat Turn Lane](../agent-runtime-harness/05-chat-turn-lane.md). Luau, streaming previews and changing the creation argument format are outside this change.

## Runtime verification

| Check | Result |
| --- | --- |
| Initial focused catalog, discovery, prewarm and tool-search tests | 89 passed |
| Extended native-worker discovery tests | 14 passed |
| Extended prewarm tests using real search assembly | 5 passed |
| Full sanctioned landing gate over `tests` | 993 files; 13,338 passed, 70 failed, 64 skipped; 822 seconds, 8 workers |
| Same 12 failing files on untouched base `7ea1c17366` | 58 passed, the identical 70 nodes failed, 3 skipped; 199 seconds |
| Documentation adjacency gate | No unwaived failures or stale waivers |
| Changed-line mutation inventory | Exit 0 |

The full gate is **red on both the candidate and the untouched base**. The node-set comparison has zero candidate-only or base-only failures. The footprint violation also matches exactly: measured `files=184 deleted_lines=959 heavy=4`, fixture `files=176 deleted_lines=883 heavy=4`. The new cache-context seam is two additive lines in an already-carried upstream file; it changes none of these ratchet metrics. The fixture was not raised.

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

The gateway failures include certificate-pin mismatch and unsuccessful peer setup. Their shared cause is not established by the node comparison. Modal's inherited failure is `TestHostPrefixList::test_all_common_host_paths_flagged_unusable`. The footprint finding already has an owner row; the other findings are recorded in the [fork hygiene queue](../../Harness_Brain/20%20%E2%80%94%20Active%20Initiatives/fork-hygiene-queue.md).

## Killing controls

Detached copies of runtime `b958a18747` and Launcher `8ead9b6ad` carried each planted defect, then reverted it. Commit `ab60947cf5` records the controls.

| Planted defect | Observed red |
| --- | --- |
| Drop host promotions from search classification | 13 discovery tests and the prewarm reuse test fail |
| Remove the connection/origin element from the definitions memo | Linked-to-unlinked cache isolation fails |
| Discard the native worker's owning relay | Continued-turn relay identity fails |
| Force the Launcher projection's eager mark to false | Per-entry metadata parity and the two-entry-point check fail |

The tests exercise boolean opt-in, legacy omission, an arbitrary future app-function name, persona deferral, admission, reach, connection teardown, warm memo hits, old session-prefix restoration, all three provider payload forms, full manual retention and refusal through the existing dispatcher.

## Product acceptance

These deterministic checks prove delivery and boundaries. First-response selection from ordinary language, visible rendering and live latency still require the built Launcher and actual provider turns. The product qualification is recorded in `EterniaLauncher/docs/mission_control/evidence/genui-discovery-qualification-2026-10-08.md`; fixture calls alone do not close the GenUI selection queue row.
