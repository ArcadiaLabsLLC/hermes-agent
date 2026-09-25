# Layout sheet — `agent_runtime/running_work.py` (lane R2)

Base: `main` @ `28012c8f8a` · sha256 `ad55a7c70b87fed9db780643b7a1ad1be5652009c0dcc9035c34d85f0888fae9` · 1,964 raw / 1,517 code / 31 top-level defs · longest `_collect_delegations` 233 (1029–1261, depth 5) · chains 0/0 · `str==` 4 · `isinstance` 21 · owner doc `docs/agent-runtime-harness/07-observability.md` (the `running_work` projection; the 152-line module docstring is its design — durable-first, the five honesty rules, contract vs ambient). 6 production importers taking 8 names (`runtime_commands.py` → `RUNNING_WORK_KINDS`, `build_running_work`, `cancel_work`, `find_work_row`, `peek_work`; `snapshot/sections.py` → `build_running_work`; `core_cache/{fingerprint,restat}.py`, `stream.py`, `serve/boot.py` → `running_work_store_paths`; `core_cache/restat.py` → the private `_STATE_DB_FILENAME`); 5 test files pinning 18 names, two private.

**Package named after the file — `agent_runtime/running_work/`.** The file's banners ARE the layout (298 helpers · 798 terminal · 990 delegations · 1264 chat turns · 1368 dispatches · 1571 cron · 1670 public surface), and `_COLLECTORS` 1674 is already the rule-12 table over the five lanes — the one thing this sheet does not change.

## 1. Skeleton (owner ruling 2026-09-25: readability first; modules target 100–300, hard cap 500; no flow over three modules)

```
agent_runtime/running_work/
  __init__.py          wiring   the docstring (durable-first; the five honesty rules; contract vs ambient) + the map; re-exports the 8 importer names, _STATE_DB_FILENAME and the 18 test names
  vocabulary.py        models   the VOCABULARY module: PROJECTION, the limits, KIND_*/RUNNING_WORK_KINDS/SOURCES, STATUS_*/STATUS_VALUES, SOURCE_*, LANE_*, REASON_NOT_IN_PROCESS, the stale fallbacks, the two store filenames, PID_*  (~90; exempt)
  rows.py              policy   the row and source shape every lane emits: bounded_operator_text (was _safe_text), _iso, _parse_iso, _iso_from_naive_local, _elapsed, _module, _stale_thresholds, _progress, _row, _preview, _strip_ansi, _source, _ambient_context, _cap  (~250)
  ownership.py         stores   who owns what, honestly: _head_home, running_work_store_paths, _pid_identity (PID honesty, rule 2), _owner_of (rule 5, shared with the delivery drain)  (~140)   entry: running_work_store_paths
  lanes_process.py     lanes    the two lanes whose liveness is a PROCESS this runtime owns: _collect_terminal (+ the registry kill seam cancel_work reaches), _cron_owned_here, _collect_cron  (~230)
  lanes_chat.py        lanes    the three lanes keyed on a chat session: _delegation_status (DELEGATION_STATUS_BY_RECORD after the CHANGE), _collect_delegations, _collect_chat_turns, _collect_dispatches  (~440)
  surface.py           lanes    the public surface: _COLLECTORS (the table), build_running_work, find_work_row, split_work_id, peek_work, _delegation_owned_here, cancel_work  (~230)   entry: build_running_work, peek_work, cancel_work, find_work_row, split_work_id
```

