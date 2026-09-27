# Native recovery repairs

Status: implementation in progress; not qualified or landed on main.

The owner approved the full [repair plan](native-hermes-lifecycle-audit-2026-09-26.md),
including compute-host answer acknowledgements. Stateful native RPC remains the
foundation. No Companion, real-profile or provider-credential changes.

## Native ownership

- Pending questions and bounded answer receipts belong to `server_requests`.
  The compute bridge returns the child's verdict, not a successful pipe write.
  Receipts contain an ephemeral keyed fingerprint, never the answer or a reusable
  secret hash. Retries address the exact session and question.
- Replay caches do not own sequence lifetime. Native session retirement releases
  sequence metadata; ring eviction preserves live numbering and its gap watermark.
- Route/admission records remain necessary for scope, fingerprint and one-unsettled
  admission. They must not become another transcript or pending-question store.

## Positive controls

- `test_native_answer_ack.py`: before repair, expired child answers and all three
  missing-ack cases incorrectly returned `ok` (4 failed, 1 passed). Seven focused
  cases now pass, including cross-session refusal and duplicate-answer receipts.
- `test_native_replay_recovery.py`: before repair, cache eviction changed the live
  session's latest sequence from 3 to 0; the repaired case passes.

These are unit controls, not end-to-end qualification. The audit's complete
reconstruction, cancellation, retirement, concurrent-surface and native UI matrix
remains required before closing its queue rows.

## 2026-09-27 branch checkpoint

Native execution identity reaches admission, events and interruption. An
acknowledged Stop remains a request, not a terminal verdict. Its durable intent
survives a missing reply; observation retries only that execution. Relayed child
events retain their original identity. Observation-only resume cannot schedule
auto-continue.

The outer event ring and question registry are removed. Reads translate native
epoch/sequence pages without retaining history. A read captures its dispatch
receipt before requesting events: the real-worker A/B/A test exposed the inverse
order returning completion ahead of its terminal event.

Measured focused checks:

- Answer owner: 7 cases; real child-process acknowledgement: 1, including a
  deliberately dropped reply, same-answer retry and cross-session refusal.
- Execution fences: 5; replay eviction sequence continuity: 1.
- Native recovery snapshot/prefix/history: 4; existing compute turn protocol: 10.
- Conversation service: 9; stateless event projection: 3; real native A/B/A: 1.
- Focused Ruff check passed. Generated gateway contracts refreshed.

Not complete: client/Compare restoration, native retirement, compressed-history
recovery, broader regression qualification and native UI acceptance. No main
landing or claim closure is justified by these focused results.

## Startup cancellation and native retirement boundary

Two added execution tests failed before the repair: cancellation during agent
startup left a running receipt, and a competing native admission replaced the
current execution. The fenced cases now pass (7 execution tests total).

`session.retire` reuses native reaper eligibility and teardown. It requires exact
settled execution evidence, refuses queued/pending/building/delegated work, checks
again after child retirement, and removes only disposable replay metadata. A
stale session reference cannot admit work after the native owner removes it.
Eleven focused cases pass; the stale-execution test also caught and corrected an
initial guard that accepted an older completed execution while a newer one existed.

The service's bounded open/facts reads pass its 9 focused cases. Generated
contracts and focused Ruff checks pass. **The retirement operation is not yet
wired to observation/retention policy.** Aggregate retention, real child retirement,
client reconstruction, compressed history and full acceptance remain unqualified.

## Durable history and uncertain child dispatch

Recovery now reads the existing native display projection through a durable
watermark, including compressed ancestors and visibility rules. Bounded JSON
chunks preserve Unicode, reasoning and tool fields without a second history
store. The compressed-lineage test failed before this correction; all 5 native
snapshot tests pass. Projection is currently rebuilt per page; large-history
cost still needs qualification before this repair can be called complete.

An uncertain native compute write no longer falls back inline. Its original
supervisor waiter and child observation route survive until a native outcome.
Atomic SessionDB metadata updates preserve Stop intent and terminal evidence
across parent/child writes. The scoped receipt lookup now has an execution index.

