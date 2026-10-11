# Console history follow-up verification — 2026-10-11

Read-only product audit of PR #7 at `8cbb135f15b0812c75d772838c31b873974c90dd`,
paired with Launcher PR #55 at `0e9fcd0b448d26ce1f31f67bb4df85749e4933fa`.
No runtime repair was applied. Counterexamples below use disposable files/stores;
they are diagnostic probes, not a full fork-suite or native UI qualification.

## H1 — checkpoint contention leaves an unnecessary Undo fence

`agent_runtime/operator_undo.py::apply_operator_undo` saves `prepared` and fences
sends before calling `CheckpointManager.restore_preview`. Its broad exception
handler converts `CheckpointStoreBusy` into durable `partial` with
`file_result_unconfirmed`. `tools/checkpoint_pruning.py::store_lock` defaults to
zero wait. The standalone restore path in `operator_checkpoints.py` specifically
clears a newly-created fence on this pre-write refusal.

Reproduced using the real Undo RPC, SQLite and Git snapshot fixture in a temporary
home/workspace. A wrapper acquired the real checkpoint store lock immediately
before the original restore-preview call, reproducing another writer winning
after the operation's preview and before restore acquisition. Output:

```text
state=partial reason=file_result_unconfirmed
file_unchanged=true chat_rows=4 pending.action=undo
explicit rollback recovery: state=rolled_back
```

This is an avoidable blocked-chat state, not necessarily permanent. If the store
is already busy during the earlier preview, admission can refuse before creating
this record. Fix the post-preview acquisition window without clearing a fence
that belongs to an earlier partial write. Add a contention-positive control.

The first direct probe omitted the test environment's lazy-install guard and
entered optional dependency setup; it was interrupted after certificate failures.
The successful probe used `HERMES_DISABLE_LAZY_INSTALLS=1`, matching tests/conftest.
That interrupted attempt supplies no correctness evidence.

## H2 — upstream checkpoint behavior changed

Compared with the PR's main merge base, `ensure_checkpoint` moves
`_checkpointed_dirs.add` after `_take` and only records successful takes. Native
Git probe: after a prior checkpoint, `new_turn`, unchanged ensure, write, ensure:

```text
unchanged_attempt=false cached_after_unchanged=false
snapshot_after_first_write=true
```

This changes per-turn deduplication/baseline timing. It still permits at most one
successful snapshot; describing it simply as "more than one snapshot" would be
wrong. Native `_take` still notifies the observer of the existing baseline on an
unchanged tree, so this probe alone does not prove the new turn-attribution
recorder loses its first baseline. Preserve or explicitly justify native semantics
and test existing checkpoint consumers as well as the new observer.

`record_agent_write` now records a missing file as `{sha256: None, deleted: true}`.
Native `_safe_restore_plan` treats a None hash as unowned and skips it. Reproduced
with a checkpoint, an authored write, deletion and a second write-ledger call:

```text
before_deletion_ledger: restore=[file.txt], skipped=[]
after_deletion_ledger: restore=[], skipped=[file.txt]
```

Thus recording deletion overwrites evidence the existing safe restore previously
accepted. This is a real compatibility defect, even though the new reviewed
restore path understands deletion separately. The current upstream-footprint
ledger calls this a held native API expansion; it does not literally say
"additive" on its checkpoint-manager row. The behavioral delta still needs a
specific disposition and proof, not an API-only description.

## H3 — mutation evidence is not recorded as required

CLAUDE's weakness rule requires a named killing mutation and its red in the
commit body. `b920ba2b1b65f8f09ad8a9c846ffc01d34d8abeb`, titled "Record race
killing controls and unchanged-main gate comparisons", has an empty body.
The committed qualification document describes the mutations and names local
`revision-pin-red.log` / `recovery-revision-red.log`; it does not contain the raw
failure excerpt. The tests and claims exist; that is not evidence that the reds
were fabricated, but it does not satisfy the prescribed recorded-proof format.
Record reproducible failure excerpts tied to exact mutations in a new commit;
do not rewrite shared history to repair the old message.

## H4 — Undo state transitions have multiple string writers

`agent_runtime/operator_undo.py` writes `prepared`, `partial`, `completed` and
`rolled_back` directly from apply, finish, reconcile and recovery. There are ten
state-writing statements counting initial construction and conditional writes,
not exactly eight. The structural concern is valid: use a typed state plus one
transition/validation owner, keeping the durable coordinator and native file/chat
owners rather than introducing a second state machine.

