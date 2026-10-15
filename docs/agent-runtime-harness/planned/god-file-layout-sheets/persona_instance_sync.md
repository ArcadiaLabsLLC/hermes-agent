# Layout sheet — `agent_runtime/persona_instance_sync.py` (lane R4 · exec lane 2B-C)

Base: `main` @ `28012c8f8a` · 1,357 raw / 975 code / 28 top-level defs · longest `apply_persona_instance_pull` 273 (W0-G7 fixture row) · chains 0/0 · `str==` 3 · `isinstance` 16 · W0-G5 fixture row `_wire_value|isinstance|value` · sha256 `5376425b358f991c7f1503da43e64d96d1d9841167c506903fb6282149e054cb` · owner doc `docs/agent-runtime-harness/09-multi-device-runtime.md` (instance replication). 7 production importers (`realm_sync/{artifacts,drift,persona_artifacts,publish,pull}`, `realm_revert`, `persona_assignments/replicate`), 5 test files. Importers take `PROJECTION_RELATIVE_PATH`, `apply_persona_instance_pull`, `instance_baseline_key`, `persona_instance_def_hash`, `project_persona_instance(s)`, `read_remote_persona_instances`, `refuse_persona_instance`, `update_persona_instance_baseline_after_publish`; tests additionally pin the three key sets and `PERSONA_INSTANCE_NEVER_TRAVELS_KEYS` (the totality gate), `cleared_travel_value`, `instance_conflict_path`, `valid_persona_instance_id`, `REFUSAL_*`; one patches `apply_persona_instance_pull` on the module.

