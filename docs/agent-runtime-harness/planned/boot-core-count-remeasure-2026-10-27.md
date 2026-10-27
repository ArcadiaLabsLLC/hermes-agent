# Planned — does a desktop boot still build a redundant core? (live count only)

**Status:** planned 2026-10-27 (planning lane w1027k-h-plan), replanning row
`RT-BOOT-RESUBSCRIBE-CORE-REMEASURE`. Supersedes
[`boot-resubscribe-fourth-core.md`](boot-resubscribe-fourth-core.md) (left in place).
Owner doc: [`../04-boot-and-lifecycle.md`](../04-boot-and-lifecycle.md).

## Problem

HY-L2 (2026-08-17) said a boot resubscribe makes the serve build a full core the boot
had already built. The row asks whether that is still true now that the core stream
has a position-gated resume, and which of three fixes is owed.

Read against the tree on 2026-10-27, both resubscribe paths that used to buy a core
now avoid it by design:

- **Stream lane.** The launcher's connector sends `resume: {event_offset}` on every
  re-subscribe that holds a watermark (launcher
  `lib/core/services/hermes/runtime/remote/lan_socket_connector.dart`, the subscribe
  write; a first subscribe omits it on purpose). Hermes resolves it in
  `agent_runtime/stream_resume.py::resolve_stream_resume`, and an honoured resume —
  including the empty span at equal offset — joins the hub with
  `restart_producer=False` (`hermes_cli/harness_parts/serve/handle_message.py`, the
  `hub.subscribe` call), so no core is built for anyone.
- **Office lane.** `runtime.office.subscribe` attaches restart-free when its baseline
  stands (`agent_runtime/serve_office_subscriptions.py`, the `restart_producer`
  decision; `agent_runtime/serve_stream_hub.py::StreamHub.subscribe` docstring names
  this caller), which is the path HY-L2 originally blamed.

What is left is a refused resume (`journal_truncated`, `span_not_foldable`,
`backlog_exceeds_cap`, …) or a subscriber that sends none; each takes the hydrate and
restarts the producer, which is the correct fallback, not a defect.

## Decisions

1. **Close the gap as met by `stream_resume` plus the restart-free office join**, of
   the row's three options. A hydrate skip at equal offset is what the honoured empty
   resume already is; a resume on the boot resubscribe is what the connector already
   sends. No code is planned.
2. **The proof is a live count, not a test.** The tree cannot show how many
   subscribers a real desktop boot opens or whether any of them is refused a resume;
   only the receipts can.
3. **If the count is above one, the fix is chosen by the refusal, not in advance.**
   Each refused resume names its reason on the ack (`resume.reason`), so the follow-up
   row names the reason it saw.

## Slices

**L1 — live count** (row `RT-BOOT-RESUBSCRIBE-CORE-REMEASURE`, READY, a live check)

On the Windows box, under the running launcher's own home (`HERMES_HOME=…\profiles\base`;
measuring another profile measures another runtime), three cold boots of the launcher.
After each, run `hermes harness observe snapshot-builds --since 3m --json`
(`hermes_cli/harness_parts/observe_commands.py`, derivations in
`agent_runtime/snapshot_build_census.py`). Read:

- the number of `snapshot_build_core role=led` builds in the boot window — met if it
  is **1** on all three boots (a core-cache hit with its shadow validation counts as
  the one);
- for any boot above 1, the subscribe acks in `agent.log` around the second build:
  the subscriber key and its `resume.reason`.

Met → delete the row and mark the old plan doc's status MET in the same commit.
Not met → file one row per refusal reason seen, naming it, and delete this one.

No files are touched by L1 itself.

## Test plan

No code, so no killing mutation. The guarantees the decision rests on are already
pinned: `tests/agent_runtime/test_stream_resume.py` (the honoured / refused spans) and
`tests/agent_runtime/test_serve_stream_resume_lane.py` (the serve's resume join) and
`tests/agent_runtime/test_serve_rpc_office_subscribe.py` (the restart-free office join). The live
count is the only open evidence.

## Open questions

None for the owner.