Positive controls: removing the retained waiter produced 2 failures (1 legacy
case still passed); removing monotonic receipt merging failed the parent/child
Stop test. Restored code passes 3 dispatch and 9 execution cases. Existing
compression watermark tests pass 16 cases; compute phase-one tests pass 8.
Gateway contracts were regenerated. These checks do not qualify client recovery,
retention, cold restart or the complete UI path; the repair remains in progress.

## Native inflight continuation checkpoint

The existing inflight record now retains segment boundaries and reasoning text
for identified native executions. Prefix reads carry a revision: an authoritative
interim rewrite invalidates an older read, while appended streaming remains
readable at its captured bound. User-row metadata preserves execution identity
through compression copies; no text matching is used.

Eight snapshot tests pass, including branch isolation. Disabling segment tracking
and the durable execution link produced two targeted failures; restoring them
passed. Generated contract checks pass (2 tests), as does focused Ruff analysis.
Launcher has a typed, awaited restoration path, qualified with a controlled RPC
peer. Real-service/compute restart, aggregate retention, large-history cost and
native desktop acceptance still prevent declaring the full repair complete.

## Retention and real-process checkpoint

Route bindings now retire through `session.retire`, with a 64-binding pressure
target and 15-minute idle threshold. Borrowed, recently observed and unsettled
bindings stay protected; native eligibility remains the final decision. The
profile worker closes only after its last retired binding releases it. No
transcript, draft or dispatch receipt is deleted. Lost retirement replies are
reconciled before reuse. Fixed-size lock stripes replace growing lock maps.

Real inline and compute A/B/A tests verify isolation, process retirement and
durable reopening without submission. A one-second pause after opening exposed
prewarming bypassing configured compute isolation; removing its guard reproduces
the failure. Existing `turn.started` acknowledgements now order child observations;
the child's canonical `session_key` also restores completed skill-history reads.

The real question/stream test reopens both inline and compute sessions, drops an
answer acknowledgement, retries the exact question, and confirms repeated Stop
without resending. Launcher additionally passes two cross-repository tests using
real handlers/workers: fresh file-backed Chat engines and independent Compare
members with an unavailable route. The model and storage cipher are test doubles;
these are not native UI or encryption acceptance.

Positive controls: removing the borrowed-session guard fails retention; removing
pre-dispatch rejection settlement changes the expected error to unknown. Seven
input-thread responsiveness cases failed before repair and pass afterward:
native recovery/retirement/answer waits, including raw compute answer frames, use
the existing RPC pool and retirement reservation. Stop remains on the input path.

Final checkpoint verification: 703 passed across 13 file-isolated service/gateway
files, with one existing expected failure in the gateway suite. The two Launcher
real-process cases also pass after dropped submission/Stop replies were added.
Focused Ruff and changed Dart analysis pass. This is not a full-suite verdict.

Large-history cost, full service-restart qualification, concurrent Mission Control
and Discuss acceptance, broader baseline comparison and native desktop acceptance
remain open. This checkpoint does not close the repair claims.

## Oversized native output

A 10 MiB answer reproduced `conversation_worker_lost`: the bounded reader
treated one oversized event as a dead connection. It now drains that frame in
bounded chunks. Native replay's existing gap watermark directs readers to the
checkpoint and durable history; no buffer increase or second history store.

Inline and compute-child tests both recover after eviction and after rebuilding
the service/worker, with unchanged execution identity and exactly two model calls
(question, answer). Restoring the old disconnect makes the inline test fail.
The final file-isolated run passes 13 tests across large recovery, live recovery,
snapshot and replay. Reading 10 MiB takes 41 pages, measured at 2.32/2.34 seconds
after reopening. This bounds wire delivery, not native history materialization:
the current projection is still rebuilt per page, so larger-history scaling is
not yet qualified. The non-repeating fixture avoids Hermes's repetition guard;
that guard correctly rejected the first repeated-text fixture.

## Missed terminal delivery and structural gates

