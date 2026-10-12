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

**The test for "Value beyond Eternia" is demonstrated native benefit, not merely
product neutrality.** Every proposed contribution must satisfy all of these:

- Name a concrete problem or valuable use case for native Hermes users or
  maintainers, with evidence. "Our fork needs a hook" or "other clients could use
  it" alone does not qualify. Explain why the benefit warrants the added API and
  long-term maintenance cost.
- Before implementation or a submission pitch, search upstream issues,
  discussions, and open/recently merged PRs for the need and overlapping work.
  Record the date, links, status and any explicit maintainer request or response.
  Distinguish a user report from maintainer demand; neither an open issue nor an
  unreviewed PR establishes endorsement. A maintainer request is strong evidence,
  not a waiver of the remaining criteria. No matching issue is not a veto on a
  demonstrated native defect or valuable use case; record that evidence instead.
- Check current upstream code and active contributions; show why an existing
  primitive cannot already deliver that benefit. Reuse first, and avoid a
  competing owner or implementation.
- Offer the smallest independently useful native change. Keep Eternia policy,
  fork bookkeeping, speculative abstractions and unrelated cleanup out. Prefer
  clear types and a direct execution path over mode flags and nested dispatch;
  retain necessary safety checks.
- Supply compatibility and failure-path evidence for the actual changed
  contract, including native behavior and performance-sensitive batching where
  affected. Document the tested limits rather than claiming universal safety.
- Make the patch reviewable on a pinned upstream base with a professional problem,
  behavior and validation description. A reviewer must be able to assess its
  benefit without adopting the Launcher or the runtime fork.

Read the column below as **candidate value, not qualification**. Native receipts,
branching, the writer extraction, lock waiting and pins have not passed this
submission test in this audit. Before submission, each entry must name its
beneficiary/problem evidence, existing-API gap, minimal change and proof. If those
are missing, keep it HELD as a documented seam; do not manufacture a public API or
submit a cleanup-only PR merely to reduce our fork diff. Product independence is
necessary, but it is not the upstream value argument.

| Capability | Existing Hermes owner | PR #7 addition | Disposition for this repair | Value beyond Eternia |
| --- | --- | --- | --- | --- |
| Rewind/edit boundary | `SessionRewindMixin.rewind_user_turn` delegates to native `rewind_to_message`, including write guards, archival, counts and compaction handling | Optional full-history digest and immutable receipt in the same transaction | **Reuse + narrow extension.** Keep that writer and its default behavior. Do not implement rewind in the RPC lane or mutate messages in Launcher. Preserve native warm-history adoption. | Acknowledgement-loss recovery and stale-review protection for other clients; generic seam candidate. |
| Branch at a selected reply | SessionDB session/message owners and `_clone_message_rows`; CLI/API whole-session fork already exists | `SessionHistoryControlsMixin.branch_before_message` clones the reviewed prefix and receipt atomically while keeping the source open | **Necessary new behavior.** The existing API/CLI fork ends the source and copies all messages, so it is not a drop-in substitute. Keep cloning/guards in SessionDB; verify lineage, complete tool pairs and source preservation. Do not add a second fork service/store or change CLI semantics. | Product-neutral selected-boundary branch API; generic seam candidate. |
| Checkpoint inventory and diffs | `CheckpointManager.list_checkpoints`, `list_all_checkpoints`, `diff`, `session_diff`, and its native Git store | Operator RPC adapters and public facts for reviewed restore/attribution | **Reuse.** Adapter authorization and DTOs only; no second snapshot repository, Git index owner, or diff engine. | Existing native capability, now available through another client boundary. |
| Reviewed selected-file restore and recovery | `CheckpointManager.restore`, ownership ledger, store lock and pruning owners | Review revision, selected paths, verified backup, per-file receipt and finish/rollback | **Extend + consolidate H5 through the native writer.** Existing restore and new apply/recovery must share native write mechanics. Checkout/deletion currently live inline in `_restore`; expose a narrow native helper where needed, preserving batching/pathspec, safeguards and return behavior. Merging only the two new paths beside the existing writer is insufficient. Keep their review/receipt coordination separate. | Reviewed restore and interrupted-operation recovery are useful native API candidates when they reuse the native writer. |
| Typed checkpoint contention and bounded lock wait | `checkpoint_pruning.store_lock` and `PruneError` | `CheckpointStoreBusy(PruneError)` and optional `wait_seconds`, defaulting to zero | **Name and retain as a small native extension.** Preserve the existing lock owner, default fail-fast behavior and exception compatibility. Prove finite waiting, release after error, and a typed no-write refusal; repair the Undo caller's H1 misclassification. | One of the clearest small generic upstream candidates: callers can distinguish contention from a write failure without parsing text. |
| Restore target/backup retention pins | Native checkpoint Git store, refs and pruning/GC owner | `pin_restore_checkpoints` / `release_restore_checkpoints` retain both trees under operation refs | **Keep and qualify as part of H5's reviewed/resumable restore.** Create verified pins before writes, keep them throughout partial/restart recovery, and release them after a terminal outcome. Prove pruning/GC survival and cleanup after pin/receipt creation failures; no separate backup repository. | **Dependent, otherwise HELD.** Current native synchronous restore holds the store lock through checkout and defers its own pruning. Pins have demonstrated purpose across released locks/restarts in reviewed/resumable restore; submit with that qualified native capability, not as a standalone cleanup feature. |
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

