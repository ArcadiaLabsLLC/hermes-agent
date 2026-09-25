# Layout sheet — `agent_runtime/persona_assignments.py` (lane R1)

Base: `main` @ `bf4377f226` · 4,053 raw / 3,172 code / 56 top-level defs · longest `PersonaInstanceStore.open_chat` 203 (2258–2460) · chains 0 · `str==` 6 · `isinstance` 2 · owner doc `docs/agent-runtime-harness/02-runtime-data-and-shapes.md` (persona instances) and `05-chat-turn-lane.md` (the chat binding). **The most-imported file in Wave 2: 60 production importers, 72 test files**, most of them taking the module-level identity helpers (`canonical_persona_instance_id`, `persona_instance_display_name`, `normalize_persona_id`, `safe_assignment_token` ×29, `safe_assignment_text` ×30) rather than the store. `PersonaInstanceStore` (480–2845) is 2,366 raw lines in one class.

**Package `agent_runtime/persona_assignments/`** — named after the file, NOT the 09-21 `persona_instances/` name: 132 files spell the path, and the H3/H4 precedent (package = old module name, `__init__` = public names) keeps every one of them green through the MOVE. The 09-21 R1 row's six lanes (`store, steering, retire, chat_binding, repair, replicate`) stand; this sheet adds `identity`, `summary`, `scan`, `profile` and `assignments`.

## 1. Section map → target modules

| lines | what is there | → module | layer |
|---|---|---|---|
| 1–72, 238–251 | imports; `TERMINAL_ASSIGNMENT_STATES` 44, `_CHAT_MODES` 48, `_BINDING_REPAIR_REASON` 51, `CHAT_BINDING_CLEARED_REASON_DELETED` 52, `PERSONA_ROWS_UNREADABLE` 58, `ACTIVE_ASSIGNMENT_STATES` 238 | `persona_assignments/vocabulary.py` (~50) — with the ladder's owner in `states.py` (§2) | models |
| 73–237 | `_note_unreadable_instance_row` 73, `reset_unreadable_instance_rows` 89, `PersonaInstanceScan` 103, `PersonaAssignmentScan` 126, `PersonaScanRefusal` 141, `_session_presence_probe` 169 (67, + `probe`) | `persona_assignments/scan.py` (~150) | stores |
| 252–320 | `StaleModelOverrideWrite`, `PersonaInstanceRetireError`, `RetiredPersonaInstanceError` | `persona_assignments/errors.py` (~60) | models |
| 321–420, 1800–2165 | `_retire_archive_batches` 321, `_retired_persona_instance_archive_path` 346, `retire_receipt_path` 371, `retired_persona_instance_ids` 383 (36, **depth 5**); `_archive_office_placements` 1800, `retire` 1854 (130), `_write_retire_receipt` 1985, `read_retire_receipt` 2041, `_archive_instance_row` 2074, `retired_instance_ids` 2091, `retired_instance_archive_path` 2097 | `persona_assignments/retire.py` (~330) — `RetireLane(store)` | stores |
| 421–478, 1502–1706 | `_as_utc`, `_safe_model_override_text`, `_model_supports_reasoning_effort` 436, `_normalize_reasoning_effort_override` 454; `update_profile` 1502 (174, depth 4), `set_backing_profile` 1677 | `persona_assignments/profile.py` (~230) — `ProfileLane(store)` | stores |
| 480–602, 1748–1799, 2086–2090, 2615–2845 | `PersonaInstanceStore.__init__`, `ensure_for_persona` 495 (80), `_instance_row`, `_mint_instance`, `get` 1748, `_resolve_stored_instance_id` 1765, `update` 2086, `add_instance` 2615, `_session_owned_by_other_instance` 2683, `scan_all` 2710, `list_all`, `ensure_for_personas` 2736, `_has_live_binding`, `_write` 2798, `_event` 2803, `_profile_patch_snapshot`, `_emit_state_patch` 2835 | `persona_assignments/store.py` (~450) — the class keeps its public methods as one-line delegations to the lanes (09-21: "composition, not mixins") | stores |
| 603–857 | `replicate_instance` 603 (94), `_replica_row`, `retire_replica` 729 (77), `apply_replicated_steering` 807 | `persona_assignments/replicate.py` (~200) | stores |
| 858–964, 1350–1501, 1707–1747 | `steer`, `set_parents`, `add_parent`, `remove_parent`, `detach_parents`, `clear_parents`; `_release_parent_references` 1350, `_apply_steer_edges` 1397 (68), `_commit_steer` 1466, `_validate_no_steering_cycle` 1707 | `persona_assignments/steering.py` (~280) — `SteeringLane(store)` | stores |
| 965–1125, 1239–1349 | `repair_non_instance_steering` 965 (79), `repair_missing_steering_references` 1045 (80), `repair_missing_chat_session_bindings` 1239 (110, depth 3) | `persona_assignments/repair.py` (~230) | stores |
| 1126–1238, 2166–2614 | `clear_chat_session_binding` 1126 (112), `assert_bindable` 2166 (65), `open_chat` 2258 (203), `rollback_chat_root_bind` 2462 (114), `create_operator_chat` 2577 | `persona_assignments/chat_binding.py` (~450) — `ChatBindingLane(store)` | stores |
| 2846–3035 | `PersonaAssignmentStore` 2846 (+ `_write` 2941, `_event` 2946), `migrate_retired_persona_assignment_task_ids` 2975 | `persona_assignments/assignments.py` (~150) | stores |
| 3036–3650 | `persona_instance_id_for`, `persona_instance_id_for_placement`, `row_is_canonical_persona_channel`, `is_canonical_persona_channel`, `canonical_persona_instance_id` 3080, `persona_chat_session_id_for`, `_durable_chat_root` 3116, `chat_session_owner_instance_id`, `chat_session_owner_persona` 3200, `persona_instance_display_name` 3240, `sender_scope_workspace_id` 3288, `chat_session_is_foreign_to_instance`, `canonical_chat_instance_id`, `resolve_default_chat_session_id_for_instance` 3370, `_display_name_for_template`, `_normalize_instance_source_persona`, `normalize_persona_id` 3424, `persona_id_from_instance_id`, `normalize_persona_or_template_id`, `_persona_comparison_key`, `personas_equal` 3502, `_coerce_travel_value`, `_role_for_persona_or_template`, `_profile_id_for_persona_or_template` 3593 | `persona_assignments/identity.py` (~420) — the seam most of the tree takes; imports `paths`, `models`, `personas`, never a store | policy |
| 3652–4053 | `persona_instance_summary` 3652 (141), `PERSONA_INSTANCE_VISIBILITY_FIELDS`, `persona_instance_visibility_ref`, `persona_instance_tool_detail` 3824, `active_persona_instance_agent_summaries` 3868, `_persona_instance_is_active_lane` 3901, `_profile_visibility_persona` 3912, `persona_assignment_summary` 3967, `safe_assignment_token` 4013, `safe_optional_token`, `_dedupe_tokens`, `_safe_skill_overrides`, `safe_assignment_text` 4051 | `persona_assignments/summary.py` (~300); `safe_assignment_token` / `safe_optional_token` / `safe_assignment_text` (59 importers) → `serde` (rule 15; `serde.safe_id` is the same 3-line shape) with `__init__` re-exports | policy |

