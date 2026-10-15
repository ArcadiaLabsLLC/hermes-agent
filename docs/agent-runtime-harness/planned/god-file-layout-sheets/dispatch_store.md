# Layout sheet — `agent_runtime/dispatch_store.py` (lane R1 · exec lane 2B-A)

Base: `main` @ `28012c8f8a` · 1,308 raw / 1,019 code / 30 top-level defs · longest `record_completion` 155 (W0-G7 fixture row) · chains 1/0 · `str==` 0 · `isinstance` 9 · sha256 `9d820992700c6f5307088751b50e0e85873ba42b14bf5c13bf26f225370b7163` · owner doc `docs/agent-runtime-harness/05-chat-turn.md` (the detached lane). 9 production importers (`dispatch_delivery`, `running_work`, `media_handles`, `mission_chat_outcome`, `decision_contract_registry`, `harness_parts/persona/chat_tickets_commands`, `harness_parts/serve/boot_phases`, `tools/agent_chat_dispatch`, `tools/agent_chat_tool`), 13 test files. Importers take the `__all__` list (line 70) plus `REARM_ERROR_KINDS`, `ERROR_KIND_DISPATCH_STORE_UNAVAILABLE`, `REPLY_LIMIT`, `STATE_COMPLETED`; tests read `_emit`, `_query`, `_TABLE`, `_backlog_report_state`, `_MAX_RETAINED_TERMINAL` by attribute.

**Package `agent_runtime/dispatch_store/`.**

## 1. Skeleton (owner rulings 2026-09-25) — this text IS the package `__init__` map

