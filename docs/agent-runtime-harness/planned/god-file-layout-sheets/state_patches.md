# Layout sheet — `agent_runtime/state_patches.py` (lane R1 · exec lane 2B-A)

Base: `main` @ `28012c8f8a` · 1,439 raw / 1,023 code / 27 top-level defs · longest `build_state_patch` 82 · chains 0/0 · `str==` 0 · `isinstance` 5 · sha256 `2a121504d135d92254f60743db28d678247ee553ba9f95eaf07b7cb552f5bdd3` · owner doc `docs/agent-runtime-harness/03-transport-and-wire.md` (the patch lane). 16 production importers (`office_store/{patches,store}`, `persona_assignments/{chat_binding,replicate,retire,store}`, `serve_rpc/params`, `serve_office_subscriptions`, `patch_coverage`, `stream`, `stream_resume`, `chat_turn`, `store`, `gateway_commands`, the stream-fixture generator), 23 test files. Every importer takes a public name (13 distinct: the nine `emit_*`, `delta_patches_enabled`, `normalize_correlation_id`, `CORRELATION_ID_KEY`, `STATE_PATCHED_EVENT_TYPE`); no private name crosses the file.

**Package `agent_runtime/state_patches/`** (named after the file — the H3/H4 precedent; every `from .state_patches import X` resolves through `__init__`).

## 1. Skeleton (owner rulings 2026-09-25: readability first; modules 100–300 code lines, floor 100 unless vocabulary/table, cap 500; no flow over three modules) — this text IS the package `__init__` map

```
agent_runtime/state_patches/
  __init__.py          wiring  the map; re-exports the 13 importer names + the entity/op constants
  models.py            models  VOCABULARY/TABLE module (floor-exempt): ops, entities, the size budget, the store→wire field table, the correlation-id grammar
  payload.py           policy  build_state_patch (the 4 KB shrink ladder), normalize_correlation_id, the office id scheme + its inverse (office_patch_scope)
  emit.py              stores  the flag (delta_patches_enabled + the ROOT-config fault probe), emit_state_patch — the ONE EventLog.append — and emit_scope_patch, the one entity with no projection
  persona_instance.py  lanes   the persona-instance projections + the three emitters (patch / create / remove)
  office.py            lanes   the office projections + the six emitters (actor / conflict / surface × upsert / remove / refresh)
```
Entry points and the modules an agent opens to follow each: an `emit_office_*` / `emit_persona_instance_*` call (every store chokepoint) → `office.py` or `persona_instance.py` → `emit.py` → `payload.py` — **3** (`models` is the table they read); `emit_scope_patch` (`store.set_active`) → `emit.py` → `payload.py` — 2; `normalize_correlation_id` (`serve_rpc/params`) and `office_patch_scope` (`serve_office_subscriptions`) → `payload.py` — 1; `delta_patches_enabled` (`stream`, `patch_coverage`) → `emit.py` — 1. Layers go DOWN only: lanes → emit → payload → models.

### 1.1 Section map → target modules (line ranges are the base file's; layers derived from what each module imports, lazy included; sizes are raw lines with the code estimate — the 100/300/500 bars are on code lines)