13 modules after the CHANGE; **after the MOVE `store.py` holds the whole class (~1,850 code) for exactly one commit** — the H4 `loop.py` precedent, because a class body cannot be byte-moved in parts; the grandfather fixture carries it for that commit. Edges: lanes → `store` → `identity`/`vocabulary`/`errors` (down). The lazy cycles: `persona_chat_history.py:17` imports this module at module level while `scan.py` 204 lazily imports `persona_chat_history._default_session_db` — a 10-line wrapper over `chat_session_scope.open_chat_session_db`; the CHANGE calls `open_chat_session_db` directly and the cycle is gone (the wrapper is the persona_chat_history sheet's dead-code row). `office_store.py:508/2061` imports `canonical_persona_instance_id` lazily and `retire.py` 1830 imports `OfficeStore` lazily — `identity.py` imports no store, so the office edge lands on a leaf and stays legal when both declare `stores`. `persona_instance_sync` 648 / `persona_instance_identity` 1787 / `persona_runtime` 3680 stay lazy.

## 2. W0-G5 ladder sites → dispatch tables

| site (base line) | fixture rows | replacement | killing mutation |
|---|---|---|---|
| `_persona_instance_is_active_lane` 3901–3910 | `\|vocab\|{assigned, possessed, running, self_healing, waiting_on_human, waiting_on_proof, waiting_on_tool}` — a set literal of seven strings that are `WorkerSessionState` members (`states.py:31`) | `states.ACTIVE_LANE_STATES: Final[frozenset[WorkerSessionState]]` declared beside the enum (owner `states.py`, 40 lines — stays far under 800); the function is `instance.state in ACTIVE_LANE_STATES`; `ACTIVE_ASSIGNMENT_STATES` 238 and `TERMINAL_ASSIGNMENT_STATES` 44 are the same class of vocabulary and move to the same owner | drop `possessed` → **no test reds today**: `active_persona_instance_agent_summaries` has 0 test files (`git grep -lw` → none) and `_persona_instance_is_active_lane` is reached only through it. The CHANGE lands a positive control FIRST (a possessed instance must appear in the active summaries), then the table; the capture-is-a-vehicle rule, not a green assertion |

`str==` 6 → ≤ 2.

## 3. W0-G7 floor rows (3) and the decomposition

| row | lines / depth | phases (comment map) | after |
|---|---|---|---|
| `open_chat` 2258 | 203 / 2 | refusals 2289 · auxiliary guard 2301 · ownership 2326 · display name 2334 · scope provenance 2354 · v1 mirror 2367 · head stamp 2370–2386 · idempotent re-open 2396 · `chat_opened` event pair 2409 | `ChatBindingLane.open_chat = refuse → bind → stamp_head → emit`, ≤ 60 each; the head stamp (the INSTANCE_RECORDED writer, 2383) is its own function because it is the one place that rung is written (rule 13) |
| `update_profile` 1502 | 174 / 4 | override validation (421–478 helpers) · apply · the S6 event 1663 | `ProfileLane.update_profile = validate → apply → emit`; the `None`-is-a-value branch 1631 stays a guard |
| `retired_persona_instance_ids` 383 | 36 / **5** | nested loops over archive batches | `_iter_archive_rows()` generator (depth 2) consumed by a one-line set comprehension |

## 4. Helpers that unify

| here | duplicate of | authority |
|---|---|---|
| `_write` 2798 / `_write` 2941, `_event` 2803 / `_event` 2946 | two 4-line private helpers with ONE name in what become two modules | **W0-G3's NAME arm reds on the split** — rename in the MOVE to `_write_instance`/`_write_assignment`, `_event_instance`/`_event_assignment` (rule 13's `_write_*` naming); the sha256 table records the two renamed lines as the MOVE's only non-identical bytes |
| `safe_assignment_token` 4013, `safe_optional_token`, `safe_assignment_text` 4051 | `serde.safe_id` 199 / `serde.safe_text` 150 | `serde` (re-exported from `__init__` for the 59 importers; retargeted in a later `style:` commit, not this lane's CHANGE) |
| `_as_utc` 421 | `clock` has no `as_utc`; `snapshot._parse_iso_timestamp`, `persona_chat_history._iso_timestamp` are the read side | `clock.as_utc` (R3 owns `clock`; this lane folds when it exists, else creates the one function — tree wins) |
| `_safe_model_override_text` 425 | `harness_parts/persona/chat_session._safe_chat_model_override_value` (H3) | `profile.py` is the authority (the write side); H3's reader imports it |
| `_dedupe_tokens` 4023 | generic | `serde.dedupe_tokens` |

## 5. Dead code found while reading

| symbol | lines | evidence |
|---|---|---|
| `reset_unreadable_instance_rows` 89 | 12 | queue row line 21 (TEST SEAM): def only, 1 test |
| `repair_missing_chat_session_bindings [if @1304]` | 10 | queue row line 49 (reach census 0 hits) — unchanged by this lane; the arm moves to `repair.py` |
| `chat_session_is_foreign_to_instance` 3334 | 20 | 3 in-file references, 1 test — keep |

Nothing new. `migrate_retired_persona_assignment_task_ids` 2975 (1 production caller, 1 test) is a migration the assignment_task_id_migration command still runs — keep.

## 6. Doors

`hermes_time.now` 13, `utils.atomic_json_write` 14 (FIRST); `hermes_cli.models.github_model_reasoning_efforts` 447 (lazy, public — FIRST; through `agent_runtime/_upstream_doors.py`, which has the room: 36 lines). W0-G6 private rows: none. No widening.

## 7. Commits

1. **MOVE** `refactor(persona_assignments): persona_assignments.py → agent_runtime/persona_assignments/ (12 modules; the store class moved whole)` — spans byte-identical except the four `_write`/`_event` renames (named in the body); `__init__` re-exports every name the 60 importers and 72 test files take; `tests/agent_runtime/test_persona_assignments.py` (5,448 lines) split along the same seams (09-21 rule 1.6); the 3 private pins retargeted. **Mutation:** drop `identity` from `__init__` → `office_store`'s lazy import reds at the first office write.
2. **CHANGE** `refactor(persona_assignments): lanes by composition (Steering/Retire/ChatBinding/Profile/Repair); ACTIVE_LANE_STATES; open_chat/update_profile as phases` — the positive control for the active-lane vocabulary lands first; `[ds-size]` −1.

## 8. Lane and what it must not touch

R1, first of two (before `office_store`). Must not edit in parallel: `office_store.py` (same lane, next), `persona_chat_history.py` (R2 — the `_default_session_db` wrapper is deleted by R2's lane; this lane only stops importing it), `persona_instance_identity.py`, `persona_instance_sync.py`, `persona_chat_continuity.py` (R1's later files), `snapshot.py`/`prompt_observability.py`/`profile_runner.py` (R2/R3 — they keep importing through `__init__`).
