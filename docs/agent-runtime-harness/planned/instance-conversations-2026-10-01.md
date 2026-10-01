# Instance conversation convergence

Status: implementation in progress; Launcher parity is required before cutover.

Reuse persona instances and their existing profile binding, chat mint receipts,
SessionDB, turn admission and discussion scheduler. Do not add another identity,
credential, session or execution authority.

Account ownership is the Launcher's existing opaque digest, stamped at session
creation and retained on replay. The Harness stays account-blind. Mission Control
defaults to the current account; explicit operator-only All accounts is labelled.
Legacy operator sessions are not silently assigned to the first Launcher caller.

Only spatial table runs claim exclusive instance occupancy. Independent rooms
retain distinct session and execution IDs; table placement is unchanged. A native
Conversations workspace supplies a stable home without moving placed instances.

Qualification must cover owner mismatch/replay, fresh versus existing sessions,
simultaneous non-spatial rooms, preserved table claims, recovery and exact Stop.
Launcher capabilities must retain parity before its profile-only route is retired.

Client plan: `EterniaLauncher/docs/companion/planned/INSTANCE_CONVERSATIONS_2026-10-01.md`.
