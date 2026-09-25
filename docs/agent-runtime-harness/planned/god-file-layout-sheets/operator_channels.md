# Layout sheet — `agent_runtime/operator_channels.py` (lane R2)

Base: `main` @ `28012c8f8a` · sha256 `5ed656c3260ab046b0177f276d9bbe8330ed84c5ebf63f9aec0d3fe6d19d3c42` · 1,670 raw / 1,394 code / 40 top-level defs · longest `_OperatorChannelBuilder.build` 203 (238–440) · chains 2/0 · `str==` 27 · `isinstance` 26 · owner doc `docs/agent-runtime-harness/07-observability.md` (the Agent Console projection). 2 production importers (`snapshot/sections.py`, `status.py`), both taking `operator_channel_summary`; 8 test files pinning 10 names, seven private (`_CONVERSATION_MESSAGE_CAP`, `_CONVERSATION_TRIMMABLE_KINDS`, `_SETTLED_TOOL_CALL_STATUS`, `_TERMINAL_TURN_MARKER_PRESENTATION`, `_conversation_contract`, `_conversation_history_message`, `_dedupe_conversation_messages`, `_turn_identity_dropped`). One public function, 39 helpers: this file IS its single entry point, and the skeleton is the projection's stages.

**Package named after the file — `agent_runtime/operator_channels/`.** It holds seven of the fork's 106 W0-G5 rows — the most of any file in this batch — and every one of them is the same shape: a wire row's `role`/`kind`/`status` compared against a literal to decide a presentation. Rule 12 says those are tables; the sheet draws three.

## 1. Skeleton (owner ruling 2026-09-25: readability first; modules target 100–300, hard cap 500; no flow over three modules)

```
agent_runtime/operator_channels/
  __init__.py           wiring   the map; re-exports operator_channel_summary and the ten test names
  vocabulary.py         models   the VOCABULARY + coercions module: the two schema versions, _CONVERSATION_MESSAGE_CAP, the kind/status sets (TRIMMABLE_KINDS, TOOL_OK/FAILED_STATUSES, TRACE_HANDOFF/FINAL/BLOCKER_STATUSES — CHANGE), _CHAT_INSTANCE_MODES, _TERMINAL_TURN_MARKER_PRESENTATION, _SETTLED_TOOL_CALL_STATUS, the two regexes; the safe coercions (_safe_conversation_text/_list, _parse_time, _safe_instance_id, _safe_session, _display_name_from_history, first_present_text)  (~110)
  instances.py          policy   which instance a channel is: _channel_key_for_instance, _canonical_instance, _newest_instance, _source_instance_ids_conflict, the recency helpers, _merged_trace + its keys, AND the ancestry graph (_operator_conversation_relationships)  (~215)
  summary.py            lanes    operator_channel_summary + _OperatorChannelBuilder (build as phases after the CHANGE)  (~320)   entry: operator_channel_summary
  contract.py           lanes    one channel's conversation: _conversation_contract, _settle_terminal_tool_calls, _turn_identity_dropped/_mismatched, _apply_conversation_cap, _order/_dedupe (DEDUPE_RULES after the CHANGE), the sort keys  (~230)   entry: _conversation_contract (test-pinned)
  history_messages.py   policy   a curated history row → a conversation message: _conversation_history_message (HISTORY_ROW_SHAPES after the CHANGE), _carry_turn_seq, _carry_history_run_budget, _conversation_assignment_message  (~190)   entry: _conversation_history_message (test-pinned)
  trace_messages.py     policy   a trace entry → conversation messages: _conversation_trace_message, _conversation_tool_call_messages, _tool_call_message, the tool-detail merge, _conversation_kind_from_status, _conversation_title_for_kind  (~250)
```