## Cross-repository identity blocker

`profile_persona_discovery.reconcile_profile_personas` mints `profile_<name>`;
`instance_catalog._project` retains it. The history producer `_history_row`
canonicalizes to `profile:<name>`. Branch apply/status/replay and origin reuse it.
Real producer output for `profile_audit` was `profile:audit`; Launcher's real
codec rejected the result. The Launcher owns the queued consumer repair.
Cancellation cannot discard an applied branch: `cancel_unapplied_history`
returns false when the native history receipt exists. Preserve that safeguard.

The producer module registers 16 history-related methods, matching the adapter's
16 call names. That inventory is narrower than a proof of all wire semantics.
Do not call the contract clean while its persona identity representation differs.

Repair H1 and H2 before landing. Then consolidate H4 and record H3's missing
proof with actual race tests. Preserve the existing native stores and lock owners.

## Architecture and upstream-value follow-up

The subsequent main fetch was `a29548b814`; PR #7 still at `8cbb135f15` lacks
269 main-side commits. Eight paths changed on both sides, including chat_turn,
history curation, profile execution/runner and RPC registration. Main adds native
retry lineage and queue-origin handling; integration must retain them. Fetching
main is not the same as integrating it into the feature. Launcher has its own
larger main delta and must be qualified with this combined runtime.

### Reused versus new behavior

- Rewind calls the existing `SessionDB.rewind_user_turn` authority, with optional
  revision and receipt parameters; no second transcript database was introduced.
- Snapshots, diffs and file restoration remain in the native CheckpointManager
  store. The added turn recorder holds attribution, not a second file snapshot.
- Existing API/CLI fork copies the full history and ends/switches away from the
  source. `SessionHistoryControlsMixin.branch_before_message` selects a precise
  prefix, leaves the source open, checks revision/leases and commits the child plus
  receipt atomically through SessionDB, reusing native `_clone_message_rows`.
  Therefore directly calling the existing API fork is not equivalent behavior.
- Combined chat/files Undo needs coordination: filesystem and SQLite do not form
  one atomic transaction. Durable progress, backup retention and explicit recovery
  have a real purpose. A separate generic workflow engine does not.

### H5 — duplicated restore-write mechanics

Although there is one checkpoint store, `CheckpointManager.restore_preview` and
`resume_restore` separately perform checkout/deletion, ledger update and per-file
receipt writes. Their verification behavior differs: recovery checks the target
blob after a write; initial apply does not use the same step. This is a concrete
maintenance/drift risk, not proof of an additional reproduced corruption.

Consolidate the new paths' common checked file-write and receipt primitive inside
the existing native owner. Keep the reviewed-operation coordinator separate from
the actual file writer. Preserve existing safe-restore semantics and the legacy
CLI behavior; do not turn this into a broad fork refactor or build another manager.
H4 still owns the separate coordinator state-transition cleanup.

### Potential upstream contribution, not submitted work

Generic candidates useful beyond Eternia: revision-pinned transactional prefix
branching, optional atomic operation receipts for rewind, reviewed selected-file
restore with crash recovery and backup retention, and a narrow checkpoint observer
for turn attribution. They should be independently tested and product-neutral
before proposing them upstream. Retain upstream's existing behavior by default.

Persona/install authorization, Mission Control RPC bindings, operator-specific
turn mapping and Launcher presentation stay fork/app responsibilities. These are
consumers of native APIs, not good reasons to put Eternia policy in upstream.
The held ledger entries are candidates; this review does not claim an upstream
PR was opened or accepted. Repair correctness and split a minimal coherent native
API contribution before considering submission. No upstream publication was done.

## H2 clarification: deletion ownership has multiple readers

The native safe-restore regression is real, but replacing the deletion's null
`sha256` with its previous hash is not sufficient as a one-line repair of the
whole feature. `record_agent_write` passes that same ledger entry to the turn
observer. `recorded_file_diff` compares the evidence hash with the current file
hash before and after diff generation. A deleted file has a null current hash;
preserving a non-null old hash there causes deletion attribution to be rejected.
`operator_turn_changes` also compares current and attributed hashes.

