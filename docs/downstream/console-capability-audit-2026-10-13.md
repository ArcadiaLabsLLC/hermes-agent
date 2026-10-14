# Agent Console capability audit — 2026-10-13

Source audit, not a new native UI qualification. Compared Hermes release v0.21.7
(`71d34bad1045610252eda02ee79549436896e784`), upstream main
`e06df9c2eae6901f4c88f464e0ae6e753c0428b8`, fork `5d62b7f08e`, and
Launcher `5fae0ed39c` (code unchanged through the queue correction `bc3f8b18dd`). Recommendations below are proposals, not implementation
claims. The two merge closeout repairs are separate from these feature candidates.

The release preserves the existing operator/history RPCs. Twenty shared stream
fixture/manifest files match byte-for-byte between the two repositories; their
README differs. This checks the pinned examples, not every live interaction.
The existing independent-conversation version mismatch below predates this merge.

## Already available: retain and extend these owners

- Transcript activity folding, semantic tool presentation, copyable input/output,
  failure navigation, local Find and windowed saved-history reads.
- Edit/resend, branch after a reply, original-chat navigation, changed files,
  combined chat/files undo, selected-file restore, and pending-operation recovery.
  These are supported boundaries, not arbitrary undo across compressed ancestry.
- Stop, queued follow-ups and steering; retry sends already carry `retry_of`.
- Context inspection, model/reasoning controls, provider usage details and the
  shared Work surface. Background work already includes delegation observations;
  a new subagent dashboard would duplicate existing surfaces.

Launcher anchors: `EterniaLauncher/lib/features/agent_console/panel/agent_console_find_scope.dart`,
`EterniaLauncher/lib/features/agent_console/history_controls/`,
`EterniaLauncher/lib/features/agent_console/panel/agent_console_pending_queue.dart`,
`EterniaLauncher/lib/features/agent_console/panel/agent_console_send_lane.dart`,
`EterniaLauncher/lib/features/agent_console/context/`,
`EterniaLauncher/lib/features/agent_console/panel/agent_console_usage_panel.dart`,
`EterniaLauncher/lib/features/agent_console/panel/agent_console_work_button.dart`.

## Decisions needed

Requested October 13: decide priority and user-facing scope for the rows below.
These are decision references, not duplicate implementation claims. Existing
queue owners and rulings remain authoritative. IDs are references, not a delivery order.

**Endpoint key:** Runtime = Eternia's authenticated `hermes harness serve` RPC;
Gateway = upstream's native TUI/Desktop RPC, which is **not automatically exposed**
to Launcher; Event = a notification, not a callable method. “None” means no
matching shipped endpoint was found in the inspected registries; no proposed
endpoint name is presented as implemented. All source links below are in Hermes.