Per entry point, the modules an agent opens (the entry's module plus the modules of what it calls directly; `vocabulary` is read like a table and not counted; `mission_chat_turns`, `dispatch_store`, `persona_assignments`, `parity` and the upstream registries are below the package):

| entry point | opens | count |
|---|---|---|
| `build_running_work` (snapshot, `harness work list`) | `surface` → `lanes_process` → `lanes_chat` (the five collectors the table names) | 3 |
| any one collector, followed on its own | its lane module → `rows` → `ownership` | 3 |
| `cancel_work` (`harness work cancel`) | `surface` → `lanes_process` (the registry kill seam) → `ownership` | 3 |
| `peek_work` | `surface` → `rows` | 2 |
| `running_work_store_paths` (core cache, stream, serve boot) | `ownership` | 1 |

Floor rule (ruling 3): five one-lane modules were the first draw; `lane_chat_turns` (~70) and `lane_cron` (~80) were sub-100, and `build_running_work` opened six modules. Refolded by what a lane's LIVENESS is: a process this runtime owns (terminal, cron) or a chat session's durable store (delegations, chat turns, dispatches). `lanes_chat` is the one module above 300 (three lanes that share the `_owner_of` memo and the row shape); it is under the cap, and splitting it back puts the projection's entry over three modules.

### 1.1 Section map → target modules

| lines | what is there | → module | layer (from imports) |
|---|---|---|---|
| 1–199 | the docstring 1–166, imports (`parity.ProjectionAccountant`, `redaction.TEXT_SECRET_ASSIGNMENT_RE`), `__all__` | `running_work/__init__.py` | wiring |
| 201–295, 482–486 | `PROJECTION` 201 … `_STATE_DB_FILENAME` 295, `PID_*` 482–486 | `running_work/vocabulary.py` | models |
| 303–411, 588–795 | `_safe_text` 303, `_iso` 322, `_parse_iso` 337, `_iso_from_naive_local` 359, `_elapsed` 393, `_module` 399, `_stale_thresholds` 588, `_progress` 606, `_row` 639, `_preview` 680, `_strip_ansi` 697 (lazy `tools.ansi_strip`), `_source` 717, `_ambient_context` 751, `_cap` 778 | `running_work/rows.py` — imports `vocabulary`, `redaction`, `parity` | policy |
| 414–585 | `_head_home` 414 (lazy `profile_home`), `running_work_store_paths` 454, `_pid_identity` 489 (lazy `gateway.status` — §4), `_owner_of` 537 (lazy `persona_assignments`) | `running_work/ownership.py` — imports `vocabulary`, `rows` | stores |
| 803–987, 1576–1667 | `_collect_terminal` 803, `_cron_owned_here` 1576, `_collect_cron` 1599 | `running_work/lanes_process.py` — imports `rows`, `ownership`; `sys.modules.get(...)` residency probes for `tools.process_registry` / `cron.scheduler` (§4) | lanes |
| 995–1568 | `_delegation_status` 995, `_collect_delegations` 1029, `_collect_chat_turns` 1269 (lazy `mission_chat_turns`), `_collect_dispatches` 1373 (+ `_named`; lazy `dispatch_store`, `persona_assignments`) | `running_work/lanes_chat.py` — imports `rows`, `ownership`; `sqlite3` | lanes |
| 1674–1964 | `_COLLECTORS` 1674, `build_running_work` 1683, `find_work_row` 1734, `split_work_id` 1746, `peek_work` 1759, `_delegation_owned_here` 1831, `cancel_work` 1848 | `running_work/surface.py` — imports `vocabulary`, `rows`, `lanes_process`, `lanes_chat` | lanes |

Edges point down: `surface` → `lanes_*` → `ownership` → `rows` → `vocabulary`. `stream.py:1768` and `core_cache/*` import `running_work_store_paths` lazily/at module level through `__init__`, which keeps working; `stream` is in the same exec lane (B4) and lands after this file. No cycle.

## 2. Routing sites → tables (the CHANGE commit)

| site (base line) | fixture row | replacement | killing mutation |
|---|---|---|---|
| `_delegation_status` 1008–1020: `if raw in {"stalled"}` / `{"stalling"}` / `{"finalizing"}` / `{"completed", "ok", "success"}` / `{"error", "failed", "interrupted"}` / `raw != "running"` | `\|ladder\|raw`, `\|vocab\|completed`, `\|vocab\|failed`, `\|vocab\|running` | `lanes_chat.DELEGATION_STATUS_BY_RECORD: Mapping[str, str]` — the delegation store's own words (upstream `tools.async_delegation`'s `status`/`state` values) mapped onto `STATUS_*`; `running` is the one key whose verdict needs the progress token, so the function is `verdict = TABLE.get(raw); if verdict is not None: return verdict; if raw != DELEGATION_RECORD_RUNNING: return STATUS_UNKNOWN; …stale check`. The keys of a dict literal are not `Compare` nodes, so the three `vocab` rows retire with the ladder row; `DELEGATION_RECORD_RUNNING = "running"` is read by name (batch-1 rule — `running` is fork-wide because `states.py` declares it, and this file's vocabulary is `STATUS_RUNNING`, a different word for a different question; the gate class defect is rowed once) | swap the `stalled` and `stalling` values → `tests/agent_runtime/test_running_work.py::test_staleness_maps_a_frozen_progress_token_to_stalled` reds (parametrised over the record shapes) |
| `_collect_chat_turns` 1346: `state in {"pending", "executing", "running"}` → `STATUS_RUNNING` | `\|vocab\|running` | `mission_chat_turns.INFLIGHT_TURN_STATES` (156) already declares the in-flight set (the delivery drain reads it at 992); this site reads it by name instead of re-spelling three of its members | replace with `TERMINAL` states → `::test_inflight_chat_turns_are_listed_with_their_owner` reds |
| `str(item.get("status") or "") == "exited"` 932, `== "finalizing"` 1148, `!= "not_found"` 1901 | not rows; boundary reads of a checkpoint row, the turn journal, the kill seam's result | constants by name in `vocabulary` (`CHECKPOINT_EXITED`, `TURN_FINALIZING`, `KILL_NOT_FOUND`), each with one reader | — |

W0-G7 floor rows (3):

| row | lines / depth | phases (comment map) | after |
|---|---|---|---|
| `_collect_terminal` 803 | 185 / 5 | head home 816 · durable read 824–845 · per-entry: dead PID dropped through the accountant 858, recycled 872, owner 887 · live enrichment only when rows were observed 916–976 · count what ships 981 | `TerminalLane.read_durable → rows → enrich_live → cap`, the per-entry body lifted to `_terminal_row(entry)` (depth 5 → 3), ≤ 50 each |
| `_collect_delegations` 1029 | 233 / 5 | head home 1044 · the `state.db` presence deliberately NOT reported 1048 · pre-table store = zero delegations 1075–1087 · per-record verdict via `_delegation_status` · live enrichment 1179–1252 · accountant 1256 | `DelegationLane.read_durable → rows → enrich_live → cap` — the same four names as the terminal lane (they are the same shape; the docstring's "Durable-backed lanes" paragraph is the reason the names match) |
| `_collect_dispatches` 1373 | 196 / 2 | the label memo, resolved at most once per pass 1406–1414 · fail-safe at the source 1428 · a dead owner is REPORTED here, not dropped 1444–1459 · the label 1463 | `DispatchLane.read → rows → report_dead → cap`; `_named` becomes the memo object's method |

`isinstance` 21 → ≤ 12 at review.

## 3. Helper folds

| here | duplicate of | verdict |
|---|---|---|
| `_safe_text` 303 | program §4: nine `_safe_text`, survivor `serde.safe_text` | NOT a fold: this one masks secret assignments in place and ends with `…`; `serde.safe_text` collapses and cuts. Renamed `bounded_operator_text` (public in `rows`) — retires this file's share of the name group; `snapshot/summaries._safe_text` (its docstring's twin) is R3's |
| `_pid_identity` 489 → `gateway.status._pid_exists` | `_upstream_doors.pid_exists` — whose docstring names THIS file as the reader still importing the private itself "until R2 splits it" | FOLD: the lazy import at 507 becomes `_upstream_doors.pid_exists`; `get_process_start_time` (public) stays direct. Closes `import_layers_grandfathered.json` `private_upstream_imports[30]` |
| `_parse_iso` 337 (→ epoch float) | `operator_channels._parse_time` (→ datetime; that sheet creates `clock.parse_iso`) | FOLD to `clock.parse_iso(value).timestamp()` IF the naive-local handling matches (`_iso_from_naive_local` 359 says stored stamps may be naive local — the lane diffs and pastes); else NOT, and the row says why |
| `_iso` 322 (epoch → `isoformat()` with `+00:00`) | `clock.iso_timestamp` (→ `Z` form) | NOT a fold: `::test_every_started_at_on_the_wire_carries_a_utc_offset` pins the `+00:00` wire form |
| `_elapsed` 393 (seconds, int) | `clock.elapsed_ms` (milliseconds), `dispatch_delivery._elapsed` (prose) | NOT a fold (units); renamed `elapsed_seconds` to retire the name group |
| `_strip_ansi` 697 | wraps `tools.ansi_strip.strip_ansi` (public upstream) | stays — the wrapper is the sensitivity guard |
| `_row` 639 | program §4's `running_work/collect.row` group | this IS the survivor the program names; it becomes `rows.work_row` (public), and the other `_row`s are renamed by their own sheets (`gateway_peers.md` §3) |

## 4. Upstream doors

| reach | class | door |
|---|---|---|
| `gateway.status._pid_exists` 507 (private; fixture row [30]) | NO | `_upstream_doors.pid_exists` — exists; §3 fold |
| `gateway.status.get_process_start_time` 507, `tools.ansi_strip.strip_ansi` 708, `tools.process_registry.process_registry.{list_sessions, get, kill_process, checkpoint_path}` (through `sys.modules`, 918/1805/1872/1891), `tools.async_delegation.list_async_delegations` 1181, `cron.scheduler.get_running_job_ids` 1619 | FIRST (public) | kept; the residency probes (`_module` 399, `sys.modules.get` — never `import_module`, per the docstring) stay exactly as written |
| `cron.scheduler._parallel_pool` / `_sequential_pool` 1595 (private ATTRIBUTES read by `getattr(scheduler, attr, None)`) | NO — a private reach the AST walk cannot see (a string, not an `ImportFrom`) | `_upstream_doors.cron_pools_present(scheduler) -> bool` (the one question asked of them); a held widening row (publish `scheduler.owns_running_jobs()`), ruling Q7 |

## 5. Dead code (verdict + the grep the lane runs)

No queue row names this file. `git grep -nw` over the 31 defs: every private has an in-file caller; `find_work_row`/`split_work_id` are imported by `runtime_commands.py` and test-pinned. Nothing filed.

## 6. Positive controls — land in the MOVE (ruling Q6)

`DELEGATION_STATUS_BY_RECORD` replaces a ladder that `::test_staleness_maps_a_frozen_progress_token_to_stalled` drives parametrically — the lane pastes the parametrisation to show every table key (`stalled`, `stalling`, `finalizing`, the three `completed` words, the three `error` words, `running` with and without a frozen token) appears in it; any key missing gains a row in that parametrisation BEFORE the table lands. The `INFLIGHT_TURN_STATES` read is pinned by `::test_inflight_chat_turns_are_listed_with_their_owner` and `::test_a_settled_chat_turn_is_not_running_work`.

## 7. MOVE hash-proof plan, then the CHANGE

1. **MOVE** `refactor(running_work): running_work.py → agent_runtime/running_work/ (6 modules)` — spans byte-identical with the sha256 table (one row per §1.1 span); `__init__` carries the docstring and re-exports the 8 + 18 names. **Killing mutation for the MOVE:** drop `ownership` from `__init__` → `agent_runtime/core_cache/fingerprint.py` fails to import `running_work_store_paths` → `tests/agent_runtime/test_core_fingerprint_cache.py` reds at collection. `[ds-size]` −1.
2. **CHANGE** `refactor(running_work): DELEGATION_STATUS_BY_RECORD; INFLIGHT_TURN_STATES read by name; Terminal/Delegation/Dispatch lanes as phases; pid_exists door; bounded_operator_text, work_row, elapsed_seconds` — §2 + §3 with each red pasted; four W0-G5 rows and the `private_upstream_imports[30]` row close.

## 8. Lane and what it must not touch

R2 (exec lane B4), FIRST of its three — `stream.md` reaches `running_work_store_paths` and lands next; `mcp_admission.md` is disjoint. Must not edit in parallel: `mission_chat_turns.py` (`INFLIGHT_TURN_STATES` is read, not moved), `dispatch_store.py`, `persona_assignments/`, `parity.py`, `core_cache/`, `snapshot/`, `serve/boot.py`, `harness_parts/runtime_commands.py` (all keep their paths through `__init__`); `_upstream_doors.py` gains `cron_pools_present` and nothing else; `clock.parse_iso` is created by the operator_channels sheet (lane B3) — if B4 lands first, this lane creates it and B3 folds ("tree wins").
