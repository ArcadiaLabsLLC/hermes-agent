# Instance conversation convergence

Status: foundation-only landing; Launcher parity is required before cutover.

## Foundation landing boundary, October 2

Land opaque ownership, canonical instance discovery, native directory paging,
account-aware open-chat, independent room admission and exact-session skills/model
inspection and selection. Existing native stores and admission remain authoritative.
No profile worker or conversation transport is retired. Shared Console mounting,
rich input/activity integration and final lifecycle parity remain branch work.

The full branch is `land/instance-foundation-main-2026-10-02`; the foundation-only
branch excludes its latency lane and transport-cutover work. The isolated hot
probe enabled `persona_chat.hot_sessions_enabled`, yet both warm turns reported
`resident_actor_reused: 0` with root-model revision invalidation. The runtime queue
records this for the retained latency lane; production configuration was not changed.
Current raw gate outputs are `foundation-*.log` in the local
`receipts/instance-conversations/` evidence directory. Historical checkpoints below
are not a claim that the latest foundation or desktop acceptance is green.

## Serial verification after rebase, October 2

Freeze investigation is separate. Tests use the existing Launcher slot wrapper
and canonical Harness runner, without custom containment or overlapping suites.
Desktop-updater tests are outside this run. Raw output and exit codes are retained
as `resume-*.log` beside the earlier receipts.

The 17 touched test files passed 1,606 tests. Boundary checks passed 57 tests;
one duplicate-refusal-constructor failure reproduces on clean main `6c5cc00678`
and is filed in the fork-hygiene queue. CLI/payload contracts, import layers,
size ceilings, thin namespace, frozen-home and documentation checks passed.
The broader run caught two missing room-capability fields in the shared wire
fixture; both repository copies now carry the native descriptor's fields.

Validated scope: 2,204 files, 24,817 passed, 92 failed, 734 skipped
(`resume-hermes-validated.log`, exit 1). Of those assertions, 87 reproduce in
the 48-file clean-main comparison; duplicate-body and realm-history failures
reproduce separately, making 89. The wire producer's three tests pass after
the fixture repair. Two download-pause failures pass isolated reruns; their
cause remains unproven, not dismissed as unrelated.

All ten collection-failure files and four of seven nonzero-exit files reproduce
on main. The other three Git fixture setup errors pass isolated reruns. The
fork-hygiene queue retains these residuals. The final focused run passed 96
tests, including all three upstream-fence checks, with the one independently
reproduced realm-history failure. No test assertion or baseline was weakened.

Rebased onto `4d22e2e53e` (queue-only incoming change). The 12-file final boundary
run passed 1,288 tests and retained only the reproduced duplicate-constructor
failure. Receipt: `resume-hermes-rebased-gates.log`, exit 1. The tombstone,
upstream-fence, import, size, namespace, contract and documentation checks passed.

These results do not establish full-suite or desktop acceptance. No worker,
operator conversation view or local transcript store is retired.

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

## Resident probe positive control, October 3

Probe branch `test/instance-latency-control-2026-10-03`, commit `ee5385d2d8`,
against production code at `52e6222648`. One isolated native serve, one instance
session, three loopback-provider turns; no external provider or desktop QA.
The boot assertion finds the resident registry. Every turn retains that registry,
the root below and its active session; root/profile configuration files are unchanged.

Native receipt fields (both warm turns):

```text
hot_sessions_enabled=True
root_chat_session_id=persona_chat_personainst_profile_latency-probe_521c4ec23fd7
registry_same=true
config_files_unchanged=true
resident_actor_reused=0
resident_rebuild_runtime_signature_changed=1
resident_rebuild_component_root_model_config_revision=1
root_model_config_changed_fields=["_usage_anchor"]
```

`agent/usage_anchor.py::persist_usage_anchor` updates token-accounting state in
the session's `model_config`. The fork's
`agent_runtime/mission_chat_turn_context.py::mission_chat_runtime_signature_components`
hashes that whole dictionary. Thus ordinary usage invalidates resident identity;
this is not a missing registry or a new-session probe artifact. The repair below
preserves native accounting and genuine configuration invalidation.

