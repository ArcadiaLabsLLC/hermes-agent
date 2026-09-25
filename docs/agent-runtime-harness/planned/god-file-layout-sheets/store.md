# Layout sheet — `agent_runtime/store.py` (lane R1 · exec lane 2B-A)

Base: `main` @ `28012c8f8a` · 1,114 raw / 911 code / 28 top-level defs · longest `WorkspaceStore.delete` 124 · chains 0/0 · `str==` 4 · `isinstance` 4 · sha256 `70e42ce25af8bcfebc8f0896a8c63c0b3e4826a83c67cc56aa7e249ec182f305` · owner doc `docs/agent-runtime-harness/02-data-shapes-and-stores.md`. **34 production importers and 113 test files** — the most-spelled path in this batch — so the package MUST be named after the file and `__init__` must re-export every name below. Importers take `AgentStore`, `WorkspaceStore`, `RealmStore`, `RunStore`, `IncidentStore`, `TaskStore` (the `task_store_stub` re-export at line 209 — 6 production importers read it FROM HERE), `ACTIVE_RUN_STATES`, the ledger helpers (`skill_tombstoned`, `active_skill_tombstones`, `lift_deleted_workspace`, `prune_settled_ledger`, `ledger_time`, `workspace_lift_is_active`, `skill_tombstone_matches`), and one test imports `_write_model`.

**Package `agent_runtime/store/`.** No collision: `store_events.py`, `store_conflicts.py`, `store_file_io.py` are siblings, not children.

## 1. Skeleton (owner rulings 2026-09-25) — this text IS the package `__init__` map

```
agent_runtime/store/
  __init__.py     wiring  the map; re-exports every name in the header, incl. TaskStore (the task_store_stub alias)
  base.py         stores  the store's floor: read/write/list model files (the ONE model writer), the slug + display-name bounds, the active-pointer compare-and-set (apply / superseded / duplicate) + its paired scope patch, and the three thin stores over the files (AgentStore, RunStore, IncidentStore) with ACTIVE_RUN_STATES
  ledgers.py      policy  the realm ledger rules: skill tombstones, workspace lifts, prune_settled_ledger, ledger_time, the two caps, the two selection normalizers
  workspaces.py   stores  WorkspaceStore (create / save / set_active / add-remove agent / rename / archive / the delete cascade)
  realms.py       stores  RealmStore (create / save / archive / bind_server / the two selections / tombstone + restore / set_active)
```
Entry points and the modules an agent opens: `WorkspaceStore.set_active` (`scope_activation`, the CLI) → `workspaces.py` → `base.py` (CAS + pointer write + scope patch) — **2**; `WorkspaceStore.delete` → `workspaces.py` → `realms.py` (membership + ledger save) → `base.py` — 3 (plus `board_store`, an inbound package); `RealmStore.tombstone_skill` (`skills delete`) → `realms.py` → `ledgers.py` → `base.py` — 3; `AgentStore.save` (`ensure_persisted_personas`, `agent create`) → `base.py` — 1; the ledger questions (`realm_sync`, `realm_revert`, `default_scope`) → `ledgers.py` — 1. Layers: stores → policy (`ledgers`) → models; `base.py` imports nothing in the package.

### 1.1 Section map → target modules (sizes are raw / est. code; the 100/300/500 bars are on code lines)