| lines | what is there | → module | raw / code | layer |
|---|---|---|---|---|
| 1–68, 70–85 | module docstring, imports, `logger` | `state_patches/__init__.py` | ~90 / 20 | wiring |
| 87–229, 946, 1062–1097, 1206–1215 | `_UNRESOLVED`, `STATE_PATCHED_EVENT_TYPE`, `PATCH_OP_*`, `FOLDABLE_PATCH_OPS`, `PERSONA_INSTANCE_ENTITY`, `SCOPE_ENTITY`, `SCOPE_PATCH_ID`, `SCOPE_PATCH_FIELDS`, `PATCH_ENVELOPE_HEADROOM_BYTES`, `PATCH_VALUE_BUDGET_BYTES`, `_PERSONA_INSTANCE_STORE_TO_WIRE`, `CORRELATION_ID_KEY` / `_MAX_LEN` / `_CORRELATION_ID_RE`; `OFFICE_ACTOR_ENTITY`, `OFFICE_SURFACE_ENTITY`, `OFFICE_CONFLICT_ENTITY`, `OFFICE_SURFACE_PATCH_FIELDS` | `state_patches/models.py` — imports `events.EVENT_PAYLOAD_LIMIT_BYTES` only (the budget is derived from the cap at module scope); vocabulary/table module | ~230 / 80 | models |
| 232–376, 949–964, 1144–1203 | `normalize_correlation_id`, `_value_bytes`, `_oversize_marker`, `_is_oversize_marker`, `_assemble`, `build_state_patch`; `office_actor_patch_id`; `office_patch_scope` | `state_patches/payload.py` — pure; imports `models`, `serde.to_jsonable` | ~260 / 130 | policy |
| 379–541, 1381–1426 | `_root_config_fault`, `delta_patches_enabled`, `emit_state_patch`, `emit_scope_patch` | `state_patches/emit.py` — imports `payload`, `config` (module level, as today at 79), `parse_cache` (lazy), `runtime_config`, `events.EventLog`, `models.Event` | ~220 / 120 | stores |
| 547–820 | `project_persona_instance_wire_fields`, `_persona_instance_wire_row`, `_resolve_persona_for`, `emit_persona_instance_patch`, `project_persona_instance_full_wire_row`, `emit_persona_instance_create`, `emit_persona_instance_remove` | `state_patches/persona_instance.py` — lazy reaches into `persona_assignments` (stores), `store.AgentStore`, `agent_create_phases` | ~280 / 150 | lanes |
| 823–1141, 1218–1378 | `project_office_actor_wire_row`, `_office_actor_unpublished`, `emit_office_actor_patch`, `emit_office_actor_remove`, `emit_office_conflict_resolved_patch`, `emit_office_surface_patch`, `emit_office_surface_refresh`, `emit_office_actor_refresh` | `state_patches/office.py` — lazy reaches `snapshot.offices.office_actor_summary_row` (**import the `stores` submodule, never `snapshot/__init__`, which declares `wiring`** — a lanes→wiring edge reds W0-G6), `office_models`, `office_sync`, `store.WorkspaceStore` | ~360 / 190 | lanes |
| 886–945, 1429–1438 | the 60-line record of the retired `snapshot.json` boot-paint lane; the S54/S66 removal notes | relocate to the package `__init__` docstring's "history" section (rule 7 / Q3) — no module | — | — |

Refolded under the no-fragmentation ruling: the earlier draft's `gate.py` (~70 code) and `scope.py` (~30 code) were both under the 100 floor and only make sense beside the writer; they are `emit.py`. Result after the MOVE: 6 modules, every non-vocabulary module 120–190 code lines. Edges: `office`/`persona_instance` → `emit` → `payload` → `models` (all down). **The cycle and who breaks it:** `store.py` lazily imports `emit_scope_patch` (store.py:130) while `persona_instance.py`/`office.py` lazily import `store` back — both stay lazy and legal; `__init__` must NOT import `store`, and `emit.py` imports nothing above `config`, so no module in the package can close the loop. `config.py` is not an importer (its `ROOT_ONLY_CONFIG_KEYS` names this module as a STRING).

## 2. Routing sites (rule 12) — none on the W0-G5 fixture; what the CHANGE does and does not convert

| site (base line) | shape | verdict |
|---|---|---|
| `office_patch_scope` 1196–1202 | two arms on the entity vocabulary (`in (OFFICE_ACTOR_ENTITY, OFFICE_CONFLICT_ENTITY)` / `== OFFICE_SURFACE_ENTITY`) | below the gate's threshold; **NOT enum-ized** — `office_actor`/`office_surface`/`office_conflict`/`persona_instance`/`scope` are spelled fork-wide (`patch_coverage`, `serve_office_subscriptions`, the launcher's `_entitySection` table) and W0-G5 arm (c) reads every `Final`/`StrEnum` member as a routed word (fork-hygiene row 2026-09-25, lane R4). The constants stay plain module constants in `models.py`; the CHANGE writes the scope rule as `_SCOPE_BY_ENTITY: Mapping[str, Callable[[str], str \| None]]` keyed by those constants, read by `office_patch_scope` alone. Killing mutation: swap the actor and surface handlers → `tests/agent_runtime/test_office_state_patches.py`'s scope case reds (4 test files pin `office_patch_scope`) |
| `build_state_patch` 345–357 | `op != PATCH_OP_UPSERT` guard + degrade | a GUARD; stays |
| `_PERSONA_INSTANCE_STORE_TO_WIRE` 157 | already the table (store field → wire fields) | the package's exemplar of rule 12; moved, not touched |

