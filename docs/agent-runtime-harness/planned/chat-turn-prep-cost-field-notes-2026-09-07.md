# Chat-turn prep cost — running record of the 2026-09-07 re-arm (hermes half)

Field notes for [`chat-turn-prep-cost.md`](chat-turn-prep-cost.md) Stages 6–10. This file is written by whoever builds a stage, in the repo the stage stands in (the launcher half of Stage 6 — the `rt_write_ahead_ms` clause and the fixture mirrors — writes its own notes beside `EterniaLauncher/docs/mission_control/planned/runtime-observability.md`). The skill, if one is written, is written LAST from these notes.

## 0. The read that re-armed the plan (Fable, 2026-09-07, read-only)

What was read and how, so the next reader can re-take every number in the plan's §0 without this session:

- **Ledger:** `<store>/mission_chat_turns/persona_chat_personainst_neko_supervisor_agent_f6844ba8_*.json` — the three 07:48–07:49Z turns (root `…894297972f70`) and the 2026-09-06 turns (roots `…115b37660a88`, `…3d6466fce9a8`, `…a9f7d06394ef`, `…cd75c54589eb`, `…6707159dd4c8`). Table script: a plain loop over each record's `phases` and `profile_timing`; the join key for the log is `phases.anchored_at`, NOT `started_at` (§0 preamble of the plan — `started_at` is 0.9–3.2 s later, it is the write-ahead persist stamp).
- **Log:** the neko profile's `logs/agent.log`, pid 28184 (build `42a07c5dfa`, register row `serve_instances/28184.json`, `hermes_home` = the store root's `profiles/base`), lines 03:48:45–03:49:45 local. The prewarm line, the eight `snapshot_build_core` lines with their `sections_top`, the six `snapshot_agents_readiness walk_ms=` lines, the three `snapshot_build_deferred` lines, the three `API call #1 … ttfb=` lines, and the `never_converged … diff=chat_turn_reservations/…` warning.
- **Launcher:** `[MissionChatTiming]` for this morning is unrecoverable — the diag log is deleted on open past 2 MB (`EterniaLauncher/lib/core/telemetry/diag_log_file.dart`) and today's file opened at 13:15:44Z; the receipts file (`diagnostics/mission_transport/receipts.jsonl` under application support) carries no chat-timing kind. The 2026-09-06 lines quoted in `runtime-observability.md` §0.4 were joined instead (plan §0.4).
- **Sandbox profile:** a robocopy of the live root minus `cache`, `lsp`, `logs`, `audio_cache`, `image_cache`, `*_archive`, `migration_backups`, `curator`, `sandboxes`, `events.jsonl` and `*.lock` (2.8 GB; 78 MB of locked files skipped); `HERMES_HOME` → `<copy>/profiles/base`, `HERMES_AGENT_RUNTIME_ROOT` → `<copy>/agent-runtime`, `HOME`/`USERPROFILE`/`APPDATA`/`LOCALAPPDATA` → `<copy>/userhome`; interpreter = the serve's own (the register row's chain). The script imports `hermes_cli.harness`, then calls, in the handler's order: `load_agent_runtime_config`, `_persona_by_id`, `_default_persona_session_db`, `PersonaInstanceStore().ensure_for_personas(ensure_persisted_personas(cfg))`, `store.get(instance)`, `apply_instance_model_overrides`, `_resolve_chat_model_override(requested_override=None)`, `_chat_effective_model_payload`, `_persona_chat_existing_turn`, `mission_chat_turn_record`, `_persona_chat_native_tip`, `_persona_chat_native_history`, `mission_chat_turn_records(session_id=)`, `_persona_chat_native_revision`, `_session_model_config`, `permission_options_for_chat`, `chat_lane_bundle_key_material`, `chat_lane_bundle`, `build_mission_chat_turn_context(agents_file=None, surface_prompt="")`, `mission_chat_prompt_observability(skill_resolver=None)`, `runtime_context_envelope`, `instance_store.update`; each wrapped in `time.perf_counter`, the two builders under `cProfile` on the cold pass and on the TTL-expired pass. Passes: cold → warm immediately → warm immediately (run 1); cold → warm immediately → warm after 17 s (run 2). The numbers in plan §0.3 are run 1's cold and immediate-warm columns and run 2's 17 s column; run 2's cold column read 595 / 339 / 619 for the bundle / context / observability (OS file cache warm from run 1), which is why the plan quotes run 1 for "cold".
- **Not run:** no serve started, no chat turn sent, nothing written under the live root; the write the script performs (queued-skill consume, model-override persist, instance update, the sandbox SessionDB open) landed in the copy.

## 1. Open at re-arm time — what the plan could not measure and says so

