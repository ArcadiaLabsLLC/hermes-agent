# Agent Console subagent controls — Step 4

The owner approved Steer and Stop and their required fork seams on October 15,
2026. The existing native helpers remain the only execution implementation.
The harness checks conversation ownership; the Console holds drafts and command
receipts. Results/history, defaults, spawning pause and release are later steps.

## Wire values and connections

The existing authenticated console method families are
`runtime.conversation.subagents.*` and
`runtime.operator.conversation.subagents.*`. Each now exposes `steer`, `stop`
and the read-only `receipt`, alongside Step 1's capabilities/list/tail.
The method manifest in `agent_runtime/subagents/params.py` publishes parameters.
Peer grants and the existing conversation route owners are unchanged.

| Value | Source and meaning |
| --- | --- |
| Native identity | `install_id`, `session_id`, `client_scope`, `profile`; validated by `conversations/service.py`, captured by the existing Launcher binding |
| Operator identity | `install_id`, `workspace_id`, `persona_id`, `persona_instance_id`, `session_id`, `client_scope`; existing `operator_session_read` and profile authority |
| `expected_generation` | Required for every command/receipt; `subagents/references.py` binds the exact owner generation |
| `child_ref` | Required opaque exact-child reference from list; signs owner, native child object and start generation; a recyclable child ID alone grants nothing |
| `request_id` | Required nonempty ID, at most 128 characters; Launcher generates one per deliberate action; the receipt binds its operation, child and correction |
| `text` | Steer only; nonblank, at most 8192 UTF-8 bytes; delivered by native `steer_subagent` / `AIAgent.steer` |
| `controllable` | List fact from current exact owner checks; operator controls additionally require an actual current live parent ancestor |
| `version`, `generation`, `observed_at` | Existing observation envelope, plus echoed conversation identity |
| `operation`, `subagent_id`, `request_id`, `child_ref` | Receipt attribution; operation/child ID may be null when no receipt exists |
| `status` | `queued`, `interrupt_requested`, `not_accepting`, `refused`, or `unknown`; queued does not assert delivery, and stop requested does not assert completion |
| `missed_steer` | Nullable native **child-level** completion fact, read by `subagents/completion.py` through `tools.async_delegation.get_durable_delegation`; never claimed as per-request delivery evidence |

Native requests borrow the existing worker and call `eternia.subagents.*` through
`conversations/subagents.py`. The one registration in
`conversations/worker_subagents.py` serves subprocess, in-process and compute-host
execution. Operator requests enter `serve_rpc/operator_subagents.py` and
`subagents/operator.py`. Both end in `subagents/native.py::inspect_records`,
`subagents/commands.py`, and the upstream public Steer/interrupt helpers.

## Per-seam footprint ledger

| Seam | Connection and disposition | Retirement condition and proof |
| --- | --- | --- |
| Service borrow mode | Existing `ConversationService.subagents` → `_session(existing_only=True)` → `Bindings.borrow`; fork-owned forwarding extension, no new attachment policy | Keep the route owner until an equivalent public owned-conversation service exists. Missing/dead/retiring workers refuse without starting another worker |
| Worker-entry registration | Existing `gateway_extensions.py` → `worker_subagents.register`; shared declarations regenerate `tui_gateway/contract_catalog_data.py`; fork-owned | Retire through an equivalent native extension registrar, not per-host registration. Real native/compute/in-process round trips exercise the same entry |
| Operator RPC family | Existing dispatcher → `serve_rpc/operator_subagents.py` → `operator_session_read`; console tier, unchanged peer allowlist; fork-owned | Retain harness target validation while the harness owns these identities. Wrong install/workspace/persona/instance/session/client and non-console callers refuse; live-parent positive control succeeds |
| Native method manifest | Existing `conversations/rpc.py` operation dispatch and `subagents/params.py`; fork-owned | Existing authenticated dispatcher remains authoritative. Discovery describes only implemented verbs and honored parameters |
| Atomic native record predicate | `tools/delegate_tool_registry.py::steer_subagent/interrupt_subagent` accept an optional predicate under the existing registry lock; **new upstream file +6/-2**, held hook candidate | Retire when native public helpers accept equivalent exact-record authority. Two signature replacements avoid copying either native execution helper. Recycled-ID race tests fail when the predicate is removed |
| Compute control sender | `HostSupervisor.control(existing_only=True)` and two classified concurrent routes; upstream file **+72/-9 → +76/-10**, held hook candidate | Retire with native non-creating public control dispatch. Guarding the existing start call avoids a duplicate sender. Missing compute owner cannot start a replacement |
| Compute control receiver | Existing `_control_ack` calls fork-owned `subagents.compute.control_ack` under the host's actual transport; receipt alone joins the observer allowlist; upstream file **+52/-5 → +56/-5**, held hook candidate | Retire with a public classified control extension. Mutation never enters the observer. Lost acknowledgement reconciles through a receipt read without replay |
| Existing private owner bridge | `agent_runtime/_upstream_doors.py` supplies the same seven recorded private imports and supervisor attribute; no allowance increase | The canonical ledger still records each dependency. Exact registry/transport/profile/lineage checks must survive replacement by public native APIs |
| Receipt cache | `subagents/commands.py::CommandReceipts`; fork-owned process-local deduplication, bounded at 1024; weak child references, no execution registry or scheduler | Remove only for equivalent native request receipts. Live-child entries are never evicted; capacity refuses new commands. After a child finishes, entries older than ten minutes may expire; stale references cannot execute |
| Missed-steer fact | Captured native transcript delegation/task locator plus durable owner IDs → existing native delegation completion; fork-owned read adapter | Replace with a public exact-child completion locator. Real final-boundary race returns native missed steering in all three execution modes; no caller path or inferred task order |

