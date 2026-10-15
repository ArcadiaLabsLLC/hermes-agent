# Layout sheet — `agent_runtime/prompt_observability.py` (lane R2)

Base: `main` @ `bf4377f226` · 3,749 raw / 2,933 code / 98 top-level defs · longest `mission_chat_prompt_observability` 501 (198–698) · chains 5/5 · `str==` 29 · **`isinstance` 118 — the densest in the fork** · owner doc `docs/agent-runtime-harness/07-observability.md`. 7 production importers (`snapshot` takes `_SkillObservabilityResolver` + `snapshot_prompt_observability`; the chat lane takes `load_workspace_agents_context`, `load_persisted_context_row`, `skills_catalog_by_hash`, `slim_chat_final_observability`), 20 test files, 5 `setattr` pins. Two W0-G6 **private upstream reaches** — the only Wave 2 file with more than one.

**Package `agent_runtime/prompt_observability/`** (named after the file). The 09-21 R2 row (`mission_chat, snapshot, skills, available_skills, resolver`) stands in grain and gains the persistence, budget, context-file and safe-view modules the def map shows.

## 1. Section map → target modules

| lines | what is there | → module | layer |
|---|---|---|---|
| 1–129 | imports, `SAFE_PREVIEW_LIMIT`, `DEFAULT_CHAT_HISTORY_LIMIT`, `OBSERVABILITY_TIMING_KEYS` 56, the span accounting `_span_totals` 74, `_accumulate_span`, `_reset_observability_spans`, `_observability_span_ms`, `_note_catalog_walk`, `_observability_catalog_walks`, `_mission_chat_memory_loaded` | `prompt_observability/spans.py` (~100) | policy |
| 130–197 | `WorkspaceAgentsContext` 130, `load_workspace_agents_context` 137 (59) | `prompt_observability/workspace_agents.py` (~80) | stores |
| 198–699 | `mission_chat_prompt_observability` 198 (501) | `prompt_observability/mission_chat.py` — moved whole; CHANGE → `MissionChatObservability` (§3) | lanes |
| 701–838 | `attach_prompt_observability_turn_results` 701, `CHAT_FINAL_OBSERVABILITY_FIELDS` 767, `slim_chat_final_observability` 781, `_safe_model_selection`, `_safe_persona_id` | `prompt_observability/turn_results.py` (~120) | lanes |
| 840–1092 | `SKILLS_REF_HASH_LEN`, `HOISTED_SKILL_LIST_FIELDS`, `_skills_list_content_hash`, `_hoist_skills_catalogs` 898, `_final_model_input_stub` 923 (60), `_evict_final_model_input`, `PROMPT_LAYER_CONTENT_FETCH`, `_prompt_layer_content_stub`, `_evict_builder_timings`, `_evict_prompt_layer_content` 1052 | `prompt_observability/hoist.py` (~180) | policy |
| 1094–1317 | `snapshot_prompt_observability` 1094 (223, depth 3, + `_situational_for` 1126) | `prompt_observability/snapshot_frame.py` (~230) | lanes |
| 1319–1448 | `skills_catalog_by_hash` 1319, `_materialize_live_skills_catalogs` 1354, `load_skills_catalog_from_store` 1379, `_store_skills_catalog` | `prompt_observability/catalog_store.py` (~110) | stores |
| 1439–1903 | `PROMPT_OBSERVABILITY_RETAIN_PER_LANE`, `_PERSIST_REF_FIELDS`, `persist_prompt_observability_context` 1450, `_lane_key_for_row`, `_load_prompt_observability_index`, `_archived_context_count`, `_rebuild_prompt_observability_index` 1528, `_index_and_retain_after_persist` 1573 (73, depth 4), `load_live_prompt_observability_contexts` 1648 (93), `load_persisted_context_row`, `load_latest_prompt_observability_contexts`, `_context_row_key`, `_filter_live_chat_contexts`, `_context_identity_is_live`, `_merge_latest_contexts` | `prompt_observability/context_store.py` (~400) — ONE writer (`persist_…`) for the per-lane index, rule 13 | stores |
| 1904–2383 | `_backfill_derived_fields` 1904 (94), `_persona_instance_id`, `_profile_persona_from_instance`, `_profile_prompt_skills_need_snapshot`, `_context_budget_needs_refresh`, `_static_context_window` 2069, `_compaction_ratio`, `CONTEXT_BUDGET_*`, `BUDGET_BASIS_*`, `COMPACTION_BASIS_*`, `_tool_schema_json_bytes`, `_estimate_used_tokens`, `_metered_assembled_tokens`, `_live_compaction_threshold`, `_context_budget` 2216 (99), `_drift_alarm_direction`, `_wire_drift_row`, `_profile_snapshot_skill_names` | `prompt_observability/context_budget.py` (~380) | policy |
| 2385–2730 | `_SkillObservabilityResolver` 2385 (+ 7 methods), `_accessible_skills_context` 2514 (137, depth 4), `_persona_skill_assignment_removals`, `_SKILL_CATALOG_TTL_SECONDS`, `_resolve_skill_walker`, `_installed_skill_catalog` 2698 (depth 4) | `prompt_observability/skills_resolver.py` (~280) | stores |
| 2731–3110 | `available_skills_context` 2731 (154), `_skill_publishability`, `_skill_realm_sync` 2916, `used_skills_context` 2946 (63), `_resolved_skill_receipt`, `_skill_md_bytes`, `_skill_candidate_content_hash`, `_list_used_skill_entries`, `_skill_trace_event_counts_as_used` 3071, `_append_used_skill_name`, `_extract_skill_name`, `_chat_metadata` 3111 | `prompt_observability/skills_context.py` (~330) | stores |
| 3148–3420 | `_profile_context_files` 3148, `_token_estimate_from_bytes`, `_layer_text_size`, `_set_row_prompt_contribution`, the six `_*_prompt_chars/_content` 3228–3304, `_attach_context_file_prompt_contributions` 3306, `_attach_skills_prompt_contribution` 3348, `_context_file_summary` 3373, `_file_kind` 3404 | `prompt_observability/context_files.py` (~250) — the three ladders' owner (§2) | policy |
| 3421–3749 | `_safe_final_model_input` 3421 (51), `_safe_context_compaction`, `_safe_user_message_wire`, `_OBSERVABILITY_PROMPT_SECRET_PATTERNS`, `_safe_prompt_body`, `_safe_system_prompt_sections`, `_safe_cache_routing`, `_safe_cache_fingerprint`, `_TURN_USAGE_FIELDS`, `_safe_turn_usage`, `turn_usage_from_result` 3638, `_safe_tool_schema`, `_safe_int` 3710, `_chat_history_context`, `_safe_preview` | `prompt_observability/safe_views.py` (~280) | policy |