- The Mac's ledger (its `write_ahead`, sub-spans, build cadence) — Stage 6 is what makes it a one-grep read.
- Which bundle key component moves on a quiet live turn (`visibility_bundle_builds`=1 on all 15 turns since 08-29) — Stage 6 item 3.
- The GIL share of the prewarm's 5,750 ms (its client closes and probes are I/O-bound; its tool-defs build and `tool_search` activation are not) — Stage 6's `prewarm_overlapped`.
- Defender / disk / filesystem `stat` cost differences between the machines — not evidenced, not claimed.

## 2. Stage 6

Built 2026-09-07 in the worktree `X:/wt/prep-stage6` on branch
`feat/prep-cost-stage6` off `c670168049`. Five items, red-first, each red quoted
below before its fix. The launcher half writes its own notes beside
`EterniaLauncher/docs/mission_control/planned/runtime-observability.md`.

### 2.1 Item 1 — the `timing` block grows six keys

`agent_runtime/mission_chat_phases.py`: `_TIMING_FROM_PHASES` gains
`context_built_ms`, `observability_built_ms`, `write_ahead_ms`, `agent_ready_ms`
and `visibility_bundle_builds`; `_TIMING_FROM_PROFILE` gains `runtime_resolve_ms`
— the one wire key whose source name carries no `profile_` prefix, because the
runner writes it bare. `_TIMING_COUNT_KEYS` replaces the inline
`wire_key == "builds_overlapped"` comparison so the second counter takes the
count ceiling rather than the millisecond one.

**Red first** (`tests/hermes_cli/test_mission_chat_turn_timing_block.py`, ten rows):

```
E       KeyError: 'runtime_resolve_ms'
E           AssertionError: context_built_ms must project onto the terminal payload
E           assert 'context_built_ms' in {'builds_overlapped': 1, 'provider_first_byte_ms': 8000, 'request_assembled_ms': 7000, 'resident_actor_reused': True, ...}
E       AssertionError: assert None == {'agent_ready_ms': 952, 'context_built_ms': 468, 'observability_built_ms': 906, 'runtime_resolve_ms': 12, ...}
E       assert None is not None            (x5, the absence parametrization)
E       AssertionError: assert set() == {'agent_ready...ite_ahead_ms'}
```

**A decision the plan left open: the six are APPENDED to `TURN_TIMING_ORDER`,
not interleaved chronologically.** "Additive in the strict sense (no existing key
moves)" is taken literally — no existing key moves in name OR position — so a
consumer written against the pre-Stage-6 block reads the payload exactly as
before. Nothing reads the block positionally (the launcher's
`MissionRuntimeTurnTiming` reads it by key name), so the only cost is that a
person scanning the tuple finds the pre-admit half below the post-admit half.
Recorded because the other reading is defensible and the next editor should not
have to re-derive which one was taken.

One PRE-EXISTING row had to move.
`test_the_projection_reads_both_instruments_and_renames_neither_wrongly`
asserted `list(block) == list(TURN_TIMING_ORDER)`, which held only while every
scripted input measured all seven keys. It now compares against that order
FILTERED to the keys the input measured — the same property, stated so it
survives the block growing.

### 2.2 Item 2 — the pre-admit sub-spans

Three in `agent_runtime/mission_chat_turn_context.py` (`CONTEXT_TIMING_KEYS`,
returned on `MissionChatTurnContext.timings`), four in
`agent_runtime/prompt_observability.py` (`OBSERVABILITY_TIMING_KEYS`, returned
under `PROMPT_OBSERVABILITY_TIMINGS_KEY`), folded by
`persona_commands._safe_pre_admit_timings` into `_profile_timing` beside
`session_db_open_ms`.

**Red first** (`tests/hermes_cli/test_mission_chat_turn_phases.py`):

```
E           AssertionError: context_skill_preload_ms was measured on this turn and must be recorded
E           assert 'context_skill_preload_ms' in {'resident_actor_reused': 1, 'session_db_open_ms': 0}
E       KeyError: 'context_skill_preload_ms'
E       AssertionError: a blind runner must contribute nothing; only the handler's own measurements may appear
E       assert {'session_db_open_ms'} == {'context_hud...alog_ms', ...}
E       KeyError: 'observability_catalog_cached'
```

Three things the plan did not anticipate, recorded rather than smoothed over:

1. **`safe_turn_profile_timing` did NOT already admit `*_cached`.** The plan's
   item 2 says it does. It admits `*_ms`, `resident_actor_reused` and
   `resident_rebuild_*` and nothing else, so `observability_catalog_cached` AND
   CP-7's `visibility_bundle_rebuild_component_*` were both being dropped
   silently. Two admitted shapes were added — `_PROFILE_TIMING_CACHED_SUFFIX`
   and `_PROFILE_TIMING_BUNDLE_REBUILD_PREFIX`, each ceiling 1 — and the census
   row `test_the_sanitizer_admits_the_handlers_census_and_the_rebuild_flags`
   pins both, plus the two shapes that must still be refused.