### Native primitive clarification

Typed lock contention/wait and restore retention pins are explicitly named above
so they are not lost inside the larger feature rows. They are existing PR code,
not newly implemented changes or accepted upstream contributions. Upstreamability
is conditional on focused compatibility/lifecycle proof, not on the size of the
patch or its placement in an upstream-owned file.

H5 means sharing the underlying native file writer with existing restore, not
merely combining `restore_preview` and `resume_restore`. The inspected main has
checkout/deletion inline in `_restore` (including batched checkout and pathspec
handling), rather than an independently callable per-file write primitive.
Extract/expose only the required native mechanism, preserve existing behavior,
and record that seam accurately in the upstream-footprint ledger. Do not call
the whole restore operation once per selected file: that would repeat its
backup/pruning/selection orchestration. Keep user-edit policy and operation
receipts with their respective owners, and prove both native and reviewed paths
exercise the shared mechanism. Avoid a broad checkpoint refactor.

### Upstream seam sequence and quality requirements

The native writer extraction edits the upstream-owned `_restore` function. It is
a seam, not fork-only cleanup. The inspected upstream tracking snapshot
`ac0cfa7db9` also has its restore writes inline; re-fetch and pin the actual
upstream SHA before preparing any implementation/submission, and check for an
equivalent accepted or active upstream change first.

1. **Native extraction commit:** isolate the smallest behavior-preserving shared
   write mechanism in the native checkpoint owner, with native tests. Existing
   restore must use it in that commit. Preserve batching, pathspec/literal path
   handling, deletion/oversize/user-edit safety, store/index/lock ownership,
   backup/pruning order, error reporting and return shape. Do not mix the PR's
   deletion/deduplication repairs, coordinator, RPC or UI changes into extraction.
   The helper's scope/signature must follow those invariants, not a predetermined
   one-file-per-Git-command design that would lose batching.
2. **Native proof:** run the existing restore tests on the pinned base and on
   extraction. Cover `test_checkpoint_manager.py` restore/safe-restore cases,
   `test_checkpoint_path_roundtrip.py`, `test_checkpoint_gitlinks.py`,
   `test_checkpoint_size_cap.py` and `test_checkpoint_store_ownership.py` as
   applicable through the canonical test runner. Add only missing meaningful
   characterization of affected behavior (including batching where needed).
   Record exact commands, commits and outcomes. Passing selected tests supports
   compatibility; it is not a claim to have proved every possible behavior.
