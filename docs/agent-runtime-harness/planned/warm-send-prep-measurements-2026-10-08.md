# Warm send-prep measurements — 2026-10-08

## Scope and provenance

Measurement base: `7ea1c17366a128103a45284958a0626015761aca`; lane refreshed before implementation to `94043a1a42e71290afde5e05de5ebef4685c2eaf` (worker connection ownership changes). No claim that historical receipts ran the lane patch. Live serve PID 82052; home `X:\Eternia\.hermes\profiles\base`; persona receipts were in `neko` and `gpt-launcher`, not solely base. Existing stores remained unchanged; the repo post-merge shared-skill verifier reported current packages with no refresh.

13 Oct 8 receipts, 04:28–04:35 UTC: accept/prep joined by turn ID, gap by physical request ID; a unique same-file window between prep markers matched the journal chat and api:1, with Launcher request_sent equality. The physical window lacks an explicit turn foreign key; that binding is contextual. Full source/line joins and raw timing-only receipts are preserved in the execution chat's output artifacts.

| group | n | accept→sent median / range, ms |
|---|---:|---|
| warm | 9 | 401 / 298–616 |
| after-idle | 1 | 526 / 526 |
| cold | 3 | 881 / 292–1508 |

Warm Neko: n6, median322.5, range298–554; Dev: n3, median528, range449–616. These persona routes use gpt-6-luna and gpt-6-luna-900k respectively; no model changes. The cold 292 ms turn is within the boot window, despite actor reuse.

## Exclusive anchor-to-send phases

| wall interval | n | median / range, ms |
|---|---:|---|
| context | 9 | 58 / 48–184 |
| observability | 9 | 27 / 19–46 |
| emitter (includes manifest patch) | 9 | 6 / 5–13 |
| write-ahead marker | 9 | 1 / 0–2 |
| agent-ready (includes remaining durable work) | 9 | 29 / 22–41 |
| provider-start / conversation-start | 9 | 2 / 1–6; 5 / 5–6 |
| turn-context | 9 | 88 / 76–313 |
| preflight | 9 | 2 / 2–3 |
| request-build | 9 | 67 / 60–98 |
| assembled / client-built | 9 | 1 / 1; 4 / 3–5 |
| transmit | 9 | 13 / 9–40 |

Accept-to-anchor: 27–34 ms. Anchor-to-send: median372, range269–582. Medians are not additive. Own CPU: median250, range171–390; process CPU:375 /218–625; unattributed CPU:46 /15–203. CPU is not a wall-clock partition.

## H1–H13 disposition (cost confirmation is not a live saving)

