# Layout sheet — `agent_runtime/board_store.py` (lane R1 · exec lane 2B-A)

Base: `main` @ `28012c8f8a` · 1,085 raw / 925 code / 16 top-level defs · longest `BoardStore._idempotent_replay` 88 · chains 0/0 · `str==` 1 · `isinstance` 4 · sha256 `3f4969014ac5489d4911d1ebfc810560692571ef07fb4a1bab33750434fa52bf` · owner doc `docs/agent-runtime-harness/06-office-and-board.md`. 11 production importers (`board_sync`, `default_scope`, `realm_revert`, `realm_sync/{drift,publish_scans}`, `runtime_hud`, `snapshot/sections`, `store`, `workspace_template`, `harness_parts/board`, `tools/board_tool`), 15 test files. Importers take `BoardStore`; one takes `_read_json` (which folds onto `serde.read_json`, §3).

**Package `agent_runtime/board_store/`.** The file is ONE class of 900 raw lines (127–1026) plus its helpers — the Q8 case: **the class moves whole for one MOVE commit (a 900-line `store.py` for that one commit — the Q8 transient, above the 500 cap on purpose and for one commit only); the CHANGE lifts its MECHANISMS out and leaves the verbs on the class**, so every flow is verb → mechanism → files and never longer.

## 1. Skeleton (owner rulings 2026-09-25) — this text IS the package `__init__` map

```
agent_runtime/board_store/
  __init__.py       wiring  the map; re-exports BoardStore, BoardScan, CardScan
  models.py         models  VOCABULARY/BOUNDS module (floor-exempt): BoardScan / CardScan (rows beside their unreadable count), the three verb tokens, ARCHIVED_LEDGER_CAP, the title / text / actor / label / checklist bounds, card sort + order-key lookup, the idempotency-key grammar
  files.py          stores  the board on disk: read_json, write_board, write_card (the two writers), where a card is (active / archived / conflict), the per-directory scans, the locked archive step, the conflict guard
  card_mechanics.py stores  the two mechanisms every card write consults under the lock: CardOrdering (the ONE ordering read; allocate / append / rebalance) and IdempotencyReceipts (replay with typed refusals; record per board, per verb)
  store.py          stores  BoardStore — the verbs: reads, ensure_default_board / create / update_board, add / edit / move / archive / restore card
  adopt.py          stores  the realm-pull arms on the same store: adopt_remote_board, adopt_remote_card, resolve_conflict (BoardStore delegates the three in one line each)
```
Entry points and the modules an agent opens: `add_card` / `edit_card` / `move_card` (the CLI, `tools/board_tool`) → `store.py` → `card_mechanics.py` → `files.py` — **3**; `archive_card` / `restore_card` → `store.py` → `files.py` — 2; `scan_all` / `scan_cards` (`realm_sync`, `snapshot/sections`, `store.WorkspaceStore.delete`) → `store.py` → `files.py` — 2; `adopt_remote_*` / `resolve_conflict` (`board_sync`, the CLI) → `adopt.py` → `files.py` — 2 (the one-line delegation on `BoardStore` is not a hop). Layers: `store`, `adopt` → `card_mechanics` → `files` → `models`; nothing imports `store`.

### 1.1 Section map → target modules (sizes are raw / est. code; the 100/300/500 bars are on code lines)

| lines | what is there | → module (MOVE) | → after the CHANGE | layer |
|---|---|---|---|---|
| 1–42 | docstring, imports | `board_store/__init__.py` | — | wiring |
| 43–82, 84–125, 1059–1085 | `VERB_*`, `ARCHIVED_LEDGER_CAP`, `BoardScan`, `CardScan`; `_safe_text`, `_safe_title`, `_safe_actor`, `_safe_labels`, `_safe_checklist`; `_sort_cards`, `_order_key_of`, `_safe_idempotency_key` | `board_store/models.py` (~120 / 90; vocabulary + bounds — floor-exempt) | — | models |
| 1031–1057, 1074–1079 | `_read_json`, `_write_board`, `_write_card`, `_archive_conflict_sidecar`, `_check_revision` | `board_store/files.py` (~50 / 35 for this commit; the sidecar/revision helpers fold onto `store_conflicts` — §3) | `files.py` grows to ~200 / 140 with 743–761, 866–909 (`_scan_card_dir`, `_scan_active_cards`, `_scan_archived_cards`, `_locate_card`, `_board_id_of_archived_card`, `_board_id_of_conflict`, `_card_path_active`, `_guard_no_conflict`) and 780–813 (`_archive_card_locked`, taking `emit` as an argument) | stores |
| 127–1026 | `BoardStore` whole (900 raw) | `board_store/store.py` — **900 raw for exactly this one commit (Q8)** | `card_mechanics.py` (~230 / 165) takes 762–778, 815–864 (`CardOrdering`) and 911–1026 (`IdempotencyReceipts`); `adopt.py` (~200 / 110) takes 534–730; `store.py` keeps 127–530 + 734–741 minus the lifted privates (~430 / 300): `__init__`, `_emit` (→ `store_events`), the reads, the three board writes, the five card writes, `_resolve_board_for_write` | stores |

Refolded under the no-fragmentation ruling: the earlier draft's `sanitize.py` (~60 code), `locate.py` (~70), `ordering.py` (~85), `receipts.py` (~80), `archive.py` (~45), `board_writes.py`, `card_writes.py` and a façade `store.py` (~70) drew a `resolve_conflict` flow four modules long and six modules under the floor; they fold to the five above, and `BoardStore` keeps its verbs instead of delegating them. Edges after the CHANGE: `store` → `card_mechanics` → `files` → `models`; `adopt` → `files`; nothing imports `store`. Lazy reach `store.py:427` (`WorkspaceStore.delete` → `BoardStore`) is the only cross-package edge and it is inbound. `runtime_hud._board_digest_for_workspace` imports `BoardStore` lazily — through `__init__`, unchanged.