Per entry point, the modules an agent opens (the entry's module plus the modules of what it calls directly; `vocabulary` is read like a table and not counted; `persona_chat_history`, `transcript_order`, `persona_assignments` are outside the package):

| entry point | opens | count |
|---|---|---|
| `operator_channel_summary` (snapshot, status) | `summary` → `instances` → `contract` | 3 |
| `_conversation_contract` (from `summary`; test-pinned) | `contract` → `history_messages` → `trace_messages` | 3 |
| `_conversation_history_message` (test-pinned) | `history_messages` | 1 |
| `_dedupe_conversation_messages` / `_turn_identity_dropped` (test-pinned) | `contract` | 1 |

Floor rule (ruling 3): the first draft had `relationships.py` (83 lines: the ancestry graph) and `text.py` (60 lines: the coercions) apart; both sub-100, so the graph joins `instances` (it is a graph OVER instances) and the coercions join `vocabulary` (a wire word and the function that reads it safely are one table). No module is drawn above 320.

### 1.1 Section map → target modules

| lines | what is there | → module | layer (from imports) |
|---|---|---|---|
| 1–22 | imports (`.models`, `persona_assignments` ×3, `redaction`, `run_budget.ACCOUNTING_KEY`, `persona_chat_history` ×8 incl. the private `_canonical_persona_id`, `relay_policy`, `transcript_order` ×2) | `operator_channels/__init__.py` | wiring |
| 24–81, 1344–1385, 1633–1670 | `OPERATOR_CHANNELS_SCHEMA_VERSION` 24, `OPERATOR_CONVERSATION_SCHEMA_VERSION` 28, `_CONVERSATION_MESSAGE_CAP` 33, `_CONVERSATION_TRIMMABLE_KINDS` 34, `_TOOL_OK_STATUSES` 35, `_TOOL_FAILED_STATUSES` 36, `_CHAT_INSTANCE_MODES` 38, `_TERMINAL_TURN_MARKER_PRESENTATION` 48, `_SETTLED_TOOL_CALL_STATUS` 65, `_SECRET_RE` 70, `_TELEMETRY_SUMMARY_RE` 71; `_safe_conversation_text` 1344, `_safe_conversation_list` 1368, `_conversation_message_sort_key` 1379; `_parse_time` 1633, `_safe_instance_id` 1650, `_safe_session` 1654, `_display_name_from_history` 1658, `_first_text` 1665 | `operator_channels/vocabulary.py` — imports `persona_chat_history` (the `PERSONA_*_KIND` words), `redaction`, `persona_assignments` | models |
| 443–528, 1477–1630 | `_operator_conversation_relationships` 443; `_channel_key_for_instance` 1477, `_canonical_instance` 1489, `_newest_instance` 1513, `_source_instance_ids_conflict` 1517, `_instance_recency` 1574, `_latest_history` 1585, `_row_recency` 1591, `_merged_trace` 1599, `_trace_entry_key` 1619, `_trace_entry_sort_key` 1626 | `operator_channels/instances.py` — imports `vocabulary`, `.models.PersonaInstance` | policy |
| 84–440 | `operator_channel_summary` 84, `_OperatorChannelBuilder` 187 (`build` 238–440) | `operator_channels/summary.py` — imports `vocabulary`, `instances`, `contract` | lanes |
| 531–578, 581–736, 1278–1324, 1388–1470 | `_turn_identity_dropped` 531, `_turn_identity_mismatched` 557, `_conversation_contract` 581, `_settle_terminal_tool_calls` 677, `_apply_conversation_cap` 1278, `_order_conversation_messages` 1388, `_dedupe_conversation_messages` 1415, `_latest_message_timestamp` 1468 | `operator_channels/contract.py` — imports `vocabulary`, `history_messages`, `trace_messages`, `transcript_order` | lanes |
| 743–929, 1016–1062 | `_conversation_history_message` 743, `_carry_turn_seq` 915, `_carry_history_run_budget` 921, `_conversation_assignment_message` 1016 | `operator_channels/history_messages.py` — imports `vocabulary`, `persona_chat_history`, `run_budget`, `relay_policy` | policy |
| 932–1013, 1065–1275, 1327–1341 | `_conversation_trace_message` 932, `_conversation_tool_call_messages` 1065, `_tool_call_message` 1170, `_TOOL_DETAIL_STR_FIELDS` 1227, `_TOOL_DETAIL_INT_FIELDS` 1249, `_merge_tool_detail` 1252, `_tool_status_token` 1269, `_conversation_kind_from_status` 1327, `_conversation_title_for_kind` 1335 | `operator_channels/trace_messages.py` — imports `vocabulary` | policy |

Edges point down: `summary` → `instances`, `contract` → `history_messages`, `trace_messages` → `vocabulary`. No lazy imports exist in this file and none are created; no cycle.

## 2. Routing sites → tables (the CHANGE commit)

| site (base line) | fixture row | replacement | killing mutation |
|---|---|---|---|
| `_conversation_history_message` 756–761 (`role == "user"` → operator, `"assistant"` → agent, `not in {...}` → refuse) and 806–830 (the `is_pre_trace_ack` / `is_relayed_message` / `is_harness_delivery` decision over `(role, kind)`, then the `if/elif/else` on role choosing `default_kind`, `actor_persona_id`, `actor_instance_id`) | `\|ladder\|role` | two things. (a) 756–761 is `persona_chat_history/vocabulary.py::WIRE_ROLES` — the fork ALREADY has this table (`user`/`operator` → `MessageRole.OPERATOR`, `assistant`/`agent` → `AGENT`, `system`); rule 15 before rule 12: the site becomes `MessageRole.from_wire(role)` and refuses on `None` (the `proof`/`blocker` roles the set at 760 admits are trace roles that never reach this function through history — the lane greps `role.*proof` in `persona_chat_history/` to confirm before narrowing, and keeps them if a history writer emits one). (b) 806–830 becomes `history_messages.HISTORY_ROW_SHAPES: tuple[tuple[Callable[[MessageRole, str], bool], RowShape], ...]` where `RowShape(kind, actor_persona, actor_instance)` — the harness-delivery row, the relayed row, the pre-trace ack, the plain agent/operator/system rows, matched first-hit in the order 806–830 already tests them | swap the harness-delivery and relayed rows → `tests/agent_runtime/test_operator_channels.py::test_conversation_history_message_relayed_attributes_sender_and_names_it` and `tests/agent_runtime/test_delivery_turn_attribution.py::test_a_delivery_projects_as_a_delivery_not_as_the_operator` red |
| `_conversation_kind_from_status` 1327 (`status in {"handoff", …}` → handoff; `in {"done", "completed", …}` → final) and `_conversation_trace_message` 989 (`status in {"blocked", "failed", "needs_input"}` → blocker) | `\|vocab\|completed`, `\|vocab\|done`, `\|vocab\|blocked`, `\|vocab\|failed` — four words fork-wide only because `states.py` declares them; the TRACE status vocabulary is the task trace's, declared nowhere | **not enum-ised** (batch-1 rule): `vocabulary.TRACE_HANDOFF_STATUSES`, `TRACE_FINAL_STATUSES`, `TRACE_BLOCKER_STATUSES` as `frozenset[str]` constants read by name in their two readers; `_conversation_kind_from_status` becomes a two-row lookup over those sets. The gate's arm counting `states.py` members here is the class defect rowed once (report §rows) | move `passed` from `TRACE_FINAL_STATUSES` to `TRACE_HANDOFF_STATUSES` → `::test_operator_channel_projects_canonical_goal_conversation_and_filters_telemetry` reds (a passed step renders as a handoff) |
| `_settle_terminal_tool_calls` 724 (`message.get("status") != "running"`) | `\|vocab\|running` | `vocabulary.TOOL_CALL_RUNNING = "running"` read by name (the same treatment); `_SETTLED_TOOL_CALL_STATUS` 65 is its partner and already a constant | replace with `TOOL_OK_STATUSES` membership → `::test_operator_conversation_projects_interrupted_turn_marker_and_settles_running_tools` reds |
| `_dedupe_conversation_messages` 1415–1465 (`kind == "handoff" and display_title == "Subagent prompt"` / `kind == "agent_update"` / `kind == "thinking_summary"`) | `\|ladder\|message.get('kind')` | `contract.DEDUPE_RULES: Mapping[str, Callable[[message, DedupeState], bool]]` keyed by kind — `handoff` (assignment id seen), `agent_update` (text already a flow message), `thinking_summary` (text is the reply or already seen); the loop is `rule = DEDUPE_RULES.get(kind); if rule and rule(message, state): continue` | swap the `agent_update` and `thinking_summary` rules → `::test_native_reasoning_mints_thinking_row_and_reply_echo_is_deduped` reds |

W0-G7 floor rows (2):

| row | lines / depth | phases (comment map) | after |
|---|---|---|---|
| `_OperatorChannelBuilder.build` 238 | 203 / 1 | canonical id 255 · source instances + conflict 269–300 · the conversation 317 · identity checks 338–353 · newborn predicate 363–376 · session_without_history 377 · dormant 393–415 · the row 416 | `build` = `_identity() → _sources() → _conversation() → _warnings() → _row()`, ≤ 45 each; the two predicates (newborn 363, dormant 393) become named functions in `instances`, which `::test_operator_channel_newborn_chat_emits_no_warnings` and `::test_operator_channel_dormant_instance_has_no_trace_empty_warning` pin |
| `_conversation_history_message` 743 | 170 / 2 | text/role/redaction gates 753–764 · the terminal-marker presentation 768–801 · the shape decision 806–830 · the message 850 · runtime_context 865 · delivery block 883 · relay/ids 895–906 | `HistoryMessage.gates → marker → shape (HISTORY_ROW_SHAPES) → message → annotations`, ≤ 40 each |

`str==` 27 → ≤ 6 at review (the remaining compares are `refs.get("source")` boundary guards).

## 3. Helper folds

| here | duplicate of | verdict |
|---|---|---|
| `_first_text` 1665 (`*values`, via `safe_assignment_text`) | `stream._first_text` 1892 (`payload, *keys`, via `optional_text`) — W0-G3 `name_groups[8]` | NOT a fold (different signatures and coercions); renamed `first_present_text` here, which retires the name group — the stream sheet keeps its own under its name |
| `_parse_time` 1633 | `running_work._parse_iso` 337 (→ epoch float), `snapshot/warnings._parse_iso_timestamp` 393 (→ datetime), `clock.iso_timestamp` (→ normalised string) | the same question asked three ways; `clock.parse_iso(value) -> datetime \| None` is CREATED here (R2 owns `clock` additions this batch) from `_parse_time`'s body, and the snapshot copy folds onto it in the CHANGE (a one-line retarget in R3's landed package, "tree wins"); `running_work` keeps its float form (its own sheet) |
| `_safe_conversation_text` 1344 | `serde.safe_text` / the nine `_safe_text` | NOT a fold: this one drops a secret-bearing line whole (`_SECRET_RE`) and bounds; unique name, stays in `vocabulary` |
| `_canonical_persona_id` (imported private from `persona_chat_history`) | fork private cross-import | the CHANGE reads `persona_chat_history.canonical_persona_id` (public) — R2's own package, one rename |