An unobserved route with a missed terminal push previously retained its stale
running receipt forever. Retirement now reads native execution evidence before
deciding; unknown/running outcomes remain protected, and native retirement still
rechecks eligibility. The new regression failed before the change and passes now.

The inflight event vocabulary uses a handler table; the history chunk helper has
a distinct name. Routing and duplicate-helper gates pass without new allowances.
The final six-file run passes 31 tests, including inline/compute large recovery,
live question/Stop, retention, snapshot and both structural gates. One earlier
loaded 10 MiB run exceeded the small-case 30-second wait; its isolated run took
20.73 seconds overall. The large case now allows 90 seconds within its existing
180-second test deadline; the final loaded run passes without retry. Focused Ruff
and diff checks pass. Native UI and the remaining acceptance matrix are still open.

## Current-main reconciliation

The repair now includes main `74490fa89a`, including the September 27 upstream
merge. The shared submit-row writer retains upstream queue persistence; only
the admitted prompt receives its native execution metadata. Execution-fenced
Stop stays session-local; legacy Stop retains upstream's voice-wake repair.
Generated gateway contracts were regenerated, not hand-merged.

The six-file merge check passes 36 tests. Two additional cases verify queued-row
identity isolation and the absence of process-wide voice effects from fenced
Stop; both pass with the native snapshot/fence files (21 tests). The broader
gateway run and final qualification are still pending. This is a branch
checkpoint, not permission to land the incomplete repair.

## Disposable history delivery

Native display projection now runs once per captured history position, not once
per page. A seekable, delete-on-close payload retains no transcript in RAM between
reads. At most 16 deliveries remain; completion, native teardown, pressure or
60 seconds idle close them. The existing native reaper handles idle cleanup.
Eviction rebuilds from SessionDB; no new durable history or lifecycle owner.
Initial projection still materializes native history once; this does not claim
bounded peak memory for arbitrarily large histories.

Eight file-isolated checks pass 53 tests, including 10 MiB inline/compute restart,
Unicode, retries, native rewrite/retirement races and existing structure gates.
Sixty-four abandoned reads retain two entries and less than 1 MiB traced memory
under the test budget. Ruff passes. Mutation controls fail when projection reloads
per page (12 calls instead of 1), pruning is removed (64 entries instead of 2),
or teardown retains files. The merge controls also fail for process-wide speech
interruption and queued prompts inheriting the active execution.

The reconciled gateway run passes 667 tests with four SSH workspace-resolution
failures. The identical four fail on unchanged main `b25aca3cafd4`; they are not
classified from the focused green results. Full qualification remains open.

## Automatic maintenance protects shared work

Concurrent desktop acceptance reproduced a separate shutdown defect: Mission
Control's network setup drained the shared service during a streaming Chat turn.
The response survived, but new connections failed; Launcher then mistook an
unconfirmed drain for exit and spawned a competing stdio runtime.

`drain_if_idle` reuses serve's drain and admission locks. Native conversation
receipts protect running/uncertain turns; the discussion owner protects open
rooms between rounds. Standing subscriptions do not count as work. The busy
projection includes these owners, without introducing another work registry.
Gateway clients cannot request this local lifecycle operation. Explicit drain
retains its existing contract. Launcher must still prove exit before replacement.

The nine-file focused run passes 197 tests. Removing idle admission in memory
fails five new cases (running, unknown, Mission Control, Discussion, unreadable
ownership). Size and duplicate-helper checks pass. The initial handler edit
exceeded the function floor; shortened rationale and flatter guards restore all
four legibility checks without an allowance. Desktop requalification is pending.

The full fork gate at `ff53b0716c66` ran 797 files: 11,648 passed, 84 failed,
nine errors and 169 skipped. Rechecking its failing files on unchanged main
`b25aca3cafd4` reproduced 78 failures and the existing collection/teardown errors.
Six branch-specific manifest assertions across the three office-RPC files were
stale after adding history/inflight recovery; the producer regenerated their one
shared fixture and all three now pass. The profile-override collection error is
fixed by a newer main test helper, not by recovery code; reconciliation remains
owed. The full gate is not green.
