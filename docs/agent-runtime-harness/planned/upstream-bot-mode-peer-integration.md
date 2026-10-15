# Discussion tables and upstream integration

Status: implementation contract; not yet integrated into main or visually certified.
Owner: the Mission Control program across Hermes and Launcher. The user explicitly
requests feature branches, with testing and main integration in a subsequent Work
session. This supersedes the chat attachment `hermes-upstream-integration-plan.md`.

## Pinned audit

Hermes: `fd13e82c94a9de0f950563b96637767c4691decd`, including upstream
`416a8177c25d87aa9929dfcf31f7964137d7fcdd`. Launcher:
`00f7c8e47fb2288ce5564f4d06a01491fce3ecb0`. Read root AGENTS.md, downstream-development.md,
relevant area AGENTS.md, Launcher CLAUDE.md, Brain Index, Mission Control program
and canonical scene/transport/chat notes. Hermes has no root CLAUDE.md at this pin.
Binary artwork was not included in the source audit; visual validation is owed.

The folded fork is not replaced: persistent persona INSTANCE identity, profile
admission, native chat persistence, task-scoped conversations, realm identity,
native transport and completion delivery remain authoritative. An upstream Bot
is profile-shaped; an instance is not a profile alias. A table is not a Task,
a persona, a desk, an upstream Bot Chat, or an executable flow-graph node.

### Findings that change the preliminary design

* `gateway/hosted_room_discussion.py::validate_roster` caps stock rooms at six and
  refuses duplicate local profiles; its turn-coordinate parser also caps seats
  at six. Twelve chairs alone would not implement a twelve-agent discussion.
  Add explicit immutable policy limits, with stock defaults unchanged; the
  native adapter admits distinct instances sharing one real profile.
* `tui_gateway/hosted_room_driver.py::HostedRoomRuntime` already supplies durable
  leases, generation fences, cancellation, ambiguous-attempt recovery and an
  injected `InternalSessionRPC`. Reuse it. Do not start a second TUI server.
* `tui_gateway/hosted_room_service.py` is a profile/desktop composition root,
  not the native instance adapter. The native composition supplies identity,
  ownership and the same pure discussion policy to the existing worker.
* `PersonaInstanceStore.open_chat` AND the finalization in
  `hermes_cli/harness_parts/persona_commands.py::_mission_chat_commit_turn`
  repoint the default chat. A room-specific session alone is insufficient.
  Add a trusted, context-local auxiliary-chat scope that preserves the instance
  row while running the SAME native handler. Never expose this bypass as a
  client flag. Ordinary operator/dispatch behavior must be unchanged.
* `MissionOfficeGame` is render-only with a shared 2D/3D actor source. Level
  decorations are deliberately not hit targets. Tables require selectable
  render nodes and their own domain write path, not fake OfficeActor personas
  and not a second world/editor implementation.
* `MissionOfficeHost` is provider-free. Pass a controller from the existing
  provider-bound composition root; do not introduce provider reads into it.
* Native cross-install relay has a documented A->B->A chain gap. Table work
  must not imply that gap or cross-account authorization has been solved.

## Product contract

The authoring flow is: drop Discussion Table -> select style/capacity -> load or
build a team -> type today's topic -> Start. Configuration has no model side
effects. Clicking the object opens Details in the existing office inspector.
A conventional transcript is available alongside the spatial presentation.

Four different lifetimes:

1. Table family/variant: geometry, dimensions and stable seat sockets.
2. Discussion preset: a versioned recipe, not a permanent group.
3. Placed table: stable table ID, workspace, transform and editable configuration.
4. Discussion run: a fresh room, member sessions, immutable start snapshot,
   public transcript and lifecycle. Starting again never reuses yesterday's room.

Supported agent capacities: 2, 4, 6, 8, 10, 12. Auto chooses the smallest variant
that fits the selected team. The optional observer/operator position is additional
presentation, not an AI participant or an extra model call. Capacity means agent
seats. Physical scale does NOT change capacity. A preset larger than the table
requires explicit resize or participant editing; no silent removal. Resizing
retains table identity and transform, validates finite values, and is blocked
while a discussion occupies the table. Round and conference layouts have actual
chair sockets and different footprints. Automatic placement is deterministic.

The participant selector lists addressable durable instances, with an ID suffix
where names collide. It does not use the template/profile creation palette as its
roster. Two instances using one profile are independently selectable. Missing,
retired, foreign-workspace or unavailable bindings are shown/refused, never
replaced by another instance with the same name. Selection is snapshotted at
Start, NOT when an animation happens to reach a chair.