```
agent_runtime/dispatch_store/
  __init__.py   wiring  the map; __all__ verbatim + REARM_ERROR_KINDS, ERROR_KIND_DISPATCH_STORE_UNAVAILABLE, REPLY_LIMIT, STATE_COMPLETED
  models.py     models  VOCABULARY/TABLE module (floor-exempt): the row vocabulary (states, delivery states, reasons, re-arm outcomes, bounds), row ↔ dict, the media-map shape check
  db.py         stores  the one database and everything that only reads it: path, connect, schema + migrations, the always-close transaction, the read-only query, the six projections (running / pending / undeliverable / mine / by id / remote media), and the process identity a row is stamped with (pid + start ticks; the supervised-id set; _emit)
  writes.py     lanes   the two writes that CREATE and SETTLE a row — record_dispatch, record_completion — and the housekeeping a settle triggers (_prune, the throttled backlog report)
  delivery.py   lanes   the delivery-state machine: claim / release / mark_delivered / drop / rearm / set_dispatch_owner, and the boot sweep that re-classifies orphaned running rows
```
Entry points and the modules an agent opens: `record_dispatch` / `record_completion` (`tools/agent_chat_*`) → `writes.py` → `db.py` — **2**; `claim_delivery` … `mark_delivered` (`dispatch_delivery`'s drain) → `delivery.py` → `db.py` — 2; `restore_undelivered_dispatches` (`serve/boot_phases`) → `delivery.py` → `writes.py` (the settle) → `db.py` — 3; `running_dispatches` / `remote_media_completions` (`running_work`, `media_handles`) → `db.py` — 1; `rearm_delivery` (the CLI repair verb) → `delivery.py` → `db.py` — 2. Layers: lanes → `db` → `models`; `delivery` → `writes` is same-layer.

### 1.1 Section map → target modules (sizes are raw / est. code; the 100/300/500 bars are on code lines)

| lines | what is there | → module | raw / code | layer |
|---|---|---|---|---|
| 1–102 | docstring, imports, `__all__` | `dispatch_store/__init__.py` | ~110 / 45 | wiring |
| 104–194, 314–371, 429–497 | `_TABLE`, `DELIVERY_*`, `STATE_*`, `TERMINAL_STATES`, `CLAIM_EXPIRY_SECONDS`, `MAX_DELIVERY_ATTEMPTS`, `DROP_REASON_*`, `REMOTE_UNREACHABLE_REASON`, `REARM_*`, `REARM_ERROR_KINDS`, `ERROR_KIND_*`, `ASK_LIMIT`, `REPLY_LIMIT`, `_RETENTION_SECONDS`, `_MAX_RETAINED_TERMINAL`, `MEDIA_*`; `mint_dispatch_id`, `_text`, `_media_rows`, `_row_to_dict`, `_SELECT` | `dispatch_store/models.py` — stdlib + `uuid`/`json` only; vocabulary + the row codec | ~260 / 170 | models |
| 105, 203–311, 374–426, 1078–1214 | `_DB_LOCK`, `dispatch_db_path`, `_connect`, `_initialize_schema`, `_add_missing_column`, `_transaction`; `_supervised_here`, `_owner_identity`, `_emit`; `_query`, `running_dispatches`, `undeliverable_dispatches`, `pending_deliveries`, `get_dispatch`, `list_dispatches`, `remote_media_completions` | `dispatch_store/db.py` — `sqlite3`, `hermes_state.apply_wal_with_fallback` (lazy), `profile_home` (lazy), `gateway.status` (lazy), `tools.agent_chat_dispatch` (lazy, `_supervised_here` only); `_emit` folds onto `store_events` (§4) | ~330 / 220 | stores |
| 505–737, 968–1070 | `record_dispatch`, `record_completion`; `_BACKLOG_REPORT_INTERVAL_SECONDS`, `_backlog_report_state`, `_backlog_report_due`, `_prune` | `dispatch_store/writes.py` — both writes hold `_DB_LOCK` + `_transaction` (rule 13) | ~340 / 240 | lanes |
| 740–965, 1222–1308 | `claim_delivery`, `release_delivery_claim`, `set_dispatch_owner`, `mark_delivered`, `drop_delivery`, `rearm_delivery`; `restore_undelivered_dispatches` (reaches `_pid_exists` — §5 door) | `dispatch_store/delivery.py` — the six state-machine writes, one lock + transaction each, and the sweep that calls `writes.record_completion(only_if_running=True)` | ~320 / 220 | lanes |

Refolded under the no-fragmentation ruling: the earlier draft's `identity.py` (~30 code), `housekeeping.py` (~75), `reads.py` (~80) and `sweep.py` (~60) were under the floor; identity and the reads sit with the database they touch, housekeeping with the settle that triggers it, the sweep with the delivery machine it re-arms. Result: 4 modules + the map, none over 240 code lines. Edges: `writes`/`delivery` → `db` → `models` (down); `delivery` → `writes.record_completion` (same layer). `tools.agent_chat_dispatch` ↔ this package is a two-way LAZY cycle today (`_supervised_here` here; `record_completion` there) and stays lazy on both sides — `db.py` is the only module that may name `tools.agent_chat_dispatch`, and only inside the function.

## 2. Routing sites (rule 12)

| site (base line) | shape today | replacement | killing mutation |
|---|---|---|---|
| `rearm_delivery` 951–964 | a three-arm ladder on `delivery_state` (`== DELIVERY_DELIVERED` → `REARM_ALREADY_DELIVERED`; `!= DELIVERY_DROPPED` → `REARM_NOT_DROPPED`; else write + `REARM_REARMED`) | `REARM_OUTCOME_BY_STATE: Mapping[str, str] = {DELIVERY_DELIVERED: REARM_ALREADY_DELIVERED, DELIVERY_PENDING: REARM_NOT_DROPPED, DELIVERY_DROPPED: REARM_REARMED}` in `models.py`, one lookup with a typed fall-through (`REARM_NOT_DROPPED` for an unknown state), the UPDATE guarded on `outcome == REARM_REARMED` | swap the `DELIVERED` and `PENDING` rows → the §6.1 control reds. **This ladder is invisible to W0-G5 arms (a)/(c)** — it compares against NAMES bound to strings, not string constants (the probe reports `chains 1/0`); the class is filed (report row) |
| `record_completion` 643–645 | `settled not in TERMINAL_STATES → STATE_UNKNOWN` | a boundary; stays |
| the `CASE WHEN delivery_state=?` arms 695–704 | routing inside SQL | stays; the sheet names it so nobody lifts it into Python |

`isinstance` 9 → 9 (all shape checks at the peer door, `_media_rows`).

## 3. W0-G7 floor row (1)

| row | lines / depth | phases | after |
|---|---|---|---|
| `record_completion` 583 | 155 / 2 | result blob 643–660 · params + UPDATE 661–708 · superseded-outcome event 709–717 · completed event 718–735 · prune 736 | `_completion_result(...)` (≤ 25), `_completion_update(conn, dispatch_id, result, *, only_if_running) -> (updated, prior)` (≤ 45), `_completion_events(dispatch_id, prior, settled, result, remote, media_rows)` (≤ 35); the verb ≤ 40 — all in `writes.py` |

## 4. Helper folds

| here | owner | verdict |
|---|---|---|
| `_emit` 408 | `store_events.emit_store_event(EventLog(), type, payload, domain="dispatch store")` — same filter/append/warn | FOLD, keeping a 3-line `db._emit(event_type, **payload)` so the lazy `EventLog()` construction and the test seam (`setattr(dispatch_store, "_emit", …)` ×3) survive; **the seam retargets to the module that binds the name for the write under test** (`dispatch_store.writes._emit` for `record_*`, `dispatch_store.delivery._emit` for the delivery writes) — or the patch reaches nothing (§6.2) |
| `_text` 314 | fixture row `_text: chat_turn, dispatch_store, mission_chat_outcome, persona_open_chat` — `str(value)[:limit]`, `None` → `""` | this lane CREATES `serde.bounded_text(value, limit)` (not `safe_text`: no strip, no `None`) and folds its copy; the other three fold in their lanes |
| `_owner_identity` 392 / `agent_chat_dispatch._child_identity` 480 / `running_work` 507 | three try/except wrappers over `gateway.status.get_process_start_time` | fold candidate `agent_runtime/process_identity.py::start_ticks(pid)`; created by the first of the three lanes to land ("tree wins") — this sheet does not require it |
| `_transaction` 292 | — | stays (lower-case class name is a style row for the `style:` commit) |

## 5. Doors

| import (line) | class | door |
|---|---|---|
| `gateway.status._pid_exists` (1243, lazy) | PRIVATE — W0-G6 fixture row `agent_runtime/dispatch_store.py\|gateway.status\|_pid_exists`; runtime-queue "H2 sheet leftovers" row names it | **FIRST**: `agent_runtime._upstream_doors.pid_exists` exists (created by H2 for `serve_registry`) — the sweep imports it; the fixture row is deleted in the MOVE (the gate's shrink-only fixture goes down by one) |
| `gateway.status.get_process_start_time` (401, 1243) | public | keep |
| `hermes_state.apply_wal_with_fallback` (230) | public | keep |

No widening.

## 6. Positive controls (ruling Q6)

1. `rearm_delivery` has **no test** (`git grep -c rearm -- tests/` → 0 on this store's tests). Land, in the MOVE: a dropped row re-arms to `pending` with `delivery_attempts == 0` and `delivery_error IS NULL` (`REARM_REARMED`); a delivered row answers `REARM_ALREADY_DELIVERED` and is untouched; a pending row answers `REARM_NOT_DROPPED`. Only then the table of §2.
2. The `_emit` seam: revert one `setattr` retarget → `test_dispatch_store.py`'s captured-events case reds (proves the patch site moved). Same for `_MAX_RETAINED_TERMINAL` (6 sites → `dispatch_store.writes`); `_backlog_report_state` needs no retarget (the dict is mutated in place through the re-export).
3. `_supervised_here` skip in the sweep: assert a `running` row whose id is in `supervised_dispatch_ids()` is NOT reclassified even with a dead PID (the race the docstring at 1251 records) — `git grep -n supervised -- tests/agent_runtime/test_dispatch_store.py`; land if absent.

## 7. Commits and the MOVE hash proof (one MOVE, one CHANGE — program §3.1d)

1. **MOVE** `refactor(dispatch_store): dispatch_store.py → agent_runtime/dispatch_store/ (4 modules); _pid_exists through the door` — spans byte-identical with one sha256 row per §1.1 range (`git show 28012c8f8a:agent_runtime/dispatch_store.py | sed -n 'A,Bp' | sha256sum`); `__all__` re-exported verbatim; the three controls; the 11 attribute seams retargeted; the W0-G6 fixture row deleted; `__layer__` per §1.
2. **CHANGE** `refactor(dispatch_store): REARM_OUTCOME_BY_STATE; record_completion phases; emit_store_event + serde.bounded_text folds` — reds pasted; `[ds-size]` −1; W0-G7 fixture row deleted.

## 8. Lane and what it must not touch

Exec lane 2B-A, last of four. Must not edit in parallel: `dispatch_delivery.py`, `running_work.py`, `media_handles.py`, `mission_chat_outcome.py` (importers through `__init__`); `tools/agent_chat_dispatch.py` — **lane 2B-C's file**; the lazy cycle is left exactly as it is on both sides, and `db.py` is the only place this package may spell that path.
