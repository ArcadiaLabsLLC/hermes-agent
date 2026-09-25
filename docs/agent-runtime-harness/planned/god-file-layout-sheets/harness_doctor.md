# Layout sheet — `agent_runtime/harness_doctor.py` (lane R3 · exec lane 2B-C)

Base: `main` @ `28012c8f8a` · 1,262 raw / 831 code / 21 top-level defs · longest `_placement_census_report` 255 (W0-G7 fixture row), `run_harness_doctor` 161 (fixture row) · chains 2/0 · `str==` 5 · `isinstance` 8 · sha256 `993f04c49b9bb0a5bfd47f27f2ca0c4ba39cc957fa01cf2f52885785c2634da7` · owner doc `docs/agent-runtime-harness/08-operations.md` (`harness doctor`). 2 production importers (`harness_parts/doctor_commands`, `harness_parts/parser/machine`), 5 test files. Importers take `run_harness_doctor`, `doctor_detail_sources`, `DEFAULT_WORKTREE_MIN_AGE_SECONDS`; tests import `_census_join_workspace`, `_census_live_actor_bindings`, `_census_duplicate_placements`, `_duplicate_placement_reason`, `ORPHAN_ACTOR_*`, `DoctorSection`, `DOCTOR_SECTIONS`, `HEALTH_*`.

**Package `agent_runtime/harness_doctor/`.**

## 1. Skeleton (owner rulings 2026-09-25) — this text IS the package `__init__` map

```
agent_runtime/harness_doctor/
  __init__.py   wiring  the map (+ the payload schema history 1–10, relocated from run_harness_doctor's body); re-exports the header names and the test-pinned census functions
  run.py        wiring  the section model (HEALTH_* vocabulary, DoctorSection, the probe context, the payload publish helpers), run_harness_doctor — the runner that spends the table — and DOCTOR_SECTIONS, THE table
  probes.py     lanes   the six one-question probes: orphan worktrees, snapshot null-id rows, event log, model authority, persona binding, root-config misplacement
  census.py     lanes   the roster/office join: the three orphan reasons + the three duplicate reasons (pure classifiers), the per-workspace sweeps, _placement_census_report
```
Entry points and the modules an agent opens: `harness doctor` (`doctor_commands`) → `run.py` → `probes.py` or `census.py` — **2**; a test asking one section its question → `probes.py` / `census.py` — 1 (the probes take a context or `None`, which is why they stay bare seams). Layers: `run` (wiring) → `probes`, `census` (lanes); `run` imports `snapshot.build_snapshot` (wiring → wiring) and injects it through the context so no probe imports `snapshot`; `census` reaches `office_store`, `persona_assignments` lazily; `probes` reaches `config`, `persona_profile_binding`, `delivery_directive`, `events` lazily or at call time.

### 1.1 Section map → target modules (sizes are raw / est. code; the 100/300/500 bars are on code lines)

