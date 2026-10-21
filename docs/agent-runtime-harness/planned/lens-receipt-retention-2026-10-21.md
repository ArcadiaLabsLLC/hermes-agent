# Planned — Lens receipts: retention folds the ledger, the budget stays a fence — 2026-10-21

**Owner domain:** Lens (`eternia-lens-in-hermes.md` §3 retention; [p10-agent-2026-10-19.md](p10-agent-2026-10-19.md) §5 L2.1
receipts).
**Status:** IMPLEMENTATION-READY (design lane w1021i-plans). One doc, no code.
**Measured / read:** 2026-10-21 against hermes `origin/main` d087df7035.

Row: `RT-LENS-RECEIPT-RETENTION` (runtime-queue § Fork-owned).

## 1. What is true today (file::symbol)

- `lens/store.py`: `MAXIMUM_RECEIPTS = 50_000` ("refused past this many, never made room for by
  eviction (W13)"); `save_receipt` counts the table and raises `LensStoreError(RECEIPTS_FULL)` at the
  budget — on the exit door's write-before-the-turn, so at the budget `trigger.py::_forge` and
  `_settle` both fail for every Episode of every monitor: the forge thread logs the exception and the
  Episode stays owed (`needs_admission` true) forever.
- Readers of receipts: `has_receipt` (the once-only guard in `admit`), `receipts_today` (the
  `daily_turn_cap` per monitor per UTC day — `CAPPED_OUTCOMES`), `receipts(limit=32)` /
  `runtime.lens.receipts`, `snapshot_fold.lens_fold` (`last_receipt`), `runtime.lens.receipt
  {episode_id}` and `runtime.lens.artifact` (the Episode folder `HERMES_HOME/lens/episodes/<id>/`,
  `artifacts.episode_folder`).
- Retention exists for observations only: `lens/retention.py::apply_retention` (24 h raw → minute
  rollups, 7 d rollups), run by `poller.py::_retention` every `RETENTION_EVERY`. `episodes` has no
  retention either; `store.episodes(limit=256)` is the reader.
- The Episode row and its receipt are written in ONE transaction (`save_receipt(receipt,
  episode=…)`) and the receipt's PK is the Episode id; `admit` is reached only for Episodes in state
  `active` whose `turn_id` is unset (`needs_admission`), so deleting an OLD receipt cannot re-forge its
  Episode: the Episode's `turn_id` is the durable "settled" mark, the receipt is the ledger.

## 2. Decisions

- `Decided (plan):` **receipts age out by time, folded into a per-monitor daily rollup; the budget stays
  as a fence.** Retention: `RECEIPT_RETENTION = 30 d` (every reader above looks at "today" or the
  newest 32; thirty days keeps a month of `runtime.lens.receipts` history). A pass folds receipts
  older than the cutoff into `receipt_rollups (monitor_id, day_ms, outcome, count)` (so a monitor's
  "turns per day" survives the row), deletes the rows, and deletes each deleted Episode's artifact
  folder (`episode_folder(id)`, `shutil.rmtree`, ignore-missing). Episodes older than the cutoff whose
  state is not `active` go with them (same pass, same transaction).
- `Decided (plan):` **the fence becomes a receipt, not a refusal of the door.** `MAXIMUM_RECEIPTS`
  stays (a runaway monitor must not fill the disk between retention passes), but at the fence
  `save_receipt` runs `fold_receipts(now)` inline FIRST and refuses only if the table is still full
  afterwards — and a refusal there writes the Episode's `turn_id = "receipts_full"` with NO receipt row
  (through the same transaction path `_settle` uses), so the Episode is settled, never owed forever.
  `ReceiptOutcome` gains nothing; the Episode's turn_id sentinel is the typed mark, and a
  `lens.receipts_full {monitor_id}` log receipt names it.
- `Decided (plan):` **`receipts_today` reads live rows only.** A fold never moves a row younger than
  the cutoff, and the cutoff (30 d) is far past "today", so the daily cap needs no rollup read.
  `runtime.lens.receipts` gains `rollups: [{day, outcome, count}]` for the monitor when a `monitor_id` is
  given (additive key on the reply; the launcher ignores unknown keys).

## 3. Stages

**L1 — schema + fold** (`lens/store.py`, `lens/retention.py`). `_SCHEMA` gains `receipt_rollups`
(PK `(monitor_id, day_ms, outcome)`); `retention.py` gains `RECEIPT_RETENTION`, a `_FOLD_RECEIPTS`
statement (`INSERT … ON CONFLICT DO UPDATE SET count = count + excluded.count`, grouped by
`monitor_id, started_ms / 86400000 * 86400000, outcome`), `fold_receipts(store, now) ->
ReceiptFoldReceipt(receipts_folded, episodes_deleted, folders_removed)`, and `apply_retention` calls
it after the observation fold. Folder removal happens AFTER the transaction commits, over the ids the
transaction collected (`SELECT episode_id … WHERE started_ms < ?` first), so a crash between the two
leaves at worst an orphan folder, never a live receipt whose folder is gone; a later pass removes any
folder under `episodes_root()` whose id is no longer in `receipts` (a bounded sweep: 256 names per
pass).
Tests (`tests/agent_runtime/lens/test_lens_receipt_retention.py`): 40 receipts over 45 days, two
monitors, mixed outcomes → after one pass the rows younger than 30 d remain, the rollup counts equal
the folded rows per (monitor, day, outcome), settled Episodes older than 30 d are gone and `active`
ones are kept, the old Episodes' folders are gone; a second pass at the same instant moves nothing.
Killing mutations: (a) fold after delete → the rollup counts red (zero); (b) drop the `state != active`
filter → the "active kept" assertion reds.

**L2 — the fence** (`store.py::save_receipt`). At the budget: `fold_receipts(self, now)` inline (import
inside the method, as `poller._retention` does); still full → settle the Episode with
`turn_id = "receipts_full"` and return False with the log receipt. `trigger.py::_forge` / `_settle`
treat False as today ("nothing written") — no change there.
Test: fill to the budget with 30-day-old rows → the next `save_receipt` succeeds (the fold made room);
fill with young rows → it returns False, the Episode's row shows `turn_id = "receipts_full"`, `admit`
on the next tick does nothing (`needs_admission` false), and the log receipt is present. Killing
mutation: raise `RECEIPTS_FULL` as today → the "Episode settled" assertion reds (it stays owed).

**L3 — the wire** (`serve_rpc/lens.py::runtime.lens.receipts`): the `rollups` list when `monitor_id`
is given; `store.receipt_rollups(monitor_id)`. Test: the reply carries `rollups` for the folded days.
Killing mutation: drop the key → red. The launcher's Lens receipts panel may show the rollup line later
(launcher row `MC-LENS-RECEIPT-ROLLUPS`, filed by the landing commit; not needed for this row to close).

## 4. Out of scope

Observation / rollup retention windows (fixed by the Lens plan, "never shortened"); the Episode folder's
1 MiB artifact cap; a per-monitor retention knob (the manifest has none; add one only when an operator
asks).

## 5. Open rulings

None. (`RECEIPT_RETENTION = 30 d` is a plan default the owner may move; nothing in the stages depends
on the number.)