14 modules, none over 400. Edges: `mission_chat`/`snapshot_frame`/`turn_results` → every store and policy module (down); `skills_context` → `skills_resolver` (same layer). **One upward reach to break in the CHANGE:** `catalog_store._materialize_live_skills_catalogs` 1366 lazily imports `snapshot.build_snapshot` while `snapshot.py:55` imports this module at module level — legal today (snapshot is undeclared), an upward import (stores → lanes) the day R3 declares `snapshot`. Fix: `skills_catalog_by_hash(token, *, materialize)` takes the builder as a parameter; `snapshot` passes `build_snapshot`. The four `persona_runtime._mission_chat_*` private reaches (3235–3288) and `runtime_hud._installs_block` 1110 are fork-private names crossing modules — R2's `persona_runtime`/`runtime_hud` sheets export them publicly; until then they stay (not a gate arm).

## 2. W0-G5 ladder sites → dispatch tables (the CHANGE commit)

| site (base line) | fixture rows | replacement | killing mutation |
|---|---|---|---|
| `_file_kind` 3404–3419, `_context_file_summary` 3373–3402 (the `path.name in {…}` / `==` preview arms 3393–3401), `_attach_context_file_prompt_contributions` 3306–3346 (`name == "SOUL.md"` / `in {"MEMORY.md","USER.md"}` / `== "config.yaml"`) | `\|ladder\|name`, `\|ladder\|path.name`, `\|ladder\|name` — **three readers of ONE six-name vocabulary** (`SOUL.md`, `MEMORY.md`, `USER.md`, `AGENTS.md`, `.skills_prompt_snapshot.json`, `config.yaml`) | `context_files.CONTEXT_FILES: Mapping[str, ContextFileKind]` with `ContextFileKind(kind: str, preview: Callable[[bytes], str \| None], contribution: Callable[[row, chars, memory_loaded], None])`; `_file_kind` = `CONTEXT_FILES.get(name, DEFAULT).kind`; the summary's preview branch = `kind.preview(raw)`; the attribution loop = `CONTEXT_FILES[name].contribution(row, …)` — the workspace-context arm (3323) stays a guard on `row["kind"]`, which is a different key | swap the `SOUL.md` and `MEMORY.md` entries → `tests/agent_runtime/test_prompt_observability.py`'s context-files `kind` assertion reds (`soul` reported for MEMORY.md) |
| `_skill_trace_event_counts_as_used` 3071–3079 | `\|vocab\|{blocked, completed, failed}` — the set literals repeat members of `mission_chat_turns.TERMINAL_TURN_STATES` (173) | import the owning vocabulary and test membership: `status in FAILED_TRACE_STATES` where the `Final` lives beside `TERMINAL_TURN_STATES` in `mission_chat_turns.py` (R2's file; 1,633 raw — its sheet keeps `vocabulary.py` well under 800) | drop `blocked` from the owning set → `test_prompt_observability_record_once.py`'s used-skills case reds (a blocked skill counted as used) |

`isinstance` 118 → ≤ 50 at review: `safe_views.py` keeps its boundary checks (they validate a foreign dict once); every `isinstance(row, dict)` inside a loop over rows this module itself wrote becomes a typed row.

## 3. W0-G7 floor rows (3) and the decomposition

| row | lines / depth | phases (comment map) | after |
|---|---|---|---|
| `mission_chat_prompt_observability` 198 | 501 / 2 | profile binding + span reset 276–313 · catalog TTL measurement 380 · per-item attribution 401–405 · situational HUD 442 · record-once 650 · usage 662 · legacy flag 671 | `MissionChatObservability.bind → context_files → skills → hud → record_once → usage`, one method per section of the row it writes (09-21 R2), ≤ 90 each; the `builder_timings` dict is a field |
| `snapshot_prompt_observability` 1094 | 223 / 3 | roster + HUD 1106–1164 · live-lane filter 1203–1239 · hoist/evict accounting 1243–1286 | `SnapshotFrame.roster → hud → live_rows → hoist`; `_situational_for` becomes a method |
| `available_skills_context` 2731 | 154 / 3 | hoisted resolver 2752 · realm-ineligible roots 2806–2814 · assigned rows 2818 | `_skill_row(name, resolver, realm_rows)` per skill (≤ 50) and a loop; the function ≤ 60 |

Depth-4 sites not over 150 (`_index_and_retain_after_persist`, `_accessible_skills_context`, `_installed_skill_catalog`) sit AT the limit — the MOVE must not add a level; the CHANGE lifts each inner loop out.

## 4. Helpers that unify

| here | duplicate of | authority |
|---|---|---|
| `_safe_int` 3710 | `mission_chat_turns._safe_int` 1596, `persona_chat_history._safe_int` 2320 (W0-G3 row) | `serde.safe_int` (H2 folded the harness copies; these three are the fixture's remaining row — R2 folds all three) |
| `_safe_preview` 3744 (`SAFE_PREVIEW_LIMIT`) | `serde.safe_block(value, limit=)` | `serde.safe_block` |
| `_safe_persona_id` 832 | `persona_assignments.identity.normalize_persona_id` | `identity` |
| `_token_estimate_from_bytes` 3178 | `profile_runner._agent_tools_json_bytes` is a different measure — NOT a duplicate; named so nobody folds it | — |
| `_chat_history_context` 3718 | reads SessionDB directly; `persona_chat_history.persona_chat_session_messages` is the reader authority | `persona_chat_history` (R2's next file — fold there) |

## 5. Dead code found while reading

| symbol | lines | evidence |
|---|---|---|
| `_skill_realm_sync` 2916 | 28 | queue row line 57 (reach census 0 hits): called at 2805 when `shared` — untested live, not dead; the row's verdict stands |
| `_backfill_derived_fields [if @1977]` | 13 | queue row line 56 — the arm moves with the function to `context_budget.py` |
| `load_skills_catalog_from_store` 1379 | 20 | 1 in-file caller (1339) + 2 tests — keep |

Nothing new.

## 6. Doors (the two private reaches)

| import | line | class | door |
|---|---|---|---|
| `agent.auxiliary_client._compression_threshold_for_model` | 2102 (W0-G6 row) | **NEAR** — a private name the fork needs | `_upstream_doors.compression_threshold_for_model` now (the W0-G6 arm counts only direct imports); a held widening row in `upstream-footprint-ledger.md`: "expose `compression_threshold_for_model` publicly" |
| `tools.skills_tool._find_all_skills` | 2691 (W0-G6 row) | **NEAR** | `_upstream_doors.find_all_skills`; the widening row asks upstream to publish it, or the fork walks `agent.skill_utils.get_all_skills_dirs` (public, 2464) itself — the resolver already imports that; the CHANGE tries the public walk first and keeps the door only if the results differ (recorded) |
| `agent.model_metadata.DEFAULT_CONTEXT_LENGTHS` 2080, `hermes_cli.profiles.get_profile_dir` 14, `agent.skill_utils.get_all_skills_dirs` 2464, `utils.atomic_json_write` 15 | — | FIRST | keep |

## 7. Commits

1. **MOVE** `refactor(prompt_observability): prompt_observability.py → agent_runtime/prompt_observability/ (14 modules)` — spans byte-identical; `__init__` re-exports the 6 importer names (incl. `_SkillObservabilityResolver`, made public as `SkillObservabilityResolver` in the CHANGE); 5 `setattr` sites retargeted. **Mutation:** re-point the `_store_skills_catalog` pin at the package → `test_snapshot_prompt_hoist.py` reds.
2. **CHANGE** `refactor(prompt_observability): CONTEXT_FILES table, terminal-state vocabulary import, MissionChatObservability/SnapshotFrame phases; two upstream doors; _safe_int/_safe_preview folded` — four ladder rows and three floor rows deleted; `[ds-size]` −1.

## 8. Lane and what it must not touch

R2, first of two (before `persona_chat_history`). Must not edit in parallel: `snapshot.py` (R3 — it imports two names, both re-exported), `mission_chat_turns.py` (R2, later — this lane only IMPORTS its vocabulary; the `Final` is added in a 3-line commit on that file, which no other Wave 2 lane opens), `persona_runtime.py`, `runtime_hud.py` (R2, later), `harness_parts/persona/*` (H3's package — retarget-only).
