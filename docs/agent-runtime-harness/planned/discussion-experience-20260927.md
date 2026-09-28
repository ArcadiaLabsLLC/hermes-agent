# Shared Discussion experience — approved 2026-09-27

Status: implementation and scoped native acceptance complete. Joint landing uses
the Launcher closeout; broader repository qualification remains safety-limited.

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

## Native acceptance continuation

Launcher `39e5b0b80` / Hermes `f3c0654b80`: client restart restored the exact
pending question without another provider request. Both participants answered;
the configured moderator conclusion settled as a third ordinary attempt with
`conclusion_completed`. The local provider proves lifecycle, not answer quality.

Launcher `9e5654b5b` / Hermes `6d7074f438`: Mission Control reopened a saved table,
started a run using the shared preset, answered its native question, confirmed
Stop while execution was held, removed a member and ended the run. All actions
used the UI through Launcher QA; native records corroborated their outcomes.
The runtime remained isolated from operator profiles and external providers.
Launcher is repairing full-inspector scaling before restart/history acceptance.
Broader gates and joint landing remain open.

Stamped Launcher `8ed07ac60` subsequently reopened the table and its stopped
transcript against the same Hermes code. Its QA window closed gracefully without
stopping that full-Hermes service. Canonical single-worker verification on Hermes
`3b7e425d20` passed 131 tests in 12 focused Discussion/setup/admission files,
103 seconds, 269 MB peak process-tree memory. This does not turn the earlier
interrupted validated suite into a pass.

The optional conclusion widens the existing upstream Group Chat host seam; its
retirement path is recorded in `upstream-footprint-ledger.md`. No parallel
orchestration or lifecycle implementation was introduced.

## Broad qualification

[Executed baseline comparison](../../downstream/discussion-qualification-2026-09-28.md)
reproduces all 60 residual red files on detached main `6ebde5afa3`, including
setup/collection errors omitted by the runner's headline. The remaining test
population and incoming main `8110944532` are still being qualified; this is not
a whole-suite pass. Launcher also includes packaged-runtime main `6d578f0e3`.
The continuation stopped during a whole-PC freeze requiring manual restart;
the qualification note records the last fixture and the no-blind-rerun boundary.

## Final native recheck

Stamped Launcher `c4f3bcbda` with Hermes `9cd5551115` reopened saved Discussion
history across Mission Control and Intelligence and loaded the shared preset.
The runtime code is unchanged from `b02479f843`; newer commits record evidence.
The isolated window closed gracefully and its service drained with zero pending
requests. Producer/consumer fixtures still match byte-for-byte.

The Launcher closeout maps the original eight acceptance steps, structural
measurements, native revisions and explicit release/layout limits:
`EterniaLauncher/docs/companion/planned/DISCUSSION_CLOSEOUT_2026-09-28.md`.
No broad-suite or host-freeze resolution claim is made. The contained continuation
exposed an updater isolation gap; its remaining population is not rerun on the
operator desktop. The fork-hygiene queue owns isolated completion.

Final reconciliation includes main `211bed8aa1` (bundled release gates and queue
claims). Its four affected bundle script test files passed through the canonical
single-worker runner. Discussion runtime code and native wire fixtures are
unchanged by that merge.