2. **The catalog walk and the shared catalog are timed WHERE THEY RUN, not at
   the call site.** `_installed_skill_catalog()` is reached from three places
   inside one build (the builder's own call, the resolver's union pass,
   `available_skills_context`), so timing the builder's call would bill one walk
   of three. A thread-local accumulator (`_accumulate_span`) collects both; the
   builder resets it when it opens its skill block and reads it when the block
   closes. The three spans are DISJOINT by construction — the two walks are
   subtracted out of the block's total — so `observability_skill_rows_ms` is the
   resolve plus the row composition and nothing else, and adding the three up
   returns the block rather than something larger than it
   (`test_the_sub_spans_are_bounded_by_the_spans_they_decompose`).
3. **`observability_catalog_cached` keys on the walk COUNT, not the walk MS.** A
   walk that finished under half a millisecond still walked, and rounding it to
   `0 ms` would report the TTL as having held.

**The `timings` mapping leaks to a THIRD consumer, and the fixtures caught it.**
The plan says the mapping is "stripped before persist". It is — but the SNAPSHOT
lane builds rows through the same function with no handler in between and puts
them straight onto the read-model frame, so the first producer-contract run went
red with two rows of the launcher's `delta_agent_create_narrow_profile.json`
carrying a wall-clock-dependent mapping onto byte-pinned bytes. Fixed at the seam
its two neighbours already use: `_evict_builder_timings(chat_contexts)` beside
`_evict_final_model_input` / `_evict_prompt_layer_content`. All three exits now
drop it — the handler pops it, the persist chokepoint pops it, the frame evicts
it — pinned by `test_the_builders_own_sub_spans_never_reach_the_FRAME` and
`test_the_persisted_row_drops_the_sub_spans_too`.

### 2.3 Item 3 — CP-7, a rebuild names the component that moved

`agent_runtime/chat_lane_bundle.py`'s `_memo` becomes `(key, material, bundle)`;
`chat_lane_bundle` composes the material once and hashes it itself rather than
calling `chat_lane_bundle_key` (which would compose it a second time). On a key
mismatch `_note_key_material_moves` records the differing TOP-LEVEL entry names,
and the handler folds them as `visibility_bundle_rebuild_component_<name>=1`.

**Red first** (`tests/agent_runtime/test_chat_lane_bundle.py`,
`tests/hermes_cli/test_mission_chat_turn_phases.py`):

```
E       AttributeError: module 'agent_runtime.chat_lane_bundle' has no attribute 'key_material_moves_this_thread'   (x4)
E       KeyError: 'visibility_bundle_rebuild_component_registry_epoch'
E       AssertionError: a rebuild on this turn must name at least one component
E       assert []
```

Shape decisions:

* **Top-level names only.** `permission` is a nested dict, and "the permission
  fingerprint moved" is the actionable fact; descending would trade one honest
  name for six that all mean the same thing.
* **A FIRST build names nothing.** "Built for the first time" and "rebuilt
  because an input changed" are different facts, and naming every component on a
  cold lookup would make every cold turn look like a cache that will not hold.
* **Cumulative + cursor, never reset**, exactly like `bundle_builds_this_thread`:
  serve runs concurrent turns on pooled threads. The cursor rides the turn plan
  (`MissionChatTurnPlan.bundle_key_material_cursor`) for the same reason
  `session_db_open_ms` does — sampled in the plan phase at the anchor, read in
  `_mission_chat_commit_turn`, and the plan IS the declared boundary between
  those two functions. The remembered-names list is bounded at 64.
* **Names, never values**, bounded twice: at the source (top-level keys of a
  dict this module owns) and again at the fold (lowercase ASCII, at most 40
  chars, `[a-z0-9_]` only).

### 2.4 Item 4 — CP-2 as a recorder

`agent_runtime/turn_activity.py` (new): `chat_turns_admitted()` and
`admitted_turn()`. `stream._chat_turns_admitted()` forwards it and the
`snapshot_build_deferred` line gains `admitted_at_exit=`, reading `unknown` when
the module cannot be consulted. `persona_chat_actor_prewarm` gains a
construction-span ledger (`record_construction`, `overlapping_constructions`,
`reset_construction_spans_for_tests`, `_ConstructionSpan`) shaped exactly like
`snapshot_build_ledger`, and `phases.prewarm_overlapped` is counted beside
`builds_overlapped` off the same window.

**Red first** (`tests/agent_runtime/test_snapshot_demote_deferral.py`):

