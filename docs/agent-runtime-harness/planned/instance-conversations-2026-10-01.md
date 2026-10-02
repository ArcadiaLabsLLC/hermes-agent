# Instance conversation convergence

Status: native foundation implemented; rebased landing qualification in progress.
Worker retirement still requires Launcher parity and matched live latency.

## Integrated checkpoint — October 2

Rebased on `175bfb88e3`, preserving Stage 7's shared app-function invocation and
permission ownership. The full three-directory suite restarted because incoming
changes touched the execution path; the earlier partial remainder is not a final
qualification. Launcher passes its 324 touched tests against this combined code.

Import layers, size, thin namespace and docket gates pass. The frozen-home probe
exceeded an initial 1-GiB test-job cap, then passed at 3 GiB with the same host
reserve. These are contained test processes, not production runtime changes.

### CLI boundary and qualification environment

Reviewed-input argument translation now belongs to the CLI's pure `chat_input`
policy module; native validation remains in `operator_input`. The reachability
and reviewed-input files pass 13 checks; import-layer guards pass 12. Generated
command-reference checks pass eight. Touched-source name resolution and the
upstream-footprint gate pass. The mutation inventory's duplicate anchor also
fails on main and remains in the fork-hygiene queue.

The integrated suite's first 1,272 files finished before discovery of a test
interpreter isolation defect: an installation-owned interpreter can redirect a
mocked update check into its owning checkout. That run was stopped; primary
remained clean. Remaining files use an independent test venv. Both sides pass
the affected sealed-build and lazy-secret files with that interpreter. Its
normal pywin32 bootstrap is required for the real stdio MCP probe, which also
passes on both sides. No runtime repair or permission bypass was added.

## October 2 model-boundary qualification

Model controls now omit absent account scope for native operator rooms; owned
rooms still carry and validate their digest. The new unowned regression first
failed with `invalid_client_scope`. Both ownership cases now preserve the peer,
instance defaults and busy-work refusal. Unowned native sessions keep their
existing workspace policy rather than acquiring an account-owned pinned directory.

Model reads also no longer call session initialization. Admission already creates
those sessions; the operator read port must refuse missing history, not recreate
it. A regression that rejects any later initialization failed for both ownership
cases before removal and passes afterward. Three model files pass **14 tests**.
This removes a redundant writer open that exposed the already-queued SQLite WAL
preflight race; it does not claim that upstream race is repaired.

The broader run found a stale Discussion capability fixture. Only the three
admitted instance flags changed in both repository copies. The native producer
passes all three tests; the Launcher codec passes five, including explicit checks
for owned rooms, instance models and retained profile models.

The first full-scope attempt completed 405 files / 5,813 passing tests before the
12-GiB host free-memory guard stopped its contained processes. It reported the
fixture failure (now repaired), the known duplicate-helper failure, and one realm
history ordering failure. Clean main `d19a19f597` reproduces the duplicate helper;
its realm-history test passes, so the ordering failure remains unresolved, not
classified as a proven baseline failure. No production profile or provider used.

Six later failures shared one stale RPC manifest expectation. Regenerating it
from the native registry adds the four operator-inspection methods and reviewed
`prompt` parameter; no runtime method or permission changed. The three stdio,
socket and office-manifest test files now pass **129 checks**. The separate
provider-child argv test fails identically on clean main and is queued.

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

## Current delivery boundary — October 2 ruling

Intelligence creates, opens and lists native instance sessions through existing
operator read/send/Stop/skills/settings/reviewed-input ports and the shared,
current-account directory. The separate console lane promotes its engine,
controller and instruments; Intelligence will mount it with engine-blind
Companion-derived materials. No new queue, steer, outbox, trace or run-budget
machinery belongs in the reduced Intelligence controllers.

Keep the profile worker, reduced operator view and local thread store. Console
history/account controls, presentation parity, combined desktop acceptance and
matched live latency qualify their later retirement, not this foundation landing.
Earlier checklists below record progression, not additional current-lane scope.

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

## Historical cutover checklist

This checkpoint preceded the October 2 owner boundary above. Later sections
record the implemented model, skills, reviewed-input and recovery work. Console
promotion, combined desktop acceptance and matched live latency remain open.

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
