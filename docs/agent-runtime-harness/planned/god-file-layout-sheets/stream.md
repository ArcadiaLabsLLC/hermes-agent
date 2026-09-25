# Layout sheet — `agent_runtime/stream.py` (lane R3)

Base: `main` @ `28012c8f8a` · sha256 `7b2049237cb8b395c4c09540c87ad67b7a0a73ec7f035292afe624ef36f2fcdf` · 1,898 raw / 1,385 code / 30 top-level defs · longest `stream_frames` 425 (1221–1645, **depth 6** — the deepest function in this batch) · chains 0/0 · `str==` 7 · `isinstance` 15 · owner doc `docs/agent-runtime-harness/03-transport-and-wire.md` (the stream lane, v1 full-core and v2 patch frames). 8 production importers taking 11 names (`serve/subscriptions.py`, `runtime_commands.py` → `stream_frames`; `serve/{handle_message,subscriptions}.py`, `serve_office_subscriptions.py` → `log_stream_attach`/`log_stream_denied`; `serve_stream_hub.py` → `resolve_fold_variant`; `stream_resume.py` → `_DELTA_BATCH_CAP`, `batch_carries_patch_rows`, `patch_batch_frame`; `core_cache/fingerprint.py` → `STREAM_SCHEMA_VERSION`; the fixture generator → five frame builders); 27 test files pinning 18 names, four private (`_batch_frames_with_liveness`, `_defer_demote_build_for_active_turns`, `_delta_op`, `_scope_fingerprint`).

**Package named after the file — `agent_runtime/stream/`** (`stream_resume.py` stays beside it and keeps importing through `__init__`). The file has no module docstring and no banners — its design lives in the `#:` comments on nine constants (30–102, 773–778, 849) and in the phase comments inside `stream_frames`. The skeleton is what those comments describe: frames, one core build and its receipts, and the session that drains a tail.

## 1. Skeleton (owner ruling 2026-09-25: readability first; modules target 100–300, hard cap 500; no flow over three modules)

```
agent_runtime/stream/
  __init__.py        wiring   the map (a docstring this file never had, written from the `#:` comments); re-exports the 11 importer names and the 18 test names
  vocabulary.py      models   the VOCABULARY + coercions module: STREAM_SCHEMA_VERSION, STREAM_PATCH_SCHEMA_VERSION, DEFAULT_STREAM_CALLER, BATCH_REASON_DEMOTE, SNAPSHOT_DEMOTE_DEFERRAL_MAX_MS + its poll, FOLD_VARIANTS_FRAME_TYPE, _DELTA_BATCH_CAP, _SNAPSHOT_CANCEL_POLL_SECONDS, FRAME_* (CHANGE); _redaction_safe_json (singledispatch after the CHANGE), _first_text  (~80; exempt)
  frames.py          policy   one frame each: hydrate_frame, _resume_offset, heartbeat_frame, _delta_entity, delta_frame, delta_batch_frame, batch_carries_patch_rows, patch_batch_frame, fold_variants_frame, resolve_fold_variant, _delta_op, _identity_map, _append_state_reconciled  (~330)   entry: hydrate_frame, heartbeat_frame, delta_frame, delta_batch_frame, patch_batch_frame, fold_variants_frame, resolve_fold_variant, batch_carries_patch_rows
  build_policy.py    stores   what a core build records and when it stands aside: _agent_runs_in_flight, _chat_turns_admitted, _a_turn_holds_the_gil, _defer_demote_build_for_active_turns (Stage 5/7), _log_snapshot_build, log_stream_attach, log_stream_denied  (~320)   entry: log_stream_attach, log_stream_denied
  build.py           lanes    one core build with liveness: _is_one_shot, _SnapshotBuildJob, _build_with_liveness, _full_core_batch_frames, _batch_frames_with_liveness  (~250)
  session.py         lanes    stream_frames (StreamSession after the CHANGE) + _room + _scope_fingerprint — the session that owns a tail  (~435 in the MOVE; ~380 after)   entry: stream_frames
