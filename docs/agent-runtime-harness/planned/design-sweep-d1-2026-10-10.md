# Design sweep D1 — admission memo, prewarm and import cost, cancel / params / spawn ownership, preload and slot caches (2026-10-10)

Lane fable-design-D1. Twelve runtime-queue rows a fix lane returned as too big or a design
job, each read against the code before a verdict. Verdicts: **PLAN** (implementation-ready
for an Opus build lane), **PROGRAM-EXISTS** (a plan already owns it), **INVESTIGATION** (the
cause is unknown; the protocol that names it), **DROP** (stale or wrong, with the evidence).
Rows that share one mechanism are designed once; the others point at it. Code is cited by
file and symbol, never line.

House rules every PLAN below inherits: fork-owned files first; an upstream file is edited
additively or not at all, with its row named in
[`upstream-footprint-ledger.md`](upstream-footprint-ledger.md); one MOVE commit and one
CHANGE commit per lane; a gate lands with its killing mutation named and its red recorded in
the commit body; the landing gate is `scripts/run_tests_bundled.sh tests`, never bare pytest.

## Cluster A — the tool registry moves every turn (D1.01, D1.02, D1.03)

Three rows, one fact: `tools/registry.py::ToolRegistry` is process-global and bumps
`_generation` on every `register` / `deregister` / `register_toolset_alias`, and two fork
paths move it on turns whose tool surface did not change — MCP admission (register N tools,
tear N down, every admitting run) and the app-function catalog flip (two attached Launchers
with different lists overwrite each other). Two memos key on the generation:
upstream `model_tools._tool_defs_cache_key` (schemas + handlers; a miss is a full
`get_tool_definitions` rebuild, measured 202–215 ms on a 44-tool fixture home) and, until it
was re-keyed on content, the chat-lane bundle. The fork's answer is **stop the churn**, not
re-key upstream's memo: the generation is the right key for a memo that caches schemas and
handlers (the content revision deliberately excludes both), so an upstream PR that keyed it on
content would be wrong for upstream's own callers.

### D1.01 = L1.03 — `agent_ready` costs 22–23 ms on a reused actor; a per-actor MCP admission memo

