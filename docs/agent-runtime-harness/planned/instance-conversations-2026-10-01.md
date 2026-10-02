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

## History checkpoint

`runtime.operator.conversation.list` reads the existing SessionDB, scopes before
pagination and uses an account/installation-bound keyset cursor. Console tier
is required for both views; All accounts is explicit. Unowned history remains
labelable, removed agents remain unavailable, and concurrent creation does not
shift subsequent pages. Projection reuses native curation, lineage and usage.

The public SessionDB list API lacks metadata predicates and keyset pagination.
One fork-local query uses its pooled `_read_all` boundary; the seams queue records
the public-door debt. No database, account directory or upstream edit was added.

Verification: 64 history/curation tests passed; the later authorization, manifest
and import-layer run passed 117 tests (overlapping counts). Disabling native
owner filtering failed the scoped-page test; disabling adapter owner validation
failed its wrong-owner test. Both controls were restored. Seven client adapter
tests passed. These are feature-branch checks, not UI acceptance or completion.

The RPC manifest now advertises the open-chat parameters, including ownership
and installation checks. Clients can refuse an older account-blind runtime
before minting. The existing send-parameter tests now permit additive method
entries rather than freezing the method set. Owner/open-chat tests passed 29
cases; send/manifest tests passed 48. Launcher production scope binding remains
part of the account-view cutover, not this checkpoint.

## First-turn baseline, October 2

The [matched loopback measurement](instance-conversation-latency-2026-10-02.md)
now covers both real native routes: three cold and six warm turns per route.
Instance opens are faster, but replies after Open and warm replies are slower.
The worker remains. These tests do not establish real-provider or UI latency
parity; final integration qualification is still required before retirement.

## Native session inspection, October 2

Shared session helpers now live below the CLI in `agent_runtime.persona_chat_session`.
The existing transcript reader and inspection share one read-only, owner-checked
SessionDB boundary. Native settings expose the existing model cascade and lineage
usage; skills expose the existing catalog, full documents and recorded loads.
Skill inspection uses the native session's recorded working directory and the
existing project-trust gate. Neither inspection starts an actor, changes selection
nor creates another store.

The Launcher mounts its existing Skills browser for the exact attached session,
only when advertised. Live skill-load events and model-write/client parity remain
open, alongside context/attachment/recovery parity and console account isolation.
The profile worker is not retired; this branch is not a completed cutover.

Verification: 1,356 tests passed across eight focused files and boundary gates;
four affected tests passed after the type/documentation cleanup, and both new
invariants passed with recorded-workspace coverage added. Removing
owner validation and profile binding failed both new invariant tests; restored
checks passed. The earlier tombstone failure was our helper-name collision,
corrected without weakening the gate. No live runtime or provider was used.
New production modules are 124 and 45 lines; the largest new function is 27 lines
with six AST decision nodes, not a cyclomatic-complexity measurement.

## Native model controls, October 2

Exact instance sessions now use upstream model inventory and `switch_model`
validation, then the existing instance-default and chat-override stores. The
worker and instance adapters share the same pure catalog projection. No provider
catalog, credential writer or settings database was added.

Selection refuses active, uncertain, admitted and question-blocked turns under
the existing session lease. Agent defaults retain native live inheritance;
Launcher labels that effect rather than promising future-conversation-only scope.
Thirty-three tests passed across five focused files. Disabling the idle guard
failed four cases; restoration passed. A bounded Dart-to-native test also passed
model read/write/default persistence alongside reconstruction and exact Stop.

These are branch checks, not desktop acceptance. Rich conversation transport,
console account isolation and final qualification still precede worker retirement.

The curated reply now carries its existing journal outcome beside its public
elements. Reopening a partial interrupted reply preserves Stop rather than
implying completion. Curation and response tests passed 63 cases. Forcing the
outcome to `completed` failed the new regression; restoration passed. The Launcher
uses these facts in its shared Activity/response presentation, including native
reconstruction coverage. No execution or transcript authority moved.

## Live skill evidence, October 2

The native runner now carries canonical skill-load receipts through its existing
journal. Conversation reads expose those receipts; no catalog, event buffer or
poller was added. Unknown/interrupted loads never imply successful loading.

Seventeen focused tests passed. Dropping the journal field failed the new
runner-to-read regression; restoring it passed with the import-layer gate.
Nine Launcher tests and one bounded Dart/native reconstruction test passed;
touched-source analysis is clean. This closes live skill evidence, not the
remaining rich-input, account-selection and transport-cutover requirements.

## Reviewed native input, October 2

Instance messages now reuse the reviewed-prompt validator and upstream multimodal
input. Native wire/history preserve admitted text and image blocks across restart;
curated previews exclude encoded image bytes. No upload service or image engine
was added. Plain CLI input retains its existing limit.

Both real-agent round trips passed: native vision and configured upstream vision
fallback. Removing the reviewed marker failed both tests by truncating context;
restoring it passed. The related native run passed 156 tests. Its one failure,
the duplicate-body gate, also fails on clean main `667f7521c8`: the unchanged
`ProviderRefused` and `DefaultModelRefused` constructors collide. It is queued,
not waived. Launcher focused input/conformance tests and the bounded native-client
reconstruction test passed. This is not full transport parity or desktop acceptance.

## Session-owned workspace, October 2

Account-owned sessions initialize SessionDB's existing cwd at mint, reusing the
persona directory policy or creating a native session directory. Execution and
preview resolve that same field. Missing owned directories refuse, never silently
fall back. Unowned console sessions retain their policy. No workspace side store
or circular import was added.

The native directory, workdir, runtime, tool visibility and layer group passed
88 tests. Disabling the pinned execution path fails the regression. Eleven
Launcher projection/review/widget tests passed. Rich input and context are now
covered; full instance cutover and account-safe console wiring remain open.

Clarification choices now persist on the existing native ticket and reopen with
its exact identity. Settled tickets disappear; history never recreates questions.
The native group passed 94 tests. Removing ticket payload persistence failed
the new recovery regression. Three client/controller/widget tests passed.

## Instance-room model parity, October 2

Account-owned room sessions now initialize the same native workspace field as
direct sessions. Model reads and changes reuse operator-session services with
the member's exact instance, session and owner; placement stays unchanged.
Uncertain execution blocks changes. The native room/model/import group passed
22 tests; the binding recheck passed separately. Full cutover remains open.

The operator-only All accounts directory includes native persona-chat rows with
null metadata. Current-account queries still exclude unowned sessions; no owner
is inferred or assigned. Three native directory tests and the isolated Launcher
creation/continuation test pass. Account-safe console wiring remains open.

## Final native boundary checks, October 2

Execution reads expose the existing admission's frame request identity so clients
can observe streaming without a second event/history owner. Eighteen room/drain
tests pass: an empty or settled non-spatial instance room permits maintenance;
queued, running and uncertain work still blocks it. Restoring the old
profile-group-only predicate fails the empty-instance-room regression.

The isolated Launcher/native room test opens an empty owned room, retries its
mint, runs Compare/Discuss/Reply on the same member sessions, rejects a different
owner and preserves the existing console room. No live profile or provider.
The October 2 owner direction keeps workers until console promotion, parity and
matched live latency qualification; this lane does not retire them.
