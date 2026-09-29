# Chat-first group messages

Owner-approved 2026-09-29. Implementation checkpoint, not release acceptance.

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

## Remaining integration

Launcher needs a chat-first participant entry, not a workspace/persona wizard.
Its discovered profile binding must reach the same Discussion authority without
manufacturing persona instances or borrowing an existing operator conversation.
Reuse the existing native conversation execution / recovery authority where profile
sessions are needed. Keep account, installation and profile evidence explicit.

The current branch implements message intent, not the complete profile-group entry.
Before landing: qualify upstream driver regressions, shared-client reconstruction,
native approvals and Stop, then the full user journey and Mission Control isolation.