| lines | what is there | → module | raw / code | layer |
|---|---|---|---|---|
| 1–33, 209 | imports, `T`, `from .task_store_stub import TaskStoreStub as TaskStore` | `store/__init__.py` (map; re-exports incl. `TaskStore`) | ~60 / 30 | wiring |
| 35, 48–79, 100–206, 212–230, 1101–1114 | `ACTIVE_RUN_STATES`; `_safe_display_name`, `_slugify`, `_dedupe_ids`, `_read_json`, `_read_model`, `_write_model` (the ONE model writer — rule 13); `_emit_active_scope_patch`, `_parse_intent_basis`, `_resolve_activation_write`, `_list_models`; `AgentStore`; `RunStore`, `IncidentStore` | `store/base.py` — imports `serde`, `paths`, `errors.NotFound`, `utils.atomic_json_write`, `hermes_time.now`; lazy `state_patches` | ~230 / 140 | stores |
| 81–97 | `_append_store_event` | folds onto `store_events.emit_store_event` (§3); no module | — | — |
| 36–45, 519–784 | `DELETED_WORKSPACE_LEDGER_CAP`, `SKILL_TOMBSTONE_LEDGER_CAP`; `_normalize_skill_selection`, `skill_tombstone_matches`, `_tombstone_blocks`, `active_skill_tombstones`, `prune_settled_ledger`, `_prune_skill_tombstones`, `workspace_lift_is_active`, `ledger_time`, `active_workspace_lifts`, `_prune_workspace_lifts`, `lift_deleted_workspace`, `skill_tombstoned`, `_normalize_agent_selection` | `store/ledgers.py` — pure over `models`; lazy `paths.safe_path_token` | ~280 / 170 | policy |
| 233–516 | `WorkspaceStore` (incl. `delete` 393–516) | `store/workspaces.py` — imports `realms` (module level; `delete` reads `RealmStore`), `base`, `ledgers._prune_workspace_lifts`; lazy `board_store`, `locks` | ~290 / 200 | stores |
| 787–1098 | `RealmStore` | `store/realms.py` — imports `ledgers`, `base`; lazy `profile_home`, `skill_promotion` (both fork) | ~315 / 230 | stores |

Refolded under the no-fragmentation ruling: the earlier draft's `files.py` (~55 code), `activation.py` (~60), `agents.py` (~20) and `historical.py` (~20) were each under the floor and share one role (the floor the two big stores stand on); they are `base.py`. Result: 4 modules + the map, every one 140–230 code lines. Edges: `workspaces` → `realms` → `ledgers`, `base` (down). **The cycle and who breaks it:** `base._emit_active_scope_patch` constructs `WorkspaceStore`/`RealmStore` (store.py:134–135) to re-read the two pointers, and both stores call `base` from `set_active` — for the MOVE the two constructions stay a function-local import (legal, lazy); in the CHANGE `base.py` breaks it for good by reading the two pointer files through its own `read_pointer(paths.active_*_path(), key)` — the SAME `_read_json(...).get(key)` read `active_id()` performs, so the on-disk pair the patch carries is unchanged and no store is constructed inside a store write. `state_patches` (lane 2B-A, lands first) stays a lazy import from `base.py`.

## 2. Routing sites (rule 12)

W0-G5 holds no row for this file (`str==` 4 are all guards). What the CHANGE converts:

| site (base line) | shape today | replacement | killing mutation |
|---|---|---|---|
| `_resolve_activation_write` 160–192 → `set_active` ×2 (307, 1077) | three free strings `"apply"` / `"superseded"` / `"duplicate"` returned, compared as `decision != "apply"`, and surfaced on the wire as `reason` (read by `scope_activation`) | constants `ACTIVATION_APPLY` / `ACTIVATION_SUPERSEDED` / `ACTIVATION_DUPLICATE` in `base.py`, compared by name in the ONE reader; **no Enum** — the words ride an RPC result and are spelled in `scope_activation` and the launcher, and W0-G5 arm (c) would red every one of them (fork-hygiene row, lane R4 2026-09-25) | make `_resolve_activation_write` answer `ACTIVATION_DUPLICATE` where it answers `ACTIVATION_SUPERSEDED` → the supersede control (§6.1) reds |
| `WorkspaceStore.set_active` 301–321 / `RealmStore.set_active` 1071–1091 | the same 20 lines with `workspace_id`/`realm_id`, the pointer path and the event name swapped | `base.apply_activation(pointer_path, key, value, *, name, event_type, event_log) -> dict`; the two methods become 4 lines each | swap the two `key` arguments → `test_store.py`'s `active_id` round-trip reds |
| `RealmStore.set_skill_selection` 891 (`mode not in {"all","selected"}`) | a hand-rolled guard beside `validate_agent_publish_mode` (models.py:711, over `REALM_AGENT_PUBLISH_MODES`) | `models.validate_skill_publish_mode` over a `REALM_SKILL_PUBLISH_MODES = ("all", "selected")` tuple — the agent twin's exact shape | drop `"selected"` from the tuple → `test_store.py`'s selection case reds |

## 3. Helper folds