**Package `agent_runtime/persona_instance_sync/`** (a sibling of `realm_sync/`, which reaches it lazily from `pull.py` — the appliers stay outside the `realm_sync` package by the batch-1 sheet's rule).

## 1. Skeleton (owner rulings 2026-09-25) — this text IS the package `__init__` map

```
agent_runtime/persona_instance_sync/
  __init__.py     wiring  the map; re-exports the importer names + the test-pinned contract names
  contract.py     models  VOCABULARY/TABLE module (floor-exempt): the three key sets (+ NEVER_TRAVELS), cleared_travel_value, the projection document constants, the refusal codes, PersonaInstancePullSummary (the typed accounting a pull returns)
  projection.py   policy  the two pure halves — publish: PersonaInstanceProjection, the def hash, wire_value, project_persona_instance(s); pull admission: instance_relative_path, valid_persona_instance_id, refuse_persona_instance, read_projection_document
  sidecars.py     stores  the never-synced files: the baseline, the dropped-steering ledger, the conflict parking, update_persona_instance_baseline_after_publish; and read_remote_persona_instances (the pulled projection file)
  pull.py         lanes   apply_persona_instance_pull — the mint door — with its per-row helpers (local hash, archived keys, retire-follows-the-desk, the dropped-edge heal)
```
Entry points and the modules an agent opens: the pull (`realm_sync/pull.py`) → `pull.py` → `sidecars.py` (baseline, ledger, conflicts) and `projection.py` (admission, hash) — **3** (+ the `contract` table); the publish (`realm_sync/persona_artifacts.py`) → `projection.project_persona_instances` → `contract` — 2; the baseline update after publish (`realm_sync/publish.py`) → `sidecars.py` → `projection.py` (the hashes) — 2; the drift/revert readers (`realm_sync/drift`, `realm_revert`) → `sidecars.py` / `projection.py` — 1. Layers: `pull` (lanes) → `sidecars` (stores) → `projection` (policy) → `contract` (models); `pull` reaches `persona_assignments.PersonaInstanceStore` and `sync_merge` lazily; `projection` reaches `persona_assignments`, `persona_config_sync`, `sync_admission`, `paths` lazily.

### 1.1 Section map → target modules (sizes are raw / est. code; the 100/300/500 bars are on code lines)

| lines | what is there | → module | raw / code | layer |
|---|---|---|---|---|
| 1–63 | docstring, imports | `__init__.py` | ~70 / 15 | wiring |
| 65–234, 753–857 | `PROJECTION_KIND`, `PROJECTION_SCHEMA_VERSION`, `PROJECTION_RELATIVE_PATH`, the three key sets, `PERSONA_INSTANCE_NEVER_TRAVELS_KEYS`, `_TRAVEL_CLEARED_WITHOUT_DEFAULT`, `_dataclass_defaults`, `cleared_travel_value`, `REFUSAL_*`; `PersonaInstancePullSummary` | `persona_instance_sync/contract.py` (`models.PersonaInstance`, `dataclasses`) | ~280 / 140 | models |
| 239–604 | `PersonaInstanceProjection`, `persona_instance_def_hash`, `_wire_value`, `project_persona_instance`, `project_persona_instances`, `read_projection_document`, `instance_relative_path`, `valid_persona_instance_id`, `refuse_persona_instance` | `persona_instance_sync/projection.py` (`yaml`, `hashlib`, `json`; lazy `serde`, `persona_assignments`, `persona_config_sync`, `sync_admission`, `paths`) | ~370 / 230 | policy |
| 616–747, 860–887, 1325–1357 | `read_persona_instance_baseline`, `write_persona_instance_baseline`, `read_dropped_steering_ledger`, `write_dropped_steering_ledger`, `instance_baseline_key`, `instance_conflict_path`, `update_persona_instance_baseline_after_publish`; `read_remote_persona_instances`; `_write_conflict_sidecar` | `persona_instance_sync/sidecars.py` (`paths`, `utils.atomic_json_write`, `yaml`) | ~200 / 120 | stores |
| 890–1322 | `_refusal_row`, `_local_projection_hash`, `_locally_archived_actor_keys`, `_retire_replicas_for_removed_desks`, `_remote_body_without_edges`, `_healable_dropped_parents`, `apply_persona_instance_pull` | `persona_instance_sync/pull.py` (lazy `persona_assignments`, `office_store`, `sync_merge`, `paths`) | ~430 / 270 | lanes |

Result: 4 modules + the map, none over 270 code lines. Edges: all down. **The lazy cycle:** `realm_sync/pull.py` → this package (lazy) and `projection.py` → `persona_config_sync.find_nonportable_values` (lazy, a flat sibling that `realm_sync` also imports) — no module here imports `realm_sync`, so nothing closes a loop; `persona_assignments/replicate.py` imports `persona_instance_def_hash` at module level while `pull.py` imports `PersonaInstanceStore` lazily — stays lazy, and `projection.py` (which `replicate` reaches through `__init__`) imports `persona_assignments` only inside functions.

## 2. Routing sites (rule 12)

| site (base line) | fixture row | replacement | killing mutation |
|---|---|---|---|
| `_wire_value` 329–339 | `\|isinstance\|value` — datetime / scalar / list-tuple / dict / else-raise on one name | `functools.singledispatch` on the value: `wire_value.register(datetime)`, `(list, tuple)`, `dict`, the scalar registrations, and the default that raises `TypeError` — rule 12's strategy-by-type shape; NOT a fold onto `serde.to_jsonable` (which neither sorts dict keys nor refuses exotic types — determinism and the refusal are the point, the docstring at 321 says so) | register the `dict` handler as the list handler → `tests/agent_runtime/test_persona_instance_publish.py`'s deterministic-bytes case reds |
| `apply_persona_instance_pull` 1193–1259 | not a fixture row: seven `if decision.action == PullAction.X: … continue` guards on an EXISTING Enum from `sync_merge` — **invisible to W0-G5 (a)/(c)** (attribute compares, `return`/`continue`-terminated; the probe counts `chains 0/0`); the class is filed in the report | `_ROW_ACTIONS: Mapping[PullAction, Callable[[_RowContext], None]]` — `{NOOP: _row_converged, KEEP_LOCAL: _row_keep_or_heal, CONFLICT: _row_hold, ARCHIVE_LOCAL: _row_upstream_absent, WRITE_REMOTE: _row_write}` — the cleanest rule-12 conversion in this batch (the `realm_revert` `REVERT_ACTIONS` shape, program §3.2), and what takes the function under the floor (§3). The two `decision.reason` literals (`"archived_local"`, `"archive_vs_edit"`, `"converged"`) are named constants in `sync_merge` (their single producer) and compared by name here | swap the `NOOP` and `KEEP_LOCAL` handlers → `test_persona_instance_pull.py`'s converged and kept_local cases red |
| `refuse_persona_instance` 546–604 | seven ordered refusals | "Order is deliberate" (526) — guards; stays |
| `read_remote_persona_instances` 873–887 | absent / unreadable / projection | three typed sources; a boundary — stays |

`isinstance` 16 → ≤ 10 at review (the `singledispatch` retires five).

## 3. W0-G7 floor row (1)

| row | lines / depth | phases (from the comment map) | after |
|---|---|---|---|
| `apply_persona_instance_pull` 1050 | 273 / 3 | read + store 1093–1102 · §5.2 retire first 1104–1111 · the two early returns 1113–1129 · phase one 1147–1259 · phase two 1261–1318 · commit 1320–1321 | a `PullPass` object (the H4 `ServeSession` shape: the locals that every phase reads — `store`, `baseline`, `ledger`, `summary`, `archived_keys`, `written`, `heal_pending` — become fields): `.retire_removed_desks()`, `.phase_one()` iterating `_ROW_ACTIONS` (≤ 40 with the per-row context built by `_row_context(...)` ≤ 30), `.phase_two()` (≤ 60), `.commit()`; the verb ≤ 35 |

## 4. Helper folds

| here | owner / duplicate | verdict |
|---|---|---|
| `_write_conflict_sidecar` 1325 | fixture row (`flow_graph_sync`, `level_sync`, `map_sync`, `persona_instance_sync` — four copies: one atomic write of `{schema_version, realm_id, <key>, kind, local_hash, remote_hash, remote_body}`, errors swallowed) | this lane CREATES **`store_conflicts.park_conflict_sidecar(path, *, realm_id, key_field, key, kind, remote_body, local_hash, remote_hash)`** and folds its copy (payload keys preserved verbatim — `persona_instance_id`); the other three fold in their lanes. Killing mutation: drop `remote_body` from the parked payload → `test_persona_instance_pull.py`'s HOLD case reds |
| `_refusal_row` 890 | `sync_admission.Refusal(key, code, message).as_dict()` — the shared shape | FOLD (three call sites) |
| `read_persona_instance_baseline` / `write_*` 616/630 | `persona_config_sync`'s baseline pair (the docstring at 610: "the same two-halves shape") — two `{"schema_version": 1, "entries": {...}}` sidecars read and written the same way | fold candidate `realm_sync/sidecar.py::read_baseline(path) / write_baseline(path, entries)`; `persona_config_sync` is R4's next sheet (program §3.2) — named for that lane, "tree wins" |
| `_locally_archived_actor_keys` 918 | `OfficeStore.scan_conflicts`/`get_surface` readers | stays (the office ledger read through the office door — the docstring says why no second ledger) |

## 5. Doors

`yaml`, `utils.atomic_json_write` (public). W0-G6 private rows: none. No widening.

## 6. Positive controls (ruling Q6)

1. Before `_ROW_ACTIONS`: every `PullAction` arm pinned — `test_persona_instance_pull.py` has `replicated`, `adopted`, `converged`, `kept_local`, `held`, `upstream_absent`; the lane greps `desk_archived` and `steering_healed` and adds the missing ones (an unpinned arm is one a swap can silently move).
2. Before `singledispatch`: `test_persona_instance_publish.py` asserts a `datetime` travels as the ISO-`Z` string AND an exotic value (a `set`) is dropped with accounting — both, in one test.
3. The seam `setattr(persona_instance_sync, "apply_persona_instance_pull", …)`: its caller (`realm_sync/pull.py`) imports the name lazily inside the function, so the package attribute IS what it reads — no retarget; the lane verifies by reverting.

## 7. Dead code found while reading

None. `read_dropped_steering_ledger`/`write_*`, `instance_relative_path`, `REFUSAL_STEERING_SHAPE`, `valid_persona_instance_id` have 0 importers by name and an in-file caller each; the three key sets are the totality gate's fixture. No queue row names this file.

## 8. Commits and the MOVE hash proof (one MOVE, one CHANGE — program §3.1d)

1. **MOVE** `refactor(persona_instance_sync): persona_instance_sync.py → agent_runtime/persona_instance_sync/ (4 modules)` — spans byte-identical with one sha256 row per §1.1 range (`git show 28012c8f8a:agent_runtime/persona_instance_sync.py | sed -n 'A,Bp' | sha256sum`); `__init__` re-exports; controls §6; `__layer__` per §1.
2. **CHANGE** `refactor(persona_instance_sync): PullPass + _ROW_ACTIONS; wire_value singledispatch; store_conflicts.park_conflict_sidecar; Refusal fold` — reds pasted; both fixture rows deleted; `[ds-size]` −1.

## 9. Lane and what it must not touch

Exec lane 2B-C, third. Must not edit in parallel: `realm_sync/` (batch 1; reads through `__init__`), `realm_revert.py`, `persona_config_sync.py`, `flow_graph_sync.py`, `level_sync.py`, `map_sync.py` (their sidecar copies fold in THEIR lanes against the owner this lane creates), `persona_assignments/` (batch 1), `sync_merge.py` (except the three reason constants it gains, named in §2 — one-line additions the lane may make), `sync_admission.py`.
