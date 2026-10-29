# Planned — drain the stored mission rows at serve boot; retire the mission-row readers

**Status:** planned 2026-10-28 (planning lane w1028p-taskbound), row
`RT-TASK-BOUND-MISSION-LANES`. Continues
[`task-bound-mode-retirement-2026-10-27.md`](task-bound-mode-retirement-2026-10-27.md)
(S1 shipped 2026-10-28; its decisions 1–5 stand). Owner doc:
[`../01-system-architecture.md`](../01-system-architecture.md).

## In plain English

S1 stopped `--goal` from stamping `task_bound`, and taught the store to read an old
steer-shaped row as an ordinary instance. Five readers still branch on a MISSION-shaped
row — a `task_bound` row whose `current_task_id` is a real task from the lane deleted
2026-07-30 — and they can only go once no such row is stored. The phase that archives
those rows runs only when an operator types `harness persona-instance reconcile`, which
nobody does on every box. This plan runs that one phase at serve boot (a write moment
the boot already owns four sweeps at), closes the one writer S1 missed
(`persona instance update --goal` still stamps `current_task_id`), then deletes the
readers, and names what the launcher stops decoding once the wire fields go.

## Evidence

- **The drain exists but has one caller.** `agent_runtime/persona_assignments/repair.py::retire_task_bound_rows`
  reads the RAW `persona_instances/*.json`, archives a mission-shaped row to
  `<archive>/<ts>_task_bound_retire/`, normalises a steer-shaped one, one
  `persona_instance.reconciled` event per row, idempotent (second apply `{[], []}` —
  `tests/agent_runtime/test_task_bound_retirement.py::test_phase_0_normalises_steer_rows_archives_mission_rows_once`).
  Its only production caller is `agent_runtime/persona_instance_identity.py::reconcile_persona_instances`
  phase 0, whose only caller is `hermes_cli/harness_parts/runtime_commands.py::_cmd_persona_instance_reconcile`.
  Nothing in `hermes_cli/harness_parts/serve/` reaches it.
