# Planned — the operator chat runs on the gateway engine (2026-11-21)

Row: `RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT` (runtime queue), slice F0 of the
fold. Slice 1 (`7030105df1`) put every Intelligence conversation on the in-process `tui_gateway`
engine. This plan maps what the operator chat's own host still does onto that engine, so F1-F4 fold
it without a second design. Ruling that binds: one turn engine for both chat types, inside the serve,
upstream's in-process machinery reused (owner 2026-11-21). Read at `origin/main` `29de410183`.

## The two hosts today

| | operator chat (Mission Control) | Intelligence conversation |
|---|---|---|
| entry | `chat_turn_message._cmd_mission_chat_message` → `chat_turn_commit/` → `persona_runtime.GPTPersonaRuntime.mission_chat_reply` | `conversations/service.py::ConversationService` → `in_process_peer.InProcessPeer` |
| host | `profile_runner/runner.py::ProfileAgentRunner.run` → `execute.py::AgentRunExecution` (builds `AIAgent` through `_default_agent_factory`) | `tui_gateway.server.dispatch` → `prompt_turn._run_prompt_submit` (builds `AIAgent` through `agent_factory._make_agent`) |
| resident agent | `persona_chat_continuity.runtime_registry` keyed by chat root, prewarmed by `persona_chat_actor_prewarm` | the gateway session record's `agent`, built eagerly by `session.create` / `session.resume` |
| busy root | `chat_root_send_queue` + `chat_root_send_runner` (durable, per root) | `prompt_turn._enqueue_prompt` / `_drain_queued_prompt` (in memory, per session) |
| goal loop | `work_store/goal_turns.after_turn` / `after_chat_goal_turn` / `wake_parked` | `prompt_turn._goal_followup_after_turn` |
| completion drain | `dispatch_delivery` drain thread (forges a mission-chat turn) | `session_notifications` poller + `_run_post_turn_followups` safety net |

Both end in `AIAgent.run_conversation` and both drains read the same
`process_registry.completion_queue` now that both live in the serve.

## The two fork seams the gateway already carries

The gateway is upstream-owned. It already calls two fork-owned functions on every session, so the
operator's policy rides them and the footprint does not move:

- **construction** — `agent_factory._make_agent` builds through
  `agent_runtime.conversations.worker_app_functions.create_agent(factory, sid, session, **kwargs)`.
- **turn scopes** — `prompt_turn._prepare_turn_input` binds `worker_app_functions.bind(sid, session)`
  and `_release_turn_scopes` resets it (`TurnScopes`, the permission block already rides it).

