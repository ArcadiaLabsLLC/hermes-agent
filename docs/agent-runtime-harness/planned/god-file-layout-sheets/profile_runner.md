# Layout sheet — `agent_runtime/profile_runner.py` (lane R3)

Base: `main` @ `bf4377f226` · 3,584 raw / 2,733 code / 95 top-level defs · longest `ProfileAgentRunner._execute_agent_run` 424 (951–1374, **depth 5** — the deepest unit in Wave 2) · chains 4/4 · `str==` 26 · `isinstance` 71 · owner doc `docs/agent-runtime-harness/05-chat-turn-lane.md`. 4 production importers, all taking four names (`AgentRunRequest`, `ProfileAgentRunner`, `RunBudgetExceeded`, `agent_runs_in_flight`); 36 test files, 8 pinning 8 private names, 9 `setattr` sites. One W0-G6 private upstream reach. Seven W0-G3 duplicate rows name this file — more than any other in Wave 2: it is where the fork's redaction helpers were copied FROM.

**Package `agent_runtime/profile_runner/`** (named after the file). The 09-21 R3 row (`runner, request, budget, mcp_lane, execute`) stands; the def map adds the payload, redaction, progress and model-input-observability modules — 1,400 raw lines the 09-21 table did not see.

## 1. Section map → target modules

| lines | what is there | → module | layer |
|---|---|---|---|
| 1–96 | imports, `_blocked_tool_names_with_registry_hygiene` 33, `_blocked_tool_names_for_run` 53, `_enabled_toolsets_for_run` 68 | `profile_runner/toolsets.py` (~70) | policy |
| 97–251 | `ProfileRunnerError` 97, `RunBudgetExceeded` 119, `_ProviderErrorCapture` 149, `_capture_provider_errors` 214, `_NO_WALL_BUDGET_SECONDS` | `profile_runner/errors.py` (~130) | models |
| 252–394 | `AgentRunRequest` 252, `AgentRunResult` 360 | `profile_runner/models.py` (~140) | models |
| 395–564, 1377–1434, 1587–1619 | `WallBudgetCheckpoint` 395 (+ 8 methods), `_ToolBudgetGuard` 550; `_enforce_result_budgets` 1377 (56), `_emit_budget_pressure_warning` 1587 | `profile_runner/budget.py` (~250) | policy |
| 565–681 | `_prepare_resident_persona_chat_agent` 565, `_finish_resident_persona_chat_agent` 595, `_sanitized_user_message_text` 622, `stage_persona_chat_user_row_marker` 641 | `profile_runner/resident_actor.py` (~110) | lanes |
| 682–950, 3537–3584 | `ProfileAgentRunner.__init__`, `run` 689, `prewarm` 705, `_run` 736 (56), `_admit_mcp_servers` 793 (88), `_teardown_mcp_admission` 882 (68); `_normalize_result` 3537, `_default_agent_factory` 3572 | `profile_runner/runner.py` (~300) | lanes |
| 951–1376, 1535–1586 | `_execute_agent_run` 951 (424, depth 5; closures `_construct_agent` 1113, `interrupt_for_budget` 1282); `_notify_agent_ready`, `_run_conversation_with_usage_ledger`, `_cleanup_agent_ready`, `_emit_agent_ready_callback_warning` 1569 | `profile_runner/execute.py` — moved whole (grandfathered one commit); CHANGE → `AgentRunExecution` (§3) | lanes |
| 1435–1534 | `_steer_mcp_admission_notice` 1435, `_on_mcp_budget_exhausted`, `_emit_mcp_budget_exhausted` 1502 | `profile_runner/mcp_lane.py` (~110) | lanes |
| 1620–1711 | `_validate_workdir`, `_agent_workdir` 1629, `_WORKDIR_LOCK`, `_ACTIVE_RUNS*`, `agent_runs_in_flight` 1693, `_counted_agent_run` | `profile_runner/workdir.py` (~80) | stores |
| 1712–1841 | `_positive_int` 1712, `_elapsed_ms` 1722, `_emit_request_timing`, `_profile_status_callback` 1747 (+ `emit`, depth 4), `_positive_float` 1786, `_binding_for_profile` 1798 | folds (§4) + `profile_runner/status.py` (~60) | policy |
| 1842–1925 | `RUNTIME_RESOLVE_CACHE_TTL_SECONDS`, `_RUNTIME_RESOLVE_*`, `reset_runtime_resolve_cache` 1855, `_runtime_resolve_cache_key`, `_resolve_request_runtime` 1890 | `profile_runner/runtime_resolve.py` (~90) — one memo, one writer | stores |
| 1926–2048 | `_progress_adapter` 1926 (62, + `emit` depth 3), `_progress_payload_from_callback` 1990, `_agent_chat_target_label` 2023 | `profile_runner/progress.py` (~130) — the ladder's owner (§2) | policy |
| 2041–2204 | `_DISPATCH_*`, `_scrub_dispatch_order`, `_agent_chat_dispatch_fields`, `_safe_dispatch_id`, `_dispatch_result_envelope`, `_agent_chat_dispatch_thread_fields`, `_agent_chat_dispatch_reply_fields` 2162 | `profile_runner/dispatch_payloads.py` (~150) | policy |
| 2205–2472, 2894–3055 | `_tool_started_payload` 2205, `_tool_finished_payload` 2241 (63), `_dev_work_payload` 2306 (62), `_PATCH_MODES`, `_patch_mode_token`, `_patch_diff_fields`, `_candidate_file_values`, `_safe_command_label`, `_safe_skill_tool_name`, `_safe_skill_identifier_from_value`; `_TODO_STATE_*`, `_todo_state_payload` 2900, `_collapse_todo_ws`, `_todo_items_from` 2962, `_duration_ms`, `_safe_exit_code` 2993, `_safe_label`, `_safe_reasoning_summary` 3011, `_looks_sensitive_or_pathish` 3043 | `profile_runner/tool_payloads.py` (~330) | policy |
| 2473–2893 | `_OPERATOR_*` constants, `_line_has_secret`, `_safe_operator_command`, `_safe_operator_output` 2531, `_render_kv_line_token`, `_render_operator_kv_block`, `_scrub_operator_block_head`, `_safe_operator_tool_input`, `_safe_operator_tool_result`, `_attach_tool_io`, `_operator_path_sensitive`, `_safe_operator_target` 2707 (+ `_clean`), `_patch_paths_from_invocation`, `_safe_operator_paths`, `_safe_tool_result_detail`, `_safe_file_labels` 2829, `_is_error_result` 2846 | **`agent_runtime/redaction.py`** (exists — the regex authority) gains the operator-facing scrubbers; `profile_runner/operator_redaction.py` keeps only the tool-IO attachment (~120) | policy |
| 3056–3536 | `CHAT_COMPACTION_RECEIPT_KIND`, `_apply_chat_compaction_threshold` 3059 (86), `_chat_compaction_observability`, `_attach_model_input_observability`, `_model_input_observability` 3189 (89), `_current_turn_user_row`, `_wire_user_message` 3305, `_system_prompt_section_receipts` 3345 (58), `_agent_cache_routing_observability`, `_rendered_skills_prompt_chars` 3418 (52), `_agent_tools_json_bytes`, `_agent_tool_names`, `_message_preview`, `_redact_prompt_text` | `profile_runner/model_input_observability.py` (~380) | stores |

