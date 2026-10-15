# Agent Console subagent foundation — Step 1

Owner authorization: October 14, 2026, Step 1 only of the seven-step Console
subagent plan. This record accompanies the implementation and its verification;
it does not authorize visual integration, controls, history, defaults or release.

## Contract and ownership

`runtime.conversation.subagents.capabilities/list/tail` and
`runtime.operator.conversation.subagents.capabilities/list/tail` are console-tier
reads on the existing authenticated method lane. The manifest publishes each
method's accepted parameters. The peer allowlist is unchanged. Discovery returns
protocol version 1 and only implemented `list` and `tail` operations.

The native service validates install, transport-derived actor, client namespace,
profile, conversation route and current profile-home binding. Its existing-only
borrow refuses absent, dead or retiring owners without starting or attaching a
worker. It sends the server-derived native session, owner digest and worker
generation through that binding's peer. The worker checks the attached native
transport/session object, then filters lineage-only visibility by the actual
child/parent database and captured profile home.

Operator reads reuse `operator_session_read` and the existing persona profile
resolver. A child must belong to the same actual SessionDB, durable compression
lineage and captured execution profile. For inherited profiles the conversation's
recorded head is the comparison, never an ambient environment read. When a parent
is active, transcript access also requires its real descendant relationship.
Visibility after a parent rebuild does not imply current transcript authority.

The server-issued reference signs the owner scope and an exact weak object
generation. Native owner generations also include worker, transport and session
record identity. `tail` requires both `child_ref` and `expected_generation`, pins
the authorized object across IO, then rechecks owner and registry membership.
Recycled ids, lost owners and changed profiles refuse. References hold no agents
alive and create no scheduler or execution store.

The list projects the eleven upstream roster fields plus nullable `child_ref`.
Lists report `truncated` at 256 children or an 800 KiB serialized-row budget.
Output reads at most 16,384 bytes from the existing live log, permits complete
assistant/tool/result/start/final lines, excludes thinking, kickoff context,
headers and unknown roles, and applies the existing server secret scrubber.
Redacted output is also byte-bounded. Paths and private objects never cross the
wire. Historical failures/results belong to Step 5 and are not claimed here.

Every reply echoes the public conversation identity and returns `version`,
`generation` and `observed_at`. The typed Launcher adapters validate that identity,
drop stale-generation and closed-binding replies, preserve unknown facts, and do
not retry through another route. `accepting_steer` remains a native fact; no
control capability is advertised in Step 1.

## Per-seam ledger

Classification uses the pinned upstream manifest and the current upstream tree.
The owner approved the additional compute-host seam on October 14, 2026. The only
changed upstream-owned file is `tui_gateway/compute_host.py`: its existing fork
observation hunk gains one allowlist line and uses the native transport-aware
dispatcher. Its measured footprint changes from +46/-5 to +47/-5; no upstream
line is newly deleted. All other feature changes are fork-owned. The canonical
ledger accounts for that file and links this per-seam register.

| Seam | Exact owner/connection | Classification and disposition | Replacement condition | Behavior proof |
| --- | --- | --- | --- | --- |
| Service borrow mode | `conversations/service.py::ConversationService.subagents` → `_session(existing_only=True)` → `bindings.py::Bindings.borrow` → `conversations/subagents.py::inspect_children` | Fork-owned; existing route-lifetime authority, zero upstream edits | Fold into a shared explicit existing-owner operation if that authority acquires one; never keep parallel attach policy | `test_subagent_conversation_route.py`: missing/dead/retiring owner never attaches; actor/client/profile cannot cross routes |
| Worker-entry registration | Existing `gateway_extensions.py::register` → `conversations/worker_subagents.py::register`; `scripts/gen_contract_catalog.py::_registry` → `tui_gateway/contract_catalog_data.py` | Fork-owned; one shared registration through the existing gateway extension, native profile scope and `register_method`. Separate subprocess/in-process installations removed | Use a native public extension registrar when it owns these hosts and generated contracts | Real child reads in subprocess, compute-host and in-process modes; registration and catalog parity |
| Compute-host observation | `subagents/native.py::inspect_native` → `subagents/compute.py::observe` → existing `HostSupervisor.observe` → `ComputeHost._handle_observe` → `server.dispatch` with the host's transport → the same child reader | Owner-approved held hook seam in one already-carried upstream file; file +46/-5 → +47/-5. No new supervisor, registry, control path or upstream PR | Retire the allowlist addition when native owned-child observation has a public extension registrar; retain the observer's real transport binding | Actual isolated `delegate_task` child roster/output; forged transport, replaced owner, stale references and no-start refusals; positive controls remove forwarding generation, transport binding and allowlist |
| Operator RPC family | `serve_rpc/__init__.py` → `serve_rpc/operator_subagents.py`; `subagents/operator.py::inspect_operator` → existing operator/session/profile authorities | Fork-owned; console tier via existing dispatcher; peer grants unchanged | Retain harness target validation while the harness owns operator identities; replace only the underlying bridge when a public owned-child service exists | Real dispatcher/stores: wrong installation/workspace/persona/instance/session/client and read-tier/unknown callers refuse |
| Native method registration and discovery | `conversations/rpc.py::OPERATIONS` → existing execute/authorization; `subagents/params.py::METHOD_PARAMS` → `serve_rpc/registry.py::manifest` | Fork-owned; one method lane and manifest, zero upstream edits | Retain while native conversation routes remain harness-owned | Manifest tier/parameter coverage; exact service-to-worker routing |
| Upstream child owner/registry bridge | `subagents/native.py`: reads `_active_subagents` under its lock; calls native `_visible_subagent_records`, `_current_session_steer_authority`, `_subagent_transport_matches`, `_is_descendant_of`; child DB/log-home evidence is read in `subagents/operator.py` | Fork-only caller of private upstream APIs, explicitly held compatibility seam; no upstream edit and no PR claimed | Retire these private reaches together through a public owned-child inspection API with exact object/transport/profile/lineage guarantees. Public plugin lifecycle handles cannot currently inspect arbitrary delegate children | Native authority, cross-profile equal durable ids, recycled id and in-flight replacement tests |
| Operator active-parent evidence | `live_turns.py::conversation_agents` → `subagents/operator.py::_Owner.exact` | Fork-owned projection of existing live turns, no additional lifetime/state owner | Replace if the existing live-turn API directly offers the same scoped object authority | Owned roster versus exact transcript access |
| Public output projection | `subagents/output.py::read_public_tail` reads the child's existing native live-log path; `redaction.py::scrub_secret_values` owns secret removal | Fork-owned reader of upstream format; zero upstream edits | Replace with a native public redacted event-tail API if it exposes the same content boundary | Real `LiveTranscriptWriter`; thinking/secret/partial/unknown lines excluded; byte bound |