```

Per entry point, the modules an agent opens (the entry's module plus the modules of what it calls directly; `vocabulary` is read like a table and not counted; `snapshot`, `core_cache`, `demote_core_reuse`, `events`, `patch_coverage`, `state_patches`, `request_control` are below the package):

| entry point | opens | count |
|---|---|---|
| `stream_frames` (serve subscriptions, `harness stream`) | `session` → `build` → `frames` | 3 |
| `_build_with_liveness` / `_batch_frames_with_liveness` (from `session`; test-pinned) | `build` → `frames` → `build_policy` | 3 |
| the frame builders (fixture generator, `stream_resume`) | `frames` | 1 |
| `log_stream_attach` / `log_stream_denied` (serve) | `build_policy` | 1 |
| `resolve_fold_variant` (`serve_stream_hub`) | `frames` | 1 |

Floor rule (ruling 3): the first draw had `deferral.py` (~150) and `receipts.py` (~170) apart, and `fingerprint.py` (~135) apart from the session; that made `_build_with_liveness` open four modules and `stream_frames` five. The deferral and the receipts are the two things a build does besides building (both bracket the same call); the fingerprint is the session's own memo ("Fingerprint BEFORE reading events" — a fact the session takes per pass). Both joined. `session` is the one module above 300 in the MOVE; the CHANGE brings it to ~380 — still above 300 and under the cap, because `StreamSession`'s phases are one object with one tail and splitting them is the closure-over-locals shape rule 17 retires.

### 1.1 Section map → target modules

| lines | what is there | → module | layer (from imports) |
|---|---|---|---|
| 1–28 | imports (`hermes_time.now`, `core_cache`, `demote_core_reuse`, `paths`, `events`, `models`, `parity` ×2, `patch_coverage` ×2, `redaction`, `request_control`, `serde` ×3, `snapshot` ×5, `state_patches` ×2) | `stream/__init__.py` | wiring |
| 30–102, 773–778, 849, 1880–1897 | `STREAM_SCHEMA_VERSION` 30, `STREAM_PATCH_SCHEMA_VERSION` 40, `logger`, `_SECRET_ASSIGNMENT_RE` 47, `DEFAULT_STREAM_CALLER` 54, `BATCH_REASON_DEMOTE` 64, `SNAPSHOT_DEMOTE_DEFERRAL_MAX_MS` 98, `_SNAPSHOT_DEMOTE_DEFERRAL_POLL_SECONDS` 102, `FOLD_VARIANTS_FRAME_TYPE` 773, `_DELTA_BATCH_CAP` 778, `_SNAPSHOT_CANCEL_POLL_SECONDS` 849, `_redaction_safe_json` 1880, `_first_text` 1892 | `stream/vocabulary.py` — imports `redaction`, `serde` | models |
| 471–563, 576–847, 1800–1877 | `hydrate_frame` 471, `_resume_offset` 553, `heartbeat_frame` 576, `_delta_entity` 605, `delta_frame` 624, `delta_batch_frame` 641, `batch_carries_patch_rows` 672, `patch_batch_frame` 704, `fold_variants_frame` 781, `resolve_fold_variant` 814, `_append_state_reconciled` 1800, `_delta_op` 1829, `_identity_map` 1846 | `stream/frames.py` — imports `vocabulary`, `snapshot` (`build_receipt_facts`), `parity`, `patch_coverage`, `state_patches`, `serde` | policy |
| 105–468 | `_agent_runs_in_flight` 105 (lazy `profile_runner`), `_chat_turns_admitted` 128 (lazy `turn_activity`), `_a_turn_holds_the_gil` 152, `_defer_demote_build_for_active_turns` 173, `_log_snapshot_build` 268, `log_stream_attach` 377, `log_stream_denied` 424 | `stream/build_policy.py` — imports `vocabulary`, `snapshot` (the `BUILD_*` words), `request_control` | stores |
| 566–573, 852–1218 | `_bounded_sleep` 566, `_is_one_shot` 852, `_SnapshotBuildJob` 866, `_build_with_liveness` 923, `_full_core_batch_frames` 984, `_batch_frames_with_liveness` 1135 | `stream/build.py` — imports `vocabulary`, `frames`, `build_policy`, `snapshot.build_snapshot`, `core_cache`, `demote_core_reuse`, `request_control` | lanes |
| 1221–1797 | `stream_frames` 1221 (+ `_room` 1324), `_scope_fingerprint` 1648 (lazy `chat_session_scope`, `running_work`) | `stream/session.py` — imports `vocabulary`, `frames`, `build`, `build_policy`, `events`, `paths` | lanes |

Edges point down: `session` → `build` → `frames`/`build_policy` → `vocabulary`. The three lazy reaches (`profile_runner`, `turn_activity`, `chat_session_scope`/`running_work`) stay lazy — `profile_runner` imports `stream`'s importers back — and no package module imports them at module level; no cycle. `stream_resume.py:` keeps its three names through `__init__` (`_DELTA_BATCH_CAP` re-exported one commit, then read from `vocabulary` in the CHANGE).

## 2. Routing sites → tables (the CHANGE commit)

| site (base line) | fixture row | replacement | killing mutation |
|---|---|---|---|
| `_redaction_safe_json` 1880–1889: `isinstance(value, dict)` / `list` / `tuple` / `str` / else | `\|isinstance\|value` | `functools.singledispatch` — the standard library's type table, and the shape `clock.iso_timestamp` already uses in this package ("One implementation per input type"); `vocabulary.redaction_safe_json` registers `dict`, `list`, `tuple`, `str`, with `object` → `to_jsonable` | drop the `tuple` registration → the §6 control reds (a tuple payload is serialised unredacted / as a tuple) |
| `frame.get("type") != "heartbeat"` 1567/1597/1618, `== "heartbeat"` 1194; `event_type == "run.progress"` 1837; `tail[0].type == "state.reconciled"` 1811 | not rows (no fork vocabulary declares the frame types today) | `vocabulary.FRAME_HYDRATE / HEARTBEAT / DELTA / DELTA_BATCH / PATCH / FOLD_VARIANTS` constants read by name — the wire words the launcher's `mission_control_bridge.dart` scans (the 1387 comment) — **unless `hermes_cli/harness_parts/serve/frames.py` (H4) already declares them**, in which case this package reads H4's constants... no: that is the upward edge; H4's package would read THESE (`stream` is below `serve`). The lane greps `serve/frames.py` for the literal and retargets it to `stream.vocabulary` if found (one line in H4's package, "tree wins"). No enum (batch-1 rule does not bite — none of these words is fork-wide — but a `StrEnum` here would make `heartbeat` one, and `serve/` compares it too; constants keep the gate's arm (c) honest) | replace `FRAME_HEARTBEAT` with `FRAME_DELTA` in `emitted_delta`'s guard (1618) → `tests/agent_runtime/test_stream_coalescing.py` reds (a heartbeat counted as a delta ends the settle window) |
| `store_path.suffix == ".db"` 1782 | boundary (SQLite vs JSON store, the WAL comment 1778) | unchanged | — |

W0-G7 floor row (1):

| row | lines / depth | phases (comment map) | after |
|---|---|---|---|
| `stream_frames` 1221 | 425 / **6** | floor/promote resolved ONCE 1315 · `_room` (a closure over 5 locals) 1324 · the stale-first hydrate, two conditions that are different questions 1365–1389 · the boot build with liveness 1424–1474 · the one-shot budget 1486 · the tail loop 1490–1645: measure the tail (never fall back to 0), explicit resync, fingerprint BEFORE reading events, the room re-read per pass, `base_offset` chaining (S6), the settle window (200 ms), the cap flush 1583 | `StreamSession(request).stale_first() → boot() → tail()`, with `tail()` = `while True: self._pass()` and `_pass` = `measure → fingerprint → room → read → flush → settle`, each ≤ 45 lines, depth ≤ 3; `_room` becomes `StreamSession.room()` reading the five fields it closed over; `_scope_fingerprint` becomes `StreamSession.fingerprint()` (150 lines today, depth 4 — split into its three store families: chat DB, running-work stores, the office/board roots, ≤ 50 each). `::test_a_room_that_declares_it_paints_is_served_the_stale_core`, `::test_a_one_shot_request_is_never_answered_with_a_stale_core`, `::test_recovered_watermark_re_baselines_instead_of_replaying_or_gapping` pin the phases |

`str==` 7 → 1 at review (the suffix check).

## 3. Helper folds

| here | duplicate of | verdict |
|---|---|---|
| `_redaction_safe_json` 1880 (walk a JSON tree, scrub strings with `ENV_SECRET_ASSIGNMENT_RE`, cap lists at 200) | `persona_chat_continuity._redacted` 167 (walk, scrub with `agent.redact` + `TEXT_SECRET_*`, different cap) — the same WALK with a different scrubber | the CHANGE creates the owner: `redaction.scrub_tree(value, *, scrub: Callable[[str], str], list_cap: int)` (the walk, once, in the module that already single-homes the patterns); this file's function becomes `scrub_tree(value, scrub=_mask_env_assignment, list_cap=200)`; `persona_chat_continuity`'s fold is R1's (its sheet §3 names `_redacted` as staying — amended by this row: it folds once the owner exists) |
| `_first_text` 1892 | `operator_channels._first_text` (renamed `first_present_text` by that sheet) | name group retired by the other rename; this one stays as `first_text` (public in `vocabulary`) |
| `_bounded_sleep` 566 | none | `build` |
| `_delta_op` 1829, `_identity_map` 1846 | `state_patches` owns the op vocabulary (`STATE_PATCHED_EVENT_TYPE`) | stay in `frames`; they read `state_patches`, not the reverse |

## 4. Upstream doors

`hermes_time.now` 11 (module-level; public) — FIRST. Everything else is fork code. W0-G6 `private_upstream_imports` rows for this file: none; the `undeclared` row closes with the MOVE. No widening.

## 5. Dead code (verdict + the grep the lane runs)

| row (`dead-code-burn-down-queue.md`, second instalment, R3) | verdict | proof |
|---|---|---|
| `stream_frames [if @1583]` 1584–1603 (20, "0 hits") — the in-pass flush when `pending` reaches `_DELTA_BATCH_CAP` | KEEP, untested live — reached only when more than `_DELTA_BATCH_CAP` events land in one drain pass, which no fixture seeds | control §6; the row closes KEEP-with-control in the CHANGE |

Nothing else: `git grep -nw` over the 30 defs finds a caller for each (`_resume_offset` 553 ← 1475/1518; `_append_state_reconciled` 1800 ← `frames`' callers).

## 6. Positive controls — land in the MOVE (ruling Q6)

Two cases: (1) in `tests/agent_runtime/test_stream_coalescing.py`, seed `_DELTA_BATCH_CAP + 1` events between two heartbeats and assert two batch frames whose `base_offset`→`watermark` chain has no gap (the 1583 arm, and the S6 chaining comment 1490–1500 made a test); (2) in `tests/agent_runtime/test_stream.py`, a `delta_frame` over a payload holding a `tuple` value and a secret-shaped string inside it asserts the string is masked and the tuple serialises as a list — the `tuple` arm of `_redaction_safe_json`, so the singledispatch mutation in §2 has a red to show.

## 7. MOVE hash-proof plan, then the CHANGE

1. **MOVE** `refactor(stream): stream.py → agent_runtime/stream/ (5 modules; stream_frames whole)` — spans byte-identical with the sha256 table (one row per §1.1 span; `_bounded_sleep` is its own two-line span into `build.py`); `__init__` re-exports the 11 + 18 names. **Killing mutation for the MOVE:** drop `frames` from `__init__` → `agent_runtime/stream_resume.py` fails to import `patch_batch_frame` and `tests/agent_runtime/test_stream.py::test_hydrate_frame_carries_snapshot_contract` (imports `hydrate_frame`) reds at collection. The two §6 controls land here. `[ds-size]` −1.
2. **CHANGE** `refactor(stream): StreamSession phases (tail/_pass, room, fingerprint); FRAME_* by name; redaction.scrub_tree + singledispatch; vocabulary` — §2 + §3 with each red pasted; the W0-G5 `isinstance` row and the §5 row close.

## 8. Lane and what it must not touch

R3 (exec lane B4), second of its three — after `running_work.md` (its lazy reach at 1768 goes through that package's `__init__`), before `mcp_admission.md` (disjoint). Must not edit in parallel: `snapshot/`, `core_cache/`, `demote_core_reuse.py`, `patch_coverage.py`, `state_patches.py`, `stream_resume.py` (retarget-only for `_DELTA_BATCH_CAP` in the CHANGE), `serve_stream_hub.py`, `serve_office_subscriptions.py`, `harness_parts/serve/` (one `FRAME_*` retarget line at most, "tree wins"); `redaction.py` gains `scrub_tree` and nothing else.