Measured on the claimed base before edits: `files=221 deleted_lines=1047 heavy=4`.
After this slice: `files=222 deleted_lines=1050 heavy=4`. The three newly deleted
lines are the two helper signatures and the supervisor's unconditional start
call. The owner-approved increase is recorded in the ratchet fixture and every
changed upstream-manifest file has a canonical row. These are held hook
candidates; no upstream PR or upstream adoption is claimed.

## Ownership and uncertain outcomes

The native helper rechecks the signed exact record at acceptance under its own
lock. Stop uses its native recursive interruption, preserving the parent and
sibling branches. Operator controls require current live ancestry in addition
to the actual SessionDB, compression lineage and captured profile home.

A receipt is reserved before dispatch; duplicate request IDs cannot reexecute.
Reusing an ID with different content refuses. Missing/late/malformed replies or
ownership loss after native acceptance are unknown outcomes, never proof that
nothing happened. The Console never retries a mutation automatically. Check
status uses only `receipt`; a failed read cannot erase a known acknowledgement.

The Console keeps the same branching inspector, inline correction editor and
inline child/descendant stop confirmation. It clears borrowed references and
receipts on ownership refusal. Its app binding continues to fence account,
route, installation, client, worker PID and execution generation.

## Qualification

The initial focused run passed all six real native round trips (Steer/Stop in
worker, isolated compute and in-process modes), existing native steering/control
regressions and read ownership tests. Its four failures exposed a test double
missing `quiet_mode`; the corrected fixture and final ownership audit passed
11 tests across the three command/operator files. Final gate and mutation
results are recorded below before landing.

Killing mutations were applied individually and restored before qualification:

- Remove the native `authorize_record` checks: both recycled-child tests fail
  (`assert 'error' in reply`, two failures; neither replacement is allowed by
  the restored implementation).
- Make the existing-only sender call `start()` unconditionally: the missing
  compute-owner test fails with `inspection started or replaced compute`.
- Remove request-ID receipt reuse: duplicate steering fails with
  `check ownership\n\ncheck ownership` instead of one `check ownership`.

These are observed red runs, not proposed mutations.

The fork landing run selected 1092 files: 13049 tests passed, 8 failed, one
environment setup error and 56 skipped in 549.1 seconds. Its feature findings
were repaired without exceptions: regenerate the one RPC manifest fixture,
give the native dispatch helper a specific name, and replace growing operation
conditionals with a dispatch table and shared required-parameter declarations.
The final focused run of all subagent files, the three manifest consumers and
both architecture checks passes **173 tests across 12 files**, including the
six real native execution round trips.

The remaining full-run error is `test_worker_slow_exit_downstream`: its PM
fixture requires Python 3.14, while this workstation's explicit test interpreter
is Python 3.13.15. The same file reproduces the same setup error on detached base
`0e7531cebe`; no worker assertion executes. The pre-existing shared-environment
qualification row in the fork-hygiene queue owns it. No fixture or runtime
requirement was relaxed, and no clean whole-suite result is claimed.

Launcher surface and validation:
`EterniaLauncher/docs/mission_control/evidence/subagent-controls-2026-10-15.md`.
