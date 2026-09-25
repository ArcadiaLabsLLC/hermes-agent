# Layout sheet — `tools/agent_chat_dispatch.py` (lane T1 · exec lane 2B-C)

Base: `main` @ `28012c8f8a` · 1,149 raw / 842 code / 20 top-level defs · longest `_run_remote_dispatch` 258 (W0-G7 fixture row; depth 5), `_run_dispatch_guarded` 147 · chains 0/0 · `str==` 4 · `isinstance` 1 · sha256 `c65ebf5e2bb2541eee75c287291e5e31f5de4c9545fe905c3d833d2318401007` · owner doc `docs/agent-runtime-harness/05-chat-turn.md` (the detached lane) and `09-multi-device-runtime.md` (Stage 7). **A fork-only file in an upstream directory** (program §0.3, Q2 yes). 7 production importers (`agent_runtime/dispatch_store` lazy, `agent_runtime/media_proxy` — a comment, `agent_runtime/serve_socket/__init__`, `harness_parts/persona/chat_reply_stamps` — a comment, `scripts/upstream_sync_gate`, `tools/agent_chat_remote`, `tools/agent_chat_tool`), 5 test files. Importers take `supervised_dispatch_ids`, `dispatch_detached_turn`, `summarize_for_caller`, `build_dispatch_argv`, `PEER_DIAL_TIMEOUT_SECONDS`; tests read `_run_remote_dispatch`, `_child_identity`, `KILL_GRACE_SECONDS`, `SERVE_STDOUT_EVENT` and patch `_child_identity` ×4, `dispatch_detached_turn` ×3, `threading` ×1.

**Package placement is owner question Q21** (program §9). Program §0.3 says T1's modules go under "a new `tools/agent_chat/` package"; the H3/H4 precedent says a package is named after its file so the 12 importers keep their path. Default: **`tools/agent_chat_dispatch/`** — the same top-level entry `tools/` already carries, replacing a fork-only FILE with a fork-only DIRECTORY of the same name, so the upstream footprint is unchanged and no importer moves; `tools/agent_chat_tool.py` (S2A's file) lands the same way. The alternative (`tools/agent_chat/dispatch/` + a ≤ 20-line shim at the old path) adds a second top-level fork entry and a shim to delete later.

## 1. Skeleton (owner rulings 2026-09-25) — this text IS the package `__init__` map

```
tools/agent_chat_dispatch/
  __init__.py   wiring  the map; __all__ verbatim + SERVE_STDOUT_EVENT, and the test-pinned private names
  child.py      policy  everything about ONE child process: the argv and environment it is built from, the bounded tails that read it, the pumps that drain it and are forced loose, its identity, its kill, the payload parser, the lane-specific error rewrite
  local.py      lanes   the supervisor pool (the supervised-id set, the executor, dispatch_detached_turn) and the local leg (_run_dispatch → _run_dispatch_guarded: spawn, stamp, wait, settle); summarize_for_caller, the status the tool returns
  remote.py     lanes   the cross-install leg (Gateway Stage 7): the peer params, the frame reader, _run_remote_dispatch's dial / ack / read / settle loop
```
Entry points and the modules an agent opens: `agent_chat_send(wait=false)` (`tools/agent_chat_tool`) → `local.dispatch_detached_turn` → `local._run_dispatch_guarded` → `child.py` — **2** (the store, `agent_runtime.dispatch_store`, is the third and is another package); a cross-install dispatch → `local.py` (the fork on `remote_install_id`) → `remote.py` → `child.parse_child_payload` — 3; the orphan sweep's question (`dispatch_store`) → `local.supervised_dispatch_ids` — 1; `agent_chat_dispatches` (the status tool) → `local.summarize_for_caller` — 1. Layers: `local`, `remote` (lanes) → `child` (policy); `local` → `remote` (same layer, one call); both lanes → `agent_runtime.dispatch_store` (lazy, the two-way lazy cycle the `dispatch_store` sheet names).

### 1.1 Section map → target modules (sizes are raw / est. code; the 100/300/500 bars are on code lines)

| lines | what is there | → module | raw / code | layer |
|---|---|---|---|---|
| 1–88 | docstring (the subprocess correction), imports, `__all__` | `__init__.py` | ~95 / 25 | wiring |
| 90–96, 106–112, 125–139, 223–535 | `KILL_GRACE_SECONDS`, `SERVE_STDOUT_EVENT`, `_MAX_STREAM_CHARS`, `_STDERR_EXCERPT`, `_PAYLOAD_MARKER`; `build_dispatch_argv`, `child_environment`, `parse_child_payload`, `_BoundedTail`, `_drain`, `_release_pumps`, `_child_identity`, `_kill_child`, `_detached_error_text` | `agent_chat_dispatch/child.py` (`subprocess`, `threading`, `json`; lazy `gateway.status`, `tools.process_registry` — §5 door, `hermes_cli`) | ~380 / 230 | policy |
| 141–215, 537–576, 925–1149 | `_executor*`, `_supervised*`, `_mark_supervised`, `_forget_supervised`, `supervised_dispatch_ids`, `_get_executor`; `_run_dispatch`; `_run_dispatch_guarded`; `dispatch_detached_turn`; `summarize_for_caller` | `agent_chat_dispatch/local.py` (lazy `agent_runtime.dispatch_store`, `agent_runtime.turn_visibility`, `tools.daemon_pool`, `hermes_cli._subprocess_compat`) | ~400 / 250 | lanes |
| 98–104, 114–120, 578–922 | `PEER_DIAL_TIMEOUT_SECONDS`, `PEER_RETRY_BACKOFF_SECONDS`; `build_peer_execute_params`, `_remote_reply_payload`, `_run_remote_dispatch` | `agent_chat_dispatch/remote.py` (lazy `agent_runtime.dispatch_store`, `gateway_peers`, `gateway_targets`, `turn_visibility`) | ~350 / 220 | lanes |

