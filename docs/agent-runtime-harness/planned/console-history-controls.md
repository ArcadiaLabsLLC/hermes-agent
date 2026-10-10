# Console history controls — audit and implementation contract

Status: implemented and verified on feature branches; native Launcher visual
qualification is held on a stale connected QA MCP server. Not landed. 2026-10-09.
Scope: operator Console branching, conversation rewind, and filesystem checkpoint
inspection/restoration. Failure navigation and retry lineage are separate work.

## Findings that change the implementation

1. `hermes_state_rewind.SessionRewindMixin.rewind_user_turn` is the existing
   carrier-aware rewind owner. It addresses the repaired active transcript and
   delegates to an atomic, guarded SessionDB writer. Console display indices are
   not native row identities. Resolve a saved user row, pin the active transcript
   and canonical target content, and refuse unavailable/ambiguous targets.
2. `gateway/platforms/api_server._handle_fork_session` copies the complete chat,
   ends the parent, and creates/copies in separate transactions. It is unsuitable
   for Branch from here. A prefix branch needs an additive SessionDB transaction;
   do not route the Console through that API or manufacture another session store.
3. Native history and `mission_chat_turns` activity are different retained evidence.
   Rewind archives native rows but does not retire journal-derived terminal markers.
   Branching native rows alone loses the tool/thought activity. Both projections
   need explicit native-history membership, while the original evidence remains.
4. `tools/checkpoint_manager.CheckpointManager` owns filesystem snapshots, scoped
   to a project directory. `session_diff` compares the earliest retained PROJECT
   checkpoint, not necessarily this chat or operator turn. `new_turn` is called for
   each agent iteration. No existing durable turn-to-snapshot relation was found.
5. `agent_runtime/checkpoint.py` is a read-model transport checkpoint. Budget
   checkpoint rows are final-reply markers. Neither is a file restore point.
6. Existing safe restore falls back to full restore when the write ledger is empty;
   its single-file arm does not apply the safe filter. A missing ledger must be an
   explicit conflict in the Console, never permission to overwrite.
7. Checkpoint hashes are currently validated against the shared Git store, not
   membership of the addressed project. Console requests must resolve their
   workspace from the exact conversation and validate project membership under
   the existing store lock. Do not accept arbitrary directory parameters.
8. Restore takes a pre-rollback snapshot but ignores failure before writing. The
   Console restore path must require a verified recovery snapshot before mutation,
   then check the preview's per-file content and report partial failures honestly.
9. `profile_runner.execute.AgentRunExecution.construct_agent` does not pass the
   native checkpoint configuration; `AIAgent` defaults it off. Exposure of a
   checkpoint list alone does not enable capture. Config admission and unsupported
   backends must be explicit, profile-scoped, and verified with a real run fixture.
10. The root lease protects active execution but accepted/queued RPC requests are
    reserved separately. History mutation needs shared admission ordering with new
    turns, plus native DB write guards; a check-then-write busy test alone is not
    sufficient. Files can also change outside Hermes; preview checks cannot promise
    an atomic transaction with arbitrary editors.

## Authority and boundaries

* Exact target: install, optional account scope, workspace, persona, instance,
  root session, active native tip. Use `exact_operator_target`, recorded
  `chat_session_scope`, and `require_session_owner` before reads or mutations.
* New RPC handlers belong beside `serve_rpc.operator_inspection`, using the same
  console admission tier and deferred-reply mechanism. No CLI fallback.
* One history service owns preview/apply and typed refusals. Native SessionDB
  owns the atomic transcript mutations. Existing checkpoint manager owns file
  snapshot/restore mechanics. These are separate operations and receipts.
* An opaque operation ID provides replay after lost acknowledgements. Store the
  receipt with the native mutation, not after it. A changed target, payload, owner,
  transcript or workspace invalidates the preview. No automatic destructive retry.
* Busy includes active/settling turns, accepted sends, clarification, native leases
  and compression. Original chats are never ended by a branch or rebound as a
  side effect. Warm actors must reload the new durable revision before continuation.

## Product behavior

Use the existing operator prompt ellipsis (`agent_console_turn_context_content_renderer`)
and the existing local chat sheet. Do not extend human DM actions or create a
parallel chat/history catalog. Preserve the agent avatar, connected activity steps,
copy controls, existing context-at-send action, and the current transcript layout.

**Branch from here:** show the selected prompt and number of earlier turns copied.
Create a new chat containing the prefix before that prompt; return the selected
prompt as an editable draft. Original chat remains intact. State that both chats
share the same workspace and that files are not copied or restored. Open the child
through the host's existing chat selection writer using its verified identity.

**Rewind to here:** show the exact selected prompt, affected turn count and retained
prefix. Explicit final action: Rewind conversation. Archive selected and later
native rows, retain evidence, return the prompt as a draft, and invalidate cached
history. Files stay as they are. Preserve an existing unsent draft through the
existing draft owner instead of silently overwriting it.

