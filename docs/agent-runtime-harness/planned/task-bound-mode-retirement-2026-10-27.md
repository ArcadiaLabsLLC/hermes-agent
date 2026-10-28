# Planned — `--goal` stops stamping `task_bound`; persisted rows are normalised

**Status:** planned 2026-10-27 (planning lane w1027k-h-plan), replanning row
`RT-TASK-BOUND-VOCABULARY`, re-anchored after `72a4f8d3ba` (PersonaAssignmentStore
retired). Supersedes [`task-bound-vocabulary-retirement.md`](task-bound-vocabulary-retirement.md)
(left in place). Owner doc: [`../01-system-architecture.md`](../01-system-architecture.md).

## Problem

The task lane was removed 2026-07-30, but its vocabulary still writes and reads:

- **The write.** `persona instance steer --goal <id>` reaches
  `agent_runtime/persona_assignments/steering.py`, which on a non-empty goal sets
  `mode = "task_bound"` and `current_task_id = goal_id`. The goal is a correlation id
  the launcher groups agent rooms by (`goal_id` on the wire; launcher
  `lib/core/services/hermes/runtime/data/snapshot/harness_snapshot_operator_conversations.dart`),
  not a task.
- **The readers.** Because of that stamp a steered instance is treated as a mission
  row: chat-history projection skips it (`agent_runtime/persona_chat_history/summary.py`,
  `agent_runtime/persona_chat_history/trace.py`); session repair skips it
  (`agent_runtime/persona_assignments/repair.py`); the identity reconciler holds it
  (`agent_runtime/persona_instance_identity.py::_held_reason_for`, `HELD_REASON_TASK_BOUND`);
  profile rebind refuses it as busy (`agent_runtime/persona_profile_binding.py`,
  `BUSY_TASK_BOUND` on `current_task_id`); detach resets the mode (`steering.py`).
- **The stub.** `TaskStoreStub` (`agent_runtime/task_store_stub.py`, re-exported as
  `TaskStore` from `agent_runtime/store.py`) exists by ruling R-3 to keep an unguarded
  `tools/board_tool.py` import working. That import is gone; nothing constructs it.

## Decisions

1. **`--goal` stays, as a pure correlation id, and keeps its name.** It writes
   `goal_id` and nothing else. Renaming it would move a wire field the launcher groups
   by and buy only a spelling.
2. **The stamp's meaning is retired at the store's decode.** `PersonaInstanceStore`'s
   decode (`get` / `scan_all`, `agent_runtime/persona_assignments/store.py`) maps a
   steer-shaped row — `mode == "task_bound"` with `current_task_id == goal_id` — to
   `mode = "configured"`, `current_task_id = None`. One chokepoint, so every reader
   above sees an ordinary chat instance without a branch of its own.
3. **The `task_bound` branches are deleted, not retargeted.** After decision 2 no
   decoded row is `task_bound` from a steer, so `BUSY_TASK_BOUND`,
   `HELD_REASON_TASK_BOUND`, the detach reset and the history/repair skips are dead.
   The repair and busy checks keep their `current_task_id` test only as long as a
   mission-shaped row (decision 4) can still decode with one; they are deleted with it.
4. **Mission-shaped rows are archived, not converted.** A persisted `task_bound` row
   whose `current_task_id` is set and is NOT its `goal_id` is a real retired-lane mission
   row; converting it would surface a mission session as a chat. A new phase in
   `reconcile_persona_instances` (`agent_runtime/persona_instance_identity.py`) archives
   those through the existing retired-instance archive and persists the decision-2
   normalisation for steer-shaped rows; `--dry-run` reports both lists with ids, and a
   second apply is a no-op.
5. **Order inside the slice:** decode normalisation and the steer write land together,
   so no row is ever written `task_bound` again while a reader still expects it.
6. **The stub's fate is the owner's** (R-3 was an operator ruling, and its stated cause
   is what changed) — its own row, below.

## Slices

**S1 — stop the stamp, normalise on decode, archive mission rows** (row
`RT-TASK-BOUND-VOCABULARY`, shipped 2026-10-28 by lane w1028a-h-persona). As built, against
the tree: the phase is the reconciler's phase 0 (`persona_assignments/repair.py::retire_task_bound_rows`,
archive dir `*_task_bound_retire`; a canonical channel is normalised, never archived); the
deleted branches are the steer stamp, the detach reset, the session-repair mode test and
`HELD_REASON_TASK_BOUND`. The chat-history and trace "skips" turned out to be the projection
of MISSION-shaped rows (the synthetic mission row, trace lane 1), which decode keeps
`task_bound` by decision 4, so they stay with `BUSY_TASK_BOUND` until no stored mission row
is left — row `RT-TASK-BOUND-MISSION-LANES`. The "keep the summary skip" killing mutation
cannot apply (the decode alone makes a steered row ordinary); the visible-effect test is the
profile rebind's `busy_reason`. Tests: `tests/agent_runtime/test_task_bound_retirement.py`.

- `agent_runtime/persona_assignments/steering.py` — no `mode` / `current_task_id` on a
  goal; detach reset removed.
- `agent_runtime/persona_assignments/store.py` — the decode normalisation.
- `agent_runtime/persona_profile_binding.py`, `agent_runtime/persona_instance_identity.py`,
  `agent_runtime/persona_assignments/repair.py`, `agent_runtime/persona_chat_history/summary.py`,
  `agent_runtime/persona_chat_history/trace.py` — the `task_bound` branches go.
- `agent_runtime/persona_instance_identity.py` — the archive / normalise phase.
- `tests/agent_runtime/test_persona_assignments.py`, `tests/agent_runtime/test_persona_instance_identity.py`,
  `tests/agent_runtime/test_operator_channels.py` — cases below; existing cases that
  assert `task_bound` after a steer are rewritten.

**S2 — the stub** (row `RT-TASK-STORE-STUB-FATE`, BLOCKED: owner decision)

- If deleted: `agent_runtime/task_store_stub.py`, the `TaskStore` re-export in
  `agent_runtime/store.py`, the comment in `agent_runtime/runtime_instances.py`, and
  `tests/agent_runtime/test_tombstone_registry.py` gains a tombstone for the name.
- If kept: its docstring says it is insurance against a future re-import, not a live
  caller.

## Test plan

- *No stamp:* `steer --goal g1` leaves `mode` unchanged and `current_task_id` `None`,
  `goal_id == "g1"`. **Killing mutation:** restore `updates["mode"] = "task_bound"` → red.
- *Decode:* a stored `{mode: "task_bound", current_task_id: "g1", goal_id: "g1"}` decodes
  as `configured` with no task id through `get` and `scan_all`. **Killing mutation:**
  normalise in `get` only → the `scan_all` half reds.
- *Positive control, mission row untouched by decode:* `{mode: "task_bound",
  current_task_id: "task_9", goal_id: null}` decodes unchanged. **Killing mutation:**
  normalise every `task_bound` row → red.
- *Visible effect:* a steered instance appears in the chat-history projection and
  profile rebind is not refused `task_bound`. **Killing mutation:** keep the summary
  skip → red.
- *Migration:* dry run lists one normalise and one archive and writes nothing; apply
  does both and emits one event each; a second apply reports zero.

## Open questions

- **`TaskStoreStub` (ruling R-3):** delete the stub and its `TaskStore` re-export now
  that `tools/board_tool.py` no longer imports it, or keep it as insurance against a
  future upstream re-import? **Recommend: delete** — nothing constructs it, and a
  re-import would then fail loudly at import time instead of raising `NotFound` at the
  first call.
