# Layout sheet — `agent_runtime/mcp_admission.py` (lane R3)

Base: `main` @ `28012c8f8a` · sha256 `e1037484dc09d04cf2e29372f6f2140bc771c185e3a6fc1cefd64a528e577b68` · 2,073 raw / 1,452 code / 37 top-level defs · longest `admit_mcp_servers` 198 (1199–1396) · chains 0/0 · `str==` 0 · `isinstance` 5 · owner doc `docs/agent-runtime-harness/archive/2026-08-22-pre-consolidation/mission-chat-mcp-admission.md` (the design the docstring says to read first) and ADR `Harness_Brain/30 — Decisions/0009` (profile declaration is the sole admission authority). 8 production importers taking 11 names (`persona_runtime` ×6, `tool_visibility` ×4, `chat_lane_bundle`, `persona_chat_actor_prewarm`, `profile_runner/{mcp_lane,runner,toolsets}`, `persona/inspect_commands`); 10 test files pinning 33 names, three private (`_default_registrar`, `_live_mcp_sessions`, and `_current_mcp_servers` by module attribute).

**Package named after the file — `agent_runtime/mcp_admission/`.** The docstring's seven invariants are the map: resolution is pure (invariants 2–3), registration is single-flight and bounded (4, 6), the registry scope belongs to the run and the transport to the process (5), the agent is told (7). The one place the file "reaches for an upstream private" is, by its own count, eight places — every one goes behind the door (§4).

## 1. Skeleton (owner ruling 2026-09-25: readability first; modules target 100–300, hard cap 500; no flow over three modules)

```
agent_runtime/mcp_admission/
  __init__.py       wiring   the docstring (the seven invariants, R2's registrar argument) + the map; re-exports the 11 importer names and the 33 test names
  vocabulary.py     models   the VOCABULARY module: the eight MCP_* denial codes, LANE_MISSION_CHAT, _MCP_TOOLSET_PREFIX, TRANSPORT_WARM/COLD, _PARKED_WAKE_TIMEOUT_SECONDS, READ_ONLY_ALLOWLIST_PROFILE (§5), READ_ONLY_INCLUDED/EXCLUDED_TOOLS, MCP_OPERATING_SKILLS, the two defaults, MCP_DENIAL_CODES (CHANGE)  (~110)
  outcomes.py       models   the typed outcomes and the one line that renders them: McpAdmissionDenial, McpAdmission, McpAdmissionOutcome, McpTeardownOutcome, McpCallBudget; render_mcp_admission_line, _admitted_clause  (~290)   entry: render_mcp_admission_line
  resolve.py        policy   resolution, pure (zero spawns): admission_config, admission_enabled, resolve_mcp_admission (Resolution phases after the CHANGE), _requested_servers, _configured_servers_for, _apply_permission_mode, _name_list, _prefixed_tool_names, _bounded_connect_timeout, scope_toolsets_to_admission, _mcp_toolset_aliases, _is_mcp_toolset, admitted_operating_skill_ids, admission_requirement_failures  (~320)   entry: resolve_mcp_admission, admission_enabled, scope_toolsets_to_admission, admitted_operating_skill_ids, admission_requirement_failures
  registration.py   lanes    the registry scope's two ends: admit_mcp_servers (Admission phases after the CHANGE), _install_call_budget, _meter_registered_tool, _metered_handler; teardown_mcp_admission, _deregister_toolset_scopes  (~360)   entry: admit_mcp_servers, teardown_mcp_admission
  transport.py      stores   the process's warm transports, behind the door: _default_registrar, classify_admission_transport, mcp_sdk_available, _current_mcp_servers, _live_mcp_sessions, _is_parked, _wake_parked_servers, _reregister_warm_server  (~200)   entry: classify_admission_transport, mcp_sdk_available
```