Six prerequisite/observation tests and one native probe passed, serialized through
the Launcher heavy-run wrapper and `scripts/run_tests.sh -j 1`, without retries.
Raw receipts: `probe-control-unit-2026-10-03.log`,
`probe-control-native-2026-10-03.log` and its JUnit `.xml`; both runs exited zero.
Ruff passed. No production change, worker retirement or new latency comparison;
the earlier warm delta remains provisional, not a measured cost of this defect.

## Resident identity repair, October 3

The fork-owned projection now lives in `agent_runtime/persona_chat_identity.py`.
The turn builder and actor prewarm retain one signature composition; no cache,
storage authority, protocol or upstream implementation was added.

Upstream accounting is correct and unchanged. Upstream also already caches
gateway agents (`gateway/run_agent_cache.py::GatewayAgentCacheMixin`); the claim
that it has no resident agents was incorrect. That gateway-owned cache is not
the Harness's persona-root registry. This repair follows selective identity
projection without introducing another owner or rewriting either cache.

The session allowlist is empty by audit: its chat override is consumed by
`_chat_effective_model_payload`, whose resolved provider/model already enter the
key. Ownership is checked before admission; transcript revision and active tip
have separate native coherence checks. Native usage/pruning/thread metadata
does not construct the actor and remains persisted unchanged.

The audit also found that resolved endpoint/credential invalidation was local-model
only. `AgentRunExecution.acquire_agent` now adds one private resolved-runtime
digest for every provider, replacing the local adapter's separate signature helper.
It covers the provider/model/API mode, endpoint, credential and existing local
parameters. Prewarming takes the same acquisition path. Receipts disclose names only.

Verification receipts (overlapping test counts):

- `identity-red-2026-10-03.log`: five bookkeeping cases fail before repair;
  two genuine provider/model invalidations pass.
- `identity-connection-red-2026-10-03.log`: five resolved-client changes fail
  to rebuild before repair; unchanged-client cleanup passes.
- `identity-move-2026-10-03.log`: 40 existing tests pass after extraction only.
- `identity-focused-2026-10-03.log`: 334 pass, zero fail.
- `identity-runtime-focused-2026-10-03.log`: 249 pass, zero fail after the
  resolved-client correction, including prewarming and send-path reuse.
- `identity-native-2026-10-03.log` / `.xml`: one native probe passes; hot sessions
  enabled, registry/root unchanged, cold reuse `0`, warm reuse `1/1`.
  Each turn reports 12 prompt / 3 completion tokens; each native usage anchor
  matches the durable session record. No external provider or desktop QA ran.

Probe assertions remain on the latency branch. Production hot-session settings
and worker wiring remain unchanged. These receipts establish reuse and accounting,
not a new worker comparison, remote acceptance or the earlier +335 ms's cause.

Health receipts: `identity-gates-2026-10-03.log` has 1,283 passes and three
failures. All three reproduce on unchanged main `541f497902` in
`identity-baseline-gates-2026-10-03.log` (six passes, three failures): duplicate
refusal constructors and two open-chat legibility checks. Their existing runtime
and fork-hygiene queue rows carry this evidence; no baseline was weakened.

Size audit (raw / repository code lines): turn context `1170/750 → 925/676`;
identity policy `126/94`; runner `822/586 → 823/588`. The new policy's largest
function has 20 code lines and nesting depth 3, not a cyclomatic-complexity score
(`identity-size-2026-10-03.log`, source spans counted through the AST).
The extraction and behavior repair are separate commits.

Remaining source-confirmed weakness: `_runtime_resolve_cache_key` stamps only
the profile's `config.yaml` and `.env`; `_resolve_request_runtime` may return that
answer for 30 seconds. Native authentication can instead change profile or shared
`auth.json`, without touching either stamped file. The actor now honors the
resolved answer, but cannot detect a change hidden by that existing memo. The
runtime queue tracks auth-owner-aware invalidation and a sign-out/rotation test;
no live sign-out failure or account leak is claimed here.