Preserve native ownership semantics while representing the current deletion
consistently for attribution. Keep current state/hash and prior ownership evidence
distinct where required, through the existing checkpoint owner; do not create a
second ledger. Update all affected readers together. H2 acceptance must cover
native safe restore of an agent-deleted file, deletion display/diff attribution,
combined Undo, and preservation of a file recreated or edited by the user.
An absent file with no prior ownership needs an explicit tested classification.

Runtime recovery also explains why Launcher needs more than draft text locally:
`operator_history_pending` discovers active fences, while terminal Undo clears
its fence and Branch/Rewind use their atomic receipts without that index. The
client's durable operation ID is needed after a lost terminal reply. This is
request intent, not another authoritative operation outcome store.

## Scoped ownership audit and repair disposition

Audit pins: runtime PR #7 `8cbb135f15b0812c75d772838c31b873974c90dd`,
runtime main `0205a4b83605ef729753971b040d3831d56f5227`; Launcher PR #55
`0e9fcd0b448d26ce1f31f67bb4df85749e4933fa`, Launcher main
`52a0e9df28ea65101799741a33717315d2114cc0`. Both PRs are still draft/open;
GitHub reports both as conflicting with main at this check.
This is source/diff and ownership verification against the fetched main and the
unchanged PR heads. The real reproductions above remain evidence for these heads;
no new runtime suite, integrated candidate, or native UI proof was run here.

Main has 272 runtime-side commits absent from the PR; eight paths changed on both
sides. Preserve main's chat-turn retry lineage, profile runner changes, curated
history and RPC registration when integrating. Existing feature tests qualify
their recorded tree only. The PR adds/changes 36 paths; the audit traced native
history/file mutation, attribution, admission, recovery and RPC ownership rather
than treating the file count as evidence of overengineering.

### Hermes reuse, extension and value table

"Extend" below means repair the already-staged extension, not commission another
implementation. Potential upstream value is an engineering assessment against
the inspected fork, not a claim of acceptance or an exhaustive survey of upstream.

| Capability | Existing Hermes owner | PR #7 addition | Disposition for this repair | Value beyond Eternia |
| --- | --- | --- | --- | --- |
| Rewind/edit boundary | `SessionRewindMixin.rewind_user_turn` delegates to native `rewind_to_message`, including write guards, archival, counts and compaction handling | Optional full-history digest and immutable receipt in the same transaction | **Reuse + narrow extension.** Keep that writer and its default behavior. Do not implement rewind in the RPC lane or mutate messages in Launcher. Preserve native warm-history adoption. | Acknowledgement-loss recovery and stale-review protection for other clients; generic seam candidate. |
| Branch at a selected reply | SessionDB session/message owners and `_clone_message_rows`; CLI/API whole-session fork already exists | `SessionHistoryControlsMixin.branch_before_message` clones the reviewed prefix and receipt atomically while keeping the source open | **Necessary new behavior.** The existing API/CLI fork ends the source and copies all messages, so it is not a drop-in substitute. Keep cloning/guards in SessionDB; verify lineage, complete tool pairs and source preservation. Do not add a second fork service/store or change CLI semantics. | Product-neutral selected-boundary branch API; generic seam candidate. |
| Checkpoint inventory and diffs | `CheckpointManager.list_checkpoints`, `list_all_checkpoints`, `diff`, `session_diff`, and its native Git store | Operator RPC adapters and public facts for reviewed restore/attribution | **Reuse.** Adapter authorization and DTOs only; no second snapshot repository, Git index owner, or diff engine. | Existing native capability, now available through another client boundary. |
| Reviewed selected-file restore and recovery | `CheckpointManager.restore`, ownership ledger, store lock and pruning owners | Review revision, selected paths, verified backup, per-file receipt, finish/rollback and retention pins | **Extend + consolidate H5.** Share the new apply/recovery checked file-write primitive within CheckpointManager. Separate coordination from writes; do not replace the native CLI restore policy with an Eternia-only coordinator. | Reviewed restore and interrupted-operation recovery are useful native API candidates. |
| Deleted files and first checkpoint timing | Native write ledger, `_safe_restore_plan`, `ensure_checkpoint` | Deletion evidence and observer notifications; PR also alters deduplication timing | **Repair compatibility H2.** Preserve legacy safe restore and per-turn baseline semantics. Current file state and ownership evidence must agree across native restore, attribution, preview and Undo. Neither remove deletion display nor retain the unsafe one-line hash-only repair. | Compatibility correction; protect existing users before proposing an extension. |
| Changes card / files belonging to a turn | Native checkpoints and proven write facts already exist; no equivalent operator-turn file attribution index was found on inspected main | `TurnCheckpointRecorder` stores turn/workspace attribution and bounded diff evidence under native metadata; `operator_turn_changes` projects it | **Narrow extension.** Observe the existing checkpoint owner. Keep first operator-turn baseline, reusable-agent rebinding, and inherited branch evidence. Never infer ownership from timestamps or snapshot every file again. | A small optional native checkpoint observer can serve other clients. Operator-turn policy and persona mapping remain fork-owned. |
| Combined chat/files Undo | Existing native chat and file writers; their stores do not share an atomic transaction | `operator_undo` durable coordinator, plan, file outcome and reviewed recovery | **Justified fork coordination; simplify H1/H4.** One typed state transition owner; distinguish no-write contention from partial writes. Keep server prepared plans authoritative. Do not introduce a generic workflow engine or a client mirror of that plan. | Recoverable combined Undo is useful to other clients of this harness; the persona-bound coordinator is not a drop-in upstream contribution. |
| Lost reply, restart and delayed request | Native mutation receipts, checkpoint receipts, existing scoped store/lock primitives | Operation status, pending fence index and durable cancel tombstone | **Keep distinct roles.** Pending is a send-admission index, not another outcome store. Recover recorded operations by ID. For an unrecorded request, durably cancel its old ID before a fresh preview. No new RPC is required for the agreed minimal-client design. | Existing staged safety contract; generic receipts can be proposed separately from runtime authorization. |
| Send/steer concurrency and crashed workers | Chat-root lease, turn journal, admission reservations and process identity already exist | Brief history admission coordination, long history mutation exclusion and orphan reconciliation | **Reuse + narrow integration.** Preserve existing send queue/deduplication and main retry lineage. Prove that contention and dead receipts do not block unrelated chats or masquerade as partial file writes. Avoid another send queue, lease owner or turn journal. | Harness correctness; do not bundle unrelated native send redesign into this PR. |
| Authorization, identity and RPC exposure | Operator session inspection, `conversation_owner`, profile resolution, existing RPC registry/deferred execution | Sixteen history/checkpoint/Undo/changes methods | **Adapter work.** Preserve account/install/persona-instance/session checks. Use existing canonical persona semantics for nested history entries; do not weaken ownership checks or spread ad-hoc alias maps through widgets. | Eternia/harness binding. Native primitives should remain independent of this policy. |