16 modules, none over 400. Edges: `runner`/`execute`/`mcp_lane`/`resident_actor` → everything else (down); `progress`/`tool_payloads`/`dispatch_payloads` → `redaction` (a leaf outside the package). Lazy reaches to `local_llama_adapter.provider` (701, 967, 1893), `mcp_admission` (88–911), `persona_chat_continuity` 961, `terminal_envelope` 965, `patch_diff_artifacts` 2404, `persona_assignments.persona_instance_display_name` 2195, `persona_turn_binding` 1550, `usage_ledger` 1551, `skill_resolution` 966, `config` 1235 — none imports back; no cycle.

## 2. W0-G5 ladder sites → dispatch tables (the CHANGE commit)

| site (base line) | fixture row | replacement | killing mutation |
|---|---|---|---|
| `_progress_payload_from_callback` 1990–2021 | `\|ladder\|callback_event` — `event_type == "run.tool.started"` / `"run.tool.finished"`, then `callback_event == "tool.started"` / `"tool.completed"` / `in {"reasoning.available", "_thinking"}`, then a default | `progress.CALLBACK_EVENTS: Mapping[str, Callable[[event_type, args, kwargs], payload]]` keyed on the wire event name, with `PROGRESS_EVENTS: Final[tuple[str, ...]]` beside it; lookup order = `event_type` first, `callback_event` second, `_progress_default` last — the two lookups are the BOUNDARY (two vocabularies arrive on one callback), never a third arm | swap the `tool.started` and `tool.completed` rows → `tests/agent_runtime/test_profile_runner.py`'s tool-progress payload test reds (`phase` wrong on the first tool event) — the same class of red H3 recorded for the chat lane's tool progress |
| `_todo_items_from` 2962–2981 | `\|isinstance\|value` — `str` → `json.loads`, then `dict` → `.get("todos")`, then `list` | one guard (`str` → parse) then `_TODO_SOURCES: tuple[(type, extract)]`; or `serde.coerce_json(value)` + a two-arm read — the CHANGE picks the serde form if `serde` gains `coerce_json` for another lane first (tree wins) | make the `dict` extractor return the whole dict → `test_profile_runner.py`'s todo-state case reds |

`str==` 26 → ≤ 10 (payload-key guards in the observability writers).

## 3. W0-G7 floor row (1) and the decomposition

| row | lines / depth | phases (comment map) | after |
|---|---|---|---|
| `_execute_agent_run` 951 | 424 / **5** | scopes 975–1009 (container identity, terminal binding, MCP registry scope) · wall checkpoint 1009–1035 · MCP admission 1036–1076 · reasoning override + agent construction 1077–1113 (`_construct_agent`) · T3 resident-actor state 1088 · conversation 1113–1250 · exit-stack + graceful checkpoint 1251–1313 (`interrupt_for_budget`) · result 1313–1374 | `AgentRunExecution(request, runner)` with `enter_scopes → checkpoint → admit → construct → converse → finalize`, ≤ 90 each and depth ≤ 3; the two closures become methods whose fields are the six enclosing locals they read (`agent`, `checkpoint`, `stack`, `result_holder`, `budget`, `request`) — rule 17's closure clause |

