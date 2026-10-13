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

## Ranked integration opportunities

| Priority / value | Capability and present state | Existing authority and next boundary | Clean presentation |
|---|---|---|---|
| 0 — correctness | Native independent conversations v3 + reviewed file input: Hermes advertises v3/files; Launcher `NativeConversationClient.open` rejects anything other than v2 and admits images only in its capability flags. | `agent_runtime/conversations/service.py::capabilities`, `conversations/prompt.py`; `EterniaLauncher/packages/agents/eternia_hermes_adapter/lib/src/conversation/native_client.dart`. Existing Launcher C019 row owns this. Qualify the v3 packet and refusal/recovery behavior, not a version-number-only edit. | Existing Files review and composer. No new attachment system. |
| 1 — very high, relatively contained | Search all saved conversation history: Console Find searches loaded rows. The required Hermes read RPC **already shipped** on October 10 (`2e7e42f5cb`). | `agent_runtime/serve_rpc/chat_verbs.py::_runtime_persona_chat_history_search`; `persona_chat_history/search.py`. Consume its curated/redacted hits and `open_before` cursor through the existing history reader. The older Launcher row saying Hermes moves first was stale; queue correction `bc3f8b18dd` points its existing owner at the shipped RPC. This RPC scans curated lineage; it is not a new indexed FTS service. | Extend the existing Find bar with older-history hits and jump-to-result. |
| 2 — very high during long work | Ask a side question without interrupting or steering the active task. Upstream `/btw` already snapshots the conversation, denies tools and detaches persistence. No Console adapter for it was found. | `agent/side_question.py::answer_side_question`, `tui_gateway/methods_prompt.py` (`prompt.btw`, `btw.complete`). Expose it through the existing authenticated conversation owner; preserve identity, cancellation and usage attribution. It still makes a model request and has a cost. | A deliberate Ask action and a small collapsible answer, separate from queued work. |
| 3 — high | Honest compaction status and completion: upstream has `status.update` compacting/compacted edges and `session.compress`; Console has context capacity/threshold displays but no explicit consumer for this lifecycle. | `tui_gateway/server.py`, `session_compression.py`, `agent/compaction_events.py`, upstream desktop `store/compaction.ts`. Project existing lifecycle facts through the runtime. Manual compaction would require its existing concurrency guards, not a direct UI mutation. | One quiet activity/status item; details in the existing Context view. Never imply displayed history was deleted. |
| 4 — high for long conversations | Branch from older compressed history: ordinary branching works; the operator history plan explicitly refuses compressed ancestry. Upstream has a display-history-aware branch source. | `agent_runtime/operator_history.py::_plan`; upstream `tui_gateway/methods_session_branch.py::_branch_source_history` and `get_resume_conversations`. Reuse/extract that native boundary with durable IDs, hidden-row policy and ancestry tests. Do not simply remove the refusal or call TUI globals from the operator service. | Keep the same Branch action; explain unavailable boundaries until qualified. |
| 5 — high when a tool needs setup | Resumable connection/setup cards: upstream has connection requests, revisions, deadlines, updates and resume snapshots. No corresponding operator/native Console projection was found. Provider login UI already exists and is not this feature. | `tui_gateway/contracts/connectors_operation.py`, `tools/connectors/`, `LiveSessionSnapshot.pending_connection`. Route through existing scoped connector/install/auth owners and preserve user decisions across reconnects. | One card attached to the requesting tool step; reuse account and installation controls. |
| 6 — high for power users | Inspect and steer a delegated child: work/delegation observations already exist; the inspected Console adapter has no `subagent.steer` or delegation-tree control consumer. | `tui_gateway/contracts/billing_delegation_pets.py`: `delegation.status`, `subagent.steer`, `delegation.pause`; `agent_runtime/running_work/`. Extend the current Work details. Pause stops **new spawns**, not running children; queued steering is not confirmed delivery. | Child details under the existing Work surface, linked to the originating turn. |
| 7 — high, requires new facts | A trustworthy turn outcome: files, validation results and Git commit/push state. Current activity summary counts tools/thoughts/failures, not verified deliverables. Upstream does not supply one ready-made outcome contract. | Existing `runtime-queue.md` turn-outcome row and `EterniaLauncher/lib/features/agent_console/trace/agent_console_turn_activity_summary.dart`. Reuse tool receipts and checkpoint attribution; distinguish agent claims, command exit status and verified repository state. | Enrich the existing result/files summary; avoid another permanent panel. |

The existing saved-history search method is `runtime.persona.chat.history.search`.
Its results open through `runtime.persona.chat.history`; neither requires a model call.

## Useful follow-ons, below the list above

- Full-conversation export: upstream desktop `lib/session-export.ts` uses the
  complete stored-message reader. Console has copy actions but no equivalent
  full export found. Reuse curated paging and redaction; do not export only the
  currently loaded projection or raw hidden database rows.
- Bookmarks and links to a durable step: useful, already a Launcher design row.
  The app has a deep-link router; it does not yet have a Console step route/store.
- Regenerate with another model: retry lineage and model selection already
  exist. An existing Launcher follow-on is owner-deferred; coordinate there.
- A dedicated Redo operation was not found in the inspected native contracts.
  Recovery backups are not a substitute for a reviewed redo feature.

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
