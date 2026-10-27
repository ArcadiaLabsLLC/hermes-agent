**BUILT — archived 2026-10-27 by triage lane w1027j-h-tri-a; landing commits 5d7435ea1a, 6b71ebd7f7, 3310a8bc26, 5b6742a369.**
B1–B4 landed: the bundled edition subtracts its profile toolsets and opt-in is the approval record.

# Planned — the bundled edition subtracts its profile's toolsets at load time; per-agent opt-in is an approval record — 2026-10-21

**Owner domain:** the bundled editions and namespaces (`docs/downstream/bundled-desktop-closure-2026-09-28.md`;
launcher plan `EterniaLauncher/docs/embedded_hermes/planned/EDITION_SWITCH_NAMESPACE_STORE.md` §6 R6); the
chat turn's tool surface ([04](../04-chat-turn.md) § Toolsets, `agent_runtime/chat_lane_tool_form.py`).
**Status:** IMPLEMENTATION-READY (design lane w1021i-plans). One doc, no code.
**Measured / read:** 2026-10-21 against hermes `origin/main` d087df7035;
`tests/scripts/test_bundle_shared_config_closure.py` (`CONFIG_ONLY = {terminal, code_execution, browser,
browser-use}`, measured 2026-10-20 over the live registry).

Row: `RT-NAMESPACE-SHARED-CONFIG-SHELL-FAMILY` (runtime-queue § Fork-owned).

## 0. Rulings this plan is bound by

`RULED 2026-10-21: owner — the bundled edition subtracts its profile's toolsets.disabled at load time
whatever the shared config.yaml says; per-agent opt-in through an explicit approval record the bundled
edition writes.` This plan decides only the record's shape and write path.

## 1. What is true today (file::symbol)

- The profile: `agent_runtime/bundle_profiles/bundled-desktop.yaml` `toolsets.disabled` (terminal,
  code_execution, browser, browser-cdp, browser-use, computer_use, the messaging five); the header says
  "present but off … a single agent's profile may drop the toolset from its own
  `agent.disabled_toolsets`, with approvals" — the opt-in the ruling now types.
- `bundle_profiles/manifest.py::apply_to_config(manifest, config)` unions the profile's list into
  `agent.disabled_toolsets` — called by NO runtime path (only tests and `scripts/bundle_profile_gate.py`).
  So today the bundled serve's refusal rests on whatever `agent.disabled_toolsets` the namespace's
  `config.yaml` holds, and a Developer-Edition edit of that shared file re-enables the four whose
  modules ship.
- The edition authority: `hermes_cli/steward.is_bundled_payload(root)` (the build stamp), used by
  `agent_runtime/namespace.py` (`edition` on the owner stamp) and `hermes_cli/namespace_cmd.py`.
