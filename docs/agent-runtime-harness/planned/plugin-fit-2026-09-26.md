# Plugin fit — every remaining `hook` / `carry` row against upstream's CURRENT plugin surface (2026-09-26)

Lane PLUGIN-FIT, design sitting, no code. Owner's ask: "anything we can do that's not PRs? like investigate if it can be moved over plugin side?"
Population: the 45 ledger rows dispositioned `hook`, `carry` or `carry-permanent`, joined with `scripts/upstream_footprint.py --json`
at `[up-fp] files=169 deleted_lines=906 heavy=4` (base `067fa1a257`); ledger and live counts agree on every row (1,639 diff lines).
Surface of record, read from `upstream/main` (`f077152871`): `hermes_cli/plugins.py::VALID_HOOKS` (41 hooks), `hermes_cli/middleware.py::VALID_MIDDLEWARE`
(`tool_request`, `tool_execution`, `llm_request`, `llm_execution`), `PluginContext.register_*`, `toolsets.create_custom_toolset`,
`plugins_dispatch.SYSTEM_PROMPT_SECTION_POSITIONS = {"after_memory"}`. Fence: `tests/tooling/test_plugin_imports_public_surface.py` (seams §1 rule 3).

Verdict vocabulary. **PLUGIN-NOW**: a fire site exists on upstream/main today, it reaches the edit's location carrying what the edit reads, and the
binding needs only public upstream names. **PLUGIN-AFTER #N**: blocked only on one of our open PRs (one line, no re-analysis). **NO**: a bug fix, a
wire the launcher reads, or no fire site — with the widening that would create one. Facts the verdicts rest on, cited once:
- Bridge tools (`tool_search`, `tool_describe`) dispatch BEFORE request middleware, `pre_tool_call` and `transform_tool_result`
  (`model_tools.py:900–906` → `_dispatch_bridge_tool`, then `_apply_request_middleware` at :934); `tool_call` is unwrapped so every hook sees the REAL tool name.
- `pre_command` fires only for SLASH commands (`cli.py:1196`, `gateway/run_inbound.py:758`) — there is no hook on `hermes <subcommand>` dispatch or on import.
- No init-phase, turn-phase, response-validation, config-read, skill-visibility or persisted-session-row hook exists; `on_session_start` fires at the FIRST
  turn's prompt build (`agent/conversation_loop.py:833`), after `init_agent` has finished.
- `llm_request` middleware receives the whole provider payload (`agent/turn_api_request.py:143`: `api_kwargs` + session_id/platform/model/provider/api_mode)
  and `{"request": …}` replaces it; `tool_request` (`model_tools.py:758`) replaces the effective args before hooks, guards, approvals and execution;
  `pre_tool_call` is fail-closed and its block is honoured for `tool_call`-unwrapped names (`hermes_cli/plugins.py:2057`).
- `on_stream_start/delta/end` are enqueued off the token path by the stream bracket (`agent/chat_completion_helpers.py:2553`, `agent/stream_delivery.py:292`).

## 1. The table