3. **Fork bookkeeping:** record the held seam and proof in the footprint ledger
   separately. Fork-only ledger/docs/manifest bookkeeping does not belong in the
   upstream patch. If it passes the "Value beyond Eternia" test above, the
   extraction is the native code-and-tests commit an upstream PR should carry,
   without a later product-removal rewrite. Its preparation is not automatic
   approval to submit a low-value extraction.
4. **Consumer commit:** only after extraction is qualified, change reviewed apply
   and recovery to consume that native primitive and delete their duplicated
   write mechanics. Keep review, receipts, recovery sequencing and persona policy
   with their existing owners. Preserve the approved feature behavior.
5. **Seam closure:** upstream acceptance alone is insufficient; integrate the
   accepted change into the fork and remove its carried delta/retire that ledger
   seam. If upstream requests revisions, adapt the consumer to the accepted API.
   Other history/restore seams remain independently tracked until resolved.

Any upstream proposal must have a concrete native use and value independent of
Eternia: fewer divergent restore implementations, preserved native safety and a
usable extension for other checkpoint consumers. A public helper existing only
to make one fork patch convenient is not enough. Use the smallest coherent typed
contract; avoid product flags, generic workflow/strategy engines, speculative
extension points, broad boolean mode matrices or repeated nested dispatch.
Necessary safety checks remain explicit. Tests should be comprehensive for the
changed contract, not an assertion count or a large rewrite of unrelated tests.

Typed busy/wait remains an independently evaluated candidate for contention among
native checkpoint clients. Retention pins do not have a demonstrated standalone
use in the current synchronous restore: that operation holds the store lock and
defers its own pruning until checkout completes. Their demonstrated use belongs
to reviewed/resumable restore across lock releases and process restarts. Keep
them in that coherent submission if it qualifies for native use, or keep them
HELD; a separate reviewable commit inside that submission is still appropriate.
Do not remove pins needed by the staged recoverable workflow. Neither pins nor
busy/wait belongs in the behavior-preserving writer extraction. An upstream PR
description must identify the native problem, demand/overlap evidence, smallest
change, before/after behavior, validation and limits.
This section is the agreed preparation plan; no native code was extracted,
upstream branch pushed or upstream PR opened by this documentation change.

### Retention and upstream-demand check — 2026-10-11