## 2. Routing sites (rule 12)

No W0-G5 row. `resolve_conflict` 701–721 (`take == "local"` / else) is a validated two-way boundary (`take not in {"local","remote"}` refuses first) — stays. The `_emit` event names are literals at each write (the standing store rule, one event per mutation) — not routing. `str==` 1 → 0 is not a goal.

## 3. Helper folds

| here | owner | verdict |
|---|---|---|
| `BoardStore._emit` 133 | `store_events.emit_store_event(self.event_log, type, payload, domain="board")` — identical | FOLD (program §4 row: `board_store`, `dispatch_store`, `office_store`'s copies; `office_store` already folded) |
| `_check_revision` 1074 | `store_conflicts.check_revision(current, expected)` | FOLD **with one named difference**: the owner refuses `current is None` as `StaleRevision`; this one would raise `TypeError` on `int(None)`. A typed refusal replaces a crash; no caller passes `None` today (`board.revision` is `int`), so no test moves — state it in the commit rather than call it byte-identical |
| `_archive_conflict_sidecar` 1045 | `store_conflicts.archive_conflict_sidecar(sidecar, resolved_path, fallback={"card_id": card_id})` | FOLD — same read-or-fallback, `resolved_at` stamp, atomic write, unlink |
| `_guard_no_conflict` 907 | `store_conflicts.guard_no_conflict(path, f"card_conflict:{card.card_id}")` | FOLD |
| `_read_json` 1031 | `serde.read_json` — identical (`json.loads(path.read_text("utf-8"))`) | FOLD; the one production importer of `_read_json` retargets to `serde.read_json` |
| `_safe_text` 84 (limit 4000, `""` for empty) | `serde.safe_text` returns `None` for empty; `serde.safe_assignment_text` returns `""` but is the persona-row spelling (limit-first) | FOLD onto `serde.safe_assignment_text(value, limit=…)` — same strip-and-bound, same `""`; the fixture row `_safe_text: child_events, events, parity, running_work, snapshot/summaries` names the OTHER copies, which fold in their lanes |
| `_safe_labels` / `_safe_checklist` 96–124 | — | stay in `models.py`; board-only shapes |

## 4. Doors

`utils.atomic_json_write`, `hermes_time.now` (public). None private. No widening.

## 5. Dead code found while reading — three queue rows, all DECIDE, resolved here

| symbol | evidence (paste the grep in the closing commit) | verdict |
|---|---|---|
| `BoardStore.update_board` 242 | queue row (line 42): 0 hits; `git grep -n "\.update_board(" -- '*.py' ':!tests/'` → `hermes_cli/harness_parts/board.py:213` | **REFUTED** — live, untested (0 test files) → positive control §6.2; row deleted |
| `BoardStore.resolve_conflict` else-arm 706–721 (take = remote) | queue row (line 43); `resolve_conflict` has 17 production and 10 test hits | the arm is the REMOTE take; the lane greps `take="remote"` in `tests/agent_runtime/test_board_store.py` — if pinned, REFUTED; if not, untested live → control §6.3 |
| `BoardStore._rebalance_column` 853 | queue row (line 44): 0 hits; called at **847** inside `_allocate_order_key`'s `except ValueError` | **REFUTED** as dead (own-file call the census did not count); untested live → control §6.1 |

## 6. Positive controls (ruling Q6)

1. `_rebalance_column`: plant two adjacent cards whose keys have no midpoint (`board_order.allocate_between` raises `ValueError`), move a third between them → assert every card's key was rewritten AND `board.rebalanced` was emitted with `card_count`. Lands in the MOVE.
2. `update_board`: rename + column change with `expect_revision` → assert `revision` bumped and `board.updated` carries `change="title,columns"`; the stale case raises `StaleRevision`.
3. `resolve_conflict(take="remote")` with a sidecar carrying `remote_card` → the card is rewritten with `revision+1`; without one → the local card is archived with `reason="remote_removed"` and NO `board.card.archived` event (the `emit=False` arm — assert the event log holds exactly one `board.card.conflict_resolved`).

## 7. Commits and the MOVE hash proof (one MOVE, one CHANGE — program §3.1d)

1. **MOVE** `refactor(board_store): board_store.py → agent_runtime/board_store/ (BoardStore whole — Q8, one commit over the cap)` — spans byte-identical with the sha256 rows (`git show 28012c8f8a:agent_runtime/board_store.py | sed -n 'A,Bp' | sha256sum`); `__init__` re-exports; the three controls of §6 landed; `__layer__` per §1.
2. **CHANGE** `refactor(board_store): card_mechanics (CardOrdering, IdempotencyReceipts) + files lifted out of BoardStore; adopt verbs beside it; store_conflicts + store_events + serde folds` — §1 skeleton + §3, each fold's red pasted; `[ds-size]` −1 and every module 110–300 code lines.

## 8. Lane and what it must not touch

Exec lane 2B-A, third. Must not edit in parallel: `board_sync.py`, `board_models.py`, `board_order.py`, `default_scope.py`, `realm_revert.py`, `workspace_template.py`, `tools/board_tool.py`, `harness_parts/board.py` (importers through `__init__`); `realm_sync/`, `snapshot/` (batch-1 packages); `store/` is the SAME lane, landed the commit before.