| lines | what is there | → module | raw / code | layer |
|---|---|---|---|---|
| 1–10, 218–269 | imports; the 52-line schema-history comment inside `run_harness_doctor` | `__init__.py` (the history becomes the docstring's "payload schema" section — rule 7 / Q3; it is a HISTORY, the docstring at 235 says so) | ~80 / 20 | wiring |
| 13–134, 137–297 (minus 218–269), 1189–1262 | `DEFAULT_WORKTREE_MIN_AGE_SECONDS`, `HEALTH_*`, `_error_text`, `_DoctorProbeContext`, `DoctorSection`, `_payload_at`, `_publish_at`, `doctor_detail_sources`; `run_harness_doctor`; `DOCTOR_SECTIONS` | `harness_doctor/run.py` (`hermes_time.now`, `events.EventLog`, `snapshot.build_snapshot`; imports `probes`, `census` for the table's `probe=` fields) | ~330 / 180 | wiring |
| 300–548 | `_worktree_report`, `_event_log_report`, `_persona_binding_report`, `_root_config_misplacement_report`, `_model_authority_report`, `_snapshot_null_id_report` | `harness_doctor/probes.py` (`delivery_directive.reap_orphan_worktrees`, `events.event_log_health`; lazy `persona_profile_binding`, `config`) | ~250 / 170 | lanes |
| 551–1187 | the D1/D8 preamble, `_census_instance_key`, `_census_unknown`, `ORPHAN_ACTOR_*` + `ORPHAN_ACTOR_REASONS`, `_orphan_actor_reason`, `DUPLICATE_PLACEMENT_*`, `_duplicate_placement_reason`, `_census_live_actor_bindings`, `_census_join_workspace`, `_census_duplicate_placements`, `_placement_census_report` (+ `_retire_receipt_for`) | `harness_doctor/census.py` (lazy `office_store`, `persona_assignments`) | ~640 / 360 | lanes |

Result: 3 modules + the map; `census.py` at 360 code lines is over the 300 target and under the 500 cap — one concept (the join and its two classifiers), kept whole rather than split into a ~90-code `census_rules.py` that would be under the floor; the CHANGE's phase split of `_placement_census_report` does not grow it. Edges: `run` → `probes`, `census` (down: wiring → lanes); neither probe module imports `run` — the `DoctorSection` type the tests construct is re-exported from `__init__`. **The cycle and who breaks it:** `DOCTOR_SECTIONS` names every probe, so the table cannot live below the probes; it lives in `run.py` with the runner, which is the only module that imports both. No lazy cycle: `config` (lane 2B-C, lands first) never imports this package.

## 2. Routing sites (rule 12)

| site (base line) | shape | verdict |
|---|---|---|
| `DOCTOR_SECTIONS` 1196 + `run_harness_doctor` 186–295 | already the table: one declaration, four derived rosters | **the batch's second exemplar of rule 12** (with `mission_chat_turns.states`); moved, not touched |
| `_model_authority_report` 477–482 | `override.get("model_state") == "shadowing"` / `"redundant"` — literals of a vocabulary `config._override_state` returns | the constants `config.loader.OVERRIDE_STATE_*` (lane 2B-C's `config` sheet §2, lands first) are imported and compared by name; no Enum (fork-hygiene row, lane R4) | swap the two notices' conditions → `test_harness_doctor.py`'s model-authority case reds (control §6.1 confirms both states are fixtured) |
| `_placement_census_report` 1117–1132 | health verdict: defect / notice / ok over four predicates | ordered guards; stays (the comment at 1119 IS the argument) |
| `_orphan_actor_reason` 717–725, `_duplicate_placement_reason` 787–791 | pure classifiers, three ordered arms each | "THE ORDER IS THE DESIGN" (784) — guards; stay. Their outputs are tokens the launcher reads by string, so no Enum |

`str==` 5 → 3 at review; `isinstance` 8 unchanged (all shape checks over a foreign payload).

## 3. W0-G7 floor rows (2)

| row | lines / depth | phases (from the comment map) | after |
|---|---|---|---|
| `_placement_census_report` 932 | 255 / 2 | read both stores + the unreadable gate 989–1035 · the retired-set read + receipt memo 1043–1064 · the per-workspace sweep loop 1066–1090 · the unplaced fold 1092–1110 · verdict 1112–1132 · the report literal with its 20-line remediation string 1133–1185 | `_census_world() -> CensusWorld \| unknown-report` (≤ 60), `_census_sweeps(world) -> (placed, orphans, duplicates, per_workspace, referenced)` (≤ 45), `_census_unplaced(world, referenced, per_workspace)` (≤ 25), `_census_health(...)` (≤ 20); the remediation string becomes the module constant `CENSUS_REMEDIATION`; the verb ≤ 40 |
| `run_harness_doctor` 137 | 161 / 2 | context 176–184 · reports + health 186–190 · counts 197–205 · verdict + repairs 206–216 · the payload literal 217–291 (52 of them the schema comment) · publish 292–296 | the schema comment relocates (§1.1); `_finding_counts(reports, section_health)` (≤ 15) and `_publish_reports(payload, reports)` (≤ 8) lift out; the verb ≤ 80 |

## 4. Helper folds

| here | owner / duplicate | verdict |
|---|---|---|
| `_error_text` 30 | `f"{type(exc).__name__}: {exc}"[:limit]` — the same expression in `persona_instance_sync._refusal_row`'s callers, `agent_chat_dispatch._run_remote_dispatch` (×5), `running_work`, … | fold candidate `errors.error_text(exc, *, limit=320)` — `agent_runtime/errors.py` is the typed-error owner and a leaf; created by the first lane that lands ("tree wins"), this sheet does not require it |
| `_census_unknown` 603 | — | stays (the census's own "unexamined" shape) |
| `_payload_at` / `_publish_at` 104/112 | — | stay (two dotted-path helpers with one reader each) |

## 5. Doors

`hermes_time.now` (public). `.snapshot.build_snapshot` — a `wiring` package imported by a `wiring` module (same layer; legal) and injected, so the probes never see it. W0-G6 private rows: none. No widening.

## 6. Positive controls (ruling Q6)

1. Before the `OVERRIDE_STATE_*` respelling: `test_harness_doctor.py` fixtures BOTH `shadowing` and `redundant` — grep; add the missing one.
2. Before the `_placement_census_report` phase split: the four verdict arms are pinned — an orphan (`defect`), an unplaced row alone (`notice`), a `cross_instance` duplicate alone (`notice`), a `same_instance` duplicate (`defect`), and a short world (`unknown` with `None` counts). `test_harness_doctor.py` is 1,500+ lines and likely holds all five; the lane greps each token and adds what is missing before the split.
3. `ORPHAN_ACTOR_REASONS` (§7): if kept, one assertion `reason in ORPHAN_ACTOR_REASONS` over every orphan row of a fixture — the only reader that makes the tuple a contract.

## 7. Dead code found while reading

| symbol | evidence | verdict |
|---|---|---|
| `ORPHAN_ACTOR_REASONS` 683 | dead-code queue row (line 24, DECIDE): 0 production, 1 test; the report cites the three members individually | the row's own rule answers it: the report cites members by string → TEST SEAM → DELETE the tuple in the MOVE and let the test read the three names (default), OR keep it with control §6.3 as its reader. The lane picks by the grep; the row closes either way |
| `DUPLICATE_PLACEMENT_CROSS_INSTANCE` / `_UNBOUND_HOLDER` | 0 importers; produced by `_duplicate_placement_reason` and read by the launcher as wire tokens | live |
| `doctor_detail_sources` 123 | 1 production reader (the CLI printer), 2 tests | live |

## 8. Commits and the MOVE hash proof (one MOVE, one CHANGE — program §3.1d)

1. **MOVE** `refactor(harness_doctor): harness_doctor.py → agent_runtime/harness_doctor/ (3 modules); schema history to the map` — spans byte-identical with one sha256 row per §1.1 range (`git show 28012c8f8a:agent_runtime/harness_doctor.py | sed -n 'A,Bp' | sha256sum`; the 218–269 comment is the one span that moves to a docstring, and it is prose — its own row states "relocated, not code"); `__init__` re-exports; controls §6; `__layer__` per §1.
2. **CHANGE** `refactor(harness_doctor): _placement_census_report and run_harness_doctor as phases; CENSUS_REMEDIATION; OVERRIDE_STATE_* by name` — reds pasted; both W0-G7 fixture rows deleted; `[ds-size]` −1.

## 9. Lane and what it must not touch

Exec lane 2B-C, second (after `config` — it imports `OVERRIDE_STATE_*` from it in the CHANGE). Must not edit in parallel: `harness_parts/doctor_commands.py`, `harness_parts/parser/machine.py` (importers through `__init__`); `office_store/`, `persona_assignments/`, `snapshot/` (batch-1 packages); `delivery_directive.py`, `persona_profile_binding.py`, `events.py`.
