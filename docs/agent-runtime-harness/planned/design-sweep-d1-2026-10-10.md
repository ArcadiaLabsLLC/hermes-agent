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

## Cluster B — a new process pays the world again (D1.04, D1.05, D1.06)

### D1.04 = L2.10 — prewarm holds `_WORKDIR_LOCK` through steps it cannot interrupt

**Verdict: INVESTIGATION** — the row's figures were taken under the boot pile-up its sibling
row describes, and the fork cannot split the two steps it names.

**What the code does.** `profile_runner/execute.py::AgentRunExecution.run` holds
`_WORKDIR_LOCK` (first in `scopes()`) for the whole prewarm and asks `yield_point` at every
phase boundary (`lock_acquired`, `runtime_resolved`, `mcp_admitted`, `agent_acquired`,
`system_prompt_stashed`, then per `warm_first_turn_paths` step); MCP admission polls the gauge
every 50 ms (`registration._ABANDON_POLL_SECONDS`). The two steps that cannot yield are
`construct_agent` (upstream `AIAgent.__init__`, one call) and
`prewarmed_system_prompt.stash_prewarmed_system_prompt` (upstream `agent._build_system_prompt`,
one call). Both need the lock: `persona_profile_context` sets process-global `HERMES_HOME`
and `_agent_workdir` chdirs, which is what the lock serialises. Moving either off the lock
means making profile context per-thread — the god-file program's seam work, not a prewarm
lane; splitting either means an upstream PR that makes `AIAgent.__init__` resumable, which is
not a reasonable door.

**Why the numbers are suspect.** The row's line (agent.log 2026-10-06 20:23:47,
`system_prompt_build_ms=7855 construct_ms=5318`) was logged by serve `5c0f130723`, which
already contains h-prewarm-order (`b62278749f`, 02:38 that day) and the process-once warm
(`first_turn_warmup.PROCESS_ONCE_WARM_RECEIPT`: scratch prune 3,050 ms and the
`openai.resources.responses` import ~1,420 ms are paid on the boot thread). The same minute is
the h-boot-pileup window (`9dba646bb1` body: the serve's first core build 70 s, two CLI
children each building a full core beside it). Offline, uncontended, the first system-prompt
build after the process-once warm is 39 ms and construction is ~1.4–1.8 s tool-setup
(`execute.py::build_turn_state` comment). A 7.9 s prompt build is CPU starvation, not a step
to split.

**Protocol.** On the operator's serve, current build, idle box (no snapshot build in flight —
confirm with no `snapshot_build_core` line in the preceding 60 s): open five chats on five
roots and read each `prewarm_first_turn … system_prompt_build_ms=… construct_ms=…` line;
repeat once with a core build deliberately in flight (`harness snapshot --rebuild` or a cold
boot). Decision rule: uncontended medians `system_prompt_build_ms` < 200 and `construct_ms`
< 2,000 → DROP this row (its cause is Cluster B's other two rows: the fix for a turn waiting on
a prewarm during a boot pile-up is to stop the pile-up); `construct_ms` ≥ 2,000 uncontended →
file ONE row naming the construction phase that dominates (take a `py-spy dump` of the prewarm
worker mid-construct, or wrap `_agent_factory` with the existing `_emit_request_timing` parts)
against `agent/agent_init.py` as upstream-owned, caller-side memo candidates only.

**Not a fix candidate:** "yield mid-construct" — a turn that arrives mid-construction of its
OWN root finds the actor the prewarm built (the NO-OP case the module docstring describes);
a turn on another root waits at most one step, and h-prewarm-order's `chat_turns_accepted`
gauge stops a prewarm from starting a step once a turn is accepted.

### D1.05 = L2.11 — every new process pays the cold snapshot sections again