No changes to upstream `tools/delegate_tool_registry.py`,
`tui_gateway/methods_subagents.py`, `tui_gateway/server.py`, config setters or
native launch/control engines are part of this step. A future upstream edit
requires its own measured canonical ledger row, disposition, retirement reason
and explicit owner approval of the extra footprint.

## Verification and remaining gates

Final focused runner: eight files / 33 tests passed, including actual
`delegate_task` child reads through native-worker, isolated-compute and in-process
execution, all using a deterministic loopback provider and disposable homes.
Dart adapter tests use replies captured from the real harness/native child
readers; their fixture capture doubles the process boundary. No paid model call
or running-user conversation is used.

The changed upstream-manifest path set is exactly `tui_gateway/compute_host.py`;
the existing ledger gate alone is insufficient because its missing-row gap is
already filed. The measured whole-fork footprint before and after is
`[up-fp] files=211 deleted_lines=1076 heavy=5`. The file's added-line count increases
by one; no ratchet changes are needed.

Launcher consumer and scope: `EterniaLauncher/docs/mission_control/evidence/subagent-foundation-2026-10-14.md`.
The already-claimed Launcher C019 row owns the existing native client capability-v3
opening mismatch. This step supplies subagent adapters for an owned route and does
not silently change that separate parent-conversation prerequisite. Full native UI
qualification requires that work; Step 2 can design against the bounded contract.

Steps 2–7 remain separately approval-gated. No UI widget, menu, visual placement,
control operation, historical storage, profile default, spawn pause or release
artifact is changed in this foundation.

## Isolated compute host: approved connection

Optional `dashboard.turn_isolation` runs the agent and child registry in a separate
compute process. Reads use the existing supervisor's non-starting observer. The
gateway extension registers the same reader in every execution host. The outer
worker verifies its attached conversation and incorporates that owner generation
into the forwarded scope; the compute host dispatches under its own real transport,
checks the attached session and signs the exact child reference. The outer owner
is revalidated before returning the result. No transport authority is fabricated
from the supplied session id.

Missing compute or session authority refuses as unavailable/owner-changed; it
never constructs a supervisor, starts a host or returns a misleading empty local
registry. The temporary unsupported-host outcome was removed from both runtime
and Launcher contracts. A replaced session/transport invalidates references;
process restart also changes the process-private signing key. Only capabilities,
list and tail are admitted. No upstream PR is claimed.

The owner authorized completion of this Step 1 connection with clean architectural
decisions and an audit. Steps 2–7 retain their separate approvals. Final landing
qualification is recorded below; release and UI acceptance are not claimed here.

Positive controls: removing existing-only borrowing attached a replacement and
failed at its unexpected native call. Removing the forwarded outer generation
let an old child reference survive parent reattachment; the refusal assertion
failed. Removing the compute transport binding or observation allowlist each
prevented actual child reads and failed two boundary tests. All mutations were
restored; the final 33-test run passed. Release and live Console acceptance
remain later work.
