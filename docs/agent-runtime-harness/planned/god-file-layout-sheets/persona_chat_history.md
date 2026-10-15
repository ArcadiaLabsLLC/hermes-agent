# Layout sheet — `agent_runtime/persona_chat_history.py` (lane R2)

Base: `main` @ `bf4377f226` · 2,325 raw / 1,753 code / 60 top-level defs · longest `persona_chat_history_summary` 270 (273–542, depth 4) · chains 0 · `str==` 24 · `isinstance` 26 · owner doc `docs/agent-runtime-harness/05-chat-turn-lane.md` (the operator-facing transcript). 8 production importers (`snapshot` takes five names incl. `_SECRET_RE` and `_canonical_persona_id`; `persona_assignments` takes the `_default_session_db` wrapper; `tools/agent_chat_tool` takes `persona_chat_session_messages`), 20 test files, 3 private pins. Three W0-G5 rows, three W0-G7 rows, three W0-G3 rows.

**Package `agent_runtime/persona_chat_history/`** (named after the file — not the 09-21 `persona_chat/history/`). The 09-21 R2 row (`summary, curation, messages, revisions`) stands; `revisions` is folded into `curation` (`_history_revision` + the cursor pair are 40 lines) and `vocabulary`, `trace`, `trace_rows`, `history_rows`, `markers`, `text` are added.

## 1. Section map → target modules

