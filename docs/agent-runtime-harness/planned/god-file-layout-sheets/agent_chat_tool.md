# Layout sheet — `tools/agent_chat_tool.py` (lane T1)

Base: `main` @ `28012c8f8a` · sha256 `d5fa1710db6b5c27f0e15bc075549dfb6d1ff05fc8f102641e77df69ead8d268` · 1,898 raw / 1,429 code / 24 top-level defs + six `registry.register(...)` statements (1809–1898) · longest `agent_chat_send` 422 (217–638, depth 3) · chains 0/0 · `str==` 5 · owner doc `docs/agent-runtime-harness/04-chat-turn.md` (the agent-chat lane; the 55-line docstring is the thread/clarify/scope contract). 1 production importer — `agent_runtime/peer_directory.py` taking two PRIVATE names (`_resolve_chat_lane_target`, `_session_belongs_to_chat_lane`) — plus upstream's tool discovery, which imports the module BY FILE because it registers tools; 11 test files pinning 14 names, two private (`_async_delivery_available`, `_session_belongs_to_chat_lane`).

**Fork-only file in an upstream directory** (program §0.3, ruling Q2): the new modules go under a new `tools/agent_chat/` package and nowhere else. Two facts of upstream's discovery decide the shape (`tools/registry.py::discover_builtin_tools` 95–135): a module is imported only if its AST holds a `registry.register(...)` call, and a module inside a subdirectory is imported only if that directory has an `__init__.py`. So **`tools/agent_chat_tool.py` stays, as the entry file** — its six `registry.register` calls and nothing else (≤ 90 lines; the exec order's "≤ 60-line entry" is met in spirit: the six calls ARE the file) — importing the handlers from `tools/agent_chat/`, whose modules register nothing and are therefore never imported by discovery on their own. `tools/agent_chat_dispatch.py` (842 code, lane T1's second file) and `tools/agent_chat_remote.py` are siblings this sheet does not move.

## 1. Skeleton (owner ruling 2026-09-25: readability first; modules target 100–300, hard cap 500; no flow over three modules)

```
tools/agent_chat_tool.py          wiring   the ENTRY: the docstring + the six registry.register calls, importing the handlers below  (~90)
tools/agent_chat/
  __init__.py      wiring   the map; nothing registers here
  schemas.py       models   the six AGENT_CHAT_*_SCHEMA tables (a TABLE module) + the two limits  (~230)
  send.py          lanes    agent_chat_send (Send phases after the CHANGE), refusal_json (was _refusal), _looks_like_instance_handle  (~300)   entry: agent_chat_send
  detached.py      lanes    the wait=false half: _async_delivery_available, _persona_of_chat_root, _dispatch_homes, _dispatch_detached, agent_chat_dispatches (DISPATCH_FILTERS after the CHANGE)  (~200)   entry: agent_chat_dispatches
  threads.py       lanes    the local roster and thread reads: scope_off, _canonical_persona_token, agent_chat_threads, session_belongs_to_chat_lane, resolve_chat_lane_target, agent_chat_open, bounded_limit, agent_chat_log_path  (~325)   entry: agent_chat_threads, agent_chat_open, agent_chat_log_path, resolve_chat_lane_target, session_belongs_to_chat_lane
  remote.py        lanes    the far-install reads: _remote_thread_read, _chat_lane_session_ids, _remote_roster_rows, agent_chat_installs, _install_roster  (~260)   entry: agent_chat_installs
```

Per entry point, the modules an agent opens (the entry's module plus the modules of what it calls directly; `schemas` is a table and not counted; `agent_runtime.*`, `tools.agent_chat_dispatch`, `tools.agent_chat_remote` and the CLI handler are below the package):

| entry point | opens | count |
|---|---|---|
| `agent_chat_send` | `send` → `detached` (the `wait=false` branch) | 2 (+ the CLI handler through the Q10 door) |
| `agent_chat_dispatches` | `detached` | 1 |
| `agent_chat_threads` / `agent_chat_open` | `threads` → `remote` (the `@install/` branch) | 2 |
| `agent_chat_installs` | `remote` | 1 |
| `agent_chat_log_path` | `threads` | 1 |
| `resolve_chat_lane_target` / `session_belongs_to_chat_lane` (`peer_directory`) | `threads` | 1 |

Floor rule (ruling 3): `agent_chat_log_path` (116 lines) could stand alone but is one local read like the thread reads beside it, and a `log_path.py` would open nothing the `threads` module does not already; joined. No module is drawn above 325.

### 1.1 Section map → target modules

| lines | what is there | → module | layer |
|---|---|---|---|
| 1–69, 1809–1898 | the shebang + docstring 1–56, imports (`relay_policy`, `dispatch_session_policy.coerce_optional_flag`, `tools.registry.registry`), `logger`; the six `registry.register(...)` 1809–1898 | `tools/agent_chat_tool.py` (kept; the entry) | wiring |
| 74–200, 922–1041 | `_REPLY_LIMIT` 74, `_MESSAGE_LIMIT` 75, `AGENT_CHAT_SEND_SCHEMA` 77, `AGENT_CHAT_DISPATCHES_SCHEMA` 177, `AGENT_CHAT_THREADS_SCHEMA` 922, `AGENT_CHAT_OPEN_SCHEMA` 947, `AGENT_CHAT_INSTALLS_SCHEMA` 985, `AGENT_CHAT_LOG_PATH_SCHEMA` 1007 | `agent_chat/schemas.py` | models |
| 203–638 | `_refusal` 203, `_looks_like_instance_handle` 207, `agent_chat_send` 217 (lazy `gateway_targets` ×4, `config`, **`hermes_cli.harness_parts.persona.chat_turn_message` 579** — §4) | `agent_chat/send.py` — imports `schemas`, `detached`, `relay_policy`, `dispatch_session_policy` | lanes |
| 641–908 | `_async_delivery_available` 641 (lazy `delivery_capability`, `gateway.session_context`), `_persona_of_chat_root` 667 (lazy `dispatch_delivery.sender_persona`), `_dispatch_homes` 686 (lazy `hermes_constants`, `profile_home`), `_dispatch_detached` 718 (lazy `config`, `dispatch_store` ×2, `tools.agent_chat_dispatch`), `agent_chat_dispatches` 852 (lazy `dispatch_store`, `tools.agent_chat_dispatch`) | `agent_chat/detached.py` — imports `schemas` | lanes |
| 1044–1329, 1419–1534 | `_scope_off` 1044, `_canonical_persona_token` 1048, `agent_chat_threads` 1054 (lazy `workspace_scope`, `config`, `persona_assignments` ×6, `persona_chat_history`, `hermes_cli.harness_parts.persona.chat_target`), `_session_belongs_to_chat_lane` 1179, `_resolve_chat_lane_target` 1202 (the same lazies), `agent_chat_open` 1288 (lazy `peer_directory`), `_bounded_limit` 1323, `agent_chat_log_path` 1419 (lazy `chat_live_log` ×2) | `agent_chat/threads.py` — imports `schemas`, `remote` | lanes |
| 1332–1416, 1537–1806 | `_remote_thread_read` 1332 (lazy `gateway_targets`, `tools.agent_chat_remote`), `_chat_lane_session_ids` 1537, `_remote_roster_rows` 1567 (lazy `gateway_peers`, `tools.agent_chat_remote`), `agent_chat_installs` 1677 (lazy `gateway_peers`, `gateway_targets`), `_install_roster` 1756 | `agent_chat/remote.py` — imports `schemas` | lanes |

Edges point down: `agent_chat_tool` → every handler module; `send` → `detached`; `threads` → `remote`. `agent_runtime/peer_directory.py` imports the two thread helpers (public after the MOVE) from `tools.agent_chat.threads` — a runtime module importing a tool package, which is the direction it already takes today (the edge is not new; it is named). `tools/` is not under `LAYERED_ROOTS`, so the `__layer__` constants are for the reader; the gate cannot see them, and the sheet says so.

## 2. Routing sites → tables (the CHANGE commit)

| site (base line) | fixture row | replacement | killing mutation |
|---|---|---|---|
| `agent_chat_dispatches` 886–889: `if wanted == "running": …elif wanted == "done": …` | `\|vocab\|done`, `\|vocab\|running` — two words fork-wide because `states.py` declares them; the FILTER vocabulary of this tool's `state` argument is its own | `detached.DISPATCH_FILTERS: Mapping[str, Callable[[row], bool]]` = `{FILTER_RUNNING: state == STATE_RUNNING, FILTER_DONE: state != STATE_RUNNING}` with `FILTER_RUNNING = "running"`, `FILTER_DONE = "done"` read by name (batch-1 rule; the gate class defect is rowed once); an unknown filter answers every row, as today | swap the two predicates → `tests/agent_runtime/test_agent_chat_dispatch.py::test_state_filter_splits_running_from_done` reds |
| `scope == "off"` 231 and `(... or "open").strip().lower() == "off"` 1045 — the SAME question asked at two sites | not a row | one reader: `threads.scope_off()` (public; 1044's body) called from `agent_chat_send` too, with `SCOPE_OFF = "off"` beside it — rule 15 before rule 12 | make `scope_off` ignore the env → `tests/agent_runtime/test_agent_chat_tool.py::test_scope_off_disables_the_tool` reds |
| `ch in "0123456789abcdef"` 1199 (a hex check inside `_session_belongs_to_chat_lane`) | not a row; the same hex check `gateway_peers._clean_fingerprint` 551 makes | `serde.is_hex(text, length)` — one owner for the two (the gateway_peers sheet folds its copy in its CHANGE if this lands first; "tree wins") | — |

W0-G7 floor row (1):

| row | lines / depth | phases (comment map) | after |
|---|---|---|---|
| `agent_chat_send` 217 | 422 / 3 | scope 231 · the tri-state `new_session` 240 · the two contradictions 254–274 · SYNTAX first for `@install/` targets 276–296 · envelope provenance 298 · detached vs inline, tri-state again 305 · the cross-install = detached-only scope statement 314–368 · the three detached preconditions 370–420 · the detached branch 422–471 · the args namespace 496–535 · the relay 578–592 · the compact reply 597–637 | `Send(request).validate → target → envelope → lane → relay → reply`, ≤ 50 each, in `send.py`; `lane` returns either the detached handle (through `detached.dispatch`) or the inline relay's payload (through the Q10 door); the six tri-state/contradiction refusals become one table of `(predicate, refusal)` walked in the order 231–274 already tests them (`::test_new_session_with_explicit_session_is_a_typed_refusal`, `::test_clarify_token_with_new_session_is_a_typed_refusal`) |

`str==` 5 → 1 at review.

## 3. Helper folds

| here | duplicate of | verdict |
|---|---|---|
| `_refusal` 203 (`json.dumps({"ok": False, "error": …, **extra})`) | program §4 names this file as "a seventh" copy of `refusals.refusal` if T1 runs; W0-G3 `name_groups[21]` | **NOT a fold**: the sync-lane `_refusal` returns a report ROW; this one returns the tool's JSON reply string. Renamed `refusal_json` (public in `send`), which retires this file's share of the name group; program §4's row is amended to six |
| `_bounded_limit` 1323 (`max(1, min(int(v), 100))` with a default) and the inline copy at 881–883 | two spellings of one clamp in one file | ONE `bounded_limit` in `threads`, called from `agent_chat_dispatches` too |
| `_canonical_persona_token` 1048 / `_looks_like_instance_handle` 207 | thin wrappers over `persona_assignments.safe_assignment_token` | stay; they name the question |
| `_dispatch_homes` 686 | `dispatch_store.py:212`, `gateway_targets.py:185`, `process_notifications.py:18` all read `profile_home.get_hermes_background_work_home` for the same "two homes" pair | NOT a fold here (the pair is this tool's env contract for the child, `::test_the_child_environment_states_both_homes_and_pins_the_tree`); named so R1/R2 see the class |

## 4. Upstream doors — and the reach into the CLI

| reach | class | door |
|---|---|---|
| `tools.registry.registry` 67 (module-level), `gateway.session_context.async_delivery_supported` 651, `hermes_constants.get_hermes_home` 712 | FIRST (public) | kept as written |
| **`hermes_cli.harness_parts.persona.chat_turn_message._cmd_mission_chat_message` 579** — a PRIVATE CLI handler, the in-process relay the docstring calls the whole point ("one canonical lane, nothing re-implemented") | the same reach `dispatch_delivery.forge_delivery_turn` makes (1131), one lane over; two callers of one private CLI name from outside the CLI | **owner question Q10** (program §9): default = `agent_runtime/mission_chat_door.py::run_mission_chat_turn(args)`, bound at CLI registration and serve boot; `send.relay` calls the door. Until Q10 lands the MOVE keeps the import where it is, byte-identical |
| `hermes_cli.harness_parts.persona.chat_target` 1080/1225 (the target resolver, a fork module — and its decision functions are PRIVATE: `_mission_chat_target_decision`, `_mission_chat_bare_persona_target`) | a fork reach, not upstream; tools → CLI in direction, into private names — the second instance of the Q10 class, named in that question | named; no change this batch — the resolver is the CLI's authority for "which instance did you mean" and the tool consumes it (`::test_threads_lists_each_placement_distinctly_and_shadows_canonical`) |
| `agent_runtime.dispatch_delivery._sender_persona` 678 (fork private) | — | `sender_persona` (public) after the dispatch_delivery sheet's MOVE; one-line retarget |

W0-G6 `private_upstream_imports` rows for this file: none (both privates are fork names). No widening.

## 5. Dead code (verdict + the grep the lane runs)

No queue row names this file. `git grep -nw` over the 24 defs: every handler is registered (1809–1898), every private has an in-file caller (`_scope_off` 1044 ← the three read tools; `_install_roster` 1756 ← 1741; `_chat_lane_session_ids` 1537 ← 1466). `AGENT_CHAT_*_SCHEMA` ×6 are read by the six registrations and test-pinned. Nothing filed.

## 6. Positive controls — land in the MOVE, before `DISPATCH_FILTERS` (ruling Q6)

`::test_state_filter_splits_running_from_done` reaches both filter arms and `::test_dispatches_lists_only_the_callers_own_work` the no-filter default, so the table lands against a suite that reaches every row. The `agent_chat_send` refusal table's six predicates each have a named test in `test_agent_chat_tool.py` (`::test_refuses_blank_persona_and_message`, `::test_new_session_with_explicit_session_is_a_typed_refusal`, `::test_clarify_token_with_new_session_is_a_typed_refusal`, `::test_scope_off_disables_the_tool`, `::test_an_unknown_install_is_refused_before_any_dial`, `::test_wait_true_to_an_install_qualified_target_stays_refused_remote_requires_detached`) — no new control is owed; the positive proof is the §2 mutations, run and pasted.

## 7. MOVE hash-proof plan, then the CHANGE

1. **MOVE** `refactor(agent_chat): agent_chat_tool.py → tools/agent_chat/ (5 modules); the entry keeps the six registrations` — spans byte-identical with the sha256 table (one row per §1.1 span; the entry file's kept spans are the docstring + imports + the six registrations, hashed too); `tools/agent_chat/__init__.py` re-exports the 14 test names; `agent_runtime/peer_directory.py` retargets its two imports to `tools.agent_chat.threads` (public names `resolve_chat_lane_target`, `session_belongs_to_chat_lane`, with the underscored aliases kept one commit). **Killing mutation for the MOVE:** drop the `remote` import from the entry file → `registry.register(name="agent_chat_installs", …)` raises `NameError` at discovery → `tests/agent_runtime/test_agent_chat_tool.py::test_read_only_companions_are_registered_on_the_agent_chat_toolset` reds. `[ds-size]`: −1 (the entry is ~90 lines).
2. **CHANGE** `refactor(agent_chat): Send phases + the refusal table; DISPATCH_FILTERS; scope_off one reader; bounded_limit; refusal_json; mission_chat_door (Q10)` — §2 + §3 + the door with each red pasted; the two W0-G5 rows close.

## 8. Lane and what it must not touch

T1 (exec lane B1, with the two charsheet files — grouped by raw size, ruling 2026-09-25; disjoint from them). Must not edit in parallel: `tools/agent_chat_dispatch.py` and `tools/agent_chat_remote.py` (consumed by name; T1's second file is sheeted separately), `agent_runtime/{gateway_targets,gateway_peers,dispatch_store,persona_assignments,persona_chat_history,peer_directory}` beyond the one retarget in `peer_directory.py`, `hermes_cli/harness_parts/persona/` (Q10's binding is one line in the plugin `__init__`, owned by the dispatch_delivery lane if it lands first — "tree wins"); `tools/registry.py` is upstream and is never edited.
