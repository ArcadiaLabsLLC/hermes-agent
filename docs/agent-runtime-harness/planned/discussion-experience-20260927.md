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

## September 28 checkpoint

Reconciled packaged-Hermes main through `3455422a17`. Setup uses the existing
persona catalog, agent creation service, WorkspaceStore and OfficeStore. The
workspace-create receipt only fences replay; it is not another workspace store.
Presets retain revisioned native storage. Scheduled synthesis extends the existing
hosted-room planner and worker, not a parallel orchestrator.

The post-merge focused batch passed 134 tests in 88 seconds: definitions, native
rooms, retention, wire decoding, operator-channel isolation, shutdown admission,
shared setup and conclusion lifecycle. It ran in one test process. Earlier
mutations disabling synthesis/preset ACK replay and changing workspace selection
produced four expected failures; synthesis-off controls passed.

Launcher now uses one neutral Discussion client for both surfaces; native
authority and protocol are unchanged. See
`EterniaLauncher/docs/companion/planned/DISCUSSION_EXPERIENCE_2026-09-27.md`.
The original native UI acceptance and broader gates are still owed. The earlier
interrupted full suite is not a passing result or a baseline classification.