- The turn's disabled set: `agent_runtime/persona_runtime.py` builds `AgentRunRequest(enabled_toolsets=
  lane_bundle.enabled_toolsets, blocked_tool_names=…, chat_lane_defer_tools=…)` from
  `chat_lane_bundle(persona, session_id)` and passes NO `disabled_toolsets`; `profile_runner/execute.py`
  hands `request.disabled_toolsets` to the agent factory; upstream `agent/agent_init.py::_load_tools`
  stores `session_disabled_toolsets(disabled, platform)` on `agent.disabled_toolsets`, which
  `model_tools._select_tool_names`, the tool_search bridge, MCP refresh and delegate children all
  subtract; `agent_runtime/tool_surface.py` and `chat_lane_tool_form.py` read `agent.disabled_toolsets`
  back. Config's own `agent.disabled_toolsets` is ADDED by upstream inside the agent (a union) — config
  can only add disables, never remove one the request carries. The prewarm builds the same request
  (`persona_chat_actor_prewarm.py`).
- Per-persona config lives in the persona's bound profile home (`persona_profiles.py`), which is where
  "its own `agent.disabled_toolsets`" would have been edited — the write the ruling replaces.

## 2. Decisions

- `Decided (plan):` **one seam, the request.** `agent_runtime/bundled_toolsets.py` (fork-owned,
  `policy`): `bundled_disabled_toolsets(persona) -> tuple[str, ...]` = the bundled profile's
  `toolsets.disabled` minus the persona's approved opt-ins, EMPTY on the Developer Edition
  (`is_bundled_payload` false). `chat_lane_bundle` carries it as `disabled_toolsets` and both request
  builders pass it. Because upstream unions config into the request's list, the shared `config.yaml`
  can never re-enable what the request disables — the ruling's "whatever the shared config says" holds
  by construction, with no edit to the config loader and no edit to an upstream file.
- `Decided (plan):` **the approval record** is `<HERMES_HOME of the persona's bound profile>/
  approvals/toolsets.json` — one file per persona profile, in the profile home the bundled edition
  already owns (never the shared namespace config, which the Developer Edition may write):

  ```json
  {"schema_version": 1,
   "approvals": [{"toolset": "terminal", "granted_at": "<iso>", "granted_by": "operator",
                  "edition": "bundled", "build": "<build stamp sha>", "reason": "<≤240 chars>"}]}
  ```

  A toolset may appear once; only names in the bundled profile's `toolsets.disabled` are accepted
  (anything else is `toolset_not_opt_in`); the messaging five are NOT opt-in-able (their adapters are
  off by `gateway.platform_adapters: false`, so an opt-in would enable tools with no platform —
  `toolset_no_platform`); `computer_use` and `browser-cdp` are opt-in-able only when their modules are
  in the shipped plan (read from the bundle manifest at runtime; today `CONFIG_ONLY` says they are
  not — `toolset_not_shipped`).
- `Decided (plan):` **the write path is one RPC, `runtime.persona.toolset.approve` (`mode: grant |
  revoke`), console tier, written by the bundled edition only** (the Developer Edition answers
  `edition_not_bundled`: it has nothing to opt into, and must not mint a record the bundled edition
  would honour). The record is written through `yaml_io`-style atomic JSON (`utils.atomic_json_write`),
  and a `persona.toolset_approved {persona_id, toolset, mode}` log receipt rides the push lane's existing
  persona section (observability is receipts, never new envelope keys). The Launcher's persona
  settings sheet gets the toggle (launcher row `MC-PERSONA-SHELL-OPT-IN`, filed by the landing commit).
- `Decided (plan):` **the record is read at request-build time, cached by file mtime** (the same
  mtime-keyed YAML cache shape `profile_readiness` uses), so a grant takes effect on the next turn with
  no restart.

## 3. Stages

**B1 — `bundled_toolsets.py`** with `bundled_disabled_toolsets(persona)`, `read_approvals(home)`,
`write_approval(home, toolset, *, mode, reason, granted_by)` and the typed refusals
(`ToolsetApprovalRefused(reason)` with `Reason` StrEnum: `edition_not_bundled`, `toolset_not_opt_in`,
`toolset_no_platform`, `toolset_not_shipped`). The profile is `load_profile("bundled-desktop")` on
desktop and `bundled-phone` under the embedded entry (`bundle_profiles.phone_hint` already knows which;
reuse its selector). Tests (`tests/agent_runtime/test_bundled_toolsets.py`, edition faked by patching
`is_bundled_payload`): Developer → empty; bundled, no record → the profile's full list; bundled with
`terminal` granted → the list minus `terminal`; `discord` grant → `toolset_no_platform`; `kanban` grant
→ `toolset_not_opt_in`. Killing mutation: return the profile's list on the Developer Edition too → the
Developer test reds (and the Developer Edition's own terminal vanishes).

**B2 — the seam into the request** (`chat_lane_bundle` → `disabled_toolsets`; `persona_runtime.py` and
`persona_chat_actor_prewarm.py` pass it; `profile_runner/models.py::AgentRunRequest.disabled_toolsets`
already exists). Test (`tests/agent_runtime/test_persona_runtime_toolsets.py`): with a fake
`_agent_factory`, a bundled edition's turn request carries `disabled_toolsets ⊇ {terminal,
code_execution, browser, browser-use}` even when the profile's `config.yaml` says
`agent.disabled_toolsets: []`; a granted `terminal` is absent from the list; the Developer Edition's
request carries `None`. Killing mutation: read `config.yaml`'s list instead of the profile's → the
"config says []" test reds. This is the positive gate the row asked for: `test_bundle_shared_config_closure
.py`'s `CONFIG_ONLY` ratchet gains the sentence "held by the request seam" and its set stays (the
modules still ship; the refusal no longer depends on the file).

**B3 — the RPC** (`serve_rpc/persona.py` or the persona methods module the manifest routes:
`runtime.persona.toolset.approve {persona_id, toolset, mode, reason}` → the record, refusals as
typed `data.reason`); manifest + contract dump (`scripts/dump_payload_contract.py --check`). Tests: grant
then `runtime.persona.get` shows `toolset_approvals: [terminal]` (an additive field on the persona
read, derived from the record); revoke removes it; Developer Edition → `edition_not_bundled`. Killing
mutation: let the Developer Edition write → red.

**B4 — the mirror in the profile header:** `bundled-desktop.yaml`'s "present but off" sentence now
names the approval record instead of "its own `agent.disabled_toolsets`"; `docs/downstream/
bundled-desktop-closure-2026-09-28.md` § shell family gets the same line.

## 4. Out of scope

The MCP stdio opt-in the same header mentions (`mcp.stdio_servers: false`) — a different switch with a
different record, filed as a follow-on row when an agent needs it. Upstream's own config-level
`agent.disabled_toolsets` semantics. The Launcher toggle (its row).

## 5. Open rulings

- Who may grant: the operator through the Launcher only (recommended), or also a persona's own
  `approvals.*`-style self-request that the operator confirms? · Recommend: operator only in this cut;
  `granted_by` is a field so a confirmed self-request can be added without a schema bump.