| ID / decision needed | Value to Eternia Harness | Existing Hermes implementation and endpoints | Scope / ownership boundary |
|---|---|---|---|
| D01 — When should Find search all saved history? | **Very high:** retrieve decisions, errors and results outside the loaded transcript without asking the model again. | [Search RPC](../../agent_runtime/serve_rpc/chat_verbs.py), [curated search](../../agent_runtime/persona_chat_history/search.py). Runtime: `runtime.persona.chat.history.search`; open hits through `runtime.persona.chat.history` using `open_before`. | Producer shipped `2e7e42f5cb`; extend the existing Find bar. Preserve redaction, durable IDs and `history_revision`. Existing Launcher Find row is claimed by **q-mc**; its stale producer hold was corrected in `bc3f8b18dd`. Current search scans curated lineage; it is not indexed FTS. |
| D02 — Add an explicit side-question action during work? | **Very high for long tasks:** answer “why?” or “what does that mean?” without steering or interrupting the running task. | [Side-question implementation](../../agent/side_question.py), [gateway handler](../../tui_gateway/methods_prompt.py). Gateway: `prompt.btw`; Event: `btw.complete`. | Expose the existing snapshot-based, tools-disabled execution through the authenticated conversation owner, with usage/cancellation attribution. A small collapsible answer is proposed. It makes a model request and has a cost. No new implementation claim. |
| D03 — Show compaction progress/completion; offer manual compaction too? | **High:** explain context pressure and apparent pauses, improving trust in long conversations. | [Session contract](../../tui_gateway/contracts/sessions.py), [completion projection](../../tui_gateway/compute_host_bridge.py), [compaction facts](../../agent/compaction_events.py). Gateway: `session.compress`; Event: `status.update` with `compacting` / `compacted`. | First decision is lifecycle visibility in existing Activity/Context. Manual compaction is a separate scope choice with native concurrency guards. Do not imply the visible transcript was erased. No new implementation claim. |
| D04 — Extend Branch to older compressed ancestry? | **High for long work:** explore an earlier approach while preserving the original conversation and its history. | [Native branch source](../../tui_gateway/methods_session_branch.py), [operator plan](../../agent_runtime/operator_history.py). Gateway: `session.branch`. Runtime: `runtime.operator.conversation.history.preview` and `runtime.operator.conversation.history.apply` with branch action; compressed ancestry currently refuses. | Extend the existing Branch action only after a qualified ancestor-prefix clone. Reuse the native history boundary, not TUI globals. Existing Hermes “lossless prefix branching across native compressed ancestry” row is **unclaimed**. |
| D05 — Add resumable tool connection/setup cards? | **High when access is missing:** let users connect or repair a dependency at the blocked tool step and recover the same decision after reconnecting. | [Connection contract](../../tui_gateway/contracts/connectors_operation.py), [handlers](../../tui_gateway/methods_connectors.py). Gateway: `connectors.operation.status`, `connectors.operation.wake`, `connection.respond`; Events: `connection.request`, `connection.update`. | Project the existing operation ID, sequence, deadline and pending snapshot through the runtime. Reuse account/install authorities. Bind one card to its `tool_call_id`; provider login alone is not this feature. No new implementation claim. |
| D06 — Add delegated-agent inspection and steering? | **High for power users:** understand who is doing what and redirect the right child without disturbing the parent task. | [Delegation contract](../../tui_gateway/contracts/billing_delegation_pets.py), [existing runtime Work owner](../../agent_runtime/running_work/surface.py). Gateway: `delegation.status`, `subagent.steer`, `delegation.pause`. | Extend current Work details, with originating-turn links. Pause blocks new spawns, not running children; accepted steering can still be queued. No second task dashboard or scheduler. No new implementation claim. |
| D07 — Add verified turn outcomes? | **High:** show what a turn actually delivered—validation, changed files, commits and push status—with provenance. | [Existing tool execution](../../agent/tool_executor.py), [turn changes RPC](../../agent_runtime/serve_rpc/operator_history.py). Runtime: `runtime.operator.conversation.turn.changes` supplies file changes, **not** a complete validation/Git verdict. No complete turn-outcome endpoint exists. | Existing Hermes turn-outcome row is **unclaimed**; the owner already ruled **plugin hook**, not upstream executor (October 10). Launcher consumer row remains claimed by **q-mc**. Decide outcome scope/evidence and priority; do not reopen the plugin ruling or infer success from assistant prose. |
| D08 — Offer complete conversation export, and in which formats? | **Useful for review/support:** preserve a portable record without repeatedly copying loaded messages. | [Desktop exporter](../../apps/desktop/src/lib/session-export.ts), [paged reader](../../apps/desktop/src/api/sessions.ts), [session contract](../../tui_gateway/contracts/sessions.py). Upstream HTTP: `GET /api/sessions/{id}/messages`; Gateway: `session.save`. Console's available Runtime read: `runtime.persona.chat.history`. | Reuse curated paging and redaction for Console export; do not export only loaded rows or bypass the runtime to read hidden database content. Choose JSON/Markdown and attachment treatment. No new implementation claim. |
| D09 — Add bookmarks and copy-link to a durable step? | **High for repeated investigations:** return to an exact failure, decision or result without searching from scratch. | [Durable history rows](../../agent_runtime/persona_chat_history/history_rows.py), [history RPC](../../agent_runtime/serve_rpc/chat_verbs.py). Runtime: `runtime.persona.chat.history` is the read/open foundation. No bookmark or Console step-link endpoint exists. | Existing Launcher design row is claimed by **q-mc**. Decide per-operator bookmark persistence and a route in the existing app deep-link router; no new Hermes bookmark service is implied. A link must resolve before a Copy link action ships. |
| D10 — Enable regenerate with another model? | **High for comparison/recovery:** try another model while keeping the original answer and retry relationship intelligible. | [Operator send](../../agent_runtime/serve_rpc/operator_conversation.py), [model control](../../agent_runtime/serve_rpc/operator_inspection.py), [retry admission](../../agent_runtime/chat_turn.py). Runtime: `runtime.operator.conversation.message` with `retry_of`, and `runtime.operator.conversation.model.select`. | Retry lineage/model control exist; a polished regenerate operation does not follow automatically. Existing Launcher follow-on is claimed by **q-mc2** and **owner-deferred**. Decision is whether to lift that deferral and define per-reply model scope without changing unrelated defaults. |
| D11 — Add Redo after a completed Undo? | **High for Undo users:** recover from undoing too far and compare alternatives without rerunning model/tool work or paying to recreate an answer. | [Undo coordinator](../../agent_runtime/operator_undo.py), [history RPCs](../../agent_runtime/serve_rpc/operator_history.py), [checkpoint owner](../../tools/checkpoint_manager.py). **No Redo endpoint exists.** Adjacent Runtime APIs include `runtime.operator.conversation.undo.preview`, `runtime.operator.conversation.undo.apply`, `runtime.operator.conversation.undo.recover`, and `runtime.operator.conversation.checkpoint.restore`. | Proposal: start with one reviewed Redo of the last completed Undo, preserving its chat/files/both mode. Decide retention and behavior after new turns or file edits. Extend SessionDB/CheckpointManager and the existing operation owner; no parallel history store. Recovery from a partial Undo is not Redo. No new implementation claim. |