| here | owner | verdict |
|---|---|---|
| `_append_store_event` 81 | `store_events.emit_store_event(event_log, type, payload, domain="store")` — identical body (drop `None` fields, append, warn-never-raise) | FOLD; the 21 call sites pass `payload` as a dict. Killing mutation: make the owner keep `None` fields → `test_store_events.py` reds |
| `_read_json` 66 | `serde.read_json` raises `FileNotFoundError`; this raises `errors.NotFound` | NOT a plain fold — keep a 3-line `base.read_model_json(path)` that maps the missing-file case to `NotFound` OVER `serde.read_json` (program §4 row satisfied without changing the exception every caller catches) |
| `_dedupe_ids` 57 | `serde.dedupe_tokens` uses `safe_optional_token` (no `:`), this uses `safe_id` (keeps `:` for profile-backed ids) | NOT a fold — a profile-backed persona id would be rewritten. Named |
| `_safe_display_name` 48 / `_slugify` 52 | `board_store._safe_title` (280 vs 160) | NOT a fold (different bounds are different contracts); a `serde.display_name(value, limit=)` owner is the CHANGE's option, not its requirement |
| `_tombstone_blocks` 583 | alias of `skill_tombstone_matches` | the two in-file uses spell the public name; alias deleted (§5) |
| `ledger_time` 663 | already the ONE owner (realm_sync folded onto it 2026-09-06) | `runtime_hud._age_phrase` re-parses ISO the same way (its sheet §4); if lane 2B-B lands `clock.parse_iso_utc` first, `ledger_time` becomes its alias — "tree wins" |

## 4. Doors

`utils.atomic_json_write`, `hermes_time.now` (public). W0-G6 private rows: none. No widening.

## 5. Dead code found while reading

| symbol | evidence (the lane re-runs the grep and pastes it) | verdict |
|---|---|---|
| `_tombstone_blocks` 583 | `git grep -nw _tombstone_blocks -- '*.py'` → own file only (2 uses) | DELETE the alias in the CHANGE; uses respelled |
| `active_workspace_lifts` 692 | dead-code queue row (line 23): 0 production, 1 test | TEST SEAM per the FORK-CODE verdict — moves to `tests/agent_runtime/_seams.py` with the MOVE; row deleted |
| `WorkspaceStore.add_agent` 355 | queue row (line 60) says 0 hits; `git grep -n "\.add_agent(" -- '*.py' ':!tests/'` → `hermes_cli/harness_parts/workspace_commands.py:237` | **REFUTED** — live (the census counted cross-file NAME matches only); row deleted with the closing commit named |
| `RunStore` / `IncidentStore` 1101–1114 | 7 / 5 production importers | live (historical readers) |

## 6. Positive controls (ruling Q6)

1. `_resolve_activation_write`: `git grep -n superseded -- 'tests/*.py'` found no pin in `test_store.py` or a `test_scope_activation*` file — land a control in the MOVE: `set_active(ws, issued_at=older)` after `set_active(ws2, issued_at=newer)` answers `applied: False, reason: "superseded"` and leaves the pointer; the same test with equal basis and equal target answers `duplicate`.
2. `WorkspaceStore.delete`'s unreadable-board refusal (445–455): confirm `test_store.py` plants an undecodable `board.json` and asserts `WorkspaceDeleteBlocked("workspace_boards_unreadable")` — if absent, land it before `delete` is touched.

## 7. Commits and the MOVE hash proof (one MOVE, one CHANGE — program §3.1d)

1. **MOVE** `refactor(store): store.py → agent_runtime/store/ (4 modules)` — spans byte-identical, one sha256 row per §1.1 range (`git show 28012c8f8a:agent_runtime/store.py | sed -n 'A,Bp' | sha256sum`); `__init__` re-exports every name in the header incl. `TaskStore`; `active_workspace_lifts` moved to the test seam; the two controls of §6 landed; `__layer__` per §1.
2. **CHANGE** `refactor(store): apply_activation + ACTIVATION_* constants; read_pointer breaks the store↔base cycle; emit_store_event fold; validate_skill_publish_mode; alias deleted` — §2 + §3 with each red pasted; `[ds-size]` −1.

## 8. Lane and what it must not touch

Exec lane 2B-A, second (after `state_patches`, before `board_store` — `workspaces.delete` lazily imports `BoardStore`, which keeps its path through `board_store/__init__`). Must not edit in parallel: `default_scope.py`, `scope_activation.py`, `realm_membership.py`, `persona_instance_identity.py`, `skill_promotion.py` (importers, all through `__init__`); `snapshot/`, `persona_assignments/`, `office_store/` (batch-1 packages).
