# Layout sheet — `hermes_cli/harness_parts/persona_commands.py` (lane H3)

Base: `main` @ `78501db796` · 8,191 raw / 6,269 code / 119 top-level defs · longest `_mission_chat_commit_turn` 1,590 (3544–5133) · `str==` 31 · `isinstance` 30 · owner doc `docs/agent-runtime-harness/05-chat-turn-lane.md`. Waits on H1 (this file is still `exec`'d into `harness.py`'s globals at harness.py:6730–6737; 41 test patches name `harness.<name>` for names defined HERE). Every line range below is on the base SHA; the MOVE commit re-derives each span's sha256 from these ranges (program §3.3).

## 1. Section map → target modules (line ranges on base; ~code = the span's code lines)

| lines | what is there | → module (package `hermes_cli/harness_parts/persona/`) | layer |
|---|---|---|---|
| 1–155 | imports, constants, `_persona_chat_fault_injection` (156–161) | `persona/__init__.py` (map + the fault-injection seam) | wiring |
| 163–424 | `_cmd_persona_{list,show,tool_diff,permission_set,assignments,assignment_task_id_migration}` | `persona/inspect_commands.py` (~330) | lanes |
| 438–990 | `_cli_create_persona`, `_cmd_agent_create` (155), `_console_denial`, `_agent_retire_outcome`, `_cmd_agent_retire`, `_placement_discriminability_refusal`, `_cmd_persona_instance_create` (156) | `persona/lifecycle_commands.py` (~600) | lanes |
| 993–1566 | `_cmd_persona_instance_open_chat` (322), `_persona_instance_updated_at`, `_cmd_persona_instance_open_new_chat` (160), `_prewarm_chat_actor_for_open`, `_emit_persona_open_chat_{payload,error}` | `persona/chat_open.py` (~620) | lanes |
| 1569–1863 | `_cmd_persona_chat_delete` (242), `_retired_persona_instance_{payload,refusal}` | `persona/chat_delete.py` (~320) | lanes |
| 1866–1971, 5136–5203 | `_coordinator_*` ×4, `_maybe_stamp_spawned_by`, `_cmd_mission_chat_steer`, `_cmd_mission_chat_queue_skill` | `persona/chat_coordinator.py` (~250) | lanes |
| 1974–2153, 2366–2402, 6420–6429, 6440–6868 | `_publish_persona_chat_{projection,metadata,send_refused}_event`, `_mission_chat_emit`, `_emit_chat_{final,frame}`, `_ChatProtocolV2Emitter` (429) | `persona/chat_events.py` (~700) — the emitter's 12 methods (6449–6864) stay one class | I/O |
| 2166–2363, 2405–2511, 2609–2846 | `_mission_chat_busy_outcome` (198), `_bind_mission_chat_delivery_capability`, `_mission_chat_lease_provenance`, `_normalize_deferred_thread_policy`, `_registry_probe_rounds`, `_visibility_bundle_*` ×3, `_within_admitted_turn`, `_turn_skill_resolver`, `_safe_pre_admit_timings`, `_prewarm_constructions_overlapped`, `_snapshot_builds_overlapped` | `persona/chat_admission.py` (~650) | policy |
| 2514–2606 | `_stamp_turn_visibility`, `_stamp_reply_media` | `persona/chat_turn_commit/finalize.py` (with the commit's finalize phase) | lanes |
| 2850–3541 | `_cmd_mission_chat_message` (692; no nested defs) | `persona/chat_turn_message.py` (~700) | lanes |
| 3544–5133 | `_mission_chat_commit_turn` (1,590; nested `_warn` 3644, `_route_turn_write` 3653, `_stamp_finalization` 3664, `_stream_progress` 4234, `_agent_ready_for_steer` 4246, `_deferred_auto_title` 5072) | MOVE whole to `persona/chat_turn_commit/__init__.py`; CHANGE splits by the phase marks (§4) | lanes |
| 5214–5563 | `_clarify_ticket_row`, `_cmd_mission_chat_dispatch_redeliver` (108), `_cmd_mission_chat_clarify_tickets`, `_cmd_mission_chat_turn_resolve` (113) | `persona/chat_tickets_commands.py` (~330) | lanes |
| 5566–5896 | `_cmd_persona_instance_{close,archive,retire,repair_steering,steer,return_summary,update_profile}` | `persona/instance_commands.py` (~340) | lanes |
| 5899–6417 | `_SetModelRequestError`, `_set_model_error_payload`, `_parse_issued_at_arg`, `_validated_set_model_request`, `_cmd_persona_instance_set_model`, `_template_write_store_target`, `_cmd_persona_set_model`, `_set_skills_error_payload`, `_validated_set_skills_request`, `_cmd_persona_set_skills`, `_unresolvable_skill_ids` | `persona/model_and_skills_commands.py` (~520) | lanes |
| 6871–6932 | `_safe_stream_text`, `_safe_stream_block`, `_safe_exit_code_value`, `_elapsed_ms`, `_tool_name_from_progress`, `_safe_chat_model_override_value` | fold into `agent_runtime/serde.py` (§3) or `persona/chat_events.py` | — |
| 6935–7227 | `_requested_chat_model_override`, `_missing_chat_message_payload`, `_invalid_chat_model_override_payload`, `_mission_chat_caller_refusal`, `_clarify_ticket_store_populated`, `_resolve_mission_chat_clarify_binding`, `_settle_mission_chat_clarify_binding`, `_mission_chat_clarify_request_payload`, `_mission_chat_retired_target_refusal` | `persona/chat_request.py` (~300) — request validation and refusal payloads | policy |
| 7230–7448 | `_session_row`, `_session_model_config`, `_persona_chat_session_owner`, `_persona_chat_bound_owner`, `_persist_chat_model_override`, `_chat_model_override_from_config`, `_resolve_chat_model_override`, `_chat_effective_model_payload`, `_persona_chat_native_{tip,history,revision}` | `persona/chat_session.py` (~220) | stores |
| 7464–7890 | `_redact_persona_chat_text`, `_safe_persona_chat_body_text`, `_chat_turn_tool_names`, `_persona_chat_existing_turn`, `_resolve_relay_sender_marker` (83), `_append_persona_{operator_turn,assistant_text}`, `_persist_persona_chat_row` (86), `_mirror_persona_chat_message`, `_update_persona_chat_token_counts`, `_positive_int_or_zero` | `persona/chat_history_writes.py` (~430) — the ONE write path for the persona chat row (rule 13) | stores |
| 7893–8183 | `_persona_by_id` (51), `_display_name_for_profile`, `_maybe_auto_title_persona_chat`, `_close_free_floating_assignments`, `_mission_chat_target_decision` (93), `_mission_chat_bare_persona_target`, `_resolve_mission_chat_persona_id` | `persona/chat_target.py` (~300); `_persona_by_id` → `harness_parts/_common.py` (H1 names it: reached from harness.py's globals) | policy |

Result: 16 modules, largest ≈ 700 (`chat_events`, `chat_turn_message`) — both under 800 raw only if their comment share is ≤ 12 %; the sheet review measures and splits `chat_events` at the emitter (`chat_events.py` + `chat_emitter.py`) if not. The 09-21 plan §2 H3 table is superseded by this one where they differ (it named 9 modules; the tree has 119 defs and needs 16).

## 2. Routing sites → dispatch tables (the CHANGE commit; each with its killing mutation)

| site (base line) | shape today | replacement | killing mutation |
|---|---|---|---|
| `_cmd_persona_instance_steer` 5769 | `if op == "detach" / elif "add_parent" / elif "remove_parent" / elif "set_parents" / else` (5 arms) over `PersonaInstanceStore` methods | `_STEER_OPS: Mapping[str, Callable[[store, args], row]]` at module scope, `op` validated against `_STEER_OPS.keys()` → typed refusal `steer_op_unknown` | swap the `detach` and `set_parents` entries → `tests/hermes_cli/test_persona_instance_steer*.py` reds on the detach case |
| `_mission_chat_commit_turn` 4599 | `if wall_budget_exceeded: … elif …` (3 arms) classifying the failure | `mission_chat_outcome.classify_turn_failure` (exists, 18 lines) is the ONE classifier; the arm becomes a lookup on `TurnOutcome` | return `TurnOutcome.completed` for the budget case → the wall-budget test reds |
| `_ChatProtocolV2Emitter.progress` 6538 → `_tool_started`/`_tool_finished` | `event_type = payload.get("type")`, `if event_type not in {"run.tool.started", "run.tool.finished"}` then `if event_type == "run.tool.started"` else finished (6541–6549) | `_PROGRESS_EVENTS: Mapping[str, Callable[[self, payload], None]]` | swap started/finished → the protocol-v2 fixture diff reds |
| `_mission_chat_busy_outcome` 2166 (198 lines) | nested `if lease … if deferred … if policy == "…"` | `_normalize_deferred_thread_policy` already returns a closed vocabulary; the outcome becomes a `BusyOutcome` Enum + table `_BUSY_OUTCOMES[policy, lease_state]` | swap two table cells → `test_mission_chat_busy*` reds |

Density after the CHANGE (goal, measured by the probe at review): `str==` 31 → ≤ 10 (the remaining are guards on payload keys), `isinstance` 30 → unchanged (they are boundary validation, allowed).

## 3. Helpers that unify (named duplicate sites; fold in the CHANGE commit)

| here | duplicate of | authority |
|---|---|---|
| `_positive_int_or_zero` 7885 | `config/mcp_admission/profile_runner._positive_int` (program §4) | `agent_runtime/serde.positive_int(default=0)` |
| `_safe_exit_code_value` 6891 | `profile_runner._safe_exit_code`, `persona_chat_history._safe_trace_int` | `serde.safe_int` |
| `_elapsed_ms` 6898 | `mission_chat_turn_context._elapsed_ms` (10 lines) | `agent_runtime/clock.elapsed_ms` (new leaf, with `now_iso`) |
| `_safe_stream_text` / `_safe_stream_block` 6871–6888 | `serde.safe_text` class (9 copies) | `serde.safe_text` |
| `_persona_by_id` 7893 | reached by harness.py and parts through the exec'd globals | `harness_parts/_common.py` (H1) |
| `_session_row` 7230 / `_session_model_config` 7240 | `chat_session_scope.recorded_instance_chat_head` reads the same row | `chat_session_scope` is the owner; these become thin calls |

## 4. `_mission_chat_commit_turn` → `TurnCommit` (the CHANGE; phase = the ledger's own marks)

The function marks its phases through `turn_phases.mark(...)` (3616 `turn_phases = plan.phases`): `context_built` 4140 · `observability_built` 4184 · `emitter_created` 4224 · `agent_ready` 4265 · `provider_request_started` 4281 · `write_ahead` 4294 · `stream_done` 4471 · `native_committed` 4767 · `projected` 5009. So the object has one method per mark, and the split is the marks:

| method (module `persona/chat_turn_commit/<name>.py`) | lines | nested helpers it absorbs |
|---|---|---|
| `TurnCommit.prepare` (`prepare.py`) | 3544–4139 | `_warn` 3644, `_route_turn_write` 3653, `_stamp_finalization` 3664 → methods |
| `TurnCommit.observe` (`observe.py`) | 4140–4223 | — |
| `TurnCommit.run` (`run.py`) | 4224–4470 | `_stream_progress` 4234, `_agent_ready_for_steer` 4246 |
| `TurnCommit.commit_native` (`commit.py`) | 4471–4766 | — |
| `TurnCommit.project` (`project.py`) | 4767–5008 | — |
| `TurnCommit.finalize` (`finalize.py`) | 5009–5133 + 2514–2606 | `_deferred_auto_title` 5072; `_stamp_turn_visibility`, `_stamp_reply_media` |

Fields = the locals every phase reads (the sheet review lists them by AST; the 09-21 plan's estimate is ≤ 25). `_mission_chat_commit_turn(...)` survives as a 20-line function that builds `TurnCommit` and runs the phases in order, so all 23 test patches on it hold. **Behaviour contract:** the `mission_chat_turns` v3 ledger record for a fixture turn is byte-identical before/after (09-21 H3 proof). **Killing mutation:** reorder `commit_native` before `run` → the write-ahead test reds (`native_committed` mark before `stream_done`).

## 5. Dead code found while reading (rows filed in the dead-code queue)

| symbol | lines | evidence |
|---|---|---|
| `_cmd_persona_instance_archive` 5591–5592 | 2 | a shim calling `_cmd_persona_instance_retire`; referenced only by `harness.py`'s parser `func=` — the parser can point at `retire` directly (contract fixture: one `func` target changes, surface unchanged) |
| `_emit_chat_final` 6420 / module-level `_emit_chat_frame` 6427 | 8 | `git grep`: `_emit_chat_final` has ONE production caller (2400, inside `_mission_chat_emit`) and one test; every other `_emit_chat_frame` hit is the emitter's METHOD of the same name (`self._emit_chat_frame`, 6502–6868) — the module-level function's only readers are three test patches (`test_c8_one_order_guards.py:138`, `test_mission_chat_turns_hardening.py:551`, `test_mission_chat_turns_perf.py:361`). Rowed as **test seam** (moves under `tests/_downstream/_seams.py`); the same-name method/function pair is itself a legibility defect the MOVE renames |
| `_persona_chat_fault_injection` 156–161 | 6 | env-driven test seam (`HERMES_PERSONA_CHAT_FAULT`); production reads it in two places — KEEP, but it moves to `tests/_downstream/_seams.py` per 09-21 §4.1's rule only if the reach census shows no field use; rowed as "test seam?" |

The census (program §0.1) found no top-level def in this file with zero references — everything else is reached through the parser or the exec'd namespace.

## 6. Doors (upstream imports; all FIRST — public names, no widening)

`tools.registry` (tool inventory read) · `tools.terminal_tool_lifecycle` · `gateway.session_context` · `agent.title_generator` · `hermes_cli.flag_binding`. All are public, read-only; they route through `harness_parts/_upstream_doors.py` (program §6, Q5) so W0-G6 sees one file.

## 7. Commits

1. **MOVE** `refactor(persona): persona_commands.py → harness_parts/persona/ (16 modules)` — spans byte-identical by the §1 ranges; `__all__`, `__layer__`, the package map docstring; 41 test patch paths retargeted by `scripts/retarget_harness_patches.py` (H1's script); contract fixture byte-identical.
2. **CHANGE** `refactor(persona): TurnCommit phases; steer/target/busy/progress routing as tables; helpers folded` — §2 + §3 + §4 with each killing mutation's red pasted; `[ds-size]` 59 → 58.
3. **DELETE** (dead-code queue, own commit): §5 rows with tombstones.
