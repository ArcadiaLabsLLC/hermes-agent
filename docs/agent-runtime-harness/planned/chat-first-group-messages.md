# Chat-first group messages

Owner-approved 2026-09-29. Implemented; live-provider desktop acceptance remains separate.

`runtime.discussion.run.send` accepts optional typed `response`: `discuss`,
`compare` or `reply`, with an explicit member audience. Omission preserves the
existing Mission Control behavior. The canonical public user event owns the intent.

The existing hosted-room planner supplies an independent task batch for Compare.
Only distinct members of the same source event may overlap; normal discussion
remains sequential. No second scheduler, public transcript or credential catalog.
Checkpoint watermarks preserve peer replies deliberately withheld during Compare.

The native worker must distinguish a requested Stop from actual exit. A worker
returning after its exact interrupt is cancelled, unless committed or uncertain
native evidence takes precedence. Other rooms and conversations keep running.

## Evidence

The serial hermetic runner passed 225 tests across 12 files: message intent,
parallel admission, native runtime, wire, conclusion and upstream driver cases.
New positive controls exposed
the unsupported response field, serialized Compare dispatch and incorrect post-
Compare watermarks before their fixes. This does not prove real-provider acceptance.

## Profile groups

`run.start_group` opens an idle group from exact installation/profile/home bindings.
The authenticated caller and client account determine its conversation scope;
it is not an office workspace. Native ConversationService supplies each member's
independent session, model defaults, credentials, execution recovery and Stop.
No persona copies, new worker manager or implicit first message.

ProfileTurns projects the exact native execution receipt into the existing task
journal. Questions come from native pending requests. `run.respond` uses native
answer acknowledgements, never a second plaintext answer store. Completed public
outcomes are bounded native receipts; durable transcripts remain the history owner.
Schema v3 preserves existing Mission Control member identities, rows and claims.

The 26-file qualification passed 285 tests; only the old upstream footprint ceiling
failed. The required held seams are now dispositioned in the ledger. Real local
provider tests cover independent replies, continuation, reconstruction, compute-host
questions, lost/repeated answer acknowledgements and exact confirmed Stop. No live
credentials or user profiles were used. The completed fork-population run and
baseline comparison are recorded in the
[qualification](../../downstream/chat-first-group-qualification-2026-09-29.md).
All nine slice-owned failures were corrected; the correction run passed 177 tests.
The wider repository is not green: 79 failures and one collection error reproduced
on unchanged primary. This is not desktop acceptance.

The first landing run was stopped after 441 reported files. Only 422 carried
test outcomes: bundle 26 reported process success although its recorder ended
with `rc: 2` and no test events. Its 19 unproven files ran individually;
green bundle labels were not counted as evidence. The remaining population also
ran through the per-file authority. The parked wrapper self-publication
test is upstream-inherited and was already outside this fork population.

## Group model setup repair — 2026-09-30

Manual acceptance found a shared sign-in without an inference model selected for
one participant. This was not a private-credential requirement. The failed turn
was durable, but Launcher hid it after task pruning.

`run.member_models` and `run.member_model` resolve the exact profile-group member
and delegate to native ConversationService. Its catalog, selection, saved-default,
busy and identity checks remain authoritative. These console-tier methods may
open that member's native session, never submit a message. Office bindings stay
on their existing operator controls. No new catalog, credential store or scheduler.

Profile dispatch now refuses missing model selection before submission, through
the existing failed-turn receipt and error classification. Other members continue.
Launcher must preserve the draft, show model setup, and require an explicit Send.

The repair regression passed 143 tests across 17 files, serially: profile groups,
real native/compute workers, recovery, exact Stop, wire producers, office-table
behavior, shared credentials and drain admission. Removing the selection guard
made the independent-member test fail; restoring it passed. Changed Python files
pass Ruff F checks. Receipts: `qa-artifacts/group-provider-regression.log` and
`group-provider-control.log` (local). These are isolated tests, not live-account
desktop acceptance or a whole-repository green claim.

The structural/contract run passed 1,270 checks; three failures reproduce on
unchanged main `d244451a5d`: the duplicate-helper-name assertion (`_flag`, `_model`,
`_owner`) and both discussion ladder assertions. Existing fork-hygiene/runtime
queue rows retain them. Size, function legibility, layer direction, tombstones
and CLI/payload contracts pass. No thresholds or baselines changed. Receipts:
`qa-artifacts/group-provider-gates.log`; primary `group-provider-baseline.log`.

## Lifecycle follow-up

`DiscussionService.idle_drain` conservatively treats every open run as busy,
including an empty or settled profile group. This preserves the existing
between-round safety fence, but can defer automatic runtime maintenance until
groups are ended. A later lifecycle pass should distinguish settled groups from
pending work using the existing planner under the admission lock; never infer
idleness from an empty task list. Source-confirmed; no maintenance behavior was
changed in this slice.
