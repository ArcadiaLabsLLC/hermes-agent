# Discussion tables — continuation handoff

Status: partial implementation on `feat/discussion-tables-20260916`; not ready for main.

This branch now contains the tested definition/persistence foundation plus the full implementation contract in `upstream-bot-mode-peer-integration.md`. The foundation is intentionally not registered on RPC and does not execute room turns.

## Implemented here

- strict table/preset values with exact `(install_id, persona_instance_id)`-shaped addressing semantics;
- capacities 2/4/6/8/10/12 and Auto, deterministic logical seats, explicit remap reporting;
- revisioned SQLite storage, workspace/kind/id ownership, tombstones, bounded listing;
- preset Load/Modified/Revert semantics that preserve the loaded revision rather than live-linking to a changing preset;
- focused tests and mutation evidence in `discussion-definition-foundation-validation.md`.

The foundation was exercised in the prior sandbox with 202 focused cases passing (78 new authoring/storage + 124 unchanged dispatch/hosted-room regressions). That run used the documented missing-`pytest-timeout` command-line workaround; rerun normally in the project environment before landing.

## Remaining runtime work

1. Bind the store to the serve-owned database/home and add one runtime owner/service. No client-supplied paths or import-time I/O.
2. Add durable Start intent, caller idempotency key, expected table revision, immutable initial snapshot, execution install, current membership, table/instance presence, and the same transactional busy fence for definition mutation.
3. Reuse `HostedRoomRuntime` through an instance-bound `InternalSessionRPC` adapter. Two persona instances that share one Hermes profile must receive separate native room sessions.
4. Preserve ordinary task-scoped/default chat pointers on room open and every terminal path. Do not restore a stale saved row after a turn; a newer operator thread must win.
5. Lift native room policy to support the user-approved 12-member capacity without changing stock Bot Mode defaults globally. Current upstream assumptions include six members, a 10-message discussion cap, and turn-coordinate positions 0–5.
6. Persist joins from room task/execution generation to exact native session/client-message identity. Reconcile commit-before-callback without another model run. Unknown outcomes remain indeterminate; retry is explicit and advances execution generation.
7. Cancellation must target the exact task/session/attempt. Stop requested is not stopped until the actual attempt settles. End/remove cannot release presence while execution may still be alive.
8. Add authenticated additive `runtime.discussion.*` methods through the existing serve JSON-RPC lane, with console authority for writes/execution, bounded reads, typed refusals, honest capabilities, and reconnect-safe revision/event behavior. Do not widen native peer permissions or add another listener.
9. Build real producer/consumer contract fixtures for Launcher rather than duplicate handwritten constants.

## Required acceptance before main

Rerun the new foundation tests with normal dependencies, then cover: same-profile distinct instances, 12-member generation/replay, default chat pointer unchanged across success/failure/clarification and concurrent operator thread changes, concurrent Start/Edit, Start crash checkpoints, commit-before-callback recovery, exact stale Stop, removal/End during work, reconnect, old-runtime capability absence, preset/capacity conflicts, and no canonical office-position writes from seating presentation.

Use deterministic models with real stores/transports before a bounded live-provider smoke. Run the repository-prescribed broader suites only at the feature-complete checkpoint. Coordinate with the Launcher branch and complete Stage C visual QA there before landing either half on main.
