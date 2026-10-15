# Second doors — every `hook` row checked for a door upstream already has (2026-09-24)

Lane DOORS, read-only analysis. For each of the 46 `hook` rows in
[`upstream-footprint-ledger.md`](upstream-footprint-ledger.md) the fork diff
(`git diff f24a1d7f92 HEAD -- <file>`) was read against `upstream/main` `749220ef00`,
and one question was asked: does upstream ALREADY give the plugin this behaviour
with zero upstream edit? The pattern is the 2026-09-24 ruling on
`tools/process_registry.py` (runtime-queue § Seams, `e7c9c6bbcb`): the fork built a
second door (a late `process notify` request, its own store, a routing block in
`_move_to_finished`) where upstream's first door (spawn-time `notify_on_complete`)
plus a plugin-set default did the job.

Classes: **FIRST** — an upstream door exists; name it and what the fork deletes.
**NEAR** — a door exists but needs one small upstream widening (named exactly).
**NO** — genuinely needs the widening PR the row already names. A row with a
first-door PIECE inside a NEAR/NO row says so in the "deletes" cell. No queue rows
are filed here; the owner rules first.

Doors checked, in order: plugin hooks (`VALID_HOOKS` in upstream
`hermes_cli/plugins.py`), the four middleware kinds (`llm_request`,
`llm_execution`, `tool_request`, `tool_execution` in `hermes_cli/middleware.py`),
config keys / env reads, existing call parameters, manifest fields, the plugin's own
middleware (`tools/downstream_schema.py` brief rewriter, the `post_api_request`
usage ledger), and fork-owned code (the persona runner
`agent_runtime/profile_runner.py`, which builds every persona agent and its
`status_callback`).

## Per-row table