Depth-4 sites under 150: `_profile_status_callback.emit` 1748 (34) — the `emit` closure becomes `status.StatusEmitter.emit` (depth 2) in the same CHANGE, so the MOVE cannot push it to 5.

## 4. Helpers that unify (the seven W0-G3 rows)

| here | duplicate of (fixture row) | authority |
|---|---|---|
| `_positive_int` 1712 | `config._positive_int` 1173, `mcp_admission._positive_int` 1004 | `serde.positive_int` (exists) — all three fold here; `config`/`mcp_admission` are R3's files too |
| `_positive_float` 1786 | `mcp_admission._positive_float` 996 | `serde.positive_float` (new, beside `positive_int`) |
| `_safe_exit_code` 2993 | `mission_chat_turns._safe_exit_code` 1604; byte-equal to `persona_chat_history._safe_trace_int` 2129 | `serde.safe_int` |
| `_elapsed_ms` 1722 | `codex_observability._elapsed_ms` 40, `mission_chat_turn_context._elapsed_ms` 150 | `clock.elapsed_ms` (exists — H2 created it; this lane folds the runtime copies) |
| `_looks_sensitive_or_pathish` 3043 | `events.py` 649, `observability.py` 442, `progress.py` 640 | `redaction.looks_sensitive_or_pathish` |
| `_safe_file_labels` 2829 | `observability.py` 426, `progress.py` 613 | `redaction.safe_file_labels` |
| `_duration_ms` 2983 | `plugins/platforms/raft/adapter.py` 115 — UPSTREAM file | left; baselined `upstream_copy_left` |
| the operator scrubbers 2473–2893 | `persona_chat_history._safe_trace_operator_{line,block,paths}` 2086–2128, `_safe_trace_file_labels` 2138 | `agent_runtime/redaction.py` — **this lane lands the owner** (R3 lands before R2's `persona_chat_history` sheet, whose §4 folds onto the same names); if R2 lands first, the owner is the same module and this lane folds toward it |

## 5. Dead code found while reading

| symbol | lines | evidence |
|---|---|---|
| `reset_runtime_resolve_cache` 1855 | 5 | queue row line 22 (TEST SEAM): def only in production, 2 tests |
| `_emit_agent_ready_callback_warning` 1569 | 16 | queue row line 55 (reach census 0 hits): two in-file callers — untested live, the row's DECIDE stands; positive control lands with the MOVE |
| `_execute_agent_run.interrupt_for_budget [if @1316]` | 10 | queue row line 54 — the arm becomes `AgentRunExecution.on_budget`'s guard; the row is re-keyed, not closed |

Nothing new.

## 6. Doors

| import | line | class | door |
|---|---|---|---|
| `agent.message_sanitization._sanitize_surrogates` | 632 (W0-G6 row) | **NEAR** | `_upstream_doors.sanitize_surrogates`; held widening row: "publish `sanitize_surrogates`" |
| `hermes_cli.profiles.{get_profile_dir, normalize_profile_name, profile_exists}` 14, `hermes_cli.runtime_provider.resolve_runtime_provider` 15, `agent.coding_context.coding_compact_skill_categories` 3449, `agent.runtime_cwd.resolve_context_cwd` 3450, `agent.system_prompt.build_system_prompt_parts` 3362 | — | FIRST (public) | keep |

## 7. Commits

1. **MOVE** `refactor(profile_runner): profile_runner.py → agent_runtime/profile_runner/ (16 modules; _execute_agent_run moved whole)` — spans byte-identical; `__init__` re-exports the four importer names; 9 `setattr` sites and 8 private pins retargeted. **Mutation:** re-point the `_resolve_request_runtime` pin at the package → `test_profile_runner.py`'s runtime-resolve case reds.
2. **CHANGE** `refactor(profile_runner): AgentRunExecution phases; CALLBACK_EVENTS; redaction owns the operator scrubbers; positive_int/positive_float/safe_int/elapsed_ms folded; sanitize_surrogates door` — two ladder rows, one floor row, six duplicate rows deleted; `[ds-size]` −1.

## 8. Lane and what it must not touch

R3, fourth of five (after `core_cache`, before `snapshot`). Must not edit in parallel: `mcp_admission.py`, `config.py` (R3, later — the `_positive_int` folds there land in THEIR MOVE, this lane only creates the serde owner), `mission_chat_turns.py`, `persona_chat_history.py` (R2 — the `_safe_exit_code`/`_safe_trace_int` copies fold in R2's lane toward the owner this lane creates), `observability.py`, `progress.py`, `events.py` (not in the 62 — their three copies fold in a `style:` commit after both lanes land), `stream.py`, `persona_runtime.py` (importers — keep their paths).
