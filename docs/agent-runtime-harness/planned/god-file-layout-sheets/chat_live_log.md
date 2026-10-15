# Layout sheet — `agent_runtime/chat_live_log.py` (lane R2 · exec lane 2B-B)

Base: `main` @ `28012c8f8a` · 1,066 raw / 849 code / 38 top-level defs · longest `_backfill_rows` 82 (depth 4) · chains 1/1 · `str==` 8 · `isinstance` 6 · W0-G5 fixture rows `_normalized_role|ladder|role`, `chat_live_log_stats|ladder|kind` · sha256 `77f64791321ea1f01dde09abf4d762db7c213a8adc65f0416dc3cc9590b84707` · owner doc `docs/agent-runtime-harness/05-chat-turn.md` (the mirror). 6 production importers (`continuity`, `media_handles`, `mission_chat_steer`, `progress`, `harness_parts/persona/chat_history_writes`, `tools/agent_chat_tool`), 10 test files. Importers take the `__all__` list (line 115); tests patch `_backfill_rows` ×3, `LIVE_LOG_ROTATE_BYTES` ×3, `record_chat_message` ×2, `record_chat_tool` ×1.

**Package `agent_runtime/chat_live_log/`.**

## 1. Skeleton (owner rulings 2026-09-25) — this text IS the package `__init__` map

```
agent_runtime/chat_live_log/
  __init__.py   wiring  the map; __all__ verbatim
  state.py      stores  the process-wide state and its writers: the captured root (+ source, + the capture ladder), the replay-dedupe index seeded from the file tail, the failure tally (note / reset)
  files.py      stores  the file on disk: path, exists, append + rotate, the claim + atomic publish, the bounded wait, create (header only, or materialized) and complete-a-pending-header
  backfill.py   lanes   the tool lane's projection walk (_backfill_rows: paged, bounded on rows and wall) and the read-backs over the header it writes (chat_live_log_stats, chat_live_log_failures)
  writes.py     lanes   the hot lane: mirrored_persona_chat_append, record_chat_message, record_chat_tool, ensure_chat_live_log — and the shape of one line (role normalization, the logical client key, the origin fields, secret masking + bound, encode / decode)
```
Entry points and the modules an agent opens: `record_chat_message` (the persist seams, `progress.ChatProgressSink`) → `writes.py` → `state.py` (dedupe) → `files.py` (ensure + append) — **3**; `ensure_chat_live_log(materialize=True)` (`agent_chat_log_path`) → `writes.py` → `files.py` (claim, create/complete) → `backfill.py` (the rows) — 3; `chat_live_log_stats` → `backfill.py` → `files.py` — 2; `capture_chat_live_log_root` (the SessionDB acquisition) → `state.py` — 1. Layers: lanes → `files` → `state`; `writes` reaches `redaction` and (lazily) `relay_policy`, `persona_chat_history`.

### 1.1 Section map → target modules (sizes are raw / est. code; the 100/300/500 bars are on code lines)