Presets: None/Custom, named dropdown, Save As, explicit Update, Revert, Modified.
Load copies values and records preset revision. Later preset edits do not mutate
loaded table copies or active runs. Topic is per run, not saved in a preset.
Deletion keeps existing table copies and run history. Rename preserves preset ID.
Saved seating preferences are optional; incompatible geometry remaps deterministically
and exposes the resulting seats before Start. A shrink never silently omits people.

A run retains its initial configuration forever. Live membership changes are
explicit, revision-checked commands over a separate current membership projection.
Historical members remain resolvable for replay. Removing a busy member requests
cancellation of that exact task; it cannot cancel a newer operator turn. An
invitation does not rewrite the preset. Physical presence is exclusive per instance
per install, and distinct from membership and current speech.

## Execution and state ownership

Hermes owns table/preset configuration, revisions, admission, current membership,
run bindings and execution. These live in a namespaced SQLite schema at the
serve's explicitly captured head home, alongside the reused hosted-room tables.
No import-time disk reads or writes. One process owns the runtime root. Startup
reconciles unfinished Starts before scheduling; shutdown quiesces new admission.
Closing a Launcher window neither stops nor recreates a discussion.

This release's table/preset storage is install-owned and shared by consoles
connected to that runtime. It does not claim realm replication of these new
entities. Existing agents and office placement retain their existing realm rules.
A replicated agent's execution install must be chosen explicitly; do not let
multiple installs run the same discussion by synchronizing an active flag.

Native room policy uses a durable admitted member catalog plus the current active
member IDs. The catalog retains removed members so old events still validate;
the active set controls future contributions. The hosted room's birth roster is
the immutable start roster, not a competing mutable roster authority. Policy
limits are persisted per run: at most three rounds, a bounded contribution budget
that accommodates the selected capacity, and bounded native member-turn time.
Only the known public log delta enters a member prompt. No private DM transcript
is copied into another member's context, and private working output is not treated
as public until the canonical turn has a committed terminal result.

Start requires a caller-generated idempotency key and expected table revision.
A SQLite transaction captures the exact effective configuration, acquires table
and instance presence, and records a deterministic run ID and initialization
intent. The hosted-room/session effects are idempotent and reconciled after a
crash; no LLM runs until initialization is complete. Same key/different content is
a conflict. A lost response is reconciled using the SAME key; never mint another
key automatically. Other consoles competing for the same table/instance receive
a typed busy conflict rather than creating a second run.

Per-member room sessions are server-issued native `persona_chat_...` sessions,
with explicit instance ownership and a durable (run, member) mapping. They remain
separate even for members with the same profile. Their title is presentation,
never an ownership lookup key. The trusted auxiliary scope prevents room opens
and room finalization from updating the default chat pointer, skill projection
or stale instance row. Existing native admission, tool permissions, transcript,
turn journal, provider routing, caching and compression still execute normally.
Profile changes after admission are a typed refusal, not implicit rebinding.

Attempt coordinates are (run ID, task ID, execution generation, instance ID,
session ID, native client-message ID). Record the mapping before execution. The
native turn journal is the authority for whether a model turn committed. Adapter
receipts retain pre-admission refusals and clarification metadata without replacing
that authority. Recover a native commit that preceded a lost callback; never rerun
it. A prior-process attempt without terminal proof is indeterminate, not success
or permission for a blind retry. Retry is an explicit operator action and advances
the existing worker's execution generation.

Cancellation uses `agent.interrupt_scope.InterruptScope` bound to the EXACT attempt.
Stop requested is not stopped: the public state remains stopping until the worker
acknowledges. A stale stop cannot select another task by the instance's current
chat pointer. End stops and drains before releasing presence. An unknown in-flight
outcome remains visible; explicit recovery never silently discards it.

## Wire and compatibility

Use additive `runtime.discussion.*` JSON-RPC methods on `agent_runtime.serve_rpc`,
not a new socket, REST listener, argv protocol or widened parity envelope. Register
with explicit tiers; all execution and definition writes require console authority.
Normal native peers gain no new methods through this feature. Caller identity
comes from RpcContext, never params. Unknown fields, malformed IDs, non-finite
coordinates, overlong text and oversized lists are rejected with typed reasons.

Operations cover capabilities; workspace tables and presets list/save/delete;
run start/get/list/send/stop/end; explicit live member add/remove; exact task retry;
and clarification continuation. Definition writes use expected revisions.
Read responses carry contract version and bounded cursors where needed. Run reads
include latest public events, tasks, pending input, initial configuration and live
membership. Unknown states are represented as unknown, never mapped to ready.
The controller serializes mutations and reconciles ambiguous outcomes.