**File checkpoints:** a separate Changes sheet, labelled Workspace checkpoints
until a genuine turn association exists. List retained snapshots and provenance;
preview additions/modifications/deletions and diffs. Show unavailable binary/large
file previews, ignored/oversized files, unsupported backend, no ledger, externally
edited paths, expired checkpoints, and failed writes/deletes honestly. Only
explicitly selected eligible paths may be restored. Never imply changes belong to
the selected turn without durable evidence.

Attachments or compressed targets that cannot be replayed losslessly are refused
with an explanation; they must not be silently flattened or sent automatically.
Changing chat/runtime while a request is pending discards that UI response. The
server still returns a durable operation receipt for recovery.

## Verification and landing order

1. Native atomic prefix branching and rewind receipts, exact row targeting,
   immutable inherited activity, and admission ordering. Test original unchanged,
   source prefix byte identity, foreign ownership/profile refusal, compression and
   attachment behavior, stale previews, busy/queued sends, and duplicate requests.
2. Guarded checkpoint preview/apply through the existing manager. Use temporary
   workspaces only. Test project isolation, traversal/symlinks, missing ledger,
   external edits/deletions, oversized files, recovery snapshot failure, expired
   hashes, partial I/O failure, and replay without a second restore.
3. Typed adapter and neutral Console port/controller; existing prompt menu and
   sheet, host selection and draft restoration. Test A→B→A scope changes, duplicate
   clicks, failed reads, lost acknowledgement, keyboard operation and narrow UI.
4. Feature-complete checkpoint; focused authority tests with a named killing
   mutation and recorded red; required repository gates and native Stage C proof.
   Only then mark queues complete, land, and sync both primary checkouts last.

## Implementation and evidence

`operator_history.py` owns exact-target history preview/apply/status and shared
send admission; `hermes_state_history_controls.py` is the native transaction door.
`operator_checkpoints.py` resolves the profile/workspace and calls the existing
CheckpointManager's reviewed API. `serve_rpc/operator_history.py` publishes both
without blocking the serve reader. `persona_chat_history/history_evidence.py`
projects retained activity against native membership; it queries archive identity
columns rather than materializing old message bodies on every history read.

The Launcher uses its existing prompt menu, chat sheet, draft registry and host
selection. A local write-ahead receipt pointer survives closing/restarting the UI;
only the runtime receipt confirms an outcome. Conversation-menu recovery stays
reachable after rewinding the first prompt. History invalidation retires pending
cache reads, and rewind waits on the existing host's fresh snapshot owner.

Focused positive checks include 84 history/curation/attachment/checkpoint tests
and the real checkpoint RPC round trip and native profile configuration test.
The final runtime authority run passes 30 tests, including partial/interrupted
restore, immutable receipts, revision races and warm-actor rehydration; Ruff and
the architecture probe are green. The Launcher final run passes 452 boundary,
projection and widget checks and 11 full Console picture tests. Its host proof
caught and fixed a dropped durable channel session id in compact snapshots.
Three additional host tests pin draft preservation and late-completion isolation.
Six Flutter-rendered baselines cover branch, rewind and restore at both supported
window sizes. A mock and test renders do not establish native capture parity.

The release QA build launched with its exact commit and isolated fixture pins,
but the connected MCP server offered retired PrintWindow capture and refused
with `helper_not_configured`; current source uses `captureFrame`. No alternate
desktop capture was used. A current MCP connection and native in-app review of
the final feature tip remain the integration landing hold. The Launcher queue
records that tool deployment gap. Temporary QA configuration and the owned QA
process were cleaned up without touching the operator session.

Verification on 2026-10-09: disabling the native writer digest rejects neither
a competing branch write nor a competing rewind write; both named regression
tests fail. Disabling the Launcher cache generation check makes its late-read
test return `removed` instead of `retained`. Both mutations were restored.
The focused UI suite passes 11 tests, including restart recovery and a narrow
sheet with enlarged text. A real rewind also invalidates the existing resident
actor's native revision, and its replacement reads only the retained prefix.

The whole-tree runtime gate selected 1,405 files, took 1,269.1 s at eight workers
(82.8% utilization, 1,097.9 rerun-worker seconds), and reported 18 red files.
The new seven-method manifest fixture was corrected; its three office test files
then passed (129 tests). Every remaining failing node was compared using the
per-file authority on unchanged runtime main `7df5194324`; the known gateway TLS,
Windows path, doctor repair and teardown failures remain separately queued.
The stream-gap timing failure and two multiplex isolation leaks are queued too.
This is not a claim that the repository's full gate is green.

Known boundaries: compressed ancestry cannot yet be copied into a lossless
prefix branch, so it is explicitly refused; ambiguous merged prompts,
attachments, redacted text and prompts over 64,000 characters are also refused
instead of being flattened. Checkpoints remain workspace-scoped, with no invented
turn association. External editors do not participate in the store lock.
An interrupted restore exposes its verified recovery checkpoint and paths to
review after the writer releases the lock; it never repeats unknown writes.

The upstream API widenings are held PR candidates: SessionDB mixin admission,
optional writer digest/receipt and its carrier-aware rewind forwarding, and the
additive CheckpointManager preview/apply/status API. The ledger owns their footprint.