- **Serve boot already runs four fail-open store sweeps before `ready`**, in
  `hermes_cli/harness_parts/serve/boot_phases.py`: `_prune_stale_records` (serve
  registry rows), `_arm_end_reason` (`prune_ended`, `prune_revoked_devices` — "a boot is
  a WRITE moment, and a read must not destroy"), and `_boot_sweeps_and_ready_frame`
  (`repair_orphaned_chat_turns`, ≤50 files; `restore_undelivered_dispatches`). Each is
  wrapped `try/except: pass` and marks the `BootTimeline`. That is the shape and the
  place.
- **The sweep's cost is one the boot already pays.** `retire_task_bound_rows` globs and
  `json.loads` every `persona_instances/*.json` once; the boot's snapshot prewarm
  (`serve/boot.py::_prewarm_read_model_snapshot`) already does the same whole-directory
  read through `PersonaInstanceStore.scan_all` on `ensure_for_personas`
  (`agent_runtime/snapshot/sections.py:227`). Measured on this box (nekwo-ubuntu24,
  2026-10-28): `paths.store_root()` = `~/.hermes/agent-runtime`, directory absent, **0
  rows, 0 `task_bound`, 0 `current_task_id`** — the live population is on the owner's
  boxes and unmeasurable here, which is itself the reason an operator-run reconcile
  cannot be the drain.
- **S1 missed a writer.** `agent_runtime/persona_assignments/profile_writes.py::_apply_chat_fields`
  line 230: `if value and instance.current_task_id != value: instance.current_task_id = value`
  — `persona instance update --goal <id>` (`hermes_cli/harness_parts/parser/persona.py:353`,
  `instance_commands.py::_cmd_persona_instance_update_profile`) still writes the goal as
  the task. It does NOT flip `mode`, so S1's decode (keyed on `mode == "task_bound"`)
  never normalises it: the row stays `configured` with `current_task_id == goal_id`, and
  every `current_task_id` reader fires — `BUSY_TASK_BOUND` (`persona_profile_binding.py:254`),
  the repair skip (`repair.py:255`), the `task:` channel key
  (`operator_channels/instances.py:228`), and the launcher's `taskBound` fallback
  (`EterniaLauncher/lib/core/services/hermes/runtime/data/snapshot/harness_agent_instance.dart:551`,
  rendered "Mission linked" by `mission_agent_profile_editor.dart:495`). No test pins
  this write (0 `update_profile(` calls with `goal_id` under `tests/`).
- **The readers, and what each does with a mission row today:**
  1. `agent_runtime/persona_chat_history/summary.py::HistorySummary.index_instances`
     (line 204) drops the default-chat pointer of a `task_bound` row whose task is set and
     whose `default_chat_session_id == session_id`; `live_mission_candidates` (line 382)
     emits the synthetic `"Mission run"` row, `kind="mission"`, anchored by
     `history_rows.py::_mission_assignment_for` (the R3 anchor, fed by the
     `persona_assignments` parameter no production caller supplies since AX2);
     `activity_key` pins `kind == "mission"`; `rows` stamps `row["task_id"]`.
  2. `agent_runtime/persona_chat_history/trace.py` lane 1 (line 95): groups `task_bound`
     instances by `current_task_id` and fetches `log.for_task`; the `_TraceAccumulator`
     carries `task_id` onto every trace row (line 162), mission or not.
  3. `agent_runtime/persona_profile_binding.py::instance_busy_reason` — `BUSY_TASK_BOUND`
     on `current_task_id` (exported, `__all__` line 880).
  4. `agent_runtime/persona_assignments/repair.py::repair_missing_chat_session_bindings`
     — skips any row with `current_task_id` (line 255).
  5. `agent_runtime/prompt_observability/skills_context.py::_chat_metadata` — titles a
     session `"Mission run"` / `source="task_bound"` when `task_id` is set and the
     SessionDB has no title; `operator_channels/summary.py:259` uses the same fallback
     title for every operator channel (no mode test — stays).
- **Wire.** The snapshot's `persona_instances` rows carry `mode` and `current_task_id`
  (`tests/agent_runtime/test_s70_persona_instance_wire_prune.py:114` pins
  `current_task_id` ON the wire, "written live by the steer/`goal_id` lane" — a sentence
  S1 made false). `persona_chat_history` rows carry `kind` / `live_mission` / `task_id`
  (`history_rows.py:212-213`, `summary.py:492`); `persona_chat_trace` rows carry
  `task_id`. The launcher decodes all of them: `harness_snapshot_tools.dart:86`
  (`currentTaskId`), `harness_agent_instance.dart:548-552` (`taskBound` from
  `mode == 'task_bound'` OR `currentTaskId != null`), `harness_snapshot_persona_chat.dart:84-85`
  (`isLiveMission: kind == 'mission' || live_mission`, `taskId`), and 19 `.taskId`
  consumers under `lib/features/mission_control/` plus `agent_console_chat_directory.dart`
  / `agent_console_transcript_adapter.dart` ("Live mission" card). 35 launcher test files
  reference one of those names.
- **Docs drift.** `docs/agent-runtime-harness/01-system-architecture.md:204` still says
  `"task_bound"` "is still written"; line 1064 (same file) says it is not. Line 1064 is
  right.

## Target shape

- `task_bound` is a **stored-only** value: nothing writes it, nothing writes
  `current_task_id`, and every serve boot drains what is stored. After S2 a row can only
  reach a reader inside a serve process that has already swept it; the one path round
  that (a cold CLI `harness snapshot` on a box that never booted the new build) sees a
  row the decode has flattened to `configured` (S3's decode hardening), which is an
  ordinary idle instance — the degraded state is "an old mission row shows as an idle
  agent until the next serve boot archives it", never a crash or a surfaced mission
  transcript.
- `mode` keeps its vocabulary minus `task_bound`; `current_task_id` stays a model field
  (the sync contract lists it under `PERSONA_INSTANCE_LOCAL_ONLY_KEYS`, the HUD and
  state-patch mirrors read it) but is always `None` on a live row. It leaves the wire
  only after the launcher stops reading it (S4, cross-repo).
- No version gate: the store has no store-level version, `schema_version` is per row and
  per sync, and a gate would only re-state "has the sweep run" — which the sweep's own
  idempotence already answers for free.

## Slices (build order; each file-disjoint, one lane each)

**S0 — close the `update --goal` stamp.** `agent_runtime/persona_assignments/profile_writes.py::_apply_chat_fields`:
delete the `current_task_id` write (lines 230-232). `tests/agent_runtime/test_task_bound_retirement.py`
gains `test_update_profile_with_a_goal_writes_no_task`: raw JSON after
`PersonaInstanceStore().update_profile(id, goal_id="g1")` has `goal_id == "g1"`,
`current_task_id is None`. Row `RT-TASK-BOUND-UPDATE-GOAL-STAMP`.

**S2 — phase 0 at serve boot.** `hermes_cli/harness_parts/serve/boot_phases.py::_boot_sweeps_and_ready_frame`,
beside `repair_orphaned_chat_turns`: `PersonaInstanceStore(event_log=…).retire_task_bound_rows(apply=True)`,
`try/except` fail-open, `self.timeline.mark("task_bound_retire_ms")`, counts onto the
ready frame the way `orphaned_repaired` rides it. The reconciler's phase 0 and the CLI
render stay (an operator can still dry-run). Tests: `tests/hermes_cli/` boot test seeds
one steer-shaped and one mission-shaped raw row under `isolate_agent_runtime_root`, drives
the boot phase, asserts the archive file exists and the normalised row reads
`configured`, and that a raised `OSError` from the sweep does not fail the boot. Row
`RT-TASK-BOUND-BOOT-SWEEP`.

**S3 — retire the readers** (this row, `RT-TASK-BOUND-MISSION-LANES`; lands after S0 and
S2 in the wave's lander, though it is correct in any order by the decode hardening):

- `agent_runtime/persona_assignments/store.py` decode: a `task_bound` row of ANY shape
  decodes `mode="configured"`; `current_task_id` is nulled for the steer shape (as now)
  and left for the mission shape (the sweep reads raw, so it still sees the shape). S1's
  positive control (`test_a_mission_shaped_row_decodes_unchanged`) flips to assert
  `mode == "configured"` and `current_task_id == "task_9"`.
- `agent_runtime/persona_chat_history/summary.py`: delete the `index_instances` mode
  branch, `live_mission_candidates`, the `persona_assignments` parameter and its
  docstring paragraph, the `"mission"` arm of `activity_key`, the `task_id` candidate
  slot and `row["task_id"]`. `history_rows.py`: delete `_mission_assignment_for`; `kind`
  stays a parameter defaulting `"chat"` and `live_mission` stays emitted `False` until S4.
- `agent_runtime/persona_chat_history/trace.py`: delete lane 1, `_TraceAccumulator.task_id`
  and the `"task_id"` row key.
- `agent_runtime/persona_profile_binding.py`: delete `BUSY_TASK_BOUND` and its arm;
  `__all__` and the busy-reason table test shrink.
- `agent_runtime/persona_assignments/repair.py`: delete the `current_task_id` skip in
  `repair_missing_chat_session_bindings` and its docstring bullet.
- `agent_runtime/prompt_observability/skills_context.py::_chat_metadata`: delete the
  `"Mission run"` / `source="task_bound"` fallback and the `task_id` parameter;
  `mission_chat.py:246` and `context_store.py:586` drop the argument.
- `agent_runtime/operator_channels/instances.py::_channel_key_for_instance`: delete the
  `task:` key arm (it keys on `current_task_id`).
- Docs: `01-system-architecture.md:204` corrected; `02-runtime-data-and-shapes.md:618`
  and `test_s70_persona_instance_wire_prune.py:11` re-worded (`current_task_id` is
  stored-only, always null live).
- Tests touched: `test_persona_chat_history_curation.py` (the four
  `test_synthetic_mission_row_*`, `test_busy_task_does_not_starve_a_quiet_personas_trace`,
  `test_persona_chat_trace_merges_task_and_session_lanes_for_one_instance`),
  `test_operator_channels.py::test_operator_channel_trace_empty_fires_for_task_bound_channel_without_trace`,
  `test_persona_assignments.py` (`test_task_terminal_reaps_task_bound_persona_instances`,
  `test_task_archive_moves_task_bound_persona_instance_evidence`,
  `test_persona_chat_history_summary_ignores_task_bound_worker_sessions`),
  `test_persona_instance_identity.py::test_reconcile_never_folds_task_bound_or_cross_persona_rows`
  (keep its cross-persona half), `test_persona_instance_identity.py::test_repair_missing_chat_session_bindings_repairs_a_stored_mission_row`
  (inverted and renamed from the skip test: the pointer is now repaired), `test_persona_profile_binding.py::test_instance_busy_reason_table`,
  `test_task_bound_retirement.py::test_a_steered_instance_is_not_refused_as_busy_by_the_profile_rebind`
  (the MISSION expectation becomes `None`). `test_tombstone_registry.py` gains
  `BUSY_TASK_BOUND`, `live_mission_candidates`, `_mission_assignment_for`.

**S4 — prune the wire** (row `RT-TASK-BOUND-WIRE-PRUNE`, BLOCKED launcher): after the
launcher's `MC-TASK-BOUND-WIRE-READERS` lands, stop emitting `current_task_id` on
`persona_instances`, `kind` / `live_mission` / `task_id` on `persona_chat_history`,
`task_id` on `persona_chat_trace`; `test_s70_persona_instance_wire_prune.py` and the
stream-frame fixtures under `tests/fixtures/` drop the keys; `02-runtime-data-and-shapes.md`
records the removal. Launcher side (filed in `Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`):
delete `HarnessAgentInstanceMode.taskBound` and both arms of `_modeFromHarness`,
`HarnessPersonaInstance.currentTaskId`, `HarnessPersonaChatSession.isLiveMission` /
`taskId`, the trace row `taskId`, the "Live mission" transcript card and "Mission linked"
label, and the 35 test files' fixtures — the launcher moves first because a decoder that
tolerates a missing key is the safe order (`wireStringOrNull` already yields `null`).

## Test plan (each with the red it must show)

- S0 — `test_update_profile_with_a_goal_writes_no_task`. **Killing mutation:** restore
  the two `current_task_id` lines in `_apply_chat_fields` → `assert stored.get("current_task_id") is None` red.
- S2 — boot sweep archives / normalises. **Killing mutation:** drop the
  `retire_task_bound_rows` call from `_boot_sweeps_and_ready_frame` → the archive glob
  is empty, red. Fail-open: monkeypatch the sweep to raise → boot reaches `ready`;
  **killing mutation:** remove the `try/except` → the boot test errors.
- S3 — decode flattens a mission row's mode. **Killing mutation:** restore the
  `current_task_id == goal_id` guard on the `mode` write → `mode == "task_bound"`, red.
- S3 — a mission-shaped row is NOT busy and IS repaired. **Killing mutation:** restore
  the `BUSY_TASK_BOUND` arm → `reasons[MISSION] is None` red; restore the repair skip →
  the dangling pointer survives, red.
- S3 — the chat-history projection emits no `kind == "mission"` row and no `task_id` key
  for a stored mission row; the trace lane fetches `for_session` only (a `for_task` spy
  records zero calls). **Killing mutation:** restore `live_mission_candidates` → the row
  reappears, red.
- S3 — tombstones: `test_tombstone_registry.py` reds if any of the three names is
  re-declared.
- S4 — the wire fixture round-trip reds on the key's reappearance (the existing s70 shape).

## Blast radius

- hermes: 11 runtime files, ~9 test files, 2 docs. The reconcile CLI's output is
  unchanged (phase 0 stays). Event log: one `persona_instance.reconciled` per archived or
  normalised row, at boot, once per row ever.
- Behaviour change an operator can see: an old mission row's dangling chat pointer is now
  repaired rather than skipped; an instance that was refused rebind with
  `busy_reason="task_bound"` is rebindable; a `persona instance update --goal` no longer
  shows "Mission linked" in the launcher.
- launcher: decoders tolerate the missing keys today; the deletion is a separate row.
- Not touched: `models.py::Assignment.evidence_kind = "task_bound"` (an assignment-store
  default, a different vocabulary — row `RT-WRITERLESS-GOAL-STATUS-KEYS`'s territory);
  `operator_channels/summary.py`'s `"Mission run"` title fallback (no mode test; every
  channel's last-resort title).

## Owner decisions

None open. The drain mechanism (serve boot, fail-open, beside the four existing sweeps)
is the pattern RO-3 / RL-16 already ruled for the registry and device stores; "archive,
never convert" is decision 4 of the S1 plan. Recommendation recorded for the record:
**serve boot runs phase 0 only** — not the full reconciler, whose merge / rename / prune
phases are operator decisions with a `--dry-run` for a reason.