Result: 3 modules + the map, none over 250 code lines. Edges: all down or same-layer. **The gate gap:** W0-G6 walks `agent_runtime/`, `hermes_cli/harness_parts/`, `plugins/eternia-harness/` — this package (like `agent/charsheet/`) is a fork-only tree in an upstream directory and is NOT walked, so its `__layer__` declarations and its one private upstream reach (§5) are unchecked by the gate; filed in the report as part of the gate-class row.

## 2. Routing sites (rule 12)

| site (base line) | shape | replacement | killing mutation |
|---|---|---|---|
| `_detached_error_text` 522–534 | two arms on `error_kind` (`== "relay_budget_exhausted"` / `in {"relay_cycle", "relay_depth_limit"}`) — literals of the `mission_chat_outcome` error-kind registry | `_LANE_REWRITES: Mapping[str, str]` keyed by the constants `mission_chat_outcome` declares (the single-reader rule; no new Enum — the kinds ride every chat payload), `.get(kind, raw[:600])` | swap the two rewrites → `test_agent_chat_remote.py`'s refused-before-run case reds (control §6.1) |
| `_run_remote_dispatch` 752–822 | the ack's three outcomes: `"error" in ack` / `idempotent_replay` / fresh | typed boundaries in order; stay — as the phases of §3 |
| `_remote_reply_payload` 655–662 | `event == SERVE_STDOUT_EVENT` / `"exit"` | a two-word frame boundary; stays. `SERVE_STDOUT_EVENT` is a constant beside its ONE reader (the 2026-09 rule already applied here) |
| `parse_child_payload` 349–352 | marked vs fallback object | a boundary; stays (the comment at 355 is the argument) |

`str==` 4 → 2 at review.

## 3. W0-G7 floor row (1) and the near-miss

| row | lines / depth | phases (from the comment map) | after |
|---|---|---|---|
| `_run_remote_dispatch` 665 | 258 / **5** | build params 700–704 · the attempt loop: dial 710–725 · send + ack 727–751 · the three ack outcomes 752–831 · read reply 832 · close 838–842 · transport retry 844–852 · settle 854–895 · the cap's terminal error 897–922 | a `RemoteDispatch` object (fields: `dispatch_id`, `spec`, `install_id`, `display`, `budget`, `params`, `root`, `failures`, `attempts`): `.run()` (the loop, ≤ 35), `._attempt(connection) -> Settled \| Retry` (≤ 60: send, ack, the three outcomes), `._settle_payload(answered)` (≤ 45), `._settle_unreachable()` (≤ 25); the six `failures.append(...) + sleep + continue` sites become one `._retry(reason)`; depth 5 → 3 |
| `_run_dispatch_guarded` 925 | 147 / 3 | the remote fork 936–938 · argv + env 945–950 · spawn 952–982 · stamp owner 989–995 · pumps + wait 997–1015 · release 1019 · the three settles 1025–1071 | lift `_spawn_child(argv, env) -> Popen` (the `popen_kwargs` + Windows flags, ≤ 30) and `_settle_local(dispatch_id, returncode, exit_reason, payload, stderr_text)` (the three `record_completion` arms, ≤ 45); the verb ≤ 70 |

## 4. Helper folds

| here | owner / duplicate | verdict |
|---|---|---|
| `_drain` 423 | fixture row (`_drain: persona_chat_actor_prewarm, persona_prewarm, agent_chat_dispatch`) — three daemon-thread line pumps into a sink | owner `agent_runtime/subprocess_pumps.py::drain(stream, sink) -> Thread` + `release_pumps(proc, threads)`; created by whichever of this lane and R2's `persona_chat_actor_prewarm` lane (program §3.2) lands first ("tree wins"); this sheet folds both `_drain` and `_release_pumps` when the owner exists, else creates it. Killing mutation: make the pump keep the HEAD instead of the tail → `test_serve_socket_lane.py`'s long-stdout dispatch case reds |
| `_child_identity` 480 | `dispatch_store._owner_identity` 392, `running_work` 507 — the same try/except over `gateway.status.get_process_start_time` | `agent_runtime/process_identity.py::start_ticks(pid)` candidate (the `dispatch_store` sheet §4 names it); not required here. The seam `setattr(agent_chat_dispatch, "_child_identity", …)` ×4 retargets to `agent_chat_dispatch.local` (the module that binds the name for `_run_dispatch_guarded`) |
| `_kill_child` 489 | — | stays; see §5 for the door it must use |
| the five `f"attempt {attempts}: {type(exc).__name__}: {exc}"` sites | `harness_doctor._error_text` (its sheet §4 names `errors.error_text`) | fold when the owner exists; the `RemoteDispatch._retry` collapses them to one site regardless |