A session opened for an operator chat root carries `source="eternia_operator"` and an
`operator_policy` record (the turn's `AgentRunRequest` minus the callbacks). `create_agent` and
`bind` dispatch on that source to one fork module, `agent_runtime/operator_turn_policy.py`
(new in F1). No other gateway file changes.

## `execute.py`'s duties, one by one

| duty in `AgentRunExecution` | where it lands on the engine | seam |
|---|---|---|
| `scopes`: `_workspace_turnstile`, `root_run_lock` | the session's own `running` admission (one turn per session); the workspace turnstile is entered in `bind` | turn scopes |
| `scopes`: `_posix_process_home`, `persona_profile_context` | the gateway's `_profile_runtime_scope_tokens(profile_home)` (home, secrets, terminal policy) — the session opens with the persona's canonical profile, as a conversation does | none (upstream) |
| `scopes`: `_agent_workdir`, `tool_execution_scope`, `chat_root_session_key_scope`, `terminal_envelope_scope`, `skill_runtime_scope`, local-engine prewarm scope | one `ExitStack` entered in `bind`, closed in `reset` (same thread: both run on the turn thread) | turn scopes |
| `scopes`: `session_approval_scope(root)` (per-chat notifier → `_notify_root`) | upstream's per-session queue is the one path: the gateway's `register_gateway_notify` emits `approval.request`; the operator side answers frames with the same `_notify_root` sink and resolves through `tools.approval` by session key | frame consumer (F1) |
| `refuse_an_unusable_chosen_credential` | run before submit, by the operator caller | caller |
| `resolve_runtime` + 30 s memo + idle refresh | the model cascade (`persona_chat_session._resolve_turn_model_selection`) is supplied as the session's `model_override` (`{model, provider, base_url, api_mode}`); the gateway resolves it (`_resolve_agent_model_runtime`) and re-syncs per turn | session facts |
| `arm_wall_checkpoint`, wall timers, `RunBudgetLedger`, `_qa_silence` | entered in `bind`: the checkpoint binds the session's agent, the timer interrupts it (`agent.interrupt`, as the gateway's Stop does) | turn scopes |
| `admit_mcp` (per-persona admission, call budget, release) | entered in `bind`, released in `reset` | turn scopes |
| `build_turn_state` (status / tool progress / start / complete / clarify callbacks, `ToolFinishJoin`, budget guard) | the gateway sets its own callbacks (`_agent_cbs`); `bind` tees them to the operator's progress adapters for this turn, `reset` restores | turn scopes |
| `construct_agent` (`_default_agent_factory`: blocked tools, `chat_lane_defer`, `_skip_mcp_refresh`, cache scope id, checkpoint kwargs, skill scope, chat speed, reasoning config) | `create_agent` for an operator session applies the same post-construction policy to the agent `_make_agent` built | construction |
| `acquire_agent` (resident registry, signature rebuild, prewarm discard) | the session record IS the resident actor; a moved signature closes and reopens the session; prewarm is `session.create` / `session.resume` | session lifecycle |
| `bind_chat_root` (checkpoint recorder, persona ids, user-row marker, `compression_in_place=False`, compaction threshold) | applied in `bind` to `session["agent"]` | turn scopes |
| `bound_tool_block` (registry hygiene + admission block) | `worker_permissions.bind` already binds `extra_blocked_tools_for_permission_mode(mode)`; the operator's per-chat mode goes through the same `remember(execution_id, mode)` — ONE permission path | turn scopes (existing) |
| `_steer_mcp_admission_notice`, `live_turns.live_turn`, `idle_turn_keeper.note_active_agent`, `agent_ready_callback` | entered in `bind` | turn scopes |
| `_run_conversation_with_usage_ledger` (usage ledger, persona turn agent, stream observers, turn defer, reasoning, turn outcome, deferred persist) | the context managers enter in `bind` and exit in `reset`; the raw result is read off the turn's `TurnScopes` handle at `reset` | turn scopes |
| `system_message` (persona prompt policy), `skip_memory`, `skip_context_files` | construction kwargs (`ephemeral_system_prompt`, skip flags) applied by `create_agent` | construction |
| `_attach_model_input_observability`, `_normalize_result`, post-run budgets, provider refusal record | run by the operator caller on the raw result the handle carries | caller |

## The slices

- **F1** — `operator_turn_policy.py` (construction + turn scopes above) and an operator turn client
  that opens (or reuses) the chat root's session on the serve's in-process gateway and submits
  `prompt.submit`, consuming frames into the existing progress / stream / clarify callbacks and
  returning `AgentRunResult`. `ProfileAgentRunner.run` calls it; `execute.py` stays only for the
  prewarm until F4.
- **F2** — one goal loop: a chat goal on an operator root is the session's `GoalManager`, evaluated by
  `prompt_turn._goal_followup_after_turn`. A Work run (`goal_mode=UNTIL_DONE`) stands (owner ruling:
  the Work board stands); its continuation becomes a queued prompt on the session instead of a forged
  send-queue entry, and `goal_turns.after_chat_goal_turn` / `_wake_chat_goals` retire.
- **F3** — one completion drain: background completions for an operator root are claimed by the
  session's notification poller (`_session_owns_notification_event`, owner = the root's session key);
  `dispatch_delivery`'s background-completion lane retires. Dispatch replies (`agent_chat_send`
  `wait=false`) keep the dispatch store; their forge submits to the session.
- **F4** — retire `runner._default_agent_factory`, `execute.py`, `resident_actor.py`, the resident
  registry's operator half, `persona_chat_actor_prewarm` and `chat_root_send_queue` /
  `chat_root_send_runner` (the gateway session's queue holds a busy root's sends; the durable "queued"
  answer becomes the session's queued prompt plus the mission-chat journal's write-ahead row).

## What can go wrong

- **History source.** The operator loads its transcript through `persona_chat_history` (compression
  lineage tip); the gateway resumes a session id and loads `session["history"]` from SessionDB. F1 resumes the
  root's current tip id and must prove both read the same rows (test: a rotated root resumes at its tip).
- **Durable queue.** The send queue survives a serve restart; the gateway's queued prompt does not.
  F4 keeps the journal's write-ahead record as the durable half and replays an unanswered queued send
  on boot, or it does not retire the queue.
- **Two drains on one queue.** Until F3, both drains pop `process_registry.completion_queue`; each
  requeues events it does not own, so no event is lost, but ownership must stay exclusive per root.
- **Footprint.** Every step above uses the two existing seams; an upstream edit is a footprint row with
  an owner ruling, never a raised ceiling.