| path | +/− | what the edit does | VERDICT | seam | a lane must prove |
|---|---|---|---|---|---|
| `.gitattributes` | 7/0 | root `eol=lf` rule | PLUGIN-AFTER #123874 | — | — |
| `AGENTS.md` | 2/0 | fork pointer line | NO (carry-permanent, ruled 09-24) | — | — |
| `README.md` | 7/1 | licence notice | NO (carry-permanent, ruled 09-24) | — | — |
| `pyproject.toml` | 64/1 | `agent_runtime` package include; ruff `F821` select + per-file ignores | NO (packaging → Stage 7; `F821` block is an upstream PR candidate) | — | — |
| `agent/agent_init.py` | 29/4 | (a) `blocked_tool_names` threaded to `_load_tools`/`get_tool_definitions` 4/3; (b) eight init-phase timing receipts 16/0; (c) `local-llama-hermes` context-floor exemption 9/1 | (a) **PLUGIN-NOW** · (b) NO · (c) NO | (a) `llm_request` middleware drops `request["tools"][i]` whose name is in the session's block set (registered by `agent_runtime/chat_lane_bundle.py` keyed on `session_id` before the turn) + `pre_tool_call` returns a block for the same names · (b) no init-phase hook: widening `on_agent_init_phase(session_id, phase, elapsed_ms)` fired at the eight sites, ~12 lines · (c) held configurable-floor PR (owner 09-24) | (a) blocked name absent from the payload at `pre_api_request` on all three api modes; a `tool_call` to it is refused; the memo key no longer needs the set (positive control: unblock → present + runs) |
| `agent/codex_runtime.py` | 39/21 | (a) usage-ledger row on the app-server path 2/0; (b) `measure_provider` phase stamps client_resolve/responses_create/stream_consume + `stream_stats` 37/21 | (a) PLUGIN-AFTER #123978 · (b) **PLUGIN-NOW** (dispatch bracket = the plugin's existing `llm_execution` `time_provider_dispatch`; TTFB = `on_stream_start`→first `on_stream_delta`; consume = first delta→`on_stream_end`; `client_resolve` and the per-attempt split are DROPPED — §4 Q4) | `llm_execution` (`agent/turn_api_call.py:133`) + `on_stream_start/delta/end` | the three stream hooks fire on the codex path (the `chat_completion_helpers.py:2553` bracket wraps `run_codex_stream`); if they do not, (b) is NO and stays |
| `agent/conversation_compression.py` | 11/2 | (a) aux-model floor exemption 9/1; (b) `child_model_config(agent)` on `publish_compression_child` 2/1 | NO · NO | (a) held floor PR · (b) no hook at the child-row publish; widening: `transform_compression_child(parent_session_id, child_session_id, model_config) -> dict or None` beside #124210's row hooks, ~8 lines | — |
| `agent/conversation_loop.py` | 16/0 | (a) `reuse_current_user_message` threading 4/0; (b) system_prompt_build/restore + turn_context timing 12/0 | (a) PLUGIN-AFTER #124210 · (b) NO | (b) no turn-phase hook (`on_session_start` fires after the build it would time): widening PHASE-PR `on_turn_phase(session_id, turn_id, phase, elapsed_ms, **meta)` observer, one fire per stamp site (here 3, `turn_api_request.py` 3, `turn_response_check.py` 1), ~20 lines | — |
| `agent/prompt_builder.py` | 46/9 | (a) Safety sentence of `OPENAI_MODEL_EXECUTION_GUIDANCE` replaced 5/1; (b) `_WINDOWS_NATIVE_TOOLING_HINT` appended to `_local_host_hints` 2/1; (c) skill runtime-compat visibility filter (`skill_surface`/`root_node_mode`, snapshot `runtime`) 33/6; (d) all four project context files load instead of first-wins 3/3; imports 3/0 | (a) **PLUGIN-NOW** · (b) **PLUGIN-NOW** · (c) NO · (d) NO | (a) `llm_request` middleware rewrites the upstream sentence in the system text (`messages[0].content` / `system` / `instructions`) — byte-stable per session, so cache-safe; sentinel miss → one WARNING, text left alone · (b) `register_system_prompt_section("eternia-harness.windows-tooling", after_memory)` rendered only when `sys.platform == "win32"` and `terminal.backend` is local · (c) widening `filter_skill_visible(skill_name, frontmatter, session_info) -> bool or None`, consulted in `hides()` and `_find_all_skills`, ~10 lines · (d) upstream PR: `context_files.load_all: true` config key (a plugin section re-reading CLAUDE.md is a second loader — rule 9) | (a) the wire system text carries the fork sentence and not upstream's on all three api modes; restoring upstream's sentence in the middleware → red · (b) hint present once on win32+local, absent elsewhere, identical bytes on turn 1 and turn 2 |
| `agent/session_persistence.py` | 5/2 | persona row projection in `_db_flush_row` | PLUGIN-AFTER #124210 | — | — |
| `agent/skill_utils.py` | 9/4 | shared skills root + excluded dirs + posix lookup names | PLUGIN-AFTER #124191 | — | — |
| `agent/system_prompt.py` | 1/0 | `tool_names` in `_plugin_session_info` | NO (1-line widening PR; the plugin already reads `session_info.get("tool_names")` defensively, so the line is additive until then) | — | — |
| `agent/turn_api_request.py` | 11/0 | request_build / pre_api_hook / request_dump stamps | NO (PHASE-PR above) | — | — |
| `agent/turn_context.py` | 18/8 | `reuse_current_user_message` staging | PLUGIN-AFTER #124210 | — | — |
| `agent/turn_facade.py` | 2/0 | forwarder kwarg | PLUGIN-AFTER #124210 | — | — |
| `agent/turn_response_check.py` | 6/0 | response_validate stamp | NO (PHASE-PR above; `post_api_request`→`post_llm_call` spans validation AND tool execution, so it cannot be derived) | — | — |
| `gateway/hosted_room_discussion.py` | 85/33 | host-declared `DiscussionLimits` + `active_member_ids` | NO (no fire site: the consumer `agent_runtime/discussions/service.py` CALLS these functions; Group Chat host-surface widening PR, this host as consumer) | — | — |
| `gateway/hosted_room_policy_checkpoint.py` | 6/3 | `max_active_events` budget | NO (same PR) | — | — |
| `gateway/hosted_rooms.py` | 72/4 | `pin_room_history`/`unpin_room_history` retention opt-in | NO (same PR; stock behaviour byte-identical with nothing pinned) | — | — |
| `tui_gateway/hosted_room_driver.py` | 15/2 | `request_reconciliation` + three settlement fixes | NO (same PR; the fixes as plain fixes) | — | — |
| `hermes_cli/auth.py` | 18/1 | (a) `_auth_file_path` honours `HERMES_AUTH_HOME` 13/1; (b) `persist_provider_login` 5/0 | (a) PLUGIN-AFTER #124190 · (b) NO (AUTH-PR below) | — | — |
| `hermes_cli/auth_codex.py` | 11/1 | `on_verification` on the device-code login; `login_codex_account` | NO — AUTH-PR: `on_verification: Callable[[str, str], None] or None = None` on `_codex_device_code_login`, `_codex_browser_login`, `_minimax_oauth_login` (+ `persist: bool = True`), `_xai_oauth_device_code_login`, plus public `persist_provider_login` in `auth.py`; ~25 lines, generic (any non-interactive front end needs it); the `login_*_account` wrappers move to fork-only `hermes_cli/auth_noninteractive.py` | — | — |
| `hermes_cli/auth_codex_browser.py` | 4/1 | `on_verification` on the browser login | NO (AUTH-PR) | — | — |
| `hermes_cli/auth_minimax.py` | 14/2 | `on_verification` + `persist=False`; `login_minimax_account` | NO (AUTH-PR) | — | — |
| `hermes_cli/auth_xai.py` | 13/1 | `on_verification`; `login_xai_account` | NO (AUTH-PR) | — | — |
| `hermes_cli/auth_commands.py` | 7/0 | `auth set-key` / `auth login` dispatch | NO (a wire the launcher reads: `provider_connect_controller.dart` builds `hermes auth set-key` / `hermes auth login`) — LAUNCHER-MOVE (§4 Q5): the launcher spells `hermes harness auth set-key` / `hermes harness auth login` under the plugin's own registered `harness` parser (`register_cli_command`, live today) and these 44 lines delete with no PR | `register_cli_command("harness")` sub-verbs | after the launcher moves: `hermes harness auth login codex --json` streams the same NDJSON; `hermes auth login` returns argparse's unknown-verb error |
| `hermes_cli/subcommands/auth.py` | 37/0 | the two parsers | NO (same wire; LAUNCHER-MOVE) | — | — |
| `hermes_cli/config.py` | 10/6 | `load_config_readonly` applies the `local-llama-hermes` read projection (ContextVar) and passes `ensure_home=False` | NO — no config-read hook and a per-read hook would sit on the 265 µs cache-hit path; widening: a module-level override point `hermes_cli.config.set_readonly_projection(fn)` (default identity, ~6 lines), this plugin its consumer; `ensure_home=False` is an upstream FIX PR on its own ("reading config must not scaffold the home") | — | — |
| `tools/image_generation_tool.py` | 2/2 | FAL config read via `load_config_readonly` | NO (upstream PR: use the read-only variant at read-only sites; 3 files, 6 lines) | — | — |
| `tools/tts_tool.py` | 5/4 | config read via readonly (deep-copied); `denotes_same_file` | NO (same PR + G2 identity hunk) | — | — |
| `tools/vision_tools.py` | 5/5 | two config reads via readonly; `_lookup_supports_vision` import | NO (same PR) | — | — |
| `hermes_cli/main.py` | 67/195 | (a) profile-bootstrap extraction to `_profile_bootstrap.py` 8/187; (b) three `_boot_clock` marks 6/0; (c) manifest-declared CLI commands attach before discovery 37/0; (d) `restore_durable_completions()` at CLI agent startup 6/0; (e) `from hermes_cli._downstream_cli import cmd_postinstall` 1/0 | (a) NO (upstream refactor PR P1) · (b) NO (`pre_command` is slash-only; import-time marks have no fire site — carry as one-liners) · (c) NO (Stage-1 widening PR = these hunks + `plugins.py` + `plugins_manifest.py`, verbatim) · (d) **PLUGIN-NOW** · (e) **PLUGIN-NOW** (DELETE: nothing in `main.py` references the name; the one test that reaches it through `main_mod.cmd_postinstall` — `tests/hermes_cli/test_postinstall_noninteractive.py` — is re-pointed at `hermes_cli._downstream_cli`) | (d) `register_hook("on_session_start", …)`, kwargs `session_id, model, platform`; gate `platform == "cli"`, once per process; the method lives in fork-only `agent_runtime/process_notifications.py` | (d) the restore runs before the first `pre_llm_call` of a CLI session and exactly once across two sessions in one process; gateway sessions never trigger it |
| `hermes_cli/plugins.py` | 50/2 | `discover_declared_cli_commands` / `_materialize_declared_cli_command`; discovery `elapsed_ms` log | NO (Stage-1 widening PR; the log line is G14, upstream trivial) | — | — |
| `hermes_cli/plugins_manifest.py` | 20/0 | manifest `cli_commands` field | NO (Stage-1 widening PR) | — | — |
| `model_tools.py` | 44/3 | (a) `blocked_tool_names` filter + memo key 12/3; (b) tool-defs memo hit/miss counters 24/0; (c) `ensure_tool_describe_present` injection 8/0 | (a) **PLUGIN-NOW** (with `agent_init.py` (a)) · (b) NO (init-observability; rides `on_agent_init_phase`) · (c) NO (injection alone is useless: upstream's `dispatch_tool_describe` serves only `_deferrable_in(current_tool_defs)`, and bridge dispatch precedes every hook — CARRY per PAR-DESIGN 7b; PR shape: describe over ALL current defs + always-inject, ~15 lines) | (a) as above | (a) as above |
| `run_agent.py` | 1/0 | `blocked_tool_names` ctor kwarg | **PLUGIN-NOW** (deletes when `chat_lane_bundle.py:555` stops passing it) | — | `AIAgent(...)` no longer accepts the kwarg; the chat lane still refuses the tool |
| `tests/tools/test_modal_sandbox_fixes.py` | 28/4 | `_native_host_cwd` fixture spelling | NO (test fix; upstream PR beside #121224) | — | — |
| `tools/async_delegation.py` | 15/1 | `_db_path` via background-work home | PLUGIN-AFTER #124190 | — | — |
| `tools/mcp_tool_config.py` | 41/1 | child `HERMES_HOME`, per-server env overrides, `runtime_env`, machine-root tokens | PLUGIN-AFTER #124210 | — | — |
| `tools/mcp_tool_transport.py` | 1/1 | call-site half | PLUGIN-AFTER #124210 | — | — |
| `toolsets.py` | 70/2 | (a) `skill_search` in core/`skills` + `harness_core` bundle 24/2; (b) `expand_toolset_names` 46/0 | (a) PLUGIN-AFTER #123979 · (b) **PLUGIN-NOW** (MOVE to `agent_runtime/toolset_names.py`; it reads only the public `toolsets.TOOLSETS`) | (b) `from toolsets import TOOLSETS` (public at base) | (b) `tests/tools/test_toolsets_downstream.py` re-pointed; `toolsets.py` has no fork def left |
| `tools/skills_tool.py` | 99/68 | (a) shared-root dirs (`_runtime_skill_dirs`, `_skill_search_dirs`, multi-level category) 32/12; (b) `resolve_skill` replaces upstream's `_skill_candidates` walk 2/50; (c) runtime-compat refusal in `skill_view` + additive `resolution_status`/`source_kind`/`content_hash` 15/0; (d) runtime filter + `identifier`/`tags` in `skills_list` 8/1; (e) `skill_inspection_reader` + two helpers 30/0; (f) posix in refusal text 4/4; imports 8/1 | (a) PLUGIN-AFTER #124191 · (b) NO — ADOPT (rule 9: a parallel resolver; §4 Q6) · (c) **PLUGIN-NOW** · (d) NO (rows carry no path; filtering means re-resolving = a second resolver; rides the skill-visibility widening with `prompt_builder.py` (c)) · (e) **PLUGIN-NOW** (MOVE to `agent_runtime/skill_inspection.py`; it calls `_find_all_skills`, `_locate_skill`, `_skill_search_dirs`, `_skill_lookup_path_error` — private names, so the move is a fork-in-tree module with a row in the ledger's "read by private name" section, never the plugin) · (f) G2 | (c) `register_hook("transform_tool_result", …)` (`model_tools.py:857–859`, kwargs `tool_name, args, result`): on `skill_view` parse the result's `rel_path`/content frontmatter and return the typed refusal dict, else the result plus the three fields | (c) a surface-incompatible skill returns `readiness_status: unsupported` to the model and a compatible one gains `content_hash`; direct in-process callers are NOT covered (§4 Q3) |
| `tools/skills_tool_plugin.py` | 10/0 | runtime-compat refusal for plugin skills | **PLUGIN-NOW** (same `transform_tool_result` binding; frontmatter via public `get_plugin_manager().find_plugin_skill`) | as above | as above |
| `tools/terminal_tool.py` | 88/1 | (a) envelope gate wrapper + `_interactive_cli_guidance` refusal 77/0; (b) persona chat container scope in `_resolve_container_task_id` 7/0; (c) `brief_schema("terminal")` at registration 3/1; import 1/0 | (a) PLUGIN-AFTER #123977 · (b) **PLUGIN-NOW** · (c) **PLUGIN-NOW** | (b) `register_middleware("tool_request", …)`: when `current_tool_execution_scope()` is set, return `{"args": {**args, "task_id": scope}}` for `terminal` (and `process`) · (c) the plugin's existing `llm_request` `brief_tool_descriptions` also replaces `parameters` of the `terminal` def with the brief schema | (b) `_resolve_container_task_id(scope)` returns `scope` unchanged on upstream/main, and the container the persona turn runs in is the chat's; direct callers (`tui_gateway/methods_complete.py`, `tools/bot_mode_dm.py`) never run a persona chat · (c) wire schema for `terminal` == `brief_schema("terminal", TERMINAL_SCHEMA)` byte-for-byte; `tool_describe` still serves the full one |
| `tools/tool_search.py` | 117/16 | (a) `never_defer` key + hardcoded promotions 25/3; (b) describe over all tools + `full_tool_description` + `parameters` in top hits + legacy single `query`/`name` args 92/13 | (a) PLUGIN-AFTER #124192 · (b) NO (bridge dispatch precedes every hook and middleware — no binding can reach a `tool_describe`/`tool_search` call or its result; CARRY per PAR-DESIGN 7b; PR shape as `model_tools.py` (c) plus `parameters` for the top 3 hits, legacy args dropped) | — | — |

Totals. **PLUGIN-NOW**: 11 files, ≈195 added / 30 deleted lines retire without any PR; `run_agent.py` and `tools/skills_tool_plugin.py` leave the
footprint outright. **PLUGIN-AFTER**: 16 rows on 8 open PRs (#123874, #123977, #123978, #123979, #124190, #124191, #124192, #124210), ≈275/35 lines;
`.gitattributes`, `session_persistence.py`, `skill_utils.py`, `turn_context.py`, `turn_facade.py`, `async_delegation.py`, `mcp_tool_config.py`,
`mcp_tool_transport.py` leave outright. **NO**: 24 whole files + the NO halves of 11 mixed files, ≈1,100 lines — of which the hosted-room PR is 178/42, the
profile-bootstrap extraction 8/187, the Stage-1 CLI widening 107/2, the four auth carries + `set-key`/`login` wire 86/6, the phase stamps 35/0.

## 2. Exec lanes (PLUGIN-NOW only; sized by raw lines of the files touched, ~5–7k each; Opus; one CHANGE commit per file)

Before: `[up-fp] files=169 deleted_lines=906 heavy=4`. Each lane records the mutation's red in its commit message (launcher `EterniaLauncher/docs/tooling/GATE_LANDING_CHECKLIST.md`).

- **PF-1 — the blocked-tool set and the terminal args** (`model_tools.py`, `agent/agent_init.py`, `run_agent.py`, `tools/terminal_tool.py`,
  `agent_runtime/chat_lane_bundle.py`, `plugins/eternia-harness/__init__.py`; ≈6.2k raw lines). Plugin gains: a session-keyed block registry the chat lane
  fills; `llm_request` tool filter; `pre_tool_call` refusal; `tool_request` task_id rewrite; the terminal brief schema on the wire.
  Killing mutation: delete the `pre_tool_call` callback — a persona whose bundle blocks `terminal` runs it through `tool_call` (red); a second control:
  delete the `llm_request` filter — the blocked def is present at `pre_api_request` (red). `[up-fp]` 169/906 → **168/899** (`run_agent.py` leaves;
  −3 `agent_init`, −3 `model_tools`, −1 `terminal_tool`).
- **PF-2 — the prompt and the CLI start** (`agent/prompt_builder.py`, `hermes_cli/main.py`, `agent_runtime/prompt_guidance.py`, plugin; ≈5.6k).
  Plugin gains: the Safety-sentence rewrite in `llm_request` (sentinel + one WARNING on miss); the `windows-tooling` section; `on_session_start` → `restore_durable_completions()`
  once per process for `platform == "cli"`; the dead `cmd_postinstall` import deleted. Killing mutation: restore upstream's Safety sentence as the
  replacement — the wire system text contains "if the next step has side effects" (red). `[up-fp]` 168/899 → **168/897**.
- **PF-3 — codex timing, toolset names, skill results** (`agent/codex_runtime.py`, `agent_runtime/codex_observability.py`, `toolsets.py`,
  `tools/skills_tool.py`, `tools/skills_tool_plugin.py`, plugin; ≈4.1k). Plugin gains: `on_stream_start/delta/end` observers writing the provider
  timing receipt (TTFB, consume); `transform_tool_result` on `skill_view`. Moves: `expand_toolset_names` → `agent_runtime/toolset_names.py`;
  the inspection reader → `agent_runtime/skill_inspection.py` (+ its private-name ledger row). Prove the stream hooks fire on the codex path FIRST;
  if not, leave `codex_runtime.py` and say so. Killing mutation: drop the `on_stream_end` handler — no `stream_consume` receipt (red).
  `[up-fp]` 168/897 → **167/876** (`skills_tool_plugin.py` leaves; −21 `codex_runtime`).

End state of the three lanes: **167/876**; with the eight open PRs merged and their AFTER rows deleted: **≈159/841**. Re-take the line at each landing.

## 3. The fence

No PLUGIN-NOW binding above imports a `_private` upstream name: the codex receipt, the process-notification restore and the prompt hint are fork-only
modules (`agent_runtime.*`, which the fence admits; rename `_WINDOWS_NATIVE_TOOLING_HINT` public on the way); the block registry and the task_id rewrite need
no upstream import; `expand_toolset_names` needs `toolsets.TOOLSETS` (public at base). Two things the lanes must watch:
- `skill_view` refusal (PF-3) needs a frontmatter parser. Use a public `agent.skill_utils` reader; if the only one is `tools/skills_tool._safe_frontmatter`,
  that binding is **PLUGIN-AFTER a "make it public" PR** — shape: `def read_skill_frontmatter(path) -> dict` in `agent/skill_utils.py`, `_safe_frontmatter` an alias, 4 lines.
- The inspection-reader MOVE (PF-3) reads four private `skills_tool` names; it is a fork-in-tree module and is RECORDED in the ledger's "read by private name"
  section, never bound from the plugin.

## 4. Open questions, each decided

1. **Rewrite the Safety sentence on the wire?** Yes. It uses upstream's first door (`llm_request` replaces the request) and is byte-stable per session; a sentinel
   miss after an upstream rewording logs ONE warning and leaves the text (fail-open) — never a second guidance paragraph beside upstream's.
2. **Blocked tools still appear in the `tool_search` catalog** (bridge reads bypass every hook). Accept: `pre_tool_call` is the enforcement; the name leak is not a capability.
3. **The `skill_view` refusal covers only the model path** (`transform_tool_result`); direct in-process callers see the skill. Accept: the launcher reads through the
   fork-only inspection reader, which gates itself; the skills INDEX in the prompt stays unfiltered until the skill-visibility widening.
4. **Codex `client_resolve` and the per-attempt split** are lost in the plugin form. Drop them: the dispatch total, TTFB and consume are the numbers Mission Control renders.
5. **LAUNCHER-MOVE for `auth set-key` / `auth login`.** Do it: the plugin's `harness` parser is registered today; the launcher's `provider_connect_controller.dart`
   changes one spelling, then 44 lines and the sub-verbs-on-a-builtin-parser PR both disappear. The row for the launcher's Mission Control queue is in the lane report.
6. **`resolve_skill` vs upstream's `_skill_candidates`.** Adopt upstream's walk (restore the 50 lines) unless a fork test goes red naming a lookup upstream's cannot do;
   a red is a RECORDED PARALLEL row, not a silent keep.
7. **`cmd_postinstall` import in `main.py`.** Delete it; `tests/hermes_cli/test_postinstall_noninteractive.py` calls it as `main_mod.cmd_postinstall` four times and is re-pointed at `hermes_cli._downstream_cli` in the same commit.