## 5. Doors

| import (line) | class | door |
|---|---|---|
| `tools.process_registry.ProcessRegistry._terminate_host_pid` (501, lazy) | PRIVATE classmethod on an UPSTREAM module (`tools/process_registry.py` is in the manifest) — the identity-verified tree-kill the docstring at 490 correctly refuses to duplicate | **NEAR**: `agent_runtime/_upstream_doors.py` gains `terminate_host_pid(pid, expected_start)`; a held widening row in `upstream-footprint-ledger.md` asks upstream to make it public (`ProcessRegistry.terminate_host_pid`). Ruling Q7 pattern: door now, widening when the next upstream batch is cut. Because W0-G6 does not walk `tools/`, this reach is on no fixture today — the door is the sheet's requirement, not the gate's |
| `gateway.status.get_process_start_time` (482) | public | keep |
| `tools.daemon_pool.DaemonThreadPoolExecutor` (204) | public, upstream | keep |
| `hermes_cli._subprocess_compat.windows_hide_flags` (969) | a public function in a privately-named upstream module | keep; named so the merge lane knows the module name is upstream's, not a fork `_private` |

## 6. Positive controls (ruling Q6)

1. Before `_LANE_REWRITES`: a test that hands `_detached_error_text` a `relay_budget_exhausted` payload AND a `relay_cycle` payload and asserts the two DIFFERENT rewrites (one fixture is green under the swap).
2. Before the `RemoteDispatch` split: the three ack outcomes pinned — a peer `error` settles `STATE_ERROR` with `reason`; an `idempotent_replay` with `settled` records `peer_turn_replayed`; a fresh accept reads the frames to `exit` — `test_gateway_peer_cross_install_chat_e2e.py` holds the third; the lane greps the first two and adds what is missing.
3. `_release_pumps`' forced release: a fake pipe that never closes → both threads are joined within the 12 s bound (the docstring's "one leak, not a growing one").
4. Dead-code queue rows 136–138 (`_get_executor`, `_kill_child`, `dispatch_detached_turn`) are **REFUTED** by the file itself — called at 1088, 1008, and imported by `tools/agent_chat_tool.py` respectively; the lane pastes the three greps and deletes the rows (the census counted cross-file NAME hits only — the class is filed in the report).

## 7. Dead code found while reading

None beyond the three refuted rows. `build_peer_execute_params`, `parse_child_payload`, `child_environment`, `SERVE_STDOUT_EVENT`, `KILL_GRACE_SECONDS`, `PEER_RETRY_BACKOFF_SECONDS` have 0 production importers by name and an in-file caller each; `summarize_for_caller`, `supervised_dispatch_ids`, `build_dispatch_argv` have one each.

## 8. Commits and the MOVE hash proof (one MOVE, one CHANGE — program §3.1d)

1. **MOVE** `refactor(agent_chat_dispatch): tools/agent_chat_dispatch.py → tools/agent_chat_dispatch/ (3 modules); _terminate_host_pid through the door` — spans byte-identical with one sha256 row per §1.1 range (`git show 28012c8f8a:tools/agent_chat_dispatch.py | sed -n 'A,Bp' | sha256sum`); `__all__` verbatim; the 8 seams retargeted (`_child_identity` → `local`; `dispatch_detached_turn` patches reach `agent_chat_tool` only if it imports by attribute — it imports lazily by name inside the function, so the package attribute IS what it reads; `threading` → `child`); the `_upstream_doors` entry + ledger row; controls §6; `__layer__` per §1 (declared even though W0-G6 does not read it — so the day the walk widens, nothing is owed).
2. **CHANGE** `refactor(agent_chat_dispatch): RemoteDispatch phases; _spawn_child + _settle_local lifted; _LANE_REWRITES; subprocess_pumps fold` — reds pasted; the W0-G7 fixture row deleted; `[ds-size]` −1.

## 9. Lane and what it must not touch

Exec lane 2B-C, last. Must not edit in parallel: `tools/agent_chat_tool.py` (S2A's file — it keeps importing through the package `__init__`), `tools/agent_chat_remote.py`, `agent_runtime/dispatch_store` (lane 2B-A — the lazy cycle is left as it is on both sides), `agent_runtime/gateway_peers.py`, `serve_socket/` (batch 1), `tools/process_registry.py` and `tools/daemon_pool.py` (upstream; never).