**Verdict: PLAN** (the admission half; the ~11 ms of durable write-ahead / mirror / executing
writes is out of scope by the row's own words).

**What the code does today.** `profile_runner/execute.py::AgentRunExecution.run` enters
`admit_mcp` on every run — prewarm or turn, cold or reused actor. `runner.py::_admit_mcp_servers`
→ `mcp_admission/registration.py::admit_mcp_servers` → `Admission.run`: acquire
`_ADMISSION_LOCK`, classify warm/cold, run `transport.py::_default_registrar` on a worker
(warm servers: `_reregister_warm_server` registers every admitted tool off the live session —
N `registry.register` calls, N generation bumps), then `_install_call_budget` swaps each
entry's handler for a `_metered_handler` closed over this run's `McpCallBudget` (attribute
write, no bump). The scope's `ExitStack` callback `runner._teardown_mcp_admission` →
`teardown_mcp_admission` → `_deregister_toolset_scopes`: N `registry.deregister` calls, N
more bumps. Net: the registry ends every admitting run exactly as it began, the generation
moved 2N, and `mcp_admission_ms` 10–11 was spent re-listing and re-registering tools the
transport already holds. The transport itself is already resident (`tools/mcp_tool._servers`
keeps the session; R2 ruled "tear the scope down, keep the transport warm").

**Why the teardown is not the isolation mechanism.** Isolation between personas is
`mcp_admission/resolve.py::scope_toolsets_to_admission`, applied to every run's enabled set:
a registered `mcp-*` toolset the run was not admitted is stripped before
`get_tool_definitions` runs. `teardown_mcp_admission`'s own fix_hint says so of the residue
case ("the next run's toolset scope still refuses any MCP toolset it was not admitted, so this
is residue, not exposure"), and `chat_lane_bundle.registry_content_revision` already ignores
`mcp-*` registrations for the same reason. Upstream's own `chat` and `gateway` lanes leave
`discover_mcp_tools()`'s registrations resident for the process lifetime. A resident admitted
scope is therefore not a new exposure class; it is the state upstream runs in.

**Decision.** An admitted server's registry scope lives as long as its transport session and
its admission content, not as long as one run. The per-run work becomes: bind this run's call
budget to the already-registered metered handlers; on the way out, unbind the budget and keep
the scope. The run-serialising `_WORKDIR_LOCK` means at most one run's budget is live per
process, so the budget slot is one per server, not a stack.

**Owner question (blocks S1):** this reverses R2's per-run teardown ruling
(`archive/2026-08-22-pre-consolidation/mission-chat-mcp-admission.md` § R2). Confirm "scope
lifetime = transport session + admission content" is acceptable, given isolation is the
toolset scope above.

**Files and symbols (all fork-owned).**
- `agent_runtime/mcp_admission/registration.py`: new `_RESIDENT_SCOPES: dict[server, ResidentScope]`
  (`ResidentScope`: `filter_revision` — digest of the admitted config's `tools` filter and
  server config; `session_id` — `id()` of the live session object from
  `transport._live_mcp_sessions()`; `tool_names`), `Admission._work` skips the registrar for a
  server whose resident scope matches and whose tools are all still registered, and
  `_install_call_budget` becomes `_bind_call_budget` (writes a per-server budget slot the
  metered handler reads at call time instead of closing over it). `teardown_mcp_admission`
  becomes `release_mcp_admission(servers)`: clears the budget slots; deregisters ONLY a server
  whose resident scope is invalid (filter changed, session object gone or replaced, partial
  registration). New `drop_resident_scopes(servers | None)` for explicit retirement.
- `agent_runtime/mcp_admission/transport.py::_default_registrar`: takes the resident map so a
  warm server already registered is not re-listed.
- `agent_runtime/profile_runner/runner.py::_admit_mcp_servers` / `_teardown_mcp_admission`:
  rename to the release verb; `timing["mcp_admission_reused"] = 1` when every admitted server
  was resident (an int flag inside the `safe_turn_profile_timing` vocabulary); the
  `run.progress` summary says "reused" vs "registered".
- `agent_runtime/persona_chat_continuity/runtime_registry.py`: actor eviction / rebuild calls
  `drop_resident_scopes` for the admission the evicted actor held (the memo must not outlive
  every actor that could use it); `tools.mcp_tool.shutdown_mcp_servers` at process exit already
  owns the connections.
- Docs: `05-chat-turn-lane.md` (the `teardown_mcp_admission` sentence) and
  `03-transport-and-wire.md` (same) say the scope is resident; `02-runtime-data-and-shapes.md`
  gains `mcp_admission_reused`.

**Stages.**
1. **S1 resident scope + budget slot.** Tests (`tests/agent_runtime/test_mcp_admission_resident_scope.py`,
   fake registrar as `admit_mcp_servers(register=...)` already allows): two admissions of the
   same set on one process — the registrar is called once, `registry.generation` is equal
   before run 2 and after its release, the second run's budget meters the second run (a call
   over the limit in run 2 is refused by run 2's `McpCallBudget`, run 1's spent count is not
   carried). Killing mutation: drop the resident-scope check in `_work` → generation moves
   (red named: the equality assertion). Second mutation: keep `_install_call_budget`'s
   closure → run 2 refuses on run 1's spent count.
2. **S2 invalidation.** Tests: a changed `tools` filter re-registers (names differ);
   a session object replaced (simulate `_live_mcp_sessions` returning a new object) re-registers;
   `drop_resident_scopes` empties the registry of that server's tools; a partial registration
   (one tool deregistered by a failed meter) is re-registered whole. Killing mutation: key
   on server name only → the filter-change test keeps stale names.
3. **S3 receipts and the D1.02 proof.** `mcp_admission_reused` lands in timing and the record;
   `tests/agent_runtime/test_tool_defs_memo_survives_admission.py`: on the fixture home, two
   admitting turns → `model_tools._bump_tool_defs_counter("hits")` counter rises on turn 2
   and `_tool_defs_cache` has one entry for the key. Killing mutation: re-enable per-run
   deregistration → the hit counter stays flat.

**Size.** ~220 lines code, ~180 lines tests, two canon doc edits. One lane (Opus), one MOVE
(the rename) + one CHANGE.

**Risks.** (1) A tool the fork never calls between runs still appears in the serve process's
`get_tool_definitions(quiet_mode=True)` at boot (`serve/boot.py`) — that call runs before any
admission, so unaffected; `tool_surface.read_surface` always passes an admission-scoped
enabled set. (2) An MCP server that re-lists a different tool set without reconnecting
(dynamic tool lists) would be served the resident names until the filter or session changes;
decision rule: the first stage also keys on `len(session.tools)` if the SDK session exposes a
tool list, else document the limit. (3) `registered_mcp_server_names()` (ground truth from the
registry) now returns admitted servers between runs — its one consumer outside admission is
`mcp_lane`; read its callers in S1 and keep the `scope_toolsets_to_admission` strip as the
gate.

### D1.02 = L3.14 — admission churn moves `registry.generation` and drops upstream's tool-definitions memo

**Verdict: PLAN — the same mechanism as D1.01; no separate build.** The lane measured the
miss (202–215 ms rebuild vs 0.1–0.5 ms warm; generation +2 per probe on a 44-tool home). The
D1.01 resident scope removes the per-run bumps, so `_tool_defs_cache_key` (which also carries
`app_function_tool_scope()`, the profile scope and the config signature) hits on a reused
actor's turn. D1.01 S3 is this row's gate. The upstream-PR alternative (key the memo on
content) is rejected above: schemas and handlers are what that memo caches, and admission
swaps every admitted handler for a metered one. The callers that pay the miss on a reused
actor are `agent/tool_executor.py` (tool_search scoped names, per search call) and
`agent_runtime/tool_surface.py::read_surface` (per preview); `agent/agent_init.py` pays it
only on construction. After D1.01 the remaining per-turn generation mover is D1.03's catalog
flip.

### D1.03 = L2.24 — the app-function registry holds ONE connection's list; two Launchers flip it

**Verdict: PLAN.**

**What the code does today.** `agent_runtime/launcher_app_functions.py::_ToolsetState` keeps
one `registered` map; `refresh_app_function_tools(link)` re-syncs the registry to THIS link's
catalog every turn (`_sync_registry`: deregister names not wanted, register changed ones),
idempotent only when the two connections' lists are equal. Two attached answerers with
different lists (stdio Launcher + a socket Launcher of another version, or the QA tool)
alternate the registry on every turn: each flip is a correct turn and a generation move, and
the bundle's `registry_content_revision` (names + toolsets) genuinely changes, so the chat-lane
bundle rebuilds too. The lane's two options: (a) a per-connection registry `scope` — rejected:
`ToolRegistry.current_scope_key()` is `hermes_home_key()`, the scope IS the profile, and
threading a connection through `get_tool_definitions` → `registry.get_definitions` is a
non-additive upstream seam; (b) key the memo on catalog identity — insufficient alone, the
registry would still move.

**Decision.** The registry holds the UNION of every live catalog's entries (by name); which of
them THIS turn may see is answered per entry at definition time, from the bound link's
catalog, through two registry features that already exist and are evaluated per
`get_definitions` call: `check_fn` (wrapped `no_cache_check_fn`, as today) and
`dynamic_schema_overrides` (a zero-arg callable merged onto the schema). A flip then moves
nothing; `forget_launcher_connection` removes only names no surviving catalog holds.

**Files and symbols (fork-owned only).** `launcher_app_functions.py`:
- `_sync_registry(entries)` → `_sync_registry_union()`: wanted = union over
  `_state.catalog.values()` by name; a name declared by two catalogs with different schemas
  registers once with `dynamic_schema_overrides=lambda: _bound_schema(name)` (the bound link's
  catalog's schema for that name, falling back to the registered one) and a one-line
  `logger.info` naming both connections; `check_fn=no_cache_check_fn(partial(_offered_to_bound_link, name))`
  — True only when the current link's catalog holds `name` (a turn with no link: False, as
  `_link_available` is today). `_state.registered` becomes derived (`name → entry` of the
  union) and stays the source for `app_function_guidance_lines` / `mutating_app_function_tools`
  (a union superset of mutating names blocks more, which is the safe direction).
- `refresh_app_function_tools`: the held-catalog branch still returns THIS link's names (the
  caller's enabled-toolset decision), and calls the union sync, which is a no-op unless a
  catalog was added or removed.
- `forget_launcher_connection`: drops the catalog, re-syncs the union (removes orphaned names;
  empties the toolset when no catalog is left, as today).
- `app_function_tool_scope()` unchanged — it already keys `_tool_defs_cache_key` per catalog
  token, so two links never share an assembled list.

**Stages.**
1. **S1 union registration.** `tests/agent_runtime/test_launcher_app_function_catalog.py::test_a_cached_catalog_is_resynced_after_another_connection_overwrote_the_registry`
   flips its expectation (the first connection's tool stays registered while any catalog
   holds it; the registry generation is equal across the two refreshes). New: a tool only
   connection B declares is NOT in `get_tool_definitions(enabled_toolsets=[APP_FUNCTIONS_TOOLSET])`
   while A's link is bound, and IS while B's is; `forget(A)` removes A-only names only.
   Killing mutation: `_offered_to_bound_link` returns `_link_available()` → B's tool leaks
   into A's definitions (red named).
2. **S2 schema conflict.** Same name, two parameter schemas: definitions under A's link
   carry A's parameters, under B's B's. Killing mutation: drop `dynamic_schema_overrides` →
   one link sees the other's parameters.
3. **S3 the bundle receipt.** `visibility_bundle_rebuild_component_registry_content` stays
   0 across alternating A/B turns on a two-connection serve test
   (`tests/agent_runtime/test_chat_lane_bundle_two_launchers.py`). Killing mutation: revert
   `_sync_registry` to the single-list form → the component flag reads 1.

**Size.** ~110 lines code, ~150 lines tests. One lane, one CHANGE commit (no MOVE).

**Risks.** `always_loaded_app_function_tools` and the guidance lines already read the bound
link's catalog, so discovery classification is unchanged. `tool_contract()`'s
`launcher_link_available` boundary read is unchanged. A paired-device link (`ORIGIN_PAIRED_DEVICE`)
reads the gateway sink's catalog exactly as today.

**Owner question:** none blocking. Decision rule for a schema conflict: the bound link's
schema wins at definition time; the registered (static) schema is the most recently listed
catalog's.
