# Layout sheet — `agent_runtime/mission_chat_turns.py` (lane R2 · exec lane 2B-B)

Base: `main` @ `28012c8f8a` · 1,613 raw / 1,141 code / 46 top-level defs · longest `_safe_elements` 84 (depth 4) · chains 1/0 · `str==` 4 · `isinstance` 32 · W0-G5 fixture row `safe_provider_refusal|isinstance|reset_at` · W0-G7 fixture row `_gc_session_files` (depth 5) · sha256 `b53577ec4971034c4d641a5616f89ab8a8a484cf660fab4f779522cf06173a8f` · owner doc `docs/agent-runtime-harness/05-chat-turn.md` (the turn journal). 15 production importers (the `harness_parts/persona/chat_*` family incl. `chat_turn_commit/{admit,run,settle}`, `persona_chat_history/{curation,markers,vocabulary}`, `persona_chat_continuity`, `running_work`, `dispatch_delivery`, `chat_turn_presence`, `discussions/native`), 27 test files. Importers take the state vocabulary (the `TURN_STATE_*` names and the six frozensets), `MissionChatTurnPersistOutcome`, the four journal verbs, the four reads, `safe_turn_profile_timing`, `TURN_PROFILE_TIMING_KEY`; tests additionally import `_safe_todo_state`, `_store_dir` and patch `_RETENTION_MAX_TURNS_PER_SESSION` ×5, `_RETENTION_MAX_SESSIONS` ×2, `_LOCK_TIMEOUT_SECONDS` ×2, `_write_session_file` ×2.

**Package `agent_runtime/mission_chat_turns/`** (the sibling `mission_chat_turn_context.py` and `mission_chat_phases.py` stay flat files; no collision).

## 1. Skeleton (owner rulings 2026-09-25) — this text IS the package `__init__` map

