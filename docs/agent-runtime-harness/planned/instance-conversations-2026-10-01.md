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

## Native foundation checkpoint

Implemented on the feature branch, not landed on main:

- Account-scoped chat mints reuse existing receipts and SessionDB metadata.
  Reopen, read, send, steer and Stop reject another owner's scope. Retry returns
  the original session without rewinding selection or recreating deleted history.
- `runtime.agent.directory` projects native canonical and placed instances.
  Existing profile promotion and bindings win; discovery does not reset work.
- `runtime.workspace.conversations` reuses the native workspace creator and its
  receipt. It never changes selection, moves instances or resurrects an archive.
- Non-spatial rooms release old occupancy claims and retain independent sessions.
  Explicit room members may remain placed elsewhere. Tables keep their placement
  fence. A missing profile fails its own turn, not initialization of the whole room.

Verification: seven focused files passed 69 tests. The later 13-file health run
passed 86 tests with one duplicate-helper gate failure. Import layers, file-size
ceilings, thin namespace, CLI and payload contracts passed. The clean starting
revision `204789cabb` reproduces that gate failure with the same six names:
`_flag`, `_model`, `_owner`, `_read_reply`, `_strip_ansi`, `_tail`.
These counts overlap; they are not a full-suite or native UI acceptance claim.

Positive controls rejected disabled account checks, restored room occupancy
claims, discovery that resets work, and room membership tied to placement. All
planted faults were removed. Tests use isolated stores and deterministic turns;
no live provider, Launcher, installed profile or credential was changed.

The three new production modules are 20–59 lines; the largest new function has
five AST decision nodes (not a cyclomatic-complexity claim).

## Remaining before cutover

Native instance conversations still need rich model/skills/context/attachment
and recovery parity with the current Direct transport. Keep execution in the
existing native owner; do not place profile workers behind a cosmetic instance ID.
Member-model parity also remains.

Then bind neutral Launcher contracts, replace profile-only creation and saved
route identity, and add current-account history plus labelled operator All
accounts. Global-instance handoff must not invent a workspace placement. Preserve
New versus Continue, account/install switches, exact Stop and Mission Control.
Qualify the complete path before retiring old Launcher glue or landing main.

## Account and global-instance checkpoint

Account-owned rooms reuse native admission records and session metadata. Listing
filters before pagination; read-only devices cannot inspect owned runs. Console
operators retain explicit cross-owner access. Scoped commands refuse mismatches.
Empty rooms wait for a message. Global instances retain a null placement, and
opening checks the selected installation before minting.

Fourteen focused tests passed. Disabling the owner and installation guards made
six tests fail; both guards were restored. The broader preceding focused run
passed 30 tests. These are overlapping counts, not full qualification.

One rerun failed when a test observer opened a writer SessionDB while the native
service was polling: upstream writer preflight reported a temporary WAL sidecar
unwritable. The observer now uses the supported read-only connection; the final
run passed. A sidecar race is suspected, not proven; no upstream workaround was
added. The upstream-owned runtime queue records the investigation separately.