### Current prerequisite and verified claim: v3 / reviewed file input

Rechecked against Hermes `bdfd4c099c` and Launcher `bc3f8b18dd` on October 13.
The live queue entry is C019 in
`EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`.
It explicitly says **TAKEN 2026-10-12 q-mc**. That proves recorded ownership,
not whether a worker is currently running. There are no separate subclaims in
that entry: its claim covers the remaining Launcher integration and qualification.

| Part | Verified status / owner | Evidence |
|---|---|---|
| Hermes v3 capability, reviewed-file packet and native staging | **Landed**, not an outstanding producer claim. | `d3ce04dfc1`, `5a374d46ec`; [service](../../agent_runtime/conversations/service.py), [validation/staging](../../agent_runtime/conversations/prompt.py), [RPC registration](../../agent_runtime/conversations/rpc.py). Runtime: `runtime.conversation.capabilities`, `runtime.conversation.send` with `prompt.files`. |
| Launcher v3 compatibility gate | **Open, inside q-mc's C019 claim.** | `EterniaLauncher/packages/agents/eternia_hermes_adapter/lib/src/conversation/native_client.dart::open` still accepts only version 2; Hermes advertises 3. |
| Reviewed file packet, typed refusals and send/recovery integration | **Open, inside the same C019 claim.** | Queue names base64 `prompt.files`, `file_unsupported` / `file_oversize` / `file_invalid`, and admitted-versus-unadmitted recovery. `EterniaLauncher/packages/agents/eternia_hermes_adapter/lib/src/conversation/native_prompt.dart` still embeds non-image file text. |
| Live qualification, including the Console turn transport | **Required and still open in C019, same owner.** | October 12 verdict requires a real serve/turn and explicitly includes the Console transport; native worker support alone does not establish that path. |

### Redo value and boundary

Redo has high recovery value; its later delivery recommendation reflects the
missing durable contract, not low usefulness. It must restore the reviewed
pre-Undo chat/file state rather than regenerate an answer. Existing Undo releases
restore retention pins when it reaches a terminal state
(`operator_undo.py::_transition` / `_release_backup`); current recovery backups
therefore cannot promise a durable Redo window. A design must retain the required
before/after state, detect intervening changes, define expiry and restore chat/files
consistently through the current owners. External tool side effects such as a sent
message are outside a chat/file Redo. Multi-level history is a separate decision;
D11 does not authorize building it or changing the existing Undo behavior.

## Boundaries and recommendation

Fix/qualify the existing v3 integration first, then connect saved-history Find.
Side questions and compaction visibility are the strongest subsequent everyday
improvements. Keep branch ancestry and connector/subagent controls scoped and
capability-gated. Do not clone upstream's Desktop store, use a second search
engine, create a second task authority, or infer success from assistant prose.

The upstream main comparison includes unreleased desktop onboarding/connector
changes. It is research only; no unreleased main content was merged. The useful
primitives named above were checked in v0.21.7. Automatic background review in
`agent/background_review.py` is memory/skill maintenance, not proof that code
was reviewed or tests passed.

Reference: [official v0.21.7 release notes](https://github.com/NousResearch/hermes-agent/releases/tag/v0.21.7).