Fresh upstream source inspected at
`97a9ae8ee55d31bebce49f1fb6b5ef775323976a`:
[`CheckpointManager.restore` / `_restore`](https://github.com/NousResearch/hermes-agent/blob/97a9ae8ee55d31bebce49f1fb6b5ef775323976a/tools/checkpoint_manager.py)
holds `store_lock` around the full restore, takes the safety snapshot with
`prune=False`, and prunes after checkout.
[`checkpoint_maintenance`](https://github.com/NousResearch/hermes-agent/blob/97a9ae8ee55d31bebce49f1fb6b5ef775323976a/tools/checkpoint_maintenance.py)
uses the same store lock for pruning and clearing. This supports the synchronous
lifetime conclusion above; it does not protect durable recovery after that lock
has been released or its process has died.

Initial demand/overlap search: open upstream issues for `checkpoint restore` and
`checkpoint lock`, open PRs for `checkpoint restore`, and discussions for
`checkpoint`. This is a scoped check, not an exhaustive survey or submission
qualification; repeat it, including recently merged work, before implementation.

| Evidence inspected | Status at check | Implication for this plan |
| --- | --- | --- |
| [#99869: partial file mutations on termination](https://github.com/NousResearch/hermes-agent/issues/99869) | Open user report; no comments | Related native recovery demand, not a request for this exact pin API or established maintainer endorsement. |
| [#123284: refresh write ledger after restore](https://github.com/NousResearch/hermes-agent/pull/123284) | Open PR; no reviews | Overlaps the native restore/ledger owner. Inspect its resolution and reuse or coordinate the accepted behavior before preparing the extraction. |
| [#95610: defer safe-restore deletions until checkout succeeds](https://github.com/NousResearch/hermes-agent/pull/95610) | Open PR; no reviews | Native safety work in the write path. Recheck its status; do not silently mix this behavior change into the behavior-preserving extraction. |
| Discussion search for `checkpoint` | No matching results | Limited search evidence only; not proof that upstream has no related discussion or demand. |

No maintainer request for the extraction, busy/wait or retention-pin API was
established by this check. No upstream contact or submission was made.


### Runtime implementation evidence — 2026-10-11

Operator clarification supersedes the earlier read-compatibility proposal:
`profile_<name>` is the sole persona-ID contract. `4bd7d84234` removes dedicated
colon alias handling and updates producers/selectors together. Stored profile
personas keep their explicit binding; unrelated permission/skill namespaces are
unchanged. Identity/assignment/curation suites: 227 passed; projection/receipt
checks: 45 passed. Launcher integration still needs qualification.

H1/H2/H4 repairs are `875e77a0f3` and `e687e9070d`: pre-write contention settles,
Undo transitions have one typed owner, first-turn baselines and safe restoration
of agent-deleted files are preserved. Native extraction `71ba58a781` is separate
from reviewed consumer `e38ec5d239`; lifecycle/Undo/recovery checks: 32 passed.
Pins remain part of resumable restoration, not a standalone upstream proposal.

H3 killing controls rerun against `e38ec5d239`: disabling the in-transaction
`check_history_digest` in `hermes_state_messages` makes the in-place rewind race
test fail at its expected `history_changed` error (an apply result was returned).
Disabling Undo's recovery-revision check makes the stale recovery test fail at
its expected `recovery_changed` error (recovery proceeded). Both mutations were
restored immediately; the two complete suites passed afterward (14 tests).
This is committed evidence of those named controls, not a claim that every
concurrency schedule or native UI path has been proved.

### Integrated runtime qualification — 2026-10-11

Runtime candidate `c92efed446` contains main `3aa2cc0236`. This evidence
supersedes earlier candidate totals; it does not certify a green whole-fork gate.

- Profile-derived persona emitters, selectors, fixtures and generated command
  reference now use only `profile_<name>`. No colon compatibility helper or
  profile alias mapping remains. Explicit stored profile bindings keep priority.
  Permission subjects, skill labels and other independent colon namespaces are
  outside this persona contract and remain unchanged.
- The first integrated fork gate (`scripts/run_tests_bundled.sh tests`) ran 1,534
  files: **18,398 passed, 87 failed, one error, 233 skipped**. Owned profile
  fixtures/reference/citation failures were repaired in `1e7a2031dc`; the routing
  gate found two untyped rollback comparisons and they were repaired in
  `c92efed446`. Follow-up: 154 tests passed before the citation-only repair;
  the complete citation suite then passed 41 tests. Routing plus Undo passed
  17 tests after restoring the killing mutation. The full gate was not rerun.
- On unchanged main `3aa2cc0236`, a seven-file baseline check reproduced the TLS
  pin, source-grep, path-identity and mid-test monkeypatch-undo gate failures:
  107 passed, four failed, one skipped, plus the PM fixture setup error. That
  fixture requires Python 3.14; this environment supplies 3.13.15. Existing
  queue evidence records local certificate interception; TLS checks were not
  weakened. This seven-file comparison is not a reproduction of all 87 reds.
- Session API's commentary failure from the bundled gate did not reproduce in
  isolation: 39 passed on the candidate and on main. Its bundled/order-dependent
  failure remains unqualified. The tree-layout failure is an empty untracked
  retired directory in this long-lived checkout, with no production diff;
  cleanup was not performed after automatic approval review rejected it.
- The original bundled gate also contains gateway/peer/media/lane TLS families,
  TUI/exit timeouts and a strict XPASS. Their existing queue evidence is relevant,
  but this repair does not claim each was rerun on the latest main.

The native extraction remains a separate behavior-preserving commit, followed
by its reviewed-restore consumer. Busy/wait is an independent held candidate;
retention pins belong to resumable restore. No upstream submission was made.
Launcher native in-app proof remains a landing requirement for the paired PRs.
Both PRs stay draft; runtime changes are committed and pushed to PR #7, not main.

### Final follow-up and full-gate comparison — 2026-10-11

Main was integrated through `8a5d6114df` in `f525b6d002`. Runtime candidate
`c0b289a072` adds the final scoped follow-ups:

- `5a54ddd63c` names `safe_assignment_token` as the shared punctuation fold and
  tests that boundary. It adds no profile-colon alias helper, migration or raw
  reader compatibility. `profile_<name>` remains the only emitted contract.
- `a90ac74fa1` binds checkpoint tool waits to the existing turn wall budget
  through an optional remaining-time callback. A resident turn rebinds that
  callback; no second clock or budget authority is introduced. Each tool wait
  is capped by both 30 seconds and remaining turn time. Unbudgeted native
  callers retain zero wait. The red test observed `[30, 30, 30, 30]` instead of
  `[30, 0.25, 0, 2]`, plus native waits `[30, 30]` instead of `[0, 0]`; both reds
  and the 76-test focused green are recorded in the commit body.
- The full gate found one owned footprint regression: the Callable import
  replaced a native import line, raising deleted lines from 970 to 971.
  `c0b289a072` uses an additive `collections.abc` import instead. The ledger
  follows the measured 421-added / 33-deleted manager diff. No ratchet allowance
  changed. Complete footprint, wait-budget and native checkpoint suites:
  **67 passed**.

The complete fork gate on `a90ac74fa1` ran 1,535 files with no cached-green skips:
**19,077 passed / 75 failed / one error / 233 skipped**, plus an exit-flush test
process that terminates without a test total. Nineteen files were red. This
supersedes the earlier full-run counts, but is not a green gate claim.

Every red file was then run on untouched main `8a5d6114df` through the same
bundled wrapper and Python 3.13.15 environment: **154 passed / 72 failed / one
error / one skipped**, with the same exit-flush process death. The differences
are explicit:

| Candidate red | Unchanged-main result | Disposition |
| --- | --- | --- |
| TLS/gateway/media/peer families; source-grep and path gates; shared-monkeypatch gate; bot relay strict XPASS | Same failures | Existing failure classes, outside this feature; certificate pinning and gate allowances remain intact. |
| PM slow-exit setup | Same Python 3.14 requirement versus configured 3.13 interpreter error | Environment qualification still owed, not a worker behavior pass. |
| Exit-flush process death | Same death, no completed total | Existing Windows test-process qualification row. |
| Upstream footprint | Nine passed | Owned regression fixed above; complete follow-up passed. |
| Retired test-directory layout | Two passed | Candidate checkout contains the previously recorded empty untracked directory; no tracked source delta. Earlier cleanup was refused by automatic approval review and was not bypassed. |
| Session API commentary in bundle | All 39 passed alone | Candidate also passes all 39 alone. The bundled/order-dependent failure remains unqualified; isolation success does not erase it. |

The four residual classes without specific rows were filed in the fork-hygiene
queue on main in `367555d5c1`. Existing TLS, source/path and exit-flush rows keep
their ownership; no duplicate feature backlog or unrelated production repair
was added. Logs: `history-final-runtime-gate.log`,
`history-runtime-current-main-baseline.log`, `history-final-runtime-focused.log`,
`history-runtime-footprint-final.log`, and
`history-runtime-final-session-isolation.log`. Focused counts overlap.

The native extraction and reviewed consumer remain separate. Busy/wait is a
held independent upstream candidate; retention pins remain part of resumable
restoration. No upstream submission was made. The paired feature PRs remain
draft and unmerged until the native Launcher proof and unresolved qualification
requirements are met; the connected MCP still advertises the retired capture
schema rather than the required in-app capture and managed build-status door.

Final main integration `4a780e08c2` includes the queue-only main update
`367555d5c1`. The runtime source is unchanged from `c0b289a072`; the gate evidence
above is not presented as a rerun after documentation-only integration.

### Current-main preparation and bounded failure comparison — 2026-10-12

Runtime merge `d0e0f40a9b` integrates main `50a9165fc2`. The runtime source is
unchanged from `c0b289a072`. Profile identity, checkpoint turn wait, combined
Undo and Session API checks report **54 passed**, including the runner's
isolated retry. That total alone is misleading: the first Session API attempt
reported **38 passed / one failed** at
`test_interim_commentary_reaches_session_sse_and_responses_stream`, and the
runner explicitly recorded an isolation leak. The failed bundle contained only
this file; it did not follow another member in the same process. Log:
`history-native-runtime-integration.log`.

An untouched-main control at `50a9165fc2` initially passed all 39 Session API
tests and 21 existing turn-budget tests in separate bundles. A bounded follow-up
then reproduced the exact commentary failure on its first attempt: **38 passed /
one failed**, followed by **39 passed** on the automatic isolated retry. The
follow-up stopped at that reproduction. Both used the canonical bundled wrapper
and Python 3.13.15, with no cached-green skip. There is no feature delta in
`tests/gateway/test_session_api.py`, `gateway/platforms/api_server.py` or the
root test fixtures. Logs: `history-session-bundle-main-control.log` and
`history-session-main-repeat-1.log`.

This closes the earlier gap in baseline equivalence for this failure. It does
not diagnose the intermittent event loss or turn either red run green. The
existing fork-hygiene row now records that distinction in main `52f2b7d56a`;
feature merge `62f6f28d90` includes the queue update. No production behavior,
test assertion, retry rule or gate allowance changed for this comparison.

The operator authorized the QA MCP rebuild from Launcher main and conditional
landing in runtime-then-Launcher order. The canonical rebuild succeeded from
Launcher `718df80817`, and its server suites passed 51 tests. The installed
executable is current, but this chat still advertises the retired PrintWindow
capture schema with no managed build-status tool. The operator is away and
requested the remaining independent checks. Native proof is still pending a
fresh host connection; neither feature PR has been merged. Launcher evidence:
`EterniaLauncher/docs/mission_control/evidence/console-history-controls-qualification.md`.

### Native sibling-branch defect — 2026-10-12

The fresh Launcher QA lane admitted the rebuilt server and reproduced a real
runtime defect: the first branch succeeded; a second branch from the same
source returned an unknown outcome. The native unique session-title index
rejected the repeated `source · branch` title. Nested branching succeeded
because it requested a different title. No extra child or receipt was committed.

`SessionHistoryControlsMixin.branch_before_message` now uses the existing
`hermes_state_titles.next_title_in_lineage` on its writer connection. Title
allocation, prefix cloning and the receipt remain one transaction; no upstream
file or index changed and no second naming algorithm was added.

The real serve/SQLite regression
`test_repeated_sibling_branches_allocate_native_titles_and_replay` failed for
both boundaries before this change (`turn_outcome_unknown` on the second
sibling), then passed. It verifies three siblings, unique native titles,
replay/status identity, exact copied prefixes and unchanged source rows and
session metadata. Replacing allocation with the supplied title is the killing
mutation. Per-file authority: **34 passed** across history controls, repair and
canonical-title guards. Local logs: `history-native-sibling-branch-red.log`,
`history-native-sibling-branch-green.log`, `history-native-sibling-authority.log`.

The stale capture-session restriction above is historical. Fresh native proof
is running; combined Undo already passed with actual row and file checks.
The corrected runtime still needs native repeated-sibling proof. Neither
feature PR has landed.
