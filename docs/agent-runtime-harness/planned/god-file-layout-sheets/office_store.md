# Layout sheet — `agent_runtime/office_store.py` (lane R1)

Base: `main` @ `bf4377f226` · 2,493 raw / 1,874 code / 23 top-level defs · longest `OfficeStore.upsert_actor` 249 (1211–1459, depth 3) · chains 0 · `str==` 1 · `isinstance` 6 · owner doc `docs/agent-runtime-harness/06-office-and-board.md`. 18 production importers, 15 of them taking only `OfficeStore` (plus `ActorScan`, `read_actor_dir`, and two private names `_read_json`, `_normalize_persona_id` from `scripts/office_actor_rekey_to_instance.py` and `office_sync`); 51 test files, 1 private pin. **No W0-G5 row and no dead-code row** — the cleanest of the ten; the work is the one floor row, the write path, and the two W0-G3 rows it shares with `board_store` (`_archive_conflict_sidecar`, `_check_revision`) plus the `_emit`/`_guard_no_conflict` pair program §4 already names.

**Package `agent_runtime/office_store/`** (named after the file — NOT the 09-21 `office/` name: 69 files spell `office_store`). The 09-21 R1 row (`store, actor_writes, adoption, conflicts, archive, patches`) stands and gains `models`, `normalize`, `files`, `surface_writes`, `reads`, `guards`.

## 1. Section map → target modules

| lines | what is there | → module | layer |
|---|---|---|---|
| 1–134, 135–416 | imports, `ARCHIVED_LEDGER_CAP` 66, `MAX_ITEMS_PER_ACTOR`, `MAX_FOLDERS`, `merge_archived_ledgers` 71 (a 12-line re-export of `sync_merge.merge_archived_ledgers` with a docstring — §5), `MAX_UNREADABLE_ACTOR_FILE_NAMES`, `UnreadableActorFiles` 135, `ActorScan` 204, `OUTCOME_OK`, `OfficeActorOutcome` 244 (the typed-outcome model rule 14 wants — already right), `ConflictScan` 378 | `office_store/models.py` (~250) | models |
| 475–654 | `_safe_actor_ref`, `_normalize_persona_id` 479, `_safe_folder`, `_safe_display_name`, `_assert_display_name_publishable` 494, `_canonical_actor_key` 506, `_item_point` 516, `_normalize_item` 537 (61), `_stamp_minted_kinds` 600, `_normalize_folders` 643 (depth 3) | `office_store/normalize.py` (~200) | policy |
| 417–474, 2440–2493 | `read_actor_dir` 417 (56); `_read_json` 2440, `_write_surface` 2446, `_write_actor` 2450, `_archive_conflict_sidecar` 2454, `_free_surface_archive_dir` 2470, `_check_revision` 2489 | `office_store/files.py` (~120) — **the ONE write path**: `git grep -n "atomic_json_write(" office_store.py` → 2447, 2451, 2466 (+ 2232 inside `_archive_actor_locked`, which moves to `archive.py` and calls `files.write_archived_actor` in the CHANGE, so rule 13 holds with four writers in one module) | stores |
| 655–689, 928–944, 1109–1151 | `OfficeStore.__init__`, `_emit` 661; `get_surface`, `surface_exists`, `list_workspaces`; `get_actor`, `actor_exists`, `scan_actors` 1118 | `office_store/store.py` (~120 after the CHANGE) — the class keeps every public method as a delegation | stores |
| 690–927, 2024–2040 | `_emit_actor_patch` 690 (111), `_emit_surface_patch` 802, `_emit_actor_remove_patch` 847, `_emit_conflict_resolved_patch` 882, `_emit_surface_refresh_patch` 2024 | `office_store/patches.py` (~250) — the five `state_patches.emit_office_*` callers (678–906, 2031: today lazy imports inside each method) | stores |
| 945–1108 | `ensure_surface` 945, `_refuse_unresolvable_workspace` 992, `_ensure_surface_locked` 1018, `update_surface` 1046 (60) | `office_store/surface_writes.py` (~150) | stores |
| 1152–1210, 1765–1903, 2273–2276 | `scan_conflicts` 1152 (56), `resolve_conflict` 1765 (136, depth 4), `_guard_no_conflict` 2273 | `office_store/conflicts.py` (~200) | stores |
| 1211–1595 | `upsert_actor` 1211 (249), `remove_actor` 1461 (78, depth 4), `restore_actor` 1540 (53) | `office_store/actor_writes.py` (~300) | stores |
| 1596–1764 | `adopt_remote_surface` 1596 (86), `adopt_remote_actor` 1683 (81) | `office_store/adoption.py` (~150) | stores |
| 1904–2272 | `workspace_resolves` 1904, `archive_orphaned_surface` 1925 (98), `_guard_surface_is_orphaned`, `_instance_bound_actor`, `archive_actors_for_instance` 2070 (90), `archived_actor_keys_for_instance` 2161 (53), `_archive_actor_locked` 2217 | `office_store/archive.py` (~300) | stores |
| 2277–2439 | `_guard_archived_actor` 2277 (50), `_guard_class_keyed_write` 2328, `_guard_class_keyed_adoption` 2370 (65) | `office_store/guards.py` (~140) | policy |

13 modules after the CHANGE; **after the MOVE `store.py` holds the whole `OfficeStore` class (655–2439, ~1,350 code) for exactly one commit** — the persona_assignments precedent. Edges: lanes → `store` → `files`/`normalize`/`guards`/`models` (down); `patches` → `state_patches` (a leaf outside the package). Two reaches to close: `_emit_actor_patch` 771 lazily imports `snapshot.MAX_OFFICE_ACTORS_PROJECTED` (stores → the builder; the snapshot sheet moves the constant to `office_models.py`, which this file imports at 44 — whichever lane lands first moves it, the sha256 table names the line); `persona_assignments.canonical_persona_instance_id` (508, 2061, lazy) lands on R1's `identity.py` leaf. `realm_sync` is named only in comments (59–60, 1126). No cycle.