Per entry point, the modules an agent opens (the entry's module plus the modules of what it calls directly; `vocabulary` is read like a table and not counted; `machine_roots`, `profile_readiness`, `personas`, `tool_permissions`, `mcp_lane`, `runtime_config` and the upstream `tools.*` are below the package):

| entry point | opens | count |
|---|---|---|
| `admit_mcp_servers` (the runner) | `registration` → `transport` → `outcomes` | 3 |
| `teardown_mcp_admission` (the runner) | `registration` → `transport` → `outcomes` | 3 |
| `resolve_mcp_admission` (persona runtime, tool visibility, inspect, prewarm) | `resolve` → `outcomes` | 2 |
| `render_mcp_admission_line` (persona runtime, mcp_lane) | `outcomes` | 1 |
| `scope_toolsets_to_admission` / `admitted_operating_skill_ids` / `admission_requirement_failures` | `resolve` → `outcomes` | 2 |

Floor rule (ruling 3): `teardown.py` (~96) and `render.py` (~90) were sub-100 in the first draw; teardown is the other end of the scope `admit_mcp_servers` opens (invariant 5), so both live in `registration`; the render line reads only the outcome objects, so it lives beside them. `registration` and `resolve` are above 300 and under the cap; neither splits without putting `admit`'s flow over three modules.

### 1.1 Section map → target modules

| lines | what is there | → module | layer (from imports) |
|---|---|---|---|
| 1–124 | the docstring 1–105, imports (`.mcp_lane.MCP_NOT_REGISTERED_ON_LANE`), `logger` | `mcp_admission/__init__.py` | wiring |
| 126–373 | `MCP_ADMISSION_DISABLED` 126 … `MCP_SDK_UNAVAILABLE` 172, `LANE_MISSION_CHAT` 178, `_MCP_TOOLSET_PREFIX` 181, `TRANSPORT_WARM/COLD` 223, `_PARKED_WAKE_TIMEOUT_SECONDS` 241, `READ_ONLY_ALLOWLIST_PROFILE` 246, `READ_ONLY_INCLUDED_TOOLS` 266, `READ_ONLY_EXCLUDED_TOOLS` 303, `MCP_OPERATING_SKILLS` 353, `_DEFAULT_CONNECT_TIMEOUT_SECONDS` 357, `_DEFAULT_MAX_TOOL_CALLS_PER_RUN` 367, `_ADMISSION_LOCK` 373 (→ `registration`, it is the mutex's state) | `mcp_admission/vocabulary.py` | models |
| 380–646, 1961–2073 | `McpAdmissionDenial` 380, `McpAdmission` 403, `McpAdmissionOutcome` 468, `McpTeardownOutcome` 505, `McpCallBudget` 528; `_ADMISSION_LINE_PREFIX` 1961, `render_mcp_admission_line` 1964, `_admitted_clause` 2048 | `mcp_admission/outcomes.py` — imports `vocabulary` | models |
| 652–1193 | `admission_config` 652 (lazy `runtime_config`, `.config`), `admission_enabled` 674, `resolve_mcp_admission` 683 (+ `_empty`; lazy `personas`, `machine_roots`), `_requested_servers` 842 (lazy `profile_readiness` ×2 — one private), `_configured_servers_for` 871 (lazy `parse_cache`, `profile_context`, `profile_readiness._configured_mcp_servers`), `_apply_permission_mode` 889 (lazy `tool_permissions`), `_name_list` 950, `_prefixed_tool_names` 960 (lazy `tools.mcp_tool_schema`), `_bounded_connect_timeout` 981, `_positive_float` 996, `_positive_int` 1004, `scope_toolsets_to_admission` 1017, `_mcp_toolset_aliases` 1051 (lazy `tools.registry`), `_is_mcp_toolset` 1067, `admitted_operating_skill_ids` 1084, `admission_requirement_failures` 1124 (lazy `mcp_lane`) | `mcp_admission/resolve.py` — imports `vocabulary`, `outcomes`, `serde` (§3) | policy |
| 1199–1569, 1844–1954 | `admit_mcp_servers` 1199 (+ `_work`; lazy `mcp_lane`), `_UNMETERED_HANDLER_ATTR` 1418, `_install_call_budget` 1421 (lazy `tools.registry`), `_meter_registered_tool` 1483, `_metered_handler` 1525 (+ `_metered`); `teardown_mcp_admission` 1844, `_deregister_toolset_scopes` 1913 (lazy `tools.registry`) | `mcp_admission/registration.py` — imports `vocabulary`, `outcomes`, `transport` | lanes |
| 1572–1838 | `_default_registrar` 1572 (lazy `tools.mcp_tool_discovery.register_mcp_servers`), `classify_admission_transport` 1626, `mcp_sdk_available` 1655, `_current_mcp_servers` 1679, `_live_mcp_sessions` 1692, `_is_parked` 1718, `_wake_parked_servers` 1733, `_reregister_warm_server` 1801 — the eight private reaches (§4) | `mcp_admission/transport.py` — imports `vocabulary`, `_upstream_doors` | stores |

Edges point down: `registration` → `transport` → `_upstream_doors`; `registration`/`resolve` → `outcomes` → `vocabulary`. The lazy reaches into `mcp_lane`, `profile_readiness`, `machine_roots`, `personas` stay lazy (they are the module's own callers' siblings; `tool_visibility` imports this package and `mcp_lane`); no cycle.

## 2. Routing sites → tables (the CHANGE commit)

W0-G5 holds no row for this file (`str==` 0 — the one file in this batch with none). Rule 14 has one site, and there are two floor rows:

| site (base line) | shape today | replacement | killing mutation |
|---|---|---|---|
| the eight denial codes 126–172 (`mcp_admission_disabled`, `_lane_busy`, `_timeout`, `mcp_server_not_configured`, `mcp_read_only_subset_unknown`, `mcp_admission_teardown_failed`, `mcp_admission_budget_exhausted`, `mcp_sdk_unavailable`) + `MCP_NOT_REGISTERED_ON_LANE` (imported) | nine constants, each spent by one writer, read by `McpAdmissionDenial.code` and the launcher's issue contract | `vocabulary.MCP_DENIAL_CODES: tuple[str, ...]` and a `__post_init__` guard on `McpAdmissionDenial` refusing a code outside it — the `_guard_turn_outcome_vocabulary` model. Not a `StrEnum`: the tests import the nine constants by name (33 pins), and the batch-1 rule keeps the words plain (none is fork-wide today, and none should become so) | remove `mcp_admission_timeout` from the tuple → `tests/agent_runtime/test_mcp_admission.py::test_a_stalled_registrar_yields_a_typed_timeout_and_the_turn_continues` reds (the denial refuses to construct) |

W0-G7 floor rows (2):

| row | lines / depth | phases (comment map) | after |
|---|---|---|---|
| `admit_mcp_servers` 1199 | 198 / 1 | empty admission → nothing 1232 · the single-flight mutex 1239–1262 · classified HERE, after the mutex, before the registrar 1264–1270 · one meter per admission 1275 · the worker meters INSIDE, still holding the mutex 1283–1297 · the bounded wait, timeout ⇒ typed degrade 1302–1343 · WHY nothing registered, before WHICH server 1350–1354 · the outcome 1357–1396 | `Admission(admission, register).guard → acquire → classify → meter → register_bounded → outcome`, each ≤ 40; the worker closure `_work` (a closure over 5 locals) becomes `Admission._work`; the release-by-the-worker rule (1294–1297) is the one `finally` and `::test_the_single_flight_mutex_is_released_after_a_completed_admission` + `::test_concurrent_admission_is_refused_not_interleaved` pin it |
| `resolve_mcp_admission` 683 | 157 / 2 | config gate 735 · requested set 753 · the machine_roots taxonomy reused verbatim 797 · permission mode 812 · the admission 827 | `Resolution(config, persona).gate → requested → resolve_roots → permission_mode → admission`, ≤ 40 each; `_empty` becomes `Resolution.empty(denials)`; `::test_resolution_performs_zero_spawns` is the invariant-2 pin and stays green by construction because nothing in `resolve.py` imports `transport` |

## 3. Helper folds

| here | duplicate of | verdict |
|---|---|---|
| `_positive_float` 996 | `serde.positive_float` (same contract: `float(value) > 0` else `None`); W0-G3 `body_groups[4]` also names `relay_policy.parse_deadline_epoch` as byte-identical | FOLD onto `serde.positive_float`; the `relay_policy` copy is R2's (its sheet does not exist yet — the row in program §4 is amended to name it) |
| `_positive_int` 1004 (refuses `bool`, `int(value) > 0` else `None`) | `serde.positive_int(value, *, default=None)` and `config._positive_int(value, default)` (W0-G3 `name_groups[15]`; program §4 row "3 copies, R3") | FOLD onto `serde.positive_int` — it already refuses `bool` through `strict_int` (its docstring records lane R3 folding `profile_runner._positive_int` onto it for that reason); same contract |
| `_bounded_connect_timeout` 981 | none | stays in `resolve` |
| `_name_list` 950 (`None`/`str`/sequence → `list[str]`, no dedupe) | `serde.dedupe_tokens` 312 (dedupes, drops unsafe tokens) | NOT a fold — different contract; stays in `resolve` |
| `_effective_required_mcp_servers` / `_configured_mcp_servers` (private imports from `profile_readiness`, a fork module outside the 62) | not a fold; fork privates | the CHANGE renames them public in `profile_readiness.py` (two `def` lines, "tree wins") and imports the public names |

## 4. Upstream doors — the eight privates, all through `agent_runtime/_upstream_doors.py` (rulings Q5, Q7)

| reach (fixture `private_upstream_imports` row) | door (added to `_upstream_doors.py`) | held widening row (`upstream-footprint-ledger.md`) |
|---|---|---|
| `tools.mcp_tool._MCP_AVAILABLE` [25] (1672) | `mcp_sdk_available_flag() -> bool` | publish `mcp_sdk_available()` |
| `tools.mcp_tool._servers`, `._lock` [27], [26] (1681) | `mcp_server_map() -> tuple[Mapping, Lock]` (one door for the pair — they are only ever read together, under the lock) | publish `current_servers()` |
| `tools.mcp_tool_scope._key_name`, `._resolve_server_key` [23], [24] (1682) | `mcp_key_name(key)`, `mcp_resolve_server_key(name)` | publish both |
| `tools.mcp_tool_loop._signal_reconnect`, `._wait_for_server_session_ready` [20], [21] (1751) | `mcp_signal_reconnect(server)`, `mcp_wait_for_session(server, timeout)` | publish both |
| `tools.mcp_tool_registration._register_server_tools` [22] (1817) — "the one place this module reaches for an upstream private", per the docstring, which undercounts by seven | `mcp_register_server_tools(name, server, config)` | publish `register_server_tools` |

Each door imports at CALL time (the doors module's contract), so `test_mcp_admission_r2.py::test_the_upstream_warm_registration_seam_exists` / `::test_a_missing_warm_seam_fails_closed` keep patching the upstream module and keep meaning what they mean. Public reaches, FIRST and kept direct: `tools.registry.registry` 1055/1442/1919, `tools.mcp_tool_schema.mcp_prefixed_tool_name` 974, `tools.mcp_tool_discovery.register_mcp_servers` 1620. Eight fixture rows close in the CHANGE; eight ledger rows open in the same commit.

## 5. Dead code (verdict + the grep the lane runs)

| row | verdict | proof |
|---|---|---|
| `READ_ONLY_ALLOWLIST_PROFILE` 246 (first instalment, TEST SEAM, R3) | TEST SEAM confirmed: 0 production readers, 5 reads in `test_mcp_admission_r2.py` (the launcher-allowlist fixture pins); the archive audit's "only in-code pointer to the launcher allowlist row" is a documentation role a comment in `vocabulary.py` can carry | `git grep -n READ_ONLY_ALLOWLIST_PROFILE -- agent_runtime hermes_cli tools plugins` → 1 (the def). The deletion is NOT this lane's commit: it lands under the queue's "Working a slice" (delete + tombstone + the seam in `tests/_downstream/_seams.py`), so the two-commit contract holds; the MOVE keeps the constant, byte-identical |

Nothing else: `git grep -nw` over the 37 defs finds a caller for each (`_is_parked` 1718 ← 1751; `_reregister_warm_server` 1801 ← `_default_registrar`).

## 6. Positive controls — land in the MOVE (ruling Q6)

No table replaces a routing site (§2's guard constrains constructors). The eight doors replace eight private imports, and each has a test that patches the upstream name today (`test_mcp_admission_parked_wake.py` ×6, `test_mcp_admission_r2.py` ×2 — the § header's private pins); the MOVE runs those eight once after the doors are wired and pastes the green — the positive proof that a door reaches the same seam a patch reaches.

## 7. MOVE hash-proof plan, then the CHANGE

1. **MOVE** `refactor(mcp_admission): mcp_admission.py → agent_runtime/mcp_admission/ (5 modules); eight doors in _upstream_doors` — spans byte-identical with the sha256 table (one row per §1.1 span); the eight lazy private imports inside moved spans are NOT edited in the MOVE (byte-identical) — the doors are ADDED to `_upstream_doors.py` in this commit and the retarget is the CHANGE's; `__init__` carries the docstring and re-exports the 11 + 33 names (the three private test pins by attribute keep resolving through `__init__`). **Killing mutation for the MOVE:** drop `outcomes` from `__init__` → `agent_runtime/persona_runtime.py` fails to import `render_mcp_admission_line` → `tests/agent_runtime/test_mcp_lane_agent_context_line.py` reds at collection. `[ds-size]` −1.
2. **CHANGE** `refactor(mcp_admission): MCP_DENIAL_CODES guard; Admission/Resolution phases; serde folds; the eight reaches through the doors; profile_readiness names public` — §2 + §3 + §4 with each red pasted; eight `private_upstream_imports` rows close, eight ledger rows open.

## 8. Lane and what it must not touch

R3 (exec lane B4), third of its three, disjoint from `running_work` and `stream`. Must not edit in parallel: `profile_runner/` (R3's landed package — consumed by name), `persona_runtime.py`, `tool_visibility.py`, `mcp_lane.py`, `machine_roots.py`, `runtime_config.py`, `chat_lane_bundle.py`, `harness_parts/persona/inspect_commands.py`; `profile_readiness.py` receives exactly the two renames in the CHANGE; `_upstream_doors.py` gains the eight doors and nothing else; `serde.py` gains at most the `bool` refusal in `positive_int`; `tools/mcp_*` is upstream and is never edited — eight ledger rows, not eight widenings.