| lines | what is there | → module | raw / code | layer |
|---|---|---|---|---|
| 1–130, 132–157 | docstring, imports, `__all__`, the constants | `__init__.py` (constants re-exported from the module that reads each) | ~150 / 40 | wiring |
| 159–165, 171–204, 739–749, 755–781, 1002–1066 | `_state_lock`, `_captured_root`, `_captured_source`, `_seen_keys`, `_seeded_sessions`, `_failures`, `_failure_logged`; `capture_chat_live_log_root`, `reset_chat_live_log_state`, `_root_from_session_db`, `_root_from_scope`, `_coerce_dir`; `_already_recorded`, `_mark_recorded`, `_seed_from_tail`, `_note_failure` | `chat_live_log/state.py` — **the three functions that `global`-rebind a name must live with the names** (a `global` cannot rebind another module's variable, so this is the one placement that keeps the spans byte-identical) | ~165 / 120 | stores |
| 207–216, 406–567, 784–796, 968–1000 | `chat_live_log_path`, `_with_claim`, `_create_log`, `_complete_backfill`, `_publish`, `_wait_for_publication`, `_exists`, `_claim_is_stale`, `_append_line`, `_rotate_if_needed` | `chat_live_log/files.py` (`paths.unlink_quietly`, `state`; lazy `backfill._backfill_rows` from `_create_log`/`_complete_backfill` — a lanes reach from stores that stays LAZY and is named) | ~250 / 170 | stores |
| 570–666, 672–736 | `_backfill_pending`, `_backfill_rows`, `chat_live_log_stats`, `chat_live_log_failures` | `chat_live_log/backfill.py` (lazy `persona_chat_history`) | ~165 / 115 | lanes |
| 222–403, 799–965, 985–987 | `mirrored_persona_chat_append`, `record_chat_message`, `record_chat_tool`, `ensure_chat_live_log`; `_decode_lines`, `_now_iso`, `_iso_or_now`, `_normalized_role`, `_safe_token`, `_logical_client_key`, `_backfilled_delivery_fields`, `_relay_sender_fields`, `_safe_session_token`, `_mirror_text`, `_encode`, `_REDACTED_LINE` | `chat_live_log/writes.py` | ~380 / 240 | lanes |

Refolded under the no-fragmentation ruling: the earlier draft's `dedupe.py` (~35 code) and `stats.py` (~45) were under the floor, and a separate `lines.py` made `record_chat_message` a five-module flow; the dedupe index lives with the state it mutates, the stats with the header they read back, the line shape with the writes that produce it. **One edge the refold creates and how it is held:** `files._create_log` / `_complete_backfill` call `backfill._backfill_rows` (stores → lanes) — kept as the function-local import it already is today (`_backfill_rows` is monkeypatched by three tests, which is also why it stays a late-bound name), and named here rather than hidden; the alternative (rows passed in by the caller) is the CHANGE's option if the gate objects. Result: 4 modules + the map, none over 240 code lines.

## 2. Routing sites (rule 12) — both W0-G5 rows

| site (base line) | fixture row | replacement | killing mutation |
|---|---|---|---|
| `_normalized_role` 826–834 | `\|ladder\|role` — five words to three | `_ROLE_BY_ALIAS: Mapping[str, str] = {"user": "operator", "operator": "operator", "assistant": "agent", "agent": "agent", "system": "system"}`; `return _ROLE_BY_ALIAS.get(role, role or "unknown")`. Keys are plain literals — `operator`/`agent` are the conversation contract's role words spelled across `persona_chat_history`, the launcher and every test; no `Final`/`StrEnum` (fork-hygiene row, lane R4 2026-09-25) | map `assistant` → `operator` → `tests/agent_runtime/test_chat_live_log.py`'s agent-row assertion reds (control §6.1 confirms the fixture writes an `assistant` row) |
| `chat_live_log_stats` 703–710 | `\|ladder\|kind` — message / tool / log_opened | `collections.Counter(row.get("kind") for row in rows)` for the two counts + ONE guard for the header row's two flags; the three-arm ladder goes | count `tool` rows as `message` → the stats test reds (`chat_live_log_stats` has 1 test file; control §6.2) |
| `_relay_sender_fields` 917–937 | delivery-marker vs sender-marker | two typed parses, mutually exclusive by `relay_policy`'s construction — a boundary; stays |

`str==` 8 → ≤ 3 at review.

## 3. W0-G7 near-miss

`_backfill_rows` 585 — 82 lines, depth 4: split the paged projection walk (`_projection_pages(session_id, session_db) -> (pages, truncated)`) from the row translation (`_backfill_row(message) -> dict \| None`); depth 2, both ≤ 40, both in `backfill.py`.

## 4. Helper folds

| here | owner | verdict |
|---|---|---|
| `_exists` 784 | 09-21 plan §5 row `_exists` / `paths.path_exists_safe` — **the owner does not exist yet** (`grep -n path_exists_safe agent_runtime/paths.py` → nothing) | this lane CREATES `paths.path_exists_safe(path)` (the `OSError → False` probe) and folds its copy; the other copies fold in their lanes |
| `_now_iso` 814 | program §4 row (`_now_iso` ×4 → `clock.now_iso`) | FOLD **with a wire-visible difference the sheet names rather than hides**: `hermes_time.now().isoformat()` spells `+00:00` and microseconds; `clock.now_iso` spells `Z` and milliseconds. Every `ts` in every mirror line changes spelling. The file is a regenerable artifact and its only reader passes `ts` through as `last_activity`, so nothing parses it — but no test pins the format either, which is a stated gap, not a licence: control §6.3 pins the NEW spelling first, then the fold lands. (Owner question Q22 in the program doc: fold, or keep the `+00:00` spelling as this file's own — default: fold.) |
| `_mirror_text` 953 (per-line secret masking) | `persona_chat_history/text.py:122` and `trace_rows.py:207` carry the same `"[redacted line — contained a secret]" if _SECRET_RE.search(line)` line | recurrence (three copies of one line + one constant): **`redaction.mask_secret_lines(text) -> str`** — the ONE per-line masker beside `TEXT_SECRET_ASSIGNMENT_RE`; this lane creates it and folds `_mirror_text`'s masking step; `persona_chat_history` (batch 1, landed) folds in a one-line follow-up the lane may make since the package is on the tree |
| `_safe_token` 837 | `serde.safe_optional_token` (id charset) | NOT a fold — this keeps every character but NUL and bounds; the id spelling would rewrite tool names. Named |
| `_decode_lines` 799 / `_encode` 985 | — | stay (the file's own line codec) |

## 5. Doors

`hermes_time.now` (public). W0-G6 private rows: none. No widening.

## 6. Positive controls (ruling Q6)

1. Before `_ROLE_BY_ALIAS`: `git grep -n '"assistant"' tests/agent_runtime/test_chat_live_log.py` — if no fixture records an `assistant` row, add one asserting the line's `role == "agent"`; likewise a `user` row → `operator`.
2. Before the `Counter`: the stats test must hold at least one `tool` line and one `message` line and assert both counts (a message-only fixture is green under the swap).
3. Before the `_now_iso` fold: assert a recorded line's `ts` matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$` (the new spelling) — written red against the current code, then the fold turns it green.
4. Seam retargets: `_backfill_rows` → `chat_live_log.backfill` (its two callers in `files.py` import it late, by name, at call time — so the package attribute is NOT what they read; patch `backfill._backfill_rows`), `LIVE_LOG_ROTATE_BYTES` → `chat_live_log.files`; `record_chat_message`/`record_chat_tool` patches reach their callers only if those import by attribute — verify by reverting.

## 7. Dead code found while reading

| symbol | evidence | verdict |
|---|---|---|
| `chat_live_log_failures` 732 | 0 production readers, 1 test; it is the "counted" half of the best-effort contract stated in the docstring (line 67) | DECIDE row for the dead-code queue: KEEP as the operator-visible tally (default) or delete with the docstring sentence. Filed on arrival by the lane; not a delete here |
| `LIVE_LOG_BACKFILL_*` 141/145 | read in-file | live |

## 8. Commits and the MOVE hash proof (one MOVE, one CHANGE — program §3.1d)

1. **MOVE** `refactor(chat_live_log): chat_live_log.py → agent_runtime/chat_live_log/ (4 modules)` — spans byte-identical with one sha256 row per §1.1 range (`git show 28012c8f8a:agent_runtime/chat_live_log.py | sed -n 'A,Bp' | sha256sum`); `__all__` verbatim; the state-with-its-writers placement (§1.1) is what keeps the spans identical; seam retargets; controls §6.1–6.2; `__layer__` per §1.
2. **CHANGE** `refactor(chat_live_log): _ROLE_BY_ALIAS + Counter stats; _backfill_rows split; paths.path_exists_safe; redaction.mask_secret_lines; clock.now_iso (ts spelling)` — reds pasted; both fixture rows deleted; `[ds-size]` −1.

## 9. Lane and what it must not touch

Exec lane 2B-B, third. Must not edit in parallel: `progress.py`, `continuity.py`, `mission_chat_steer.py`, `media_handles.py`, `tools/agent_chat_tool.py` (importers through `__init__`); `persona_chat_history/` (batch 1) except the one-line `mask_secret_lines` fold named in §4; `relay_policy.py`.