```
agent_runtime/mission_chat_turns/
  __init__.py   wiring  the map; re-exports the vocabulary, the outcome enum, the verbs, the reads, the test seams
  states.py     models  VOCABULARY/TABLE module (floor-exempt): the turn states, the lifecycle buckets, the decision sets, the transition table, the import-time guard, next_turn_state, the two state readers
  storage.py    stores  the store on disk: layout constants + every path, the per-session lock (over file_locks; yields acquired: bool), read / write / archive of one session file, the per-session turn cap, the session-file GC, the one-time monolith migration
  records.py    policy  the durable record shape: _safe_record, the journal metadata whitelist, profile timing, provider refusal; the elements (segment / tool) and their bounded sub-shapes (todo state, exit code, file labels)
  journal.py    lanes   the four writes (persist / transition / abandon / mark stale) over _mutate_session — the ONE write chokepoint
  reads.py      lanes   elements / record / records / inflight roots / inflight rows
```
Entry points and the modules an agent opens: `persist_mission_chat_turn` / `transition_mission_chat_turn` (`chat_turn_commit/*`, `chat_admission`) → `journal.py` → `storage.py` (lock, read, write, cap) and `records.py` (the record's shape) — **2** (+ the `states` table for `next_turn_state` and the transitions); `mission_chat_turn_records` (`persona_chat_history`) → `reads.py` → `storage.py`, `records.py` — 2 (+ `states`); `inflight_chat_session_roots` then `mark_stale_inflight_turns_interrupted` (`serve/boot_phases`) → `reads.py` / `journal.py` → `storage.py` — 2 each (+ `states`). Layers: lanes → policy (`records`) → models (`states`); lanes → stores (`storage`); `states.py` imports nothing in the package.

### 1.1 Section map → target modules (sizes are raw / est. code; the 100/300/500 bars are on code lines)

| lines | what is there | → module | raw / code | layer |
|---|---|---|---|---|
| 1–24 | imports (`paths`, `persona_assignments.safe_assignment_*` — see the edge note, `serde`, `mission_chat_phases`, `run_budget`) | `__init__.py` | ~40 / 25 | wiring |
| 76–351, 356–401, 1453–1465 | `TURN_STATE_*`, `JOURNAL_/LEGACY_/ALL_TURN_STATES`, the three buckets, the three decision sets, `_LEGACY_TO_JOURNAL_STATE`, `_JOURNAL_TRANSITIONS`, `_guard_turn_state_vocabulary` + its call, `MissionChatTurnPersistOutcome`, `next_turn_state`, `_safe_turn_state`, `_record_state` | `mission_chat_turns/states.py` | ~340 / 200 | models |
| 38–75, 823–1156 | the constants; `_apply_session_turn_cap`, `_gc_session_files`, `_migrate_legacy_if_present`; `_file_lock`, `_lock_fd_exclusive_nonblocking`, `_unlock_fd`; `_store_dir` … `_iter_session_files`; `_read_session`, `_read_session_map`, `_write_session_file`, `_session_file_recency`, `_archive_session_file` | `mission_chat_turns/storage.py` (`paths.store_root`, `hashlib`, `os`, `json`; `file_locks` after §4) | ~380 / 265 | stores |
| 1164–1184, 1187–1471, 1474–1613 | `_safe_record`, `_JOURNAL_TEXT_FIELDS`, `_JOURNAL_RUN_BUDGET_FIELD`, `TURN_PROFILE_TIMING_KEY` + `_PROFILE_TIMING_*`, `safe_turn_profile_timing`, `_JOURNAL_EMPTY_PRESERVING_FIELDS`, `_JOURNAL_PROVIDER_REFUSAL_FIELD`, `_PROVIDER_REFUSAL_TEXT_FIELDS`, `safe_provider_refusal`, `_safe_journal_metadata`, `_utc_now_iso`; `_safe_elements`, `_TODO_STATE_*`, `_safe_todo_state`, `_safe_exit_code`, `_safe_file_label` | `mission_chat_turns/records.py` (`serde`, `mission_chat_phases`, `run_budget`, lazy `auxiliary_chat`) | ~450 / 280 | policy |
| 404–577, 643–689, 777–820 | `persist_mission_chat_turn`, `transition_mission_chat_turn`, `abandon_mission_chat_turn`, `mark_stale_inflight_turns_interrupted`, `_mutate_session` | `mission_chat_turns/journal.py` | ~300 / 210 | lanes |
| 580–640, 692–774 | `mission_chat_turn_elements`, `mission_chat_turn_record`, `mission_chat_turn_records`, `inflight_chat_session_roots`, `inflight_turn_rows` | `mission_chat_turns/reads.py` | ~145 / 100 | lanes |

Refolded under the no-fragmentation ruling: the earlier draft's `layout.py` (~75 code), `session_lock.py` (~30), `files.py` (~60), `retention.py` (~100) and `elements.py` (~110) drew `persist` across five modules; layout/lock/files/retention are one thing (the store on disk) and elements are part of the record's shape. Result: 5 modules + the map, none over 280 code lines. Edges: `journal`/`reads` → `storage`, `records` → `states` (down). **The upward edge and who breaks it:** `records.py` (policy) takes `safe_assignment_text`/`safe_assignment_token` from `persona_assignments` (a `stores` package) — W0-G6 reds that once declared. Both names are OWNED by `serde` (serde.py:299, 328) and `persona_assignments/__init__` merely re-exports them (lines 57–58); the MOVE imports them from `serde`, which is the one-line respelling that turns the edge down. No lazy cycle exists in this file.

## 2. Routing sites (rule 12)

| site (base line) | fixture row | replacement | killing mutation |
|---|---|---|---|
| `safe_provider_refusal` 1382–1390 | `\|isinstance\|reset_at` — bool / number / str arms on one name | a `serde.number_or_bounded_text(value, *, limit)` owner (bool → `None`, int/float → itself, str → `safe_text`, else `None`): the coercion moves DOWN into serde and the ladder row is deleted | make the owner answer `None` for numbers → `tests/agent_runtime/test_mission_chat_turns_hardening.py`'s provider-refusal case reds (`safe_provider_refusal` has 1 test file) |
| `_safe_elements` 1488–1530 | not a fixture row (2 arms) | `kind not in ELEMENT_KINDS` guard + `_ELEMENT_FIELDS: Mapping[str, Callable[[dict], dict]] = {"segment": _segment_fields, "tool": _tool_fields}` — the per-kind builders lift out of the loop (depth 4 → 2). **`ELEMENT_KINDS` is a plain tuple, not `Final`/`StrEnum`**: `segment`/`tool` are spelled in `persona_chat_history`, `stream`, `progress` and the launcher, and W0-G5 arm (c) reads every `Final` member as a routed word fork-wide (fork-hygiene row, lane R4 2026-09-25) | swap the two builders → `test_mission_chat_turns_per_session.py`'s tool-element case reds |
| `_LEGACY_TO_JOURNAL_STATE` 216, `_JOURNAL_TRANSITIONS` 220, the six frozensets | already tables with an import-time guard | **the batch's exemplar of rule 12 and rule 14** (a vocabulary in ONE table, a guard that fails at import); moved, not touched |
| `next_turn_state` 391–401 | five ordered guards over the vocabulary | guards; stays |

`isinstance` 32 → ≤ 20 at review (the element builders and `_safe_journal_metadata` keep the boundary checks; the `reset_at` ladder leaves).

## 3. W0-G7 floor row (1) and the near-miss

| row | lines / depth | after |
|---|---|---|
| `_gc_session_files` 854 | 45 / **5** | lift the per-candidate body (886–896) into `_archive_if_idle(path) -> bool` (probe the lock non-blocking, skip in-flight, archive) → depth 3; the fixture row is deleted |
| `_safe_elements` 1474 | 84 / 4 | the §2 table takes it to depth 2 |

## 4. Helper folds

| here | owner | verdict |
|---|---|---|
| `_lock_fd_exclusive_nonblocking` 994 / `_unlock_fd` 1006 | fixture rows (`== persona_chat_continuity._try_lock/_unlock`); owner `file_locks.try_lock_exclusive/unlock` (program rule 15) | FOLD **with one named difference**: the owner works on an open HANDLE and pads an empty file to one byte on Windows; this works on a raw `os.open` fd and locks byte 0 of a possibly-empty `.lock` file. `storage.try_session_lock` opens with `open(path, "r+b")` (creating first) and hands the handle over; the only observable change is one `0` byte in each `.lock` file. Killing mutation: make `try_session_lock` yield `True` on `LockUnavailable` → `test_mission_chat_turns_per_session.py`'s `SKIPPED_LOCK_TIMEOUT` case reds |
| `_file_lock` 964 | fixture row (`_file_lock: locks.py, mission_chat_turns.py`) | NOT a fold onto `locks._file_lock`: that one RAISES on timeout, this one yields `acquired: bool` and the whole journal is written against the bool (the typed `SKIPPED_LOCK_TIMEOUT` outcome). `storage.try_session_lock(path, timeout) -> Iterator[bool]` keeps the contract over `file_locks`; the duplicate-body row closes because the fd helpers go |
| `_utc_now_iso` 1468 | `mission_chat_phases._utc_now_iso` 163, `persona_chat_continuity._utc_now_iso` 696 — three copies of the MICROSECOND `Z` spelling | NOT a fold onto `clock.now_iso` (milliseconds — `started_at` ORDERING keys on the stamp, and a coarser stamp changes replay order between two turns started in the same millisecond). This lane creates **`clock.now_iso_micro()`** and folds its copy; `mission_chat_phases` folds in the same commit (a flat sibling this lane may edit — one line); `persona_chat_continuity` folds in its own lane. Program §4 gains the row |
| `_safe_file_label` 1606 | `redaction.safe_file_labels` | NOT a fold — the owner drops anything pathish and takes the basename; the journal keeps the label as given and drops only `_SENSITIVE_FILE_MARKERS`. Folding would empty `files` on every tool row. Named; the marker tuple stays beside its one reader |
| `_write_session_file` 1099 | `serde.write_json_atomic` | NOT a fold — compact separators, no indent, and the Windows `winerror 5/32/33` rename retry the owner does not carry; bytes on disk would change |
| `safe_assignment_text/_token` | `serde` (see the §1.1 edge) | respelled import, no body change |

## 5. Doors

None: stdlib, `paths`, `serde`, `mission_chat_phases`, `run_budget`, `auxiliary_chat` (lazy). W0-G6 private rows: none. No widening.

## 6. Dead code found while reading

| symbol | evidence | verdict |
|---|---|---|
| `_guard_turn_state_vocabulary` 271 | dead-code queue row (line 47) says 0 hits; the guard is CALLED at line 351 at import time (`pragma: no cover` hides it from coverage, not from the interpreter) | **REFUTED** — the import-time contract; row deleted, closing commit named |
| `next_turn_state` 368, `JOURNAL_TURN_STATES`, `LEGACY_TURN_STATES`, `safe_provider_refusal` | 0 production importers by name; each has an in-file caller (`persist_mission_chat_turn`, `transition_*`, `_safe_journal_metadata`) | live |

Nothing to delete.

## 7. Positive controls (ruling Q6)

1. Before the `_ELEMENT_FIELDS` table: assert one `segment` element keeps `seg_type`/`text`/`ttft_ms` AND one `tool` element keeps `name`/`command`/`exit_code`/`files` in the same test (both arms, one fixture).
2. The seam retargets (`_RETENTION_*`, `_LOCK_TIMEOUT_SECONDS`, `_write_session_file` → `mission_chat_turns.storage`): revert one → its test reds; paste the red.
3. `now_iso_micro`: a test asserting two `persist` calls in one millisecond order by `started_at` (the C8 replay contract) — land it before the fold, since it is what the fold could break.

## 8. Commits and the MOVE hash proof (one MOVE, one CHANGE — program §3.1d)

1. **MOVE** `refactor(mission_chat_turns): mission_chat_turns.py → agent_runtime/mission_chat_turns/ (5 modules)` — spans byte-identical with one sha256 row per §1.1 range (`git show 28012c8f8a:agent_runtime/mission_chat_turns.py | sed -n 'A,Bp' | sha256sum`); `__init__` re-exports the header's names + `_safe_todo_state`, `_store_dir`; the `serde` respelling of the two `safe_assignment_*` imports (the one non-byte-identical line, named); 11 seam retargets; controls §7.1–7.2; `__layer__` per §1.
2. **CHANGE** `refactor(mission_chat_turns): _ELEMENT_FIELDS; serde.number_or_bounded_text; try_session_lock over file_locks; clock.now_iso_micro; _gc_session_files depth 3` — reds pasted; both fixture rows deleted; `[ds-size]` −1.

## 9. Lane and what it must not touch

Exec lane 2B-B (with `runtime_hud`, `chat_live_log`, `terminal_envelope`), FIRST of the four (no lane-B sibling imports it). Must not edit in parallel: `persona_chat_continuity.py` (its `_try_lock/_unlock` and `_utc_now_iso` fold in ITS lane), `persona_chat_history/` (batch 1), `harness_parts/persona/` (H3's package — retarget-only), `running_work.py`, `dispatch_delivery.py`.
