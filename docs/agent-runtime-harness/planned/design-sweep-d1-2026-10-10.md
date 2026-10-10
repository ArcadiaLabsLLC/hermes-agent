# Design sweep D1 — admission memo, prewarm and import cost, cancel / params / spawn ownership, preload and slot caches (2026-10-10)

**Status:** planned — owner-ruled 2026-10-10 (see Owner rulings at the end); build lanes pending.

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

**Built (lane build-1011-B1, 2026-10-10).** S1 BUILT `5260a6b87fb`, S2 BUILT `7069d9adeb9`,
S3 BUILT `f925cebe8d`. Where the code differed from this plan: the resident logic is its own
module (`mcp_admission/resident.py`, stores); the memo key is `(hermes_home_key(), server)`
because MCP tools may live in a profile overlay; `teardown_mcp_admission` stays as the removal
verb beside the new `release_mcp_admission`, so there was no rename MOVE; the filter-revision
check landed in S1 (a narrower admission must never inherit, even between commits); a slot-less
dispatch is refused with `mcp_admission_budget_exhausted`; the actor-eviction hook was NOT built
— `ResidentPersonaChatRuntime` holds no admission and the ruling ties the scope's lifetime to
the transport session plus content; `mcp_admission_reused` is documented in `07-observability.md`
(where the record vocabulary lives), not `02`. Measured (60-tool warm server, 40 admitting
runs): admit 5.55 → 0.92 ms median, end-of-run 2.30 → 0.56 ms, generation +121 → 0 per run,
tool-defs memo 0/40 → 39/40 hits.

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
actor's turn. D1.01 S3 is this row's gate (BUILT `f925cebe8d`:
`tests/agent_runtime/test_tool_defs_memo_survives_admission.py`). The upstream-PR alternative (key the memo on
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

**Built (lane build-1011-B1, 2026-10-10).** S1 BUILT `0df2a3a79c`, S2 BUILT `d75fbb323f`, S3
BUILT in the commit that carries this line. Where the code differed: the handler also dispatches
with the bound link's entry for the name (`_call_bound`), so a same-named entry runs with THIS
turn's method and confirmation; S3's receipt is proven on the component's source
(`chat_lane_bundle.registry_content_revision` per alternating turn), not through a serve
harness. Measured (two Launchers, 40 alternating turns): generation moves 40 → 0, tool-defs
memo misses 40 → 0, `get_tool_definitions` median 11.81 → 0.09 ms.

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

## Cluster C — ownership: who may cancel, who reads params, who stamps a child (D1.07, D1.08, D1.09)

### D1.07 = L1.06 — a dispatch supervised by another process cannot be cancelled from this one

**Verdict: PLAN** (the cross-install half); the same-machine second-serve half is one owner
question away from a stage.

**What the code does today.** `tools/agent_chat_dispatch/local.py::request_cancel` answers
`not_owned_here` when `dispatch_id` is not in `dispatch_store.supervision.supervised_dispatch_ids()`
(the process-local set of dispatches a live supervisor thread in THIS process answers for);
`running_work/surface.py::_cancel_dispatch` routes `cancel_work("dispatch:…")` to it and
passes the typed refusal through. A cross-install dispatch is sent as
`peer.agent_chat.execute` (`remote.py::build_peer_execute_params`): the far install B runs it
as a turn whose `turn_request_id` is derived from the dispatch id (R8's idempotent replay);
the sender's row carries `remote_install_id`. There is no peer verb that names a turn to stop:
`serve_rpc/peer.py` declares `ping`, `agent_chat.execute`, `media.get`, `announce`,
`roster.list`, `thread.read` (and `call_authorization` lists the same six). So a Stop on a
relay that crossed an install boundary has nowhere to go.

**Decision.** Cancel is owned by the process that supervises the work; a non-owner never kills
by pid. Across installs, the sender asks the owner with a peer verb carrying the dispatch id,
authenticated exactly as the execute was (same peer session, same tier); the owner resolves the
derived `turn_request_id` and interrupts its live turn through the existing turn-interrupt
seam (`cancel_work`'s turn kinds / the chat Stop door), settling the sender's row from the
answer.

**Files and symbols (fork-owned).**
- `agent_runtime/chat_turn.py`: `PEER_CHAT_CANCEL_METHOD = "peer.agent_chat.cancel"` beside
  `PEER_CHAT_EXECUTE_METHOD`.
- `agent_runtime/serve_rpc/peer.py`: `@method("peer.agent_chat.cancel", tier=TIER_CONSOLE)`:
  params `{dispatch_id, reason}`; derives the turn request id the same way execute did;
  answers one of `stopping` (live turn found and interrupted), `already_finished`
  (settled; state echoed), `not_running` (no such turn here). `call_authorization`'s peer list
  gains the name.
- `tools/agent_chat_dispatch/remote.py`: `request_remote_cancel(row, reason)` — one dial with
  `PEER_DIAL_TIMEOUT_SECONDS`, no retry loop (a cancel that cannot reach the peer is reported
  `peer_unreachable`, the row's existing reason vocabulary); on `stopping` the sender's row is
  marked `cancel_requested` and the normal remote settle path records the terminal state the
  peer later reports.
- `tools/agent_chat_dispatch/local.py::request_cancel`: before answering `not_owned_here`, a row
  with `remote_install_id != ""` routes to `request_remote_cancel`; a local row another process
  owns keeps `not_owned_here` (see the owner question).
- `running_work/surface.py::_cancel_dispatch`: passes the new outcomes through typed, no
  pretend success.

**Stages.**
1. **S1 the verb.** Tests (`tests/agent_runtime/test_peer_agent_chat_cancel.py`, fake peer
   session as the execute tests use): cancel of a live derived turn → `stopping` and the turn's
   interrupt seam called once with the derived request id; cancel of a settled one →
   `already_finished`; unknown → `not_running`; a caller below `TIER_CONSOLE` is refused by the
   tier gate. Killing mutation: derive the request id from `dispatch_id` with a different salt
   → `not_running` for a live turn (red named).
2. **S2 the sender's leg.** Tests: `request_cancel` on a row with `remote_install_id` dials
   exactly once and returns the peer's outcome; peer down → `peer_unreachable`, row untouched;
   `cancel_work("dispatch:…")` surfaces the outcome. Killing mutation: keep the
   `not_owned_here` short-circuit ahead of the remote check → the remote test gets
   `not_owned_here`.
3. **S3 docs:** `03-transport-and-wire.md` peer verb table; `05-chat-turn-lane.md` cancel
   semantics ("a cancel is a request to the supervisor; `not_owned_here` names the case a
   local non-supervisor cannot route").

**Size.** ~160 lines code, ~160 lines tests, one lane (Opus).

**Owner questions.** (1) Same-machine, second serve: the row holds `owner_pid` /
`owner_started_at` (the child's identity) but not the supervising serve's. Either stamp
`supervisor_pid` on the row at `_mark_supervised` and have the non-owner answer
`not_owned_here` with `supervised_by` so the console re-aims at that serve's socket, or write a
durable `cancel_requested` column the supervisor polls (today the mark is checked before spawn
and after exit only; a mid-run poll is new). Which? (2) Is a peer-initiated cancel allowed to
interrupt a turn that already produced partial output on B (Stop semantics), or only to refuse
a turn not yet started? The verb above assumes Stop semantics, matching the local
`request_cancel`'s `stopping`.

### D1.08 = L1.08 — params / JSON-doc readers recur per module, renamed apart to pass W0-G3

**Verdict: PLAN.** The family is three families, and one of them already has its owner.

**What the code holds** (`d04f2766ca` renamed them apart; the gate
`tests/agent_runtime/test_duplicate_helper_bodies.py` is why):

| family | members | refusal each raises |
|---|---|---|
| RPC params reader | `serve_rpc/realm.py::_param_text/_param_flag/_param_strings`; `chat_turn.py::_text/_flag/_strings`; `serve_rpc/console_operations.py::_console_text` | `_Refused("invalid_request", msg)`; `ChatTurnInvalid(f"{key}_invalid", msg)`; `ValueError(key)` |
| versioned JSON document reader (default shape on fault) | `workspace_slot_env.py::_read`; `workspace_slot_runs.py::_read_runs` | none — returns `{"schema_version": …, <collection>: {}}` on `OSError`/`ValueError`/shape mismatch |
| CLI verb runner (refusal → `emit_harness_error`) | `persona/slots_commands.py::_run_slot_verb`; `workspace_slots_commands.py::_run_workspace_slot_verb` | catches `SlotAssignmentRefused` / `(SlotRefused, SlotEnvRefused)` |

`bundle_profiles/manifest.py::_strings` is NOT a member: it is a validating manifest parser
that raises `ProfileManifestError`; a defaulting reader is the wrong shape for it. The owner
that already exists: `agent_runtime/serve_rpc/params.py` — `_text_param` plus `ParamRefused`
(one exception, `frame(rid, **data)` → `-32602` with `RpcRefusal`), today used by the office /
level / map verbs.

**Decision — the refusal-type injection shape.** A reader takes `refuse: Callable[[str, str], BaseException]`
— `(key, sentence) → exception` — and raises what it is handed. Each lane supplies its own
constructor once, at module top: realm `lambda key, msg: _Refused("invalid_request", msg)`;
chat_turn `lambda key, msg: ChatTurnInvalid(f"{key}_invalid", msg)`; console
`lambda key, msg: ValueError(key)`; the office verbs `lambda key, msg: ParamRefused(msg, RpcRefusal.…)`.
Two arguments, no kwargs, no base class the lanes must share: each lane's error envelope is
untouched, which is what the lane result asked for.

**Files and symbols (fork-owned).**
- `agent_runtime/serve_rpc/params.py`: `read_text(params, key, *, refuse, required=False, limit=None)`,
  `read_flag(params, key, *, refuse, default=False)`, `read_strings(params, key, *, refuse)`;
  `_text_param` keeps its lenient `None`-on-malformed contract (its callers rely on it).
- `agent_runtime/json_document.py` (new, `__layer__ = "models"`):
  `read_versioned_document(path, *, schema_version, collection) -> dict` — the default shape
  on `OSError`, `ValueError`, non-dict payload or non-dict collection; used by
  `workspace_slot_env._read` and `workspace_slot_runs._read_runs` (the two become one-line
  calls or are deleted in favour of direct calls).
- `hermes_cli/harness_parts/verb_runner.py` (new): `run_refusing_verb(args, kind, action, *, refusals: tuple[type[BaseException], ...], code="invalid_payload")`
  — the shared body of the two `_run_*_verb`s; the message format `f"{exc.reason}: {exc.detail}"`
  is the contract both already share.

**Stages** (one lane, three CHANGE-sized steps; one MOVE commit if the helpers are relocated
rather than deleted).
1. **S1 params readers.** The three lanes delete their local readers and call the shared ones
   with their constructor. Tests: each lane's existing refusal tests stay green (the envelope
   is unchanged by construction); `tests/agent_runtime/test_duplicate_helper_bodies.py` loses
   its three STALE/NEW rows. Killing mutation: re-add `_param_text` to `realm.py` → the
   duplicate-bodies gate goes red (its red is the recorded one).
2. **S2 JSON document reader.** Tests: the two stores return the default shape on a missing
   file, a corrupt file, a dict without the collection; a valid file round-trips. Killing
   mutation: drop the collection-shape check → the "collection is a list" case returns the
   malformed payload.
3. **S3 verb runner.** Tests: a refusal of each listed type emits `invalid_payload` with the
   reason/detail sentence; an unlisted exception propagates. Killing mutation: catch
   `Exception` → the propagation test fails.

**Size.** ~90 lines new, ~110 lines deleted, ~120 lines tests.

**Owner question:** none. Decision rule for a fourth family member found during the lane: add
it if its refusal fits `(key, sentence)`; otherwise file it, do not widen the shape.

### D1.09 = L2.20 — hermes children are invisible to the Launcher's process index

**Verdict: PLAN**, with one correction to the row: the serve's gateway is not a child
process. `serve/gateway_listener.py::start_gateway_listener` is a listener thread inside the
serve (`boot_phases.py`), so "the upstream-spawned gateway (seam)" names nothing that can
outlive the serve. The children that can:

| spawn site | owner | can outlive the parent | stamp |
|---|---|---|---|
| `tools/agent_chat_dispatch/local.py::_spawn_child` (detached dispatch turn) | fork | yes — by design (`child.py` detached contract) | at spawn / at settle |
| `agent_runtime/provider_signin_child.py` (`subprocess.Popen` in the sign-in child owner) | fork | yes, on a hard serve exit | at spawn / on close |
| the `tui_gateway` worker handed to `conversations/native_peer.NativePeer(process=…)` | fork (the spawner that constructs it) | yes, on a hard serve exit | at construction / on close |
| `hermes_cli/bundled_app.py` child | fork (bundled runner) | yes | at spawn / on exit |
| stdio MCP hosts, `tools/mcp_tool.py` `subprocess.Popen` inside the SDK's stdio client | upstream | yes — the known orphan class (the Launcher already has `orphan_mcp_reap_policy.dart` by ancestry) | after admission, from `mcp_admission/transport.py`, IF the pid is reachable (see owner question) |

Everything else in the fork is `subprocess.run` (bounded, waited) and needs no entry.

**The Launcher's contract** (`EterniaLauncher/lib/core/services/hermes/runtime/hygiene/mission_process_index.dart`,
`mission_process_index_io.dart`): directory `%LOCALAPPDATA%\EterniaLauncher\process_index`
(else `~/.eternia_launcher/process_index`); one `<pid>.json` per process:
`{pid, started_at_ticks?, store_root, purpose, recorded_by_pid?}`; `purpose` wire values
`serve_runtime | serve_starter | qa_launcher | qa_mcp_server | hermes_child | unknown`; the
reader spares a pid it names by identity (pid + `started_at_ticks` compared with the host
record's observed start). The unit of `started_at_ticks` is the launcher's
`host_process_record.dart` — the first stage reads it and pins it in the fixture (cross-repo
contract fact; name it in the commit body).

**Decision.** One fork chokepoint owns the entry: `agent_runtime/process_index.py` —
`record_child(pid, *, purpose, started_at_ticks) -> Entry | None` (writes `<pid>.json`
atomically — temp file + replace — never raises; `None` when no directory resolves),
`forget_child(pid)` (unlink, never raises), `index_directory()` (the launcher's resolution
rule, env `LOCALAPPDATA` then home). `store_root` from `agent_runtime.paths.store_root()`,
`recorded_by_pid=os.getpid()`. The four fork spawn sites call it in pairs; the serve itself is
NOT written here (the Launcher's `serve_register_source` already knows the serve by its own
register). Upstream's MCP host: no edit to `tools/mcp_tool.py`; the stamp is post-hoc from
`mcp_admission/transport.py` after a cold spawn, reading the pid off the SDK session's
transport if that reach is public, else not at all.

**Stages.**
1. **S1 the chokepoint + two sites.** `process_index.py` with `_spawn_child` and
   `provider_signin_child` wired. Tests (`tests/agent_runtime/test_process_index.py`, tmp
   `LOCALAPPDATA`): a spawn writes `<pid>.json` with the five keys and `purpose="hermes_child"`;
   settle / close unlinks it; an unresolvable directory writes nothing and raises nothing; the
   JSON matches a fixture copied from the Launcher's test fixture
   (`EterniaLauncher/test/fixtures/…`, pinned both sides). Killing mutation: write
   `started_at_ticks` in the wrong unit → the fixture compare goes red.
2. **S2 the remaining fork sites.** `native_peer` worker spawner and `bundled_app`. Same test
   shape per site.
3. **S3 the MCP host.** Measure first: can the fork read the stdio transport's process from
   `tools/mcp_tool._servers[name]` through `_upstream_doors` without a private reach? If yes,
   stamp after `_default_registrar`'s cold path and forget at `shutdown_mcp_servers`
   (a fork callback registered on the serve's shutdown path, not an upstream edit). If not, the
   MCP host stays with the Launcher's ancestry policy and this stage is a DROP with the reason
   recorded.

**Size.** ~140 lines code, ~160 lines tests, one lane (Opus); the launcher half (reading
`hermes_child` entries in the sweep) is already in place per the row.

**Owner question (blocks S3 only):** is a reach into the MCP SDK's stdio transport process
handle acceptable as a seam row (`upstream-footprint-ledger.md` § Door map), or does the MCP
host stay under the Launcher's `orphan_mcp_reap_policy` by ancestry?

## Cluster D — per-turn caches on upstream-shaped work (D1.10, D1.11, D1.12)

### D1.10 = L2.04 — send-prep H2: skill preload 73 ms median on the skill-heavy persona

**Verdict: PLAN**, measurement stage first; the memo's inputs are named below, which is what
the M1.03 lane asked for.

**What the code does.** `agent_runtime/mission_chat_turn_context.py::_resolve_skill_preload`
→ `resolvers.build_preloaded_skills_prompt` (default: upstream
`agent/skill_commands.py::build_preloaded_skills_prompt`) → `_load_skill_blocks` →
per skill `_load_skill_payload` → upstream `tools/skills_tool.py::skill_view(name, preprocess=False)`.
Per skill, `skill_view`: locates the skill (`_skill_search_dirs`, `_locate_skill` — inside the
fork's `skill_root_registry_scope`, so the walk is the turn's), reads the file, parses
frontmatter (parse 1), platform gate, disabled check (`_is_skill_disabled`, and on a
by-name hit the catalog `_skill_catalog(...)`), `_skill_linked_files(skill_dir)` (a directory
listing), `_skill_readiness(frontmatter, name)` (env vars / credentials), `pm.ensure(dep)` per
`deps:` entry (activation side effect), `_mark_background_review_read(skill_md)` (side
effect), `_log_security_warnings` (log). Then `_load_skill_blocks`: `_inject_skill_config`
re-parses the frontmatter from the content (parse 2) and resolves `metadata.hermes.config`
values from config.yaml; `bump_use(name, task_id)` writes usage (durable side effect). H6
(package stamps / preload checks) measured 2–5 ms and is below the bar — DROP that half.

**The inputs of the rendered block, and the signature that covers each:**

| input | covered by |
|---|---|
| ordered skill ids, `required_skill_names`, `excluded_loaded_names` | the key tuple itself |
| SKILL.md bytes and the linked-files listing | `skill_resolution.skill_package_content_hash(skill_dir, skill_md)` (exists; hashes the package) |
| disabled set, `metadata.hermes.config` values | config.yaml `(mtime_ns, size)` — `chat_lane_bundle._path_revision` shape |
| readiness: env vars the frontmatter names, credentials | presence signature of the named env vars + the auth-store file stamps `_skill_readiness` reads (S0 names the files) |
| platform / apps / environment gates | process constants plus `HERMES_KANBAN_TASK` |
| `task_id` | NOT an input of the text (`preprocess=False`); it is `bump_use`'s target |

Side effects a hit must still perform: `tools.skill_usage.bump_use(name, task_id)` (public),
`pm.ensure(dep)` for each `deps:` entry (public, idempotent), `_mark_background_review_read`
(private upstream name — a door or a seam row; decision rule: if no door, the hit skips it and
the review-read mark lands on the next miss, which is a bounded staleness of one memo
lifetime, recorded in the module docstring).

**Files and symbols (fork-owned).** `agent_runtime/skill_preload_memo.py` (new):
`memoised_preload(names, *, task_id, required_skill_names, root_registries, build)` wrapping
the default resolver; an 8-entry FIFO keyed on the tuple above; on a hit runs the side effects
and returns the cached `(prompt, loaded, missing)`; `mission_chat_turn_context._default_build_preloaded_skills_prompt`
routes through it; `timings["context_skill_preload_memo"] = 1|0` beside
`context_skill_preload_ms`.

**Stages.**
0. **S0 split (fixture, Dev persona's grant list copied into a scratch home; n=25 A/B/A/B).**
   Wrap `skill_view`, `_inject_skill_config`, `bump_use`, `_skill_readiness`,
   `_skill_linked_files` with timing shims (test-only monkeypatch) and record the per-skill
   split. Decision rule: memo-coverable share (everything but the side effects) ≥ 70 % of the
   span → S1; else the upstream PR alone (S2) and this row closes on it.
1. **S1 the memo.** Tests (`tests/agent_runtime/test_skill_preload_memo.py`): two turns, same
   inputs → one `skill_view` call per skill in total, `bump_use` called on both turns, the
   prompt byte-identical; edit a SKILL.md → miss; change config.yaml → miss; unset a named env
   var → miss; a different `task_id` → hit (text unchanged) with `bump_use` on the new id.
   Killing mutations: drop the package hash from the key → the edited-SKILL.md test serves the
   stale text (red named); drop the side-effect replay → `bump_use` count 1 across two turns.
2. **S2 upstream door (held PR row).** `skill_view`'s result gains `"frontmatter"` so
   `_inject_skill_config` stops re-parsing; additive on upstream's side. Filed in
   `upstream-footprint-ledger.md` as a held PR row; carried only if accepted.

**Size.** S0 one day of measurement; S1 ~130 lines code, ~150 lines tests; one lane (Opus).

**Owner question (blocks S1):** the value is ~70 ms per turn on the skill-heavy persona only
(Neko 3 ms). A six-input memo is a correctness surface; is it worth taking ahead of the
upstream door, or does this row wait on S2?

### D1.11 = L1.05 — send-prep H7: request build 47–50 ms per warm turn, ~17–19 ms unattributed

**Verdict: INVESTIGATION** — the upstream function is unsplit by receipts and the two shares
have different owners; the fork-side candidate depends on which part is heavy. Blocked behind
M1.02's owner call for the web-search half (22–25 ms of the ~41).

**What the code does.** `agent/transports/codex.py::ResponsesApiTransport.build_kwargs`
(upstream): `convert_tools(tools)` (`codex_responses_adapter._responses_tools`),
`_alias_wire_tools` (→ `_openai_prefers_native_web_search` → `web_search_registry.get_active_search_provider`:
the M1.02 share), `convert_messages` (history → Responses input items; scales with history),
`_content_cache_key(instructions, response_tools, scope)` (`json.dumps` of the name-sorted
tools + SHA-256), `_resolve_reasoning`, `_default_prompt_cache_retention_for_request`. The
fork's `persona_turn_binding.capture_final_request_tools` reads the result; it adds nothing to
the span (other parts 0 in the attribution pass).

**Protocol** (the codex-warm-prep fixture from
[`warm-send-prep-measurements-2026-10-08.md`](warm-send-prep-measurements-2026-10-08.md),
44 tools, histories of 0 / 20 / 80 rows; n=25 A/B/A/B per history size): test-only timing
shims on the six callees above; report medians per part per history size. Decision rules:
(a) `convert_tools` + `_content_cache_key` ≥ 8 ms together → the fork candidate is one memo of
`(response_tools, cache_key_tools_part)` keyed on the tool list's identity and the final-tools
revision the fork already computes — reachable only through an additive hunk in
`build_kwargs` (a seam row with its ledger entry) or an upstream PR adding a
`tools_prepared=` parameter; file whichever the owner prefers, never a transport subclass
(the fork owns none: `ResponsesApiTransport` is referenced by `agent_runtime/cache_routing.py`
only); (b) `convert_messages` dominates and scales with rows → upstream-owned, caller-side
nothing; file a marker row naming the per-row cost; (c) the web-search share → M1.02's row
exactly as it stands. The final wire-tool receipt is kept in every branch.

### D1.12 = L3.17 — repo-slot context sections are not deduplicated against the prompt builder's cwd chain

**Verdict: PLAN** — no upstream door needed; the M1.06 objections are met by deduplicating on
CONTENT against the chain upstream will actually inject for the RESOLVED workdir, computed
with upstream's public finder.

**What the code does.** `agent_runtime/persona_slots.py::load_slot_context` reads each
assigned slot's `context.files` (default `CLAUDE.md` and `AGENTS.md`) into
`SlotContextSection(slot, file, content)`; `mission_chat_turn_context` joins them into
`workspace_agents_content`, which reaches `persona_runtime.mission_chat_reply` as one string.
When the persona sets `include_core_context_files`, upstream
`agent/prompt_builder.py::build_context_files_prompt(cwd=workdir)` also loads
`_load_agents_md` (the `AGENTS.override.md` / `AGENTS.md` / `agents.md` chain from the git
root to cwd, first non-empty per directory, `seen_content` local to that walk) and
`_load_claude_md` (cwd only). The workdir is `mission_chat_workdir_for_persona(persona,
workspace_agents_path, primary_slot_path)` — rung 1 (persona-config workdir) can outrank the
primary slot, so "the slot's file" and "the chain's file" are not the same thing, and plan
`build-running-work-2026-10-04.md` §3.3's claim that the chain's `seen_content` deduplicates the
slot section is false (confirmed: `seen_content` is a local in `_load_agents_md`).

**Decision.** Dedup where both facts are in hand, by content, against what the chain WILL
inject: upstream's public `prompt_builder.discover_context_files(cwd_path)` returns every
`(kind, label, path, content)` the prompt build will load for that cwd, in its priority order.
A slot section whose content equals one of those contents is dropped (it will reach the prompt
through the chain); every other section is kept — an `AGENTS.override.md` that replaced the
slot's `AGENTS.md` in the chain leaves the slot's content unmatched (kept, correct: it is not
otherwise in the prompt); a rung-1 workdir elsewhere leaves nothing matched (kept). Dedup runs
ONLY when `include_core_context_files` is on AND the workdir is grounded (an ungrounded run's
cwd is the process cwd and may hit upstream's install-tree suppression, which the fork must
not second-guess).

**Files and symbols (fork-owned).**
- `agent_runtime/mission_chat_turn_context.py`: the workdir is resolved ONCE here
  (`mission_chat_workdir_for_persona` with the same three inputs) and handed to
  `mission_chat_reply` as `workdir=`; `mission_chat_reply` resolves only when not handed one
  (its other callers). One write path for one fact — today the turn context and the reply
  would otherwise each resolve it.
- `agent_runtime/persona_slots.py`: `dedup_against_chain(sections, *, cwd) -> tuple[kept, dropped]`
  — `discover_context_files(Path(cwd))` contents, compared after the same whitespace strip
  `_read_context_file` applies; pure; never raises (a finder fault keeps every section).
  `SlotContext` keeps `sections` (already present) so the per-(slot, file) decision is made
  on sections, not on the joined string.
- Receipt: `turn_context_receipt.slot_context.dedup = {"against": cwd, "dropped": [[slot, file], …]}`
  beside the existing slot receipts.
- Docs: `build-running-work-2026-10-04.md` §3.3 corrected (the `seen_content` sentence);
  `05-chat-turn-lane.md` slot-context paragraph names the rule.

**Stages.**
1. **S1 the resolver hand-off** (MOVE-sized, behaviour-neutral): the workdir resolved in the
   turn context and passed down. Test: `mission_chat_reply` receives the same `workdir`
   receipt as before for the three ladder cases (config rung, agents-file pointer, primary
   slot). Killing mutation: pass `None` → the reply re-resolves and the receipt still matches
   (so the mutation is caught by a call-count assertion on `mission_chat_workdir_for_persona`
   = 1).
2. **S2 the dedup.** Tests (`tests/agent_runtime/test_slot_context_chain_dedup.py`, tmp git
   repo as the slot): primary slot = cwd, `include_core_context_files` on → the slot's
   `CLAUDE.md` and `AGENTS.md` sections are dropped and the chain carries them (assert the
   built prompt contains each content exactly once); an `AGENTS.override.md` in the slot →
   the slot's `AGENTS.md` section is KEPT (the chain injects the override); rung-1 workdir
   elsewhere → everything kept; `include_core_context_files` off → everything kept, no
   `discover_context_files` call. Killing mutations: compare by path instead of content →
   the override case drops a section the prompt no longer carries (red named); drop the
   grounded guard → the ungrounded case calls the finder.

**Size.** ~120 lines code, ~160 lines tests, one lane (Opus), one MOVE + one CHANGE.

**Owner question:** none blocking. Decision rule for a slot that is not the cwd but is ON the
chain (a parent directory of the workdir inside the same git root): content match drops it,
which is correct — the chain carries that directory's `AGENTS.md`.

## Summary

| row | verdict | value / size |
|---|---|---|
| D1.01 | PLAN (owner question: reverses R2) | 10–11 ms every admitting warm turn; ~220 code / ~180 tests |
| D1.02 | PLAN — designed under D1.01 | 202–215 ms per tool-definitions miss on a reused actor; D1.01 S3 is the gate |
| D1.03 | PLAN | registry stable across two Launchers; ~110 / ~150 |
| D1.04 | INVESTIGATION | re-measure uncontended; the lock split is not a fork move |
| D1.05 | PLAN (CF-1..3 in `cold-first-core-build-cost.md`; owner question: cache dir) | ~12 s of each process's first build; ~300 / ~250 |
| D1.06 | INVESTIGATION | segment protocol; precompile vs lazy decided by the data |
| D1.07 | PLAN (two owner questions) | Stop works across an install boundary; ~160 / ~160 |
| D1.08 | PLAN | three helper families → three owners; ~90 new / ~110 deleted |
| D1.09 | PLAN (gateway half of the row corrected; owner question on the MCP host) | launcher sweep spares hermes children by identity; ~140 / ~160 |
| D1.10 | PLAN, S0 first (owner question: memo vs door) | ~70 ms on the skill-heavy persona; ~130 / ~150 |
| D1.11 | INVESTIGATION (behind M1.02) | the unattributed 17–19 ms named before any fix |
| D1.12 | PLAN | duplicate CLAUDE.md/AGENTS.md out of the prompt; ~120 / ~160 |

Structural findings for the queues (one line each; the parent files them):

- **`mission_chat_workdir_for_persona` is resolved in `persona_runtime.mission_chat_reply` while its three inputs are first in hand in `mission_chat_turn_context`; D1.12 S1 moves the resolve up and hands it down (one write path per state)** · fork-owned / chat turn · evidence: this doc § D1.12 · lane: D1.12 → `runtime-queue.md` § Fork-owned.
- **The L2.20 row's "upstream-spawned gateway" names no process: `serve/gateway_listener.start_gateway_listener` is a thread in the serve; the row's spawn-site list is the table in § D1.09** · fork-owned / serve · evidence: this doc § D1.09 · lane: the parent amends the row → `runtime-queue.md` § Fork-owned.
- **Plan `build-running-work-2026-10-04.md` §3.3 states that `prompt_builder._load_agents_md`'s `seen_content` deduplicates the slot section; it is a local of that walk and does not** · fork hygiene / docs · evidence: this doc § D1.12, `agent/prompt_builder.py::_load_agents_md` · lane: D1.12 S2 corrects it → `fork-hygiene-queue.md`.

## Owner rulings — 2026-10-10

The owner took every recommendation ("go with recommendation").

- D1.01: confirmed — the MCP admission scope lives for the transport session plus the admission content; isolation stays `scope_toolsets_to_admission`. This supersedes R2's per-run teardown ruling.
- D1.05 CF-2: the derived frontmatter cache lives in the store root beside `core_cache`, excluded from realm sync.
- D1.07: (a) a durable `cancel_requested` column the supervisor polls, not `supervisor_pid` re-aim; (b) yes, a peer cancel may stop a turn with partial output on B, and the partial output is kept.
- D1.09 S3: no seam into the MCP SDK stdio transport; MCP hosts stay with the Launcher's `orphan_mcp_reap_policy`.
- D1.10: wait on the upstream frontmatter-in-result door (S2); no six-input preload memo.
