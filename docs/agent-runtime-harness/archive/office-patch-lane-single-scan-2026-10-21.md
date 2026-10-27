> **BUILT** — archived 2026-10-27 from `planned/` (lane w1027j-h-tri-b); landed: `a198b3fff5` (S1), `322c7055f7` (S2), `4cbb187f85` (S3), 2026-10-21.
> History, not truth: the domain docs and the queues hold what is current.

# Planned — one actor scan per office upsert: the patch lane reads the scan the write already took — 2026-10-21

**Owner domain:** the office and board ([06](../06-office-and-board.md) § The office store, § The patch lane).
**Status:** IMPLEMENTATION-READY (design lane w1021i-plans). One doc, no code.
**Measured / read:** 2026-10-21 against hermes `origin/main` d087df7035.

Row: `RT-OFFICE-PATCH-LANE-SCANS-EVERY-UPSERT` (runtime-queue § Fork-owned).

## 1. What is true today (file::symbol)

- `office_store/actor_writes.py::upsert_actor` runs, inside `office_lock`: `_guard_class_keyed_write`
  (skipped when `allow_class_key`, the furniture path — it otherwise calls
  `office_class_key_guard.class_key_collision`, which scans), `_guard_no_conflict`, the unaimed
  `_place_unaimed` (`position_policy(store.scan_actors(wsid))` — a second scan on the unaimed lane),
  the archive/tombstone fences, `_write_actor`, then `_emit_upserted` → `store._emit_actor_patch`.
- `office_store/patches.py::_emit_actor_patch` calls `store.scan_actors(actor.workspace_id)` a THIRD
  time, after the write, to decide patch-vs-refresh: `scan.unreadable` or `len(scan.actors) >
  MAX_OFFICE_ACTORS_PROJECTED` (200) → `emit_office_actor_refresh`, else `emit_office_actor_patch`.
  Its docstring names the cost and rejects a filename glob ("would count unparseable files as members").
- `office_store/store.py::scan_actors` is THE chokepoint: `files.read_actor_dir` (glob + JSON parse per
  file, unreadable counted by name, bounded by `MAX_UNREADABLE_ACTOR_FILE_NAMES`).
- **Measured** (`read_actor_dir`, this workstation, warm): 20 actors 3.7 ms · 50 actors 9.4 ms · 200 actors
  36.9 ms; a name glob is 0.3 / 0.7 / 1.0 ms. A generic desk write on a 50-desk floor pays 9.4 ms in the
  patch lane alone; a persona placement on the unaimed lane pays it three times (≈ 28 ms).

## 2. The question the row asks, answered

**Can the patch lane key its patch off the written actor instead of rescanning?** Not alone: the two
facts it needs — `unreadable` and the post-write count — are properties of the DIRECTORY, not of the
actor. What the written actor contributes is one row the scan would otherwise have to re-read. So:

`Decided (plan):` **one scan per upsert, taken once inside the lock and threaded to every consumer.**
The write path scans at most once (zero times for a furniture write that needs no fence and no
placement, IF the count can be answered without a scan — it cannot, see below), and the patch lane
reads that scan plus the written actor instead of scanning again.

`Decided (plan):` **the count stays exact.** A name glob (1 ms) answers "more than 200 files" but
cannot answer `unreadable`; the docstring's objection stands. The patch lane therefore keeps ONE scan
(the only one, on the furniture path) rather than a cheaper, wrong probe. The row's "still pays one
directory scan" becomes "pays exactly one, shared" — the saving is the second and third scan on the
persona/unaimed paths, and the patch lane's own scan on the furniture path is the one that remains.

`Decided (plan):` **no cross-call cache.** A per-workspace "last scan" memo keyed on the directory's
mtime is wrong on Windows (a rewrite of an existing file does not bump the directory mtime) and would
be a second write path for the one fact the lock serializes.

## 3. Stages

**S1 — `ActorScan.with_written(actor)`** (`office_store/models.py`): a pure method returning a new scan
whose `actors` has `actor` replacing (by `actor_key`) or appended, sorted by key as `scan_actors`
sorts, `unreadable` unchanged. Test (`tests/agent_runtime/office_store/test_actor_scan.py`): replace
keeps the count, append raises it by one, order is by key. Killing mutation: drop the replace arm →
"replace keeps the count" reds (count +1).

**S2 — one scan inside the lock** (`actor_writes.py::upsert_actor`). After `_guard_no_conflict`, take
`scan = store.scan_actors(wsid)` ONCE when any consumer needs it: the class-key guard (pass the scan
into `class_key_collision(store, wsid, payload, scan=scan)` — an additive keyword; the guard scans itself
only when `scan is None`), `_place_unaimed(..., scan)`, and `_emit_upserted(..., scan=scan)`. On the
furniture path (`allow_class_key` and no `position_policy`) the one scan is taken AFTER
`_write_actor`, so it already holds the written row; on the other paths the pre-write scan is
`with_written(actor)`-ed before the patch lane reads it. `_emit_actor_patch(store, actor, *, created,
correlation_id, scan=None)` scans only when handed none (every other caller — `restore_actor`,
`remove_actor`'s paths — is unchanged this cut and keeps passing none).
Test (`tests/agent_runtime/office_store/test_office_store_scan_count.py`, the p10-d counter widened):
patch `OfficeStore.scan_actors` with a counting wrapper; a persona upsert on the unaimed lane scans
ONCE; a furniture upsert scans ONCE; the emitted patch is `office_actor` on a 5-actor floor and
`refresh` on a 201-actor floor (the count seen through the threaded scan). Killing mutations: (a) have
`_emit_actor_patch` ignore `scan` and rescan → the "once" counts red at 2/3; (b) skip `with_written` →
a floor of exactly 200 actors plus the new one emits a patch instead of `refresh` → the 201 test reds.

**S3 — the receipt.** `_emit_actor_patch`'s docstring loses its "cost of the count itself" paragraph for
one sentence naming the shared scan; the office lane's performance ledger row (`07-observability` §
performance ledger, office upsert) gets the measured numbers above and the after-number from S2's
counter test run on the 50-actor fixture.

## 4. Out of scope

`remove_actor` / `restore_actor` / `archive.py`'s scans (each is one scan already); the realm-sync
reader of a peer's actor dir; any change to `read_actor_dir` or to `MAX_OFFICE_ACTORS_PROJECTED`.

## 5. Open rulings

None.