Old Hermes without the methods shows an unavailable feature explanation; no inert
Start button. New Hermes with old Launcher remains compatible. Register methods
lazily without filesystem work; retain RPC_CONTRACT_VERSION and existing payload
keys. Add a shared contract fixture and test it against real producers, not two
identical hand-authored constants.

## Launcher architecture

Feature-owned typed models/RPC client/controller/actions under
`lib/features/mission_control/discussions/`. Composition uses the currently aimed
serve connection and workspace; stale replies after an install/workspace change
are discarded by controller identity. Domain state and mutations do not live in
widget build. Transient UI edits stay in the controller, save results reconcile
by revision, and transport failures preserve unsaved values and pending intent.

The palette uses the existing world/screen placement adapter. Tables enter the
ONE office render model with explicit selectable identity. Table dragging sends
one definition write at gesture end. Table configuration and layout writes never
call agent creation, desk movement or the ordinary office actor upsert.

A presentation controller derives chair positions and agent pose/attention from
authoritative membership/task state. Approach/return are transient transforms,
not OfficeStore writes; interruption/reload can skip to the current pose. Renderer
absence, reduced motion, obstruction and frame rate cannot block execution. Return
uses the latest canonical position, not an obsolete position captured at Start.
No double-ticking the engine animation clock. A table can be inspected in 2D as
well as rendered in the actual 3D lane. Use existing spatial descriptors/materials,
not a screenshot or a flat image standing in for 3D geometry.

Details is a responsive existing-inspector child: style, capacity/Auto, preset,
searchable instance selection, topic, settings, validation, Start. Active mode
shows speaker/working/needs-input/stopping/unknown, transcript, invitations and
End. History opens without starting a new run. Draft changes cannot edit a live
run by accident. Keyboard controls, labels, focus and reduced-motion behavior are
required. Validate at 1280x800 and 1100x720, then larger sizes/DPI. Visual QA is
through the documented launcher_qa MCP path and a stamped test binary.

## Implementation slices and gates

A. Definition/validation store and atomic Start intent; per-room upstream policy
limits; native auxiliary-session and exact-attempt adapter; serve lifecycle/RPC.
B. Native coordinator over HostedRoomRuntime, durable recovery, public log,
clarification and membership; no second model loop or scheduler.
C. Typed Launcher client/controller, preset/details authoring, task transcript,
actual office drop/hit/resize/move and 3D table/seat/avatar projection.
D. Focused behavioral tests after feature-complete checkpoint; real cross-repo
contract tests, base-failing positive controls and Stage C validation; then Work
reviews and integrates both branches. Main remains unchanged in the cloud task.

Mandatory tests: two same-profile instances; default chat pointer unchanged at
open AND successful/failed completion; context scope restored after exceptions;
12-member turn coordinates; invalid capacity and NaN; oversized preset; concurrent
CAS writes and Start keys; Start crash between native intent and hosted room;
commit-before-callback recovery; lease expiration; exact stop vs newer operator
turn; removal during execution; shutdown/reconnect with no duplicate turn;
clarification continuation in the correct child session; same-name instances;
empty/unavailable roster; old-runtime method absence; stale aimed connection
responses; preset update/deletion isolation; no canonical agent movement;
selectable 3D table and reachable Details/Start/End/history controls.

Validation commands: Hermes `scripts/run_tests.sh` for changed focused files and
relevant existing native/hosted-room suites. Launcher `flutter analyze`, codegen
only when annotated declarations change, focused `flutter test <file>` and the
canonical `dart run tool/run_tier.dart --tier=fake` / tooling lane at integration.
Do not run expensive suites against half-written code. Record actual commands and
outcomes, not assumed success; report environmental limits independently of defects.

## Original upstream roadmap retained, not silently promised by a table

Stock peer interoperability is a separate opt-in transport: use async Runs API,
capability negotiation and retained idempotency keys for long work; never expose
API_SERVER_KEY to a widget/model/schema/log. Remote canonical Bot Chat is not the
native task-scoped session contract. Inbound exposure requires an explicit export
binding, not profile-name-to-first-instance guessing. Native-to-native installs
keep their existing transport and credential allowlist.

Delegation remains temporary child work, not office-agent creation. Reuse its
steer/stop/schema/cost mechanisms through existing native completion delivery.
Cron routine occurrences need an explicit execution install and occurrence owner;
MCP discovery/catalog visibility never grants capability. Cross-install rooms
need one fenced authority and a real recovery protocol; no automatic split-brain
failover or new cross-account trust is included merely by adding chairs.

These optional roadmap items remain separate from the user-approved table flow;
implementation receipts must name precisely which capabilities shipped. The table
feature must not advertise any transport, routine or permission behavior it does
not actually implement.