## 4. Upstream doors

None — every import is fork code. W0-G6 `private_upstream_imports` rows for this file: none; the `undeclared` row closes with the MOVE. No widening.

## 5. Dead code (verdict + the grep the lane runs)

No queue row names this file. `git grep -nw` over the 40 defs: `_latest_message_timestamp` 1468 ← 670, `_newest_instance` 1513 ← 1509/1510, `_conversation_title_for_kind` 1335 ← 1005 — every private has an in-file caller (the lane pastes the 39-line grep). `_CHAT_INSTANCE_MODES` 38 is read at 1481. Nothing filed.

## 6. Positive controls — land in the MOVE, before `HISTORY_ROW_SHAPES` and `DEDUPE_RULES` (ruling Q6)

Every §2 mutation names a test that exists today (§ header lists the eight files), and the one arm no mutation names — the `system` role at 762–764 (`default_kind = "system_message"`) — is reached by two cases already (`grep -c '"role": "system"' tests/agent_runtime/test_operator_channels.py` → 2). The tables therefore land against a suite that reaches every arm they rewrite; no new control is owed, and the lane's positive proof is the four §2 mutations, run and pasted.

## 7. MOVE hash-proof plan, then the CHANGE

1. **MOVE** `refactor(operator_channels): operator_channels.py → agent_runtime/operator_channels/ (6 modules)` — spans byte-identical with the sha256 table (one row per §1.1 span); `__init__` re-exports `operator_channel_summary` and the ten test names. **Killing mutation for the MOVE:** drop `summary` from `__init__` → `agent_runtime/snapshot/sections.py` fails to import `operator_channel_summary` → `tests/agent_runtime/test_operator_channels.py` reds at collection. `[ds-size]` −1.
2. **CHANGE** `refactor(operator_channels): MessageRole.from_wire + HISTORY_ROW_SHAPES; TRACE_*_STATUSES by name; DEDUPE_RULES; build/HistoryMessage phases; clock.parse_iso; first_present_text` — §2 + §3 with each red pasted; five of the seven W0-G5 rows are deleted from the fixture (the two `vocab` rows on `completed`/`done` and the three on `blocked`/`failed`/`running` close by the constant-name reading — the fixture rows are deleted only if the gate stops counting them, which it will, since a `Name` is not a `Constant`).

## 8. Lane and what it must not touch

R2 (exec lane B3), third of its three, disjoint from the other two. Must not edit in parallel: `snapshot/` (R3's landed package — the `_parse_iso_timestamp` fold is one retarget line and nothing else), `status.py`, `persona_chat_history/` (R2's landed package — the `canonical_persona_id` rename is one line), `transcript_order.py`, `run_budget.py`, `relay_policy.py`; `clock.py` gains `parse_iso` and nothing else.