| ID | disposition | source and evidence |
|---|---|---|
| H1 | UNRESOLVED | `preparation_reads.InstanceReadEpoch`, `persona_assignments/store.PersonaInstanceStore.scan_all`: no scan-only live lap; context 48–184 and HUD5–10 do not isolate it. |
| H2 | UNRESOLVED live root | `skill_resolution`, `mission_chat_turn_context._resolve_skill_preload`: preload3–6 Neko,65–95 Dev. Isolated full Dev skill preserves44,112chars; cProfile median30.9ms, two frontmatter parses/load (~8.4ms combined), usage write~9.6ms. Does not reproduce or explain the entire live Dev span. |
| H3 | CONFIRMED narrow repeated lookup | `provider_access.current_access`→`plugins.get_plugin_manager`→`_plugin_home_key`: discovery is idempotent, but home.resolve repeats. Controlled unprofiled request-build original24.9ms, cached18.3ms, restored24.6ms (n25 each); exact kwargs parity. Fix reuses existing `hermes_home_key`, never auth/provider answers. |
| H4 | UNRESOLVED; existing owner | `agent/turn_context._refresh_mcp_tools_between_turns`, chat defer/request middleware: turn-context76–313, middleware4–8. Three-writer row TAKEN sol-runtime; no duplicate scheduler or tool-policy change. |
| H5 | REJECTED as major residual | `chat_turn_commit/run._observe`: entire post-observe emitter interval5–13 bounds the manifest patch in this sample. |
| H6 | UNRESOLVED | `skill_resolution.skill_package_content_hash`, `mission_chat_turn_context._resolve_skill_preload`: signature2–3 is not a hash/preload-only lap. |
| H7 | UNRESOLVED live attribution | `transports/codex.ResponsesApiTransport.build_kwargs`, `persona_turn_binding.capture_final_request_tools`: kwargs52–87; middleware4–8. Tiny-schema no-search fixture0.207ms profiled; does not prove real-tool serialization is zero. Receipt retained. |
| H8 | UNRESOLVED | `turn_context.build_api_messages`, request assembly and preflight token estimation: native-history2–23 and broad turn-context76–313; no clone/sanitize/estimate-only live split. |
| H9 | CONFIRMED conditional fixture cost | `transports/codex._alias_wire_tools`→`_openai_prefers_native_web_search`→`web_search_registry._resolve`: full selection probes11providers/build. cProfile56.9ms with search versus0.207ms without; unprofiled original24.9ms. Consistent with live kwargs52–87, not exclusive live attribution. Preserve fresh selection; residual credential/config/path work remains. |
| H10 | UNRESOLVED durable cost | `chat_turn_commit/run._write_ahead`, `agent/turn_context._persist_turn_start`: marker0–2 does not bound the full write; next interval22–41. No durability deferral. |
| H11 | REJECTED for observed prewarm overlap | `profile_runner/execute.AgentRunExecution.scopes`: prewarm_overlapped0 across9warm; general build overlap1 on989cd416 is distinct. Existing lock lane TAKEN sol-runtime; unseen workdir wait not disproven. |
| H12 | REJECTED as major reopen cost | `chat_session_writer.ChatSessionWriterOwner`: warm session_db_open1–2, resident reuse9/9; no evidence of physical reopen. |
| H13 | REJECTED construction/TLS hypothesis here | `agent/codex_runtime`, transport trace: pooled9/9, client3–5, pool~0.4–1.1; transmit9–40 includes actual upload. No TLS/connect setup. |

Outliers: dbb92eef warm554ms has turn-context313ms; 989cd416 warm616ms has context184, turn-context198, ownCPU343, unattributed203 and one background build; 6f02ca3e transmit40ms/upload37.3ms. Cold Dev47b89da4:1508ms, observability951 (skill rows946), plus two background builds. After-idle18187983:526ms, turn-context302.

## Delivery and remaining work

One four-line additive seam plus `agent_runtime/plugin_manager_home.py`; existing upstream fallback retained. Profile switch, environment switch, equivalent-path reuse, missing-home creation and fallback have regression guards. No cross-turn provider/config/credential cache and no prompt/tools/model/journal changes.

Positive control on a throwaway copy bypasses the seam: warm syscall-budget guard fails (25 resolves vs1). Killing mutation freezes first home: real manager identity guard fails (a==b). Unmodified copy:7passed. Touched-module ruff:PASS. Importing-file lane proof and commit details are recorded in the execution chat; landing gates are not lane gates.

The ~250ms target is NOT met: last measured warm median401ms. The ~6.6ms fixture saving is not a live or end-to-end saving. Remaining priorities: isolate turn-context steps with bounded tested instrumentation; attribute Dev skill/observability cost; resolve the remaining conditional search-selection cost with freshness parity. Coordinate H4/H11 with sol-runtime. Approved batch integration and new real warm/cold/idle receipts are required before acceptance; never lower budgets or bypass final wire/durable receipts.
Implemented-source check: n25 per A/B/A arm, legacy23.811ms, seam17.820ms, restored24.223ms medians; exact full kwargs parity for all75 samples. About6.0ms fixture benefit; no live saving claim.

Import scope:151 explicitly named files, isolated homes. Shared interpreter aborted in pytest-timeout in video-generation; that file passed9 tests per-file. Per-file authority finished2058passed,5failed,29skipped plus a package-manager timeout. Clean94043a1a42 repeated the same4 encoding failures (webhook exit delivery; three gateway update notifications) and the same PM fetch-retry timeout. Packaging's branch-only failure required the new seam module to be git-tracked; scoped staging followed by the two-file packaging/regression check passed35/35 (exit0). Existing reds are filed in fork-hygiene; no full landing gate run.

Identity risk: this shares the existing registry canonical-home contract, including its invalidation behavior if an existing directory is relocated or a symlink is retargeted. Active profile/environment selection remains live; missing homes are not memoized. No new independent path cache.