```
E       ImportError: cannot import name 'turn_activity' from 'agent_runtime' (X:\wt\prep-stage6\agent_runtime\__init__.py)   (x4)
E       AttributeError: <module 'agent_runtime.stream'> has no attribute '_chat_turns_admitted'
E       AttributeError: module 'agent_runtime.persona_chat_actor_prewarm' has no attribute 'reset_construction_spans_for_tests'   (x2)
```

**DEVIATION, and the reason.** The plan says the context manager is "entered by
the handler at the anchor". `_cmd_mission_chat_message`'s plan phase is ~700
lines with a dozen refusal returns above the lease, and the commit phase it
dispatches to has fourteen terminal transitions; a `with` around the body means
re-indenting the most-live code in the harness, and an explicit
increment/decrement pair repeated at every exit is exactly the shape that leaks
one and wedges the demote lane for the life of the process once Stage 7 reads
it. So it is a decorator, `_within_admitted_turn`, applied to the handler.
`functools.wraps` keeps `inspect.getsource` and the AST gates over
`_cmd_mission_chat_message` reading the real function (both re-run green:
`test_s26_retired_mission_chat_task_goal_flags.py`,
`test_mission_chat_relay_guard.py`). The window it opens is the handler's first
instruction and the anchor is two local imports later, so for every purpose this
counter has, they begin at the same instant.

**A prewarm that stood DOWN records no span.** `_ConstructionSpan` opens past
the first `agent_runs_in_flight()` yield and covers `_prepare` +
`runner.prewarm` — which is the whole of the §0.2 line it exists to bill
(`elapsed_ms=5750`), since `_prepare` reads SessionDB, resolves the lane bundle
and composes the runtime signature. A refusal that constructed nothing must not
be counted as a span some turn overlapped.

`prewarm_overlapped` is a fourth `PHASE_COUNTER`, so it is a new key in the
`phases` block and not on the wire `timing` block. Stage 6 records it; nothing
reads it to decide anything.

### 2.5 Item 5 — the join rule, and the canon it landed in

The join rule is in `../07-observability.md` beside the `phases` census: join
`agent.log` on `phases.anchored_at`; `started_at` is the write-ahead persist
stamp, 0.9–3.2 s later. That census also grew `prewarm_overlapped`, the seven
handler sub-spans, CP-7's flag family and the sanitizer's two new admitted
shapes. `../05-chat-turn-lane.md` § 2 and § 2a grew the same facts on the owner
side, including the thirteen-key projection table.

**Collateral: 57 cite tokens and 21 waiver keys renumbered.** The source
insertions shifted `stream.py` by +26 then +32, `persona_commands.py` by +2 /
+156 / +215, and four other cited files — pointing 23 previously-green canon
cites at unrelated text. Renumbered by a difflib old→new map over
`git show HEAD:<path>` against the worktree file (never by a constant offset:
the offsets differ per hunk) across 01/02/03/04/05/07/08, and
`cite-adjacency-baseline.json`'s waiver keys renumbered with them — a waiver
follows its cite, precedent `d4cca42fe1`. FIVE waivers were then genuinely
stale and were DELETED rather than renumbered: their cites are the sentences
this stage rewrote out of 07's census paragraph. Baseline 72 → 67 keys;
unwaived failures 0.

### 2.6 Gates

Run in `X:/wt/prep-stage6`:

| gate | verdict |
|---|---|
| `tests/hermes_cli/test_mission_chat_turn_timing_block.py` | 31 passed |
| `tests/hermes_cli/test_mission_chat_turn_phases.py` | 48 passed |
| `tests/agent_runtime/test_chat_lane_bundle.py` | 18 passed |
| `tests/agent_runtime/test_snapshot_demote_deferral.py` | 18 passed |
| `tests/agent_runtime/test_snapshot_prompt_hoist.py` | 18 passed |
| the plan's full gate list (seven paths) | 214 passed |
| `EterniaLauncher/tool/test_quality/check_producer_contracts.py --hermes-root=X:/wt/prep-stage6` | `producer contract fixtures match Hermes: stream frames + response envelopes` — RED before `_evict_builder_timings`, green after |

**A pre-existing red, not this stage's.**
`tests/agent_runtime/test_harness_serve.py::test_ready_line_and_exit_frames`
fails identically on clean `main` in `X:/Eternia/hermes-agent`
(`assert 'stderr' == 'ready'`): the linked SQLite 3.45.3 WAL warning becomes a
`stderr` frame ahead of `ready`. Environmental; rowed here, not fixed here.

### 2.7 Owed

* The gate is an operator read, not a number: one agent-chat turn per machine
  whose `[MissionChatTiming]` line carries `rt_write_ahead_ms`, and whose record
  carries the seven sub-spans and — on the PC — at least one
  `visibility_bundle_rebuild_component_*` name.
* §4.1's ledger row for Stage 6 fills at landing.

## 3. Stage 7

## 4. Stage 8

## 5. Stage 9

## 6. Stage 10