## 2. W0-G5 ladder sites

None. Rule 14 is already met by `OfficeActorOutcome` (244–376: `archived`, `archive_failed`, `scan_unreadable`, `conflict_read`, `succeeded` constructors and `as_failure_row`) — the model the office RPC lane translates (serve_rpc sheet §2). The CHANGE adds nothing here; it names this module the reference for typed store outcomes the way `serve_rpc._METHODS` is the reference for routing.

## 3. W0-G7 floor row (1) and the decomposition

| row | lines / depth | phases (comment map) | after |
|---|---|---|---|
| `upsert_actor` 1211 | 249 / 3 | unaimed-lane refusal 1301 · refusal-vs-creation split 1316–1323 · class-key fence inside the lock 1328 · desk fence 1349 · tombstone fence (D1) 1360–1369 · existing-vs-live decision 1369 · surface creation under the lock 1423 · archived-key restore 1430 · patch emission from the written object 1440–1443 | `ActorUpsert.refuse_unaimed → fence (class key, desk, tombstone — three guards, one function each ≤ 40) → decide → write → emit`, the lock held across `fence → write` as today; `upsert_actor` ≤ 40 |

Depth-4 sites under 150: `remove_actor` 1461 (the archived-copy branch 1737-class nesting) and `resolve_conflict` 1765 — each loses a level when its `with office_lock` body becomes a `_*_locked` function, the pattern `_ensure_surface_locked` 1018 and `_archive_actor_locked` 2217 already use.

## 4. Helpers that unify

| here | duplicate of (fixture row) | authority |
|---|---|---|
| `_archive_conflict_sidecar` 2454 | `board_store._archive_conflict_sidecar` 1045 | new `agent_runtime/store_conflicts.py` (program §4: R1 creates) — `guard_no_conflict`, `archive_conflict_sidecar`, `check_revision` |
| `_check_revision` 2489 | `board_store._check_revision` 1074 | `store_conflicts.check_revision` |
| `_guard_no_conflict` 2273 | `board_store._guard_no_conflict` 907 | `store_conflicts.guard_no_conflict` |
| `_emit` 661 | `board_store._emit` 133, `dispatch_store._emit` 408 (program §4: `serve.py`'s `_emit` is a frame writer, NOT this) | new `agent_runtime/store_events.py::emit_store_event(log, event)` — R1 creates here; `board_store`/`dispatch_store` fold in their own R1 lanes |
| `_read_json` 2440 | `board_store` 1031, `mission_chat_steer` 350, `runtime_instances` 95, `serve_registry` 1067, `store` 65 (program §4, 6 copies) | `serde.read_json(path)` (new — `store_file_io.read_json_object` is the stricter, secure-path form and stays) |
| `merge_archived_ledgers` 71 | `sync_merge.merge_archived_ledgers` — a re-export with a docstring; `board_store.py:41` imports the original | callers (1663 in-file) use `sync_merge` directly; the wrapper is deleted in the CHANGE (a §5 row) |
| `_normalize_persona_id` 479 | `persona_assignments.identity.normalize_persona_id` 3424 — DIFFERENT contract (4 lines: strip + lower for an actor ref) | not folded; renamed `_normalize_actor_persona_ref` so the name arm never pairs them |

## 5. Dead code found while reading

| symbol | lines | evidence |
|---|---|---|
| `merge_archived_ledgers` 71 | 12 | a docstring-carrying alias of `sync_merge.merge_archived_ledgers`; `git grep -nw` → the def, one in-file call (1663), `board_store` uses the original; 4 test files name the symbol through either module. Row: delete the alias, retarget the call |
| `workspace_resolves` 1904 | 20 | 5 in-file references + `snapshot` (2 → `_offices_summary`), 3 tests — keep |
| `read_actor_dir` 417 | 56 | 4 production importers, 7 tests — keep (it is `files.py`'s public read) |

No queue row names this file today.

## 6. Doors

`hermes_time.now` 41, `utils.atomic_json_write` 42 (FIRST, public). W0-G6 private rows: none. No widening.

## 7. Commits

1. **MOVE** `refactor(office_store): office_store.py → agent_runtime/office_store/ (7 modules now, store class moved whole)` — spans byte-identical; `__init__` re-exports `OfficeStore`, `ActorScan`, `read_actor_dir`, `_read_json`, `_normalize_persona_id` (the last two private for one commit); `tests/agent_runtime/test_office_store.py` (2,095 lines) split along the seams; the 1 pin retargeted. **Mutation:** drop `read_actor_dir` from `__init__` → `office_sync`'s import reds on the first pull.
2. **CHANGE** `refactor(office_store): lanes by composition (ActorUpsert, adoption, conflicts, archive, surface); store_conflicts + store_events created; serde.read_json; merge_archived_ledgers alias deleted` — one floor row deleted; `[ds-size]` −1.

## 8. Lane and what it must not touch

R1, second of two (after `persona_assignments`, whose `identity.py` this lane's lazy imports land on). Must not edit in parallel: `board_store.py`, `dispatch_store.py`, `store.py` (R1's later files — they fold toward the owners this lane creates), `office_sync.py`, `office_class_key_guard.py`, `office_models.py` (the one-constant move is coordinated with the snapshot sheet), `serve_rpc.py`/`snapshot.py`/`realm_sync.py` (R3/R4 — importers through `__init__`), `scripts/office_actor_rekey_to_instance.py` (retarget-only, in the CHANGE).