`str==` 0 and `isinstance` 5 (all boundary checks) — no density goal.

## 3. Helper folds

| here | owner / duplicate | verdict |
|---|---|---|
| `_value_bytes` 258 | `events.EventLog.append`'s own measure (events.py:152, `json.dumps(to_jsonable(p), ensure_ascii=False).encode("utf-8")`) | FOLD: `events.payload_bytes(value)` created by this lane (the cap and its ruler in one file); `EventLog.append` reads it — killing mutation: make it measure `ensure_ascii=True` → `test_state_patches.py`'s 4 KB boundary case reds |
| `_resolve_persona_for` 627 | `snapshot`'s `personas_by_id.get(persona_id)` | NOT a fold — this one is read-only by contract (never seeds); the docstring says why. Named so nobody folds it toward `ensure_persisted_personas` |
| `_office_actor_unpublished` 853 | `snapshot._offices_summary`'s `_actor_unpublished` closure (now `snapshot/offices.py`) | NOT a fold — one is a closure over a prebuilt workspace→realm map, this one reads the store per call; folding would change the archived-workspace answer's cost, not its value. Named |
| `_assemble` 277 | — | stays; the one payload constructor |

## 4. Doors

`hermes_time.now` (public). W0-G6 private rows for this file: none. No widening.

## 5. Dead code found while reading

| symbol | evidence | verdict |
|---|---|---|
| comments 886–945, 1429–1438 | 70 raw lines describing lanes that no longer exist | relocate (rule 7), not delete — the `__init__` history section |
| `SCOPE_PATCH_FIELDS` 142, `OFFICE_SURFACE_PATCH_FIELDS` 1215, `PATCH_VALUE_BUDGET_BYTES` 149 | `git grep -nw <name> -- '*.py' ':!agent_runtime/state_patches.py'` → 0 production, 1–2 tests each; each is read in-file or pinned by the launcher mirror | KEEP (contract constants); no row |
| `FOLDABLE_PATCH_OPS` 102 | 1 production reader (`patch_coverage`) | live |

Nothing else: every def has a production or in-file caller (`git grep -nw` per name, run by the lane and pasted in the MOVE body).

## 6. Positive controls to land BEFORE any table replaces a routing site (ruling Q6)

1. **The monkeypatch retarget IS the MOVE's killing mutation.** 14 test sites `setattr(sp, "load_root_runtime_config", …)` and 2 sites `setattr(sp, "project_office_actor_wire_row", …)` patch the FILE's namespace; after the MOVE the names are bound in `emit.py` / `office.py` and a patch on the package no longer reaches them. Retarget to `state_patches.emit` / `state_patches.office`; control = revert ONE retarget → that test reds (the fake config never reaches `delta_patches_enabled`). Paste the red in the MOVE body.
2. `office_patch_scope`: assert a `persona_instance` row answers `None` AND an `office_conflict` row answers its workspace (both arms, the same test) before the `_SCOPE_BY_ENTITY` table lands.

## 7. Commits and the MOVE hash proof (one MOVE, one CHANGE — the exec-lane contract in program §3.1d)

1. **MOVE** `refactor(state_patches): state_patches.py → agent_runtime/state_patches/ (6 modules)` — spans byte-identical; per module `git show 28012c8f8a:agent_runtime/state_patches.py \| sed -n 'A,Bp' \| sha256sum` vs the new module's span, one row per range in §1.1, pasted in the body; `__init__` re-exports the 13 importer names + every `*_ENTITY` / `PATCH_OP_*` constant; the 16 monkeypatch sites retargeted (§6.1); `__layer__` declared per §1.
2. **CHANGE** `refactor(state_patches): _SCOPE_BY_ENTITY; events.payload_bytes; history relocated` — §2 + §3 with each red pasted; `[ds-size]` −1 (1,023 → 0 units over).

## 8. Lane and what it must not touch

Exec lane 2B-A (with `store`, `board_store`, `dispatch_store`), FIRST of the four: `store.py` imports it lazily and lands second. Must not edit in parallel: `office_store/`, `persona_assignments/`, `serve_rpc/`, `snapshot/` (batch-1 packages — retarget-only, through their submodules); `patch_coverage.py`, `stream.py` (R3 files; they keep importing through `__init__`).