| lines | what is there | → module | layer |
|---|---|---|---|
| 1–255 | imports; `PERSONA_*_KIND` ×6 (59–96), `TerminalTurnMarker` 100, `TERMINAL_TURN_MARKERS` 108, `_UNKNOWN_MARKER_STATES`, `PERSONA_TURN_SILENT_KIND`, `SILENT_TURN_MARKER_TEXTS` 167, `_CHAT_INSTANCE_MODES`, **`CHAT_READ_UNAVAILABLE` / `CHAT_READ_FAILED` / `CHAT_SCOPE_UNRESOLVED` / `CHAT_SCOPE_MISMATCH` / `CHAT_REDACTION_UNKNOWN` 214–229**, tails and limits 231–246, `_SECRET_RE` 252, `_ASSISTANT_CLIENT_MESSAGE_ID_RE`; `logical_persona_chat_client_message_id` 256, `canonical_persona_chat_turn_id` 266 | `persona_chat_history/vocabulary.py` (~200): `ChatReadStatus(StrEnum)` for the five read/scope reasons — rule 14 (the strings unchanged: they are the launcher contract at 634–636) | models |
| 273–543 | `persona_chat_history_summary` 273 (270, depth 4) | `persona_chat_history/summary.py` (~280) | lanes |
| 545–717 | `persona_chat_session_messages` 545 (155), `_with_chat_scope` 702 | `persona_chat_history/messages.py` (~170) | lanes |
| 718–956 | `persona_chat_trace_summary` 718 (133, depth 4, + `_accumulator` 766), `_supports_for_session`, `_fetch_trace_events` 857, `_TraceAccumulator` 873, `_retain_trace_tail` 918, `_priority_trace_entry`, `_trace_event_sort_key` | `persona_chat_history/trace.py` (~220) | stores |
| 1926–2205 | `_trace_entry` 1926 (115), `_first_safe_trace_text`, `_trace_summary` 2051, `_safe_trace_text`, `_safe_trace_operator_line`, `_safe_trace_operator_block` 2095, `_safe_trace_operator_paths` 2112, `_safe_trace_int` 2129, `_safe_trace_file_labels` 2138, `_safe_trace_list_text`, `_looks_pathish` 2169, `_bounded_message_tail`, `_trace_fetch_limit` 2183, `_INTERNAL_SCAFF…` 2197 | `persona_chat_history/trace_rows.py` (~180 after §4's folds to `redaction`) | policy |
| 957–1402 | `_list_sessions` 957, `_get_session_row`, `_default_session_db` 1004, `_mission_assignment_for` 1016, `_history_row` 1047 (119), `_lineage_aggregate` 1168 (68), `_cache_policy_fields`, `_chat_model_fields`, `_model_config`, `_persisted_persona_instance_id`, `_persona_chat_candidate_sort_key`, `_token_usage_fields` 1321, `_infer_persona_id`, `_persona_token_from_chat_session_tail`, `_canonical_persona_id` 1372, `_fallback_title`, `_safe_recent_messages` 1393 | `persona_chat_history/history_rows.py` (~330) | stores |
| 1403–1713 | `_safe_curated_messages` 1403 (251, depth 3), `_history_revision` 1656, `_encode_history_cursor`, `_decode_history_cursor`, `_carry_run_budget` 1699 | `persona_chat_history/curation.py` (~300) | policy |
| 1714–1867 | `_silent_turn_marker_row` 1714 (61), `_terminal_turn_marker_rows` 1777 (59), `_ordered_message_rows` 1838 | `persona_chat_history/markers.py` (~150) | policy |
| 1868–1925 | `_iso_timestamp` 1868 (56, + `_format`) | `agent_runtime/clock.py` as `iso_timestamp(value)` (§2) | models |
| 2206–2325 | `_curate_chat_message_text` 2206, `_decision_summary_text`, `_safe_message_role` 2257, `_safe_display_text` 2268, `_safe_display_body_text`, `_mask_secret_lines` 2302, `_safe_chat_body_text`, `_safe_int` 2320 | `persona_chat_history/text.py` (~90 after the folds) | policy |

10 modules + two folds out, none over 330. Edges: `summary`/`messages` → `history_rows`/`curation`/`markers`/`trace` → `text`/`trace_rows`/`vocabulary` (down); `history_rows` → `chat_session_scope`, `persona_chat_continuity`, `cache_policy` (lazy, leaves). The module-level import of `persona_assignments` (17–21: `persona_instance_id_for`, `retired_persona_instance_ids`, `safe_assignment_text`, `safe_assignment_token`) lands on R1's `identity`/`retire`/`serde` — down once R1 declares; and the cycle back (`persona_assignments.py:204` → `_default_session_db`) closes when the wrapper goes (§5).

## 2. W0-G5 ladder sites → dispatch tables (the CHANGE commit)

| site (base line) | fixture row | replacement | killing mutation |
|---|---|---|---|
| `_safe_message_role` 2257–2266 | `\|ladder\|role` — `in {"user","operator"}` → `operator`, `in {"assistant","agent"}` → `agent`, `== "system"` → `system` | `vocabulary.MessageRole(StrEnum)` (`OPERATOR`, `AGENT`, `SYSTEM`) + `WIRE_ROLES: Mapping[str, MessageRole]` (`user`/`operator`/`assistant`/`agent`/`system`); `MessageRole.from_wire(value)` = one lookup | map `assistant` → `OPERATOR` → `tests/agent_runtime/test_persona_chat_history_curation.py` reds (agent replies rendered as operator rows) |
| `_safe_curated_messages` 1501–1621 | `\|ladder\|role` — inside the per-row loop, `role == "agent" and logical_client_message_id` (1501, 1530, 1621) / `role == "operator"` (1506, 1588, 1617) select the curation of the row | `curation.ROLE_CURATORS: Mapping[MessageRole, Callable[[CurationState, row], None]]` — one `_curate_operator_row`, one `_curate_agent_row` (which owns the pre-trace-ack 1561, relay/harness attribution 1573–1581 and C8 ordering 1612 arms), the loop = `ROLE_CURATORS[role](state, row)`; a role with no curator is skipped by the table, not by a fall-through | swap the two curators → the same test file's silent-turn case reds (an operator row treated as an agent reply consumes the silent-turn marker) |
| `_iso_timestamp` 1868–1924 | `\|isinstance\|value` — `datetime` / `int, float` / `str` (which itself tries epoch then ISO) | `clock.iso_timestamp` built on `functools.singledispatch` — the standard-library spelling of an `isinstance` table: `@iso_timestamp.register(datetime)`, `.register(int)`, `.register(float)`, `.register(str)`; the epoch-ms tolerance (1893, 1910) is one helper both numeric arms call; `snapshot._parse_iso_timestamp` 2296 (the read side) becomes `clock.parse_iso` beside it | register `float` with the `str` coercer → the epoch-timestamp case in `test_persona_chat_history_curation.py` reds (`ValueError` → `None`, the row loses its `ts`) |

`str==` 24 → ≤ 6.

## 3. W0-G7 floor rows (3) and the decomposition

| row | lines / depth | phases (comment map) | after |
|---|---|---|---|
| `persona_chat_history_summary` 273 | 270 / 4 | task-bound mirror 323 · candidate discovery 358–381 (source pool, broad pool, retirement archive read at most once 364, compression roots 378) · dedupe + persisted-binding check 427–435 · live mission sessions + R3 anchor 459–481 · creation-order directory + bound 502–537 | `HistorySummary.candidates → bind_check → live_missions → rows`, ≤ 70 each, depth ≤ 2; the archive listing is read once in `candidates` and carried as a field |
| `persona_chat_session_messages` 545 | 155 / 2 | per-conversation scope resolution 565–602 (two-authority mismatch 580 → `CHAT_SCOPE_MISMATCH`) · read 620 · "a read that did not happen is not an empty conversation" 634 | `resolve_scope → read → envelope`; the honesty envelope (status, redaction) is one function returning `ChatReadStatus` |
| `_safe_curated_messages` 1403 | 251 / 3 | silent-turn bookkeeping 1457–1472 (journal read once) · per-row curate 1480–1531 · residue/attribution/ordering arms 1561–1629 · redaction verdict 1651 | the `ROLE_CURATORS` table (§2) with a `CurationState` object holding the loop's seven accumulators; the function ≤ 60 |

`persona_chat_trace_summary` 718 (133, depth 4) is under 150 but AT the depth limit — the `_accumulator` closure becomes `_TraceAccumulator.from_events` in the MOVE's companion `style:` commit so it cannot reach 5.

## 4. Helpers that unify

| here | duplicate of (fixture row) | authority |
|---|---|---|
| `_safe_int` 2320 | `mission_chat_turns._safe_int` 1596, `prompt_observability._safe_int` 3710 | `serde.safe_int` (R2 folds all three; prompt_observability's sheet §4 names the same owner) |
| `_safe_trace_int` 2129 | byte-equal to `profile_runner._safe_exit_code` 2993 | `serde.safe_int` |
| `_safe_display_text` 2268 | `observability._safe_display_text` 368 | `redaction.safe_display_text` — the operator-scrubber owner R3's profile_runner sheet lands; whichever lane is first creates the name, the other folds |
| `_safe_trace_operator_line/block/paths` 2086–2128, `_safe_trace_file_labels` 2138, `_looks_pathish` 2169, `_mask_secret_lines` 2302 | `profile_runner._render_operator_kv_block` 2585, `_safe_operator_paths` 2792, `_safe_file_labels` 2829, `_looks_sensitive_or_pathish` 3043 — one family, two spellings | `agent_runtime/redaction.py` (same rule) |
| `_iso_timestamp` 1868 | `snapshot._parse_iso_timestamp` 2296, `persona_assignments._as_utc` 421 | `clock.iso_timestamp` / `clock.parse_iso` / `clock.as_utc` (§2) |
| `_canonical_persona_id` 1372 | `persona_assignments.identity.normalize_persona_id` + the instance-tail inference 1345–1370 | stays (it composes identity's helper with a session-tail read); made PUBLIC as `canonical_persona_id` because `snapshot` imports it |
| `_default_session_db` 1004 | `chat_session_scope.open_chat_session_db` — a 10-line docstring-carrying wrapper | deleted (§5); callers use `open_chat_session_db` |

## 5. Dead code found while reading

| symbol | lines | evidence |
|---|---|---|
| `_default_session_db` 1004 | 10 | wraps one call; `git grep -nw` → the def, 3 in-file calls, `persona_assignments.py:204` (which creates the module cycle §1) — row: delete, retarget the four calls |
| `_safe_recent_messages` 1393 | 8 | 2 production importers, 5 tests — keep |
| `logical_persona_chat_client_message_id` 256 / `canonical_persona_chat_turn_id` 266 | 8 + 5 | 2 / 1 production callers — keep |

No queue row names this file today; one row filed (the wrapper).

## 6. Doors

None — every import is a fork module or the standard library. W0-G6 private rows: none.

## 7. Commits

1. **MOVE** `refactor(persona_chat_history): persona_chat_history.py → agent_runtime/persona_chat_history/ (10 modules)` — spans byte-identical; `__init__` re-exports the 8 importer names (incl. `_SECRET_RE`, `_canonical_persona_id`, `_default_session_db` for one commit); 3 pins retargeted. **Mutation:** drop `persona_chat_trace_summary` from `__init__` → `snapshot`'s module-level import reds at every build.
2. **CHANGE** `refactor(persona_chat_history): MessageRole + ROLE_CURATORS, clock.iso_timestamp (singledispatch), ChatReadStatus; HistorySummary phases; redaction/serde folds; _default_session_db deleted` — three ladder rows and three floor rows deleted; `[ds-size]` −1.

## 8. Lane and what it must not touch

R2, second of two (after `prompt_observability`, which creates nothing this lane needs; before R2's `mission_chat_turns` and `chat_live_log`). Must not edit in parallel: `persona_assignments.py` (R1 — this lane deletes the wrapper R1's `scan.py` stops importing; the two CHANGEs are ordered R1 first, or this lane keeps the wrapper one more commit — tree wins), `snapshot.py` (R3, last — imports five names, all re-exported), `observability.py`, `mission_chat_turns.py` (the other `_safe_int`/`_safe_display_text` copies fold in their own commits), `tools/agent_chat_tool.py` (T1 — importer, path survives).