**Verdict: PLAN**, landing as stages CF-1..CF-3 of the owning doc
[`cold-first-core-build-cost.md`](cold-first-core-build-cost.md) (which today says "no stage
is aimed at the number"). The 2026-10-06 verdict stands: upstream changed none of the four
walkers since the merge base; this is ours.

**The four costs, where each sits, and the fix per cost** (idle box, copy of the operator's
store, 11 personas, ~2,000 SKILL.md; `9dba646bb1` body):

| cost (first build) | owner | why it repeats | fix |
|---|---|---|---|
| `parse_frontmatter` × 2,004, ~4.8 s | `agent_runtime/skill_resolution.py::_skill_root_registry` parses every manifest with `_skills.parse_frontmatter(manifest.read_text())` directly, while `_cached_skill_frontmatter` (same module, `parse_cache.cached_by_mtime`) exists for the compatibility pass | two parsers of one file; the mtime memo is per process | CF-1: one parser; CF-2: a disk tier under the memo |
| skill catalog walk 3.8 s + installed catalog 2.0 s | `prompt_observability/skills_resolver.py::_installed_skill_catalog` → `_walk_skill_catalog(upstream _find_all_skills)` | TTL memo per process; the walker parses frontmatter itself | CF-2 feeds it where the fork owns the call; CF-3 measures the residue |
| provider probe / credential pool 2.7 s | `agent_runtime/provider_probes.py::codex_credentials_resolvable_read_only` → `load_pool("openai-codex").peek()` per snapshot | `load_pool` rebuilds the pool from its files every call | CF-3: build-scoped memo keyed on the pool file and auth-store file signatures |
| kanban toolset detection 2.9 s | upstream `tools/skills_tool.skill_matches_environment` (offer-time gate) per skill per fork walk | called once per manifest per walk | CF-3: measure what inside it costs (env read vs probe); memo per build keyed on `HERMES_KANBAN_TASK` and the probe's inputs — caller-side, fork walk only |

Imports and plugin discovery (~5.7 s of the 17.9 s) are the process's own and stay; the
bytecode recompile after a checkout change is D1.06's.

**Stages.**
- **CF-1 one parser (fork-owned, `skill_resolution.py`).** `_skill_root_registry` reads each
  manifest's frontmatter through `_cached_skill_frontmatter(manifest)`. Test
  (`tests/agent_runtime/test_skill_root_registry_single_parse.py`): a fixture root with 40
  manifests, count `agent.skill_utils.parse_frontmatter` calls (monkeypatch wrapper) across one
  `_skill_root_registry` build plus one `skill_runtime_compatibility` pass per skill = 40.
  Killing mutation: restore the direct `parse_frontmatter` call → 80 (red recorded).
  ~15 lines.
- **CF-2 cross-process frontmatter cache (fork-owned, `agent_runtime/parse_cache.py`).**
  `cached_by_mtime` gains an optional disk tier for ONE loader family — skill frontmatter —
  at `<store_root>/cache/skill_frontmatter.json`: `{resolved_path: [mtime_ns, size, frontmatter]}`,
  loaded once per process on first miss (one JSON read of ~2,000 small dicts, ~10–20 ms),
  written back on the idle path (`idle_turn_keeper.register_refresh`, never on the turn
  thread; a crashed process loses at most the unwritten deltas). Validity is the file
  signature already used by the memo; a stale entry misses and re-parses. The frontmatter
  dict is read-only by contract (docstring of `_cached_skill_frontmatter`). Test
  (`tests/agent_runtime/test_skill_frontmatter_disk_cache.py`): process A builds the registry
  over the fixture root and flushes; a child interpreter (subprocess, same store root) builds
  it with `parse_frontmatter` counted via an env-guarded counter receipt = 0 parses; edit one
  manifest → exactly 1. Killing mutation: skip the disk read on cold miss → 40 parses in the
  child. ~120 lines + the cache dir in the realm-sync hard-exclusion list
  (`realm_sync/families.py::_is_hard_excluded_path`) with its pin test. **Owner question:** a
  derived cache under the store root (beside `core_cache`), or under the profile's cache dir —
  name the directory; the sync exclusion follows.
- **CF-3 build-scoped memos for the probe and the gates (fork-owned).**
  `provider_probes.codex_credentials_resolvable_read_only` memoised per snapshot build keyed
  on `(pool file signature, auth.json signature)` (both paths are the pool's own; read them
  through `parse_cache.cached_by_mtime`'s stamp) — a readiness build asks it once per persona
  today, 11 times per build. Kanban: time `skill_matches_environment` on the fixture root
  first (a 1.5 ms env read × 2,000 is 3 s; if the cost is a probe, memo the probe's answer per
  build keyed on its inputs; if it is import-time, it is a one-time cost mis-attributed to the
  walk). Tests: probe called once per build across 11 personas (killing mutation: drop the
  memo → 11); kanban gate ≤ 1 call per distinct (manifest, env) per build. ~150 lines.
- **Gate for the whole:** extend `tests/agent_runtime/test_stream_relay.py`'s warm budget
  (`agents_readiness` / `prompt_observability` ≤ 1,500 ms warm over the seeded store) with a
  COLD-process budget on the same seed (60 skills, 4 personas; child interpreter with the
  disk cache primed): record the measured numbers in the commit body, set the budget at 2×.

**Size.** Three stages, one lane (Opus), ~300 lines code, ~250 lines tests. Value: the per-process
cold half (~12 s of 17.9 s on the operator's store) drops to the imports (~5.7 s) plus the
unparsed residue CF-3 names; the serve's boot snapshot and every CLI child stop paying the
frontmatter twice.

**Risks.** A disk cache is a second source of truth: validity rests on `(mtime_ns, size)`,
which Windows preserves across copies — a copied store with same stamps and different bytes
is the one false hit; decision rule: also key on the manifest's inode-equivalent where the
platform reports one, else accept (the same rule `parse_cache._stamp` already applies).

### D1.06 = L1.20 — `harness serve` cold boot: interpreter_ms 15,203 of total_ms 21,592

**Verdict: INVESTIGATION** — the segments exist; which of them is I/O and which is CPU is not
yet measured, and the two have different fixes.

**What exists.** `hermes_cli/_boot_clock.import_tax_segments` already splits `interpreter_ms`
into `interpreter_boot_ms` (process start → `main.py` import start), `main_import_ms`,
`dispatch_ms` (main entered → the serve's timeline start), with `bytecode_sweep_ms` and
`harness_parser_ms` reported beside `dispatch_ms`; `serve/boot.py::_annotate_import_tax`
puts them on the boot frame the Launcher parses. The QA-seed figures (interpreter_boot 5,196 /
main_import 4,016 / dispatch 5,991, disk-cold) do not say whether `dispatch_ms` is parser
build, the bytecode sweep, or page-cache misses.

**Protocol** (QA seed machine; one checkout change between runs to force the recompile case):
1. Five boots each in three states — disk-cold after a checkout change (bytecode invalid),
   disk-cold with valid bytecode (reboot, no change), warm (second boot within a minute) —
   reading the five segments off the boot frame. Record medians per state.
2. `python -X importtime -c "import hermes_cli.main"` warm, sorted by cumulative; and the same
   with the harness parser built (`python -X importtime -m hermes_cli.main harness --help`).
3. Decision rules, per segment: (a) cold ≥ 3× warm and the recompile state is ≥ 1.5× the
   valid-bytecode cold state → the cost is bytecode + page cache; the fix is a precompile
   step at install/checkout-change time (fork-owned `scripts/precompile_tree.py` running
   `compileall` over the 149 package dirs, invoked by the Launcher's build step — launcher half
   filed to `mission-control-queue.md`) and nothing lazy; (b) warm `harness_parser_ms`
   ≥ 500 → the harness subparsers build per verb (fork-owned `hermes_cli/harness_parts`
   parser), gated by a test that `harness serve --help` imports no verb module but
   `serve`'s; (c) a warm `main_import_ms` module ≥ 300 ms in `importtime` → named as an
   upstream-owned caller-side lazy import candidate (a `main.py` edit is non-additive;
   the row is a marker). Serve readiness semantics do not move in any branch: the ready
   frame is still emitted after the same phases (`boot_phases.py`).

**Not a fix candidate before the measurement:** moving imports lazy on a disk-cold number — the
page-cache cost moves with the import, it does not shrink.
