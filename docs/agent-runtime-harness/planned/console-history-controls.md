# Console history controls — audit and implementation contract

Status: approved repair implemented; qualification in progress. Not landed.
2026-10-10. The repair section supersedes the original product plan.
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
  snapshot/restore mechanics. Each native owner retains its own receipt; the Undo coordinator joins them.
* An opaque operation ID provides replay after lost acknowledgements. Store the
  receipt with the native mutation, not after it. A changed target, payload, owner,
  transcript or workspace invalidates the preview. No automatic destructive retry.
* Busy includes active/settling turns, accepted sends, clarification, native leases
  and compression. Original chats are never ended by a branch or rebound as a
  side effect. Warm actors must reload the new durable revision before continuation.

## Approved repair, 2026-10-10

Status: isolated repair branch, not landed. The earlier prompt-menu UI and its
qualification claims are superseded by this section. The original audit is
retained in console-history-controls-review-2026-10-10.md.

Edit operates on a saved prompt and resends through the existing Launcher outbox.
Branch here operates AFTER a completed reply, including that reply in the child.
The original chat stays intact and both chats share the existing workspace.
Changed files and Undo require durable turn attribution; they are not inferred
from tool labels. Undo reviews chat/files/both before applying. Advanced File
history remains available for independently reviewed checkpoints.

### Authority map

- `operator_history.py` resolves exact native rows, reviews revisions and invokes
  the native SessionDB history owner. `hermes_state_history_controls.py` owns
  atomic branch transactions and history receipts. Canonical rewind uses the
  existing rewind writer with an in-transaction revision check and receipt.
- `chat_turn_reservations.py` separates brief, bounded send admission from the
  long history writer fence. Status/stop can still observe a pending operation.
  Accepted receipts record PID and process start time. Startup retires only
  proven dead/reused owners; unknown legacy ownership remains conservative.
- `CheckpointManager` owns snapshots, file evidence, verified recovery backups,
  per-file receipts, resumable restore and retention pins. New public observer
  APIs expose a stable tree, proven file diff and namespaced metadata location.
  Fork code does not import its private store/index/ledger helpers.
- `turn_checkpoints.py` owns attribution only: exact root session and operator
  request, first baseline across agent iterations, proven paths and bounded
  recorded diffs. `profile_runner/execute.py` binds the observer on each run,
  including reused resident agents. No second Git store or file writer exists.
- `operator_turn_changes.py` joins canonical turns to attribution. Undo includes
  the selected and later turns, refuses multiple workspaces or expired snapshots,
  and excludes another chat's or a person's later writes. The UI only receives
  attributed paths, never an unrelated whole-workspace diff.
- `operator_undo.py` coordinates existing owners with a durable SessionDB record.
  Files finish before canonical rewind. It does not claim filesystem/SQLite
  atomicity. A partial result retains the original request and backup. Status
  reconciles crashes between native receipts and coordinator writes.
- `history_recovery.py` stores a minimal admission fence, not outcomes or prompt
  content. `operator_history_recovery.py` discovers pending work or proves a
  pre-write crash empty. `history_cancellation.py` rejects a delayed command
  after verified unapplied cancellation. Partial writes can never be discarded.
- Recovery compares the reviewed revision. Finish and rollback preserve later
  external edits. Terminal receipts replay terminal results; stale UI cannot
  reverse an already finished command. Backup refs are released after settlement.
- `serve_rpc/operator_history.py` uses the existing console admission tier and
  deferred replies. No CLI fallback and no new conversation selection owner.

### Review findings closed by the repair

Native write guards now map to definite refusal when nothing was written.
Concurrent sends serialize briefly instead of reporting a false history conflict.
Proven orphaned accepted turns no longer permanently fence a chat after restart.
Pending operations survive closed drawers, reconnection and lost client records.
Launcher request persistence is encrypted and keyed by durable session identity.
The UI only acknowledges a rewind after canonical history has been refreshed.

### Evidence

Focused runtime qualification after the owner-API refactor: **45 tests passed**
across test_operator_turn_undo, test_operator_history_repair,
test_turn_checkpoint_provenance, test_operator_history_controls,
test_operator_checkpoints, and test_checkpoint_reviewed_restore_downstream.
They use actual isolated SQLite stores and temporary native Git workspaces.

The prior append-race rewind test could fail because of alternation repair and
was not a valid positive control for the revision pin. That claim is withdrawn.
The new in-place edit keeps IDs, role order and row count unchanged. Disabling
`check_history_digest` makes precisely that test fail. Disabling the recovery
revision comparison makes the stale-choice test fail. Both mutations restored.
Evidence logs: revision-pin-red.log, recovery-revision-red.log and
repair-final-focused.log in the task's local console-history-evidence/runtime.

New coverage includes new/deleted/net-unchanged files, first operator baseline
across iterations, unproven/oversized writes, another chat's subsequent write,
manual edits during partial recovery, backup survival through native pruning,
branch-after-reply lineage, cancellation versus delayed dispatch, file/chat/both
modes, replay and crash after files but before rewind.

The upstream footprint is remeasured against the repository's current v0.21.6
manifest: 188 upstream files, 951 deleted lines, 5 heavy files. The widening
stays in native owners and is recorded as held upstream PR candidates in the
footprint ledger, not claimed as an already opened upstream PR.

Final fork-scope landing run: **1,465 files; 18,574 passed, 110 failed, 233
skipped**. This was a red full gate, not a green qualification. Repeating its
27 failing files on untouched main `7094d8b3ba` reproduced **99 identical failed
node IDs**, plus the same `test_serve_exit_flush.py` process failure before a
complete test summary. Those failures remain tracked by the existing runtime
and fork-hygiene queues.

The 11 other failed nodes were resolved or explained individually:

- Four structural checks now pass after splitting the Undo coordinator helpers,
  reusing the native history-action enum, naming the SQLite writer specifically,
  and giving the pre-prompt boundary the precise `before_user_message` value.
  No gate exemption or baseline was expanded.
- Six manifest assertions correctly found nine recovery methods absent from the
  reviewed expected manifest. The producer regenerated exactly those nine
  console-tier entries; all six assertions pass on the final source.
- The test-tree layout check found an empty retired `tests/honcho_plugin`
  directory left in this long-lived worktree, with no tracked or untracked
  files. A fresh detached checkout of the final commit passes the same gate.

The final focused safety/architecture run passed **96 tests in 11 files**. A
fresh-checkout manifest/layout run passed **131 tests in 4 files**, with one
recorded retry: the office-subscribe suite's test fixture intermittently sees
`hermes_state` before `_STATE_DB_GUARD_EXTRA_DENY_ROOTS` exists. Its first attempt
was 81 passed / 1 setup error; its retry was 82 passed. This is filed for suite
repair and is not presented as a clean first-attempt pass.

Evidence under `console-history-evidence/runtime`: `repair-landing.log`,
`repair-landing.json`, `repair-baseline.log`, `baseline-comparison.json`,
`repair-final-gates.log`, and `repair-clean-final.log`. No repeated whole-fork
run was used to hide the original reds.

Native Launcher qualification remains outstanding.
The Launcher QA schema still exposes PrintWindow rather than required in-app
capture; its policy blocks native verification until the connected server is
refreshed. Do not mark this work landed or feature qualification complete.