| file | fork behaviour | class | the upstream door | what deletes | confidence |
|---|---|---|---|---|---|
| `agent/agent_init.py` | local-llama floor exemption, init timing, blocked-tool pass-through | NO | none for init-phase timing. Pieces: floor → NEAR (widen upstream's `_allow_lmstudio_explicit_below_floor` from `provider == "lmstudio"` to any `is_local_endpoint(base_url)` with an explicit positive `model.context_length`); blocked tools → NEAR (see `model_tools.py`) | floor condition (9 lines) and the `blocked_tool_names` threading (4) if both widenings land; init receipts stay | medium |
| `agent/chat_completion_helpers.py` | pass persona header cache scope; copy routing observability to agent | FIRST | `llm_request` middleware: it receives the final provider kwargs, so it can overwrite `prompt_cache_key` (in kwargs or `extra_body`, wherever upstream placed it) and the `session_id` / `x-client-request-id` extra headers IN PLACE — no re-derivation of placement, which was CARRY3's objection. The persona scope reaches it through a fork ContextVar set by `profile_runner` around the turn (the middleware runs synchronously in the turn thread), not through the middleware context | the whole hunk (8/2); routing observability is recorded by the middleware keyed on `api_request_id` | medium |
| `agent/codex_runtime.py` | provider phase timing; usage-ledger row on app-server path | NO | timing: `on_stream_*` are queued off the token path with no event timestamp, so `client_resolve` / `responses_create` / `stream_consume` cannot be derived. Piece: usage → NEAR — upstream fires `post_api_request` on the Codex app-server path (a parity fix: every other path fires it, and the fork's ledger already consumes it) | the `record_usage` call (2 lines) with that fix; timing (37, incl. the −21 re-indent) stays | high (timing), medium (usage) |
| `agent/conversation_compression.py` | aux floor exemption; persona keys on compression child | NEAR | floor: the same one-line local-endpoint widening as `agent_init.py`. Piece: child metadata → FIRST — upstream passes `agent._session_init_model_config` through `publish_compression_child`, and upstream itself mutates that dict after construction (`tools/delegate_tool.py` stamps `_delegate_from`); `profile_runner` already sets `_persona_chat_root_session_id` on the agent and can stamp `mission_chat_root_id` / `persona_instance_id` / `source` into the same dict | `child_model_config` import + call (2 lines) and `agent_runtime/compression_metadata.py` now; the floor condition (9) with the widening | high (metadata), medium (floor) |
| `agent/conversation_loop.py` | turn-wide venv-install barrier wrapper; row reuse; timing marks | FIRST (partial) | G1 barrier: upstream `tools/lazy_deps.py` already refuses venv mutation through `security.allow_lazy_installs: false` (plugin-set profile default) or redirects every lazy install to a durable side target via `HERMES_LAZY_INSTALL_TARGET` (the sealed-venv mode; the running venv is never mutated). Behaviour change: the fork allows installs outside a turn, upstream's door blocks/redirects always. `reuse_current_user_message` → NO (ROW-PR); `system_prompt_*` / `turn_context` marks → NO | the `run_conversation` wrapper + rename (~40 lines); with it the G1 upstream rows `tools/lazy_deps.py` (85), `hermes_cli/tools_config_cua.py` (7) and the refusal half of `agent/anthropic_adapter.py` | medium |
| `agent/prompt_builder.py` | skill surface filter; Windows hint; all context files; Safety line | NO | carries have no door (the Safety line REPLACES upstream text; context files are first-found upstream). Piece: skill surface/mode filter → NEAR — upstream already offer-gates skills by `environments:` (`_ENV_DETECTORS`) and `metadata.hermes.requires_toolsets` / `requires_tools` / `session_platforms`; widening = a plugin-registered environment detector (e.g. `mission_chat`, `root_node`). Or FIRST if persona skills declare `requires_toolsets: [agent_chat]` | the `runtime` snapshot field + `hides(... runtime)` edits (~30 lines) with the widening | medium-low |
| `agent/session_persistence.py` | project persona rows to native wire shape at flush | NO | none: no persisted-row hook (`transform_llm_output` covers final assistant text only) | — (ROW-PR) | high |
| `agent/skill_commands.py` | "required by runtime policy" activation note | FIRST | upstream's preload note already marks the skill active for the session; the "required on this surface" emphasis rides the plugin's existing `eternia-harness.tool-guidance` system-prompt section (`register_system_prompt_section`) | the `required_skill_names` parameter and branch (8/2) | low-medium |
| `agent/skill_utils.py` | append shared skills root; exclude inbox dirs; trust all roots | NEAR | `skills.create_dir` — a WRITABLE, non-external root upstream already places second in `get_all_skills_dirs()` (upstream's own docstring: "e.g. a shared fleet dir"); a plugin-set profile default points it at the shared root. ADOPT checked `external_dirs` only. Widening: `normalize_skill_lookup_name` and `skills_tool._skill_search_dirs` trust `get_all_skills_dirs()` (upstream reads only external dirs there — a bug for any create_dir user); `.realm_inbox` / `.provenance` move outside the root or join `EXCLUDED_SKILL_DIRS` | the shared-root append (4 lines) now; the trust edit (1) and the excluded names (1) with the widening | medium |
| `agent/system_prompt.py` | `tool_names` in plugin section session info | NO | none: the section callback has no other view of the session's tool set; the 1-line widening IS this row | — | high |
| `agent/transports/codex.py` | persona content-addressed cache key and bounded headers | FIRST | same `llm_request` door as `chat_completion_helpers.py`: `persona_content_cache_key(instructions, tools)` is computable from the request (and matches the briefed wire tools better than the pre-brief ones) | the whole hunk (20/0) | medium |
| `agent/turn_api_call.py` | request-assembled mark + provider-dispatch span around dispatch | FIRST | `llm_execution` middleware wraps EXACTLY the callable `ProviderDispatchTiming.wrap` wraps (`_perform_api_call`), inline, with `api_request_id` / `api_call_count` / model in context. The sink (`agent.status_callback`) comes from a fork ContextVar set by `profile_runner`, which builds that callback. Loss: the mark lands before the Codex transport preflight, so a Codex token refresh is charged to the provider side | the two hunks (6/1) and `ProviderDispatchTiming.wrap`/`mark` | medium-high |
| `agent/turn_api_request.py` | request_build / pre_api_hook / request_dump stamps | FIRST | bracketing doors: `pre_api_request` carries `started_at` (attempt start); `llm_request` middleware entry ends request_build; the plugin's own `pre_api_request` callback ends pre_api_hook (registered last); `llm_execution` entry ends request_dump. Same ContextVar sink | the 11 added lines | medium-low |
| `agent/turn_context.py` | skip re-append of the pre-persisted persona user row | NO | none (ROW-PR `history_includes_current_user`) | — | high |
| `agent/turn_facade.py` | `reuse_current_user_message` forwarder kwarg | NO | none (ROW-PR) | — | high |
| `agent/turn_response_check.py` | response_validate timing stamp | NO | none: no bracket around `validate_response_shape`. Recommend deleting the stamp (a sub-ms span) rather than a widening PR | 6 lines if the stamp is dropped | high |
| `apps/desktop/src/lib/desktop-slash-registry.json` | `/queue-status` + `/qstatus` entries | FIRST | follows `/queue-status` onto `pre_gateway_dispatch` (see `hermes_cli/commands.py`) | 2 lines | medium |
| `gateway/hosted_room_discussion.py` | host-declared Discussion limits, active member set | NO | none: the planner reads module constants | — (Group Chat host PR) | high |
| `gateway/hosted_room_policy_checkpoint.py` | host-declared active-event budget | NO | none | — | high |
| `gateway/hosted_rooms.py` | pin/unpin retained room history | NO | none (a plugin-side transcript copy would be a second store — the very pattern) | — | high |
| `gateway/run.py` | downstream mixin; tirith heads-up; durable restore at start | NO | tirith is an upstream fix PR; restore is P2 (upstream restores in `ProcessRegistry.__init__`, the import side effect the fork removed). Pieces FIRST: `/queue-status` → `pre_gateway_dispatch`; `_kanban_blocked_pm_hook_watcher` → `on_kanban_dispatch_tick` | the mixin sheds `_handle_queue_status_command` and the PM watcher (they move to the plugin); the mixin line stays for the BG helpers | medium |
| `gateway/run_busy.py` | `queue-status` in the busy-path plain commands | FIRST | `pre_gateway_dispatch` (async, kwargs `event`, `gateway`, `session_store`; fires before auth and before the busy intercept): the plugin matches `/queue-status`, checks `gateway._is_user_authorized_for_source(event.source)`, sends the report via the adapter, returns `{"action": "skip"}`. Answers both S2 objections (no runner context; busy path never dispatches plugin commands) | 1 line | medium |
| `gateway/run_startup.py` | PM blocked-hook watcher in the pre-reconnect tuple | FIRST | `on_kanban_dispatch_tick` — fires in the gateway dispatcher once per tick, after the dispatch lock is released; the watcher's cursor scan (`unseen_blocked_events` + `handle_blocked_event`) runs there. `kanban_task_blocked` is the event-driven alternative (fires in the worker process). Latency moves from 5 s to `kanban.dispatch_interval_seconds` | 1 line; ~70 lines of watcher move from the mixin to the plugin | medium-high |
| `hermes_cli/auth.py` | head-bound auth store selection | NO | none: `_auth_file_path` is the one resolver; secret sources (`register_source`) cannot carry a single-use OAuth refresh chain | — (HOME-PR) | high |
| `hermes_cli/auth_commands.py` | `auth set-key` / `auth login` dispatch | FIRST | the fork's own top-level plugin command (`register_cli_command`, the `harness` verb): `hermes harness auth set-key|login`. Needs a launcher argv change (`provider_connect_controller.dart`) — cross-repo | 7 lines | medium |
| `hermes_cli/commands.py` | `queue-status` CommandDef | FIRST | `pre_gateway_dispatch` as in `run_busy.py`; the plugin may still `register_command` a stub for help listings | 2 lines | medium |
| `hermes_cli/config_defaults.py` | BG agent-turns default; kanban claim TTL default | FIRST | BG: both readers (`gateway/downstream_extensions.py`, `tui_gateway/session_notifications.py`) already return False when the key is absent, so the DEFAULT_CONFIG line changes no behaviour. Claim TTL: upstream `kanban_db._resolve_claim_ttl_seconds` reads `HERMES_KANBAN_CLAIM_TTL_SECONDS` for every claim AND the heartbeat extension (the config key never reaches the latter); the plugin sets it with `os.environ.setdefault(..., "2700")` at `register()` — a default with the operator's env as the opt-out | 8 lines; with the G9 upstream rows (below) | medium-high |
| `hermes_cli/main.py` | profile-bootstrap move, boot clock, parsers, restore, declared commands | NO | bulk is P1 (profile bootstrap, −187) and P2 (restore). Boot-clock marks: none (`pre_command` is slash-only). Parser seam → `register_cli_command` is already planned S1 | S1 hunks only (already planned) | high |
| `hermes_cli/plugins.py` | manifest-declared CLI commands without discovery | NO | none: `_plugin_cli_discovery_needed` imports every plugin for a non-builtin verb | — (Stage 1 PR) | high |
| `hermes_cli/plugins_manifest.py` | `cli_commands` manifest field | NO | none | — (Stage 1 PR) | high |
| `hermes_cli/profiles.py` | mark bound personas orphaned on delete | FIRST | upstream writes a durable tombstone on delete (`hermes_constants.mark_named_profile_deleted`) and exposes `named_profile_is_deleted` / `named_profile_is_live`; the fork derives orphanhood at read time from that fact instead of writing a second one. Caveat for the owner: `clear_named_profile_deleted` on re-create would re-adopt same-name personas | 2 lines + `mark_profile_personas_orphaned` | medium |
| `hermes_cli/subcommands/auth.py` | `set-key` / `login` parsers | FIRST | as `auth_commands.py` | 35 lines | medium |
| `model_tools.py` | per-run blocked tools; memo counters; `tool_describe` injection | NEAR | blocked tools: upstream `disabled_toolsets` is already subtracted at tool granularity; widening = a `disabled_tools: list[str]` beside it on `get_tool_definitions` / `init_agent` (a parameter, not a hook). A pure first door (`llm_request` drop + `pre_tool_call` veto) was rejected: the tool-search catalog listing in the system prompt would still name blocked tools. Injection → `llm_request` middleware appends the schema (needs the `tool_search.py` describe widening). Counters: drop | the filter (~15) with the parameter; the injection (8) with the middleware | medium |
| `run_agent.py` | `blocked_tool_names` constructor kwarg | NEAR | the same `disabled_tools` parameter | 1 line | medium |
| `tests/tools/test_modal_sandbox_fixes.py` | expects injected `tool_describe`; native host cwd helper | NEAR | follows `model_tools.py`; `_native_host_cwd` is G2 | the injection expectation with it | medium |
| `tools/async_delegation.py` | delegation store at background-work home | NO | none (upstream `_db_path` is private; no per-store home) | — (HOME-PR) | high |
| `tools/mcp_tool_config.py` | child HERMES_HOME, per-server env overrides, platform drop | NO | none verified. Unchecked lead: upstream `hermes_platform.declaration` availability (the `requires_apps` gate) may express the platform drop | — (G13) | medium |
| `tools/mcp_tool_transport.py` | pass `server_name` / `runtime_env` to safe env | NO | follows `mcp_tool_config.py` | — | high |
| `tools/process_registry.py` | late notify request routing; checkpoint home; wait ceiling; PTY EOF | FIRST (ruled 2026-09-24) | `tool_request` middleware sets `notify_on_complete=True` on `terminal(background=True)` at spawn; the persona-gone drop moves to delivery. Residue: `checkpoint_path` → NO (HOME-PR); the 600 s wait ceiling → candidate first door `TERMINAL_TIMEOUT` (upstream `wait` reads it at call time) if mission chat runs in its own process (side effect: raises the foreground terminal default there); `0x1A` EOF → G2 | the `_move_to_finished` block, `notify` action/enum/schema line, `ProcessNotificationMixin` notify path, `tools/process_notify_store.py` (~45 of 55 lines here) | high (ruled) |
| `tools/skills_tool.py` | fork resolver, surface gate, provenance fields, POSIX paths | NO | resolution replaces upstream's candidate collection (no hook). Pieces: surface gate → NEAR (as `prompt_builder.py`); `resolution_status` / `source_kind` / `content_hash` result fields → FIRST via `transform_tool_result` on `skill_view` | the 3 result-field lines now; the surface gate (9) with the widening | medium |
| `tools/skills_tool_plugin.py` | surface gate on plugin-served skills | NEAR | as `prompt_builder.py`. Note: upstream's `environments:` is offer-time only — explicit loads always succeed — so the typed refusal becomes a hidden-from-offer | 10 lines | medium-low |
| `tools/terminal_tool.py` | envelope gate + provenance; CLI guidance; container scope; brief | NO | the S2 objections: direct callers (`bot_mode_dm`, `tui_gateway/methods_complete.py`, evals) bypass any executor-level door — stands. The typed-result objection does NOT: `tool_execution` middleware can return the typed block JSON and merge provenance. Piece FIRST: `brief_schema("terminal", …)` is a literal second door — the plugin's `llm_request` brief rewriter already carries `terminal` in `BRIEF_DESCRIPTIONS` and `tools/downstream_schema.py` says it is idempotent over the registration opt-in | the `brief_schema` import + wrap (2 lines) now; the gate stays until the guard PR | high (brief), high (gate) |
| `tools/tool_search.py` | never_defer; top-hit parameters; always-on describe; legacy args | NEAR | widening = `tools.tool_search.never_defer` config key + `dispatch_tool_describe` serving every current tool, not only deferrable ones (the G19 core). Pieces FIRST: legacy `query`/`name` args → `tool_request` rewrite + `transform_tool_result` reshape; top-hit `parameters` and the full description on describe → `transform_tool_result` | ~60 lines by first doors now; the rest with G19 | medium |
| `toolsets.py` | `skill_search` in core/skills; `harness_core` composite; expander | NEAR | widening = register-toolset / core-bundle membership for `skill_search`. Pieces FIRST: the `skills` list edit is redundant (`resolve_toolset(include_registry=True)` already merges the plugin's `register_tool(toolset="skills")`); `harness_core` → persona profile configs list its 15 member toolsets (a plugin-set default); `expand_toolset_names` is a pure function over `TOOLSETS` → `agent_runtime` | ~50 of 70 lines now | medium |
| `tui_gateway/hosted_room_driver.py` | reconciliation request; settlement fixes | NO | none (Group Chat host PR + plain fixes) | — | high |
| `website/docs/reference/slash-commands.md` | `/queue-status` doc row | FIRST | follows `/queue-status` onto `pre_gateway_dispatch` | 1 line | medium |

## Summary

**Counts:** FIRST 16 · NEAR 8 · NO 22 (46 rows). First-door PIECES also sit inside
six NO/NEAR rows: `gateway/run.py` (queue-status, PM watcher), `terminal_tool.py`
(brief), `skills_tool.py` (result fields), `tool_search.py` (args, parameters,
description), `toolsets.py` (skills list, composite, expander),
`conversation_compression.py` (child metadata).

**FIRST-DOOR, by lines deleted from upstream files** (fork-file moves not counted):

1. `tools/process_registry.py` — ~45 of 55 (ruled; `tool_request` sets `notify_on_complete` at spawn)
2. `agent/conversation_loop.py` — ~40, plus upstream rows `tools/lazy_deps.py` 85 and `hermes_cli/tools_config_cua.py` 7 (`security.allow_lazy_installs` / `HERMES_LAZY_INSTALL_TARGET`)
3. `hermes_cli/subcommands/auth.py` — 35 (harness spelling; launcher change)
4. `agent/transports/codex.py` — 20 (`llm_request` in-place cache-key rewrite)
5. `agent/turn_api_request.py` — 11 (bracketing doors)
6. `agent/chat_completion_helpers.py` — 8 (with 4)
7. `hermes_cli/config_defaults.py` — 8, plus G9 upstream rows below (`HERMES_KANBAN_CLAIM_TTL_SECONDS`)
8. `agent/skill_commands.py` — 8 (preload note + prompt section)
9. `hermes_cli/auth_commands.py` — 7 (with 3)
10. `agent/turn_api_call.py` — 6 (`llm_execution` middleware)
11. `apps/desktop/src/lib/desktop-slash-registry.json` — 2 (queue-status)
12. `hermes_cli/commands.py` — 2 (queue-status)
13. `hermes_cli/profiles.py` — 2 (upstream tombstone)
14. `gateway/run_busy.py` — 1 (queue-status)
15. `gateway/run_startup.py` — 1, plus the ~70-line watcher leaving the mixin (`on_kanban_dispatch_tick`)
16. `website/docs/reference/slash-commands.md` — 1 (queue-status)

**NEAR-DOOR widenings, one line each:** local-endpoint floor exemption (`agent_init`,
`conversation_compression`); `skills.create_dir` trusted by lookup/search
(`skill_utils`); plugin-registered skill environment detector (`prompt_builder`,
`skills_tool`, `skills_tool_plugin`); `disabled_tools` parameter (`model_tools`,
`run_agent`, test); `never_defer` key + describe-all (`tool_search`); core-bundle
membership (`toolsets`); `post_api_request` fired on the Codex app-server path
(`codex_runtime` usage half).

**Upstream-row hits (same shape, `upstream` rows):**

- G1 — `tools/lazy_deps.py`, `hermes_cli/tools_config_cua.py`, the refusal half of
  `agent/anthropic_adapter.py`: upstream's `security.allow_lazy_installs` and the
  `HERMES_LAZY_INSTALL_TARGET` sealed-venv redirect already keep a turn from mutating
  the running venv (behaviour differs outside a turn — owner question).
- G9 — `gateway/kanban_watchers_dispatcher.py`, `hermes_cli/kanban_ops.py`,
  `hermes_cli/kanban_parser.py`, the `run_daemon(ttl_seconds)` half of
  `hermes_cli/kanban_db_dispatch.py`: `HERMES_KANBAN_CLAIM_TTL_SECONDS` is read by
  every claim and by the heartbeat extension; a plugin `setdefault` replaces the
  config key and the `--claim-ttl` flag.
- BG (gateway half) — `gateway/run_notifications.py`, `evals/completion_backlog_probe.py`:
  "compact notice, no agent turn" is upstream's `notify_on_complete=False` plus
  `display.background_process_notifications: result`. This COLLIDES with the
  2026-09-24 ruling ("notify on by default"): with notify on and BG off the fork
  suppresses the very turn the ruling turns on. The owner reconciles which door
  "on" means. The TUI half (`tui_gateway/session_notifications.py`) also gates
  kanban and delegation events and has no door.

**Top 5 for the next merge lane** (conflict risk × confidence × no owner question left):

1. `tools/process_registry.py` notify block — ruled; it is the trial merge's one conflict.
2. Kanban claim TTL → `HERMES_KANBAN_CLAIM_TTL_SECONDS` default — `config_defaults.py`
   plus the four G9 upstream rows; also fixes the heartbeat never seeing the config value.
3. PM blocked-hook watcher → `on_kanban_dispatch_tick` — `run_startup.py` and the
   watcher out of `gateway/run.py`'s mixin.
4. `/queue-status` → `pre_gateway_dispatch` — five files (`commands.py`, `run_busy.py`,
   the desktop registry, the docs row, the mixin handler).
5. Provider dispatch timing → `llm_execution` middleware (`turn_api_call.py`), with
   the ContextVar sink it needs, which then also serves `turn_api_request.py` and the
   cache-routing pair (`chat_completion_helpers.py`, `transports/codex.py`).

Free with any of them: delete `brief_schema("terminal", …)` in
`tools/terminal_tool.py` (2 lines; the middleware already does it). Held for an owner
answer: G1 via lazy-install config (behaviour outside turns), BG vs the notify ruling,
`profiles.py` tombstone (re-create re-adopts), the auth spelling move (launcher change).
