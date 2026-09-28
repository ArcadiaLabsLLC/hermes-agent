# Shared Discussion experience — approved 2026-09-27

Status: implementation in progress; not a closeout.

Extend the existing discussion owner, stores and hosted-room worker. Mission
Control and Intelligence remain independent consumers of focused contracts.
Multi-harness execution, voice and unrelated Companion slices are excluded.

## Delivery

1. Fence idle shutdown against operator-turn registration and new discussion
   admission. Failed idle claims leave both owners accepting. Existing answers,
   exact Stop and End remain available during an explicit drain.
2. Reuse workspace/agent creation and revisioned presets through shared adapters.
   Do not create a second catalog, office controller or hidden table.
3. Expose public execution progress: working/waiting members, round, and terminal
   reason. Private working content stays private.
4. Add opt-in synthesis to the existing scheduler. It is an ordinary identified
   member turn with the same Stop, restart, failure and publication rules. Its
   completion is not a quality guarantee. Existing runs default to no synthesis.

## Acceptance

The original table contract and `discussion-tables-checkpoint-20260916.md` remain
the acceptance references; recovery closeout does not replace their checklist.
Test shared preset revisions, exact instance/workspace ownership, ordinary
operator-chat isolation, progress, synthesis lifecycle, and producer/consumer
wire parity. Launcher adds native UI acceptance at default/minimum sizes.

## Admission repair evidence

`test_serve_drain_admission.py` holds each operator admission before registration,
accepts idle drain, then releases it. Both method and argv must refuse; the same
inputs without drain must register and prevent maintenance. The real RPC
dispatcher must refuse a new Room after accepted drain and accept it after a
busy conversation rejects maintenance.

Focused checkpoint: 13 tests passed. Removing the two locked drain checks and
the discussion admission fence produced three expected failures (method, argv,
and native Room admission); the three positive controls passed. Restored guards
passed again. Broader integration verification is pending.