The current implementation contains one transcript database and one checkpoint
store. It also contains avoidable duplication in the new file-write mechanics
(H5) and too many direct coordinator state writers (H4). Multiple records alone
are not proof of parallel authority: accepted-send journal, native chat receipt,
file progress receipt, coordinator plan and admission index each record a
different fact. Keep those distinctions explicit and remove copied decisions.

### Repair acceptance, within the existing PRs

1. Integrate current main into the existing PR lineage, preserving all overlapping
   owners; record candidate hashes before qualification. Runtime H1/H2 and the
   Launcher persona receipt blocker are release blockers.
2. Preserve native semantics while fixing H1/H2 and consolidating H4/H5. Test
   ordinary CLI safe restore as well as reviewed restore: deletion, user recreate,
   external edits, unchanged first checkpoint, selection and expired snapshots.
3. Exercise prepared-before-write, crash between individual file writes, crash
   after files/before chat receipt, lost terminal reply and stale recovery choice.
   A partial result must remain inspectable; finish/rollback must not repeat an
   already-proven write. No-write refusal must not leave an unnecessary send block.
4. Test real profile-derived identities across apply/status/origin, sibling
   instances and switched account/install scopes. Join producer and consumer
   fixtures; method-name inventory alone is insufficient.
5. Test accepted-send versus history admission, simultaneous sends/steers, dead
   worker reconciliation and two windows. Preserve the existing outbox/journal
   idempotency and prove an unrelated chat remains usable.
6. Record actual killing-mutation reds in a new commit body (H3). Maintain the
   upstream-footprint ledger honestly, including behavioral compatibility deltas.
   A held upstream candidate is not an upstream submission.

Scope ends at repair and qualification of Branch/Edit/Undo/File history/Changes
and their necessary recovery seams. Retain explicit refusals for unsupported
compressed branches, unsafe attachment draft restoration, unavailable backends
and multiple-workspace Undo. Generalizing those features, shipping new history
products, or routing CLI through fork-specific policy requires separate work.
