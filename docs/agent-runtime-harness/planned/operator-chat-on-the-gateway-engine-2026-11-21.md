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

- **F1** (with F2; see "Read while starting F1") — `operator_turn_policy.py` (construction + turn scopes above) and an operator turn client
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

## Read while starting F1 (2026-11-21, w1118a-onepath-fold)

Three facts in code change the F1 step list above; each was read, none reproduced yet.

1. **The operator chat lives in the head store, not the persona's.** `chat_turn_commit/run.py` builds
   `GPTPersonaRuntime(session_db=self.session_db)` on the head home, and `profile_runner` hands that
   handle to the agent; the persona's profile is bound only for tools, secrets and the workdir
   (`persona_profile_context`). A gateway session opened with the persona's `profile` reads and writes
   that profile's `state.db` (`session_registry._start_agent_build` → `_open_profile_session_db`). So the
   operator's gateway session is opened on the head profile (the launch scope of the serve), and the
   persona binding stays inside the turn scope, as today. `InProcessPeer` refuses a non-profile home
   (`_profile_for`), so F1 gives it a launch-scope mode instead of a second peer.
2. **The gateway writes the submitted text as a user row and the agent adopts it.**
   `prompt.submit` persists the text into the session key and `_adopt_submit_user_row` hands it to the
   agent as `_pending_cli_user_message`. The operator's scratch row today carries the composed user
   message (HUD, preloaded skill), the relay sender marker (`stage_persona_chat_user_row_marker`) and
   image `MEDIA:` lines, and a replayed pending turn reuses its row (`reuse_current_user_message`).
   RECOMMENDED, awaiting the owner (2026-11-21; built on the branch meanwhile, reworked there before
   landing if the owner rules otherwise): the gateway session is resumed on the chat's
   native TIP, the submitted text is the composed user message, and the agent adopts the gateway's
   row (upstream's transcript model wins — the ruling's "reuse upstream's machinery"); the relay marker
   and image lines are staged onto that adopted row by the construction policy, and a replay submits
   nothing new (the turn scope clears the adoption). Alternatives weighed: a hidden phantom session
   (rejected: a second copy of every operator message in the head store) and an upstream "submit
   without a row" flag (rejected: footprint, and it keeps two transcript models).
3. **F1 and F2 cannot land apart.** A chat goal arms upstream's `GoalManager` on the chat ROOT
   (`chat_goal.arm(root_session_id, …)`); the gateway's loop evaluates the goal of the session KEY. On a
   chat that never compressed, root == tip == key, so with F1 alone both `goal_turns.after_turn` and
   `prompt_turn._goal_followup_after_turn` would judge and continue the same goal. F1 therefore lands
   with F2's switch of the operator's chat-goal continuation onto the gateway loop (Work runs keep their
   binding and continue as queued prompts on the session).

## Built on the branch (2026-11-21, w1118a-onepath-fold)

What the build found, and where it departs from the steps above.

1. **Fact 1 was wrong.** The operator transcript lives in the runner's `session_db`: the persona's
   own profile store when the persona has one, the head's otherwise. The chat's gateway session is
   resumed in THAT store, through one in-process peer per store home (`operator_gateway_turn.
   _store_home`); `InProcessPeer` needed no launch-scope mode.
2. **The transcript choice is an empty submit, not the adopted gateway row.** The turn is
   submitted with `text=""`: the gateway writes no submit row, the door hands the composed message
   to the operator lane's own execution, and the agent writes the user row exactly as before (relay
   marker, image lines, replay reuse unchanged). One transcript, no upstream edit, and none of the
   row-adoption staging the recommendation needed. RECOMMENDED, awaiting the owner, in place of 2.
3. **The policy rides a door, not bind/reset.** The gateway calls the agent's `run_conversation` on
   its turn thread; the operator agent's is wrapped (`_install_door`) so that call runs the
   operator lane's `AgentRunExecution` around the real one. Its scopes nest as context managers
   around the conversation, which bind/reset (two calls) would have had to split. The engine still
   runs every turn; `execute.py` is the operator lane's turn policy inside it.
4. **Two seams beyond the two the plan named, both additive:** the gateway's factory asks
   `worker_app_functions.operator_agent` before it resolves a model (the `create_agent` wrapper runs
   after, and refused 5000 when the gateway config resolves no runtime), and the first-contact
   onboarding note skips a `first_contact_owned` session (it latched onboarding into the store
   home's `config.yaml`). Both are on the footprint ledger.
5. **A completion for a chat with no open session.** The poller parks an event whose owner session is
   not live and drops it after ten minutes; an operator chat whose actor was retired would never
   hear it. The operator lane keeps exactly those (queue and park) and forges the turn that reopens
   the chat; the engine's poller has every completion for an open chat.
6. **Found on the way:** importing `tui_gateway.server` swaps `sys.stdout` for stderr; in the serve
   every reply line printed after the first in-process session became a stderr frame. The
   in-process peer now imports it keeping the serve's stdout.
7. **F4 is held.** `persona_chat_actor_prewarm` already opens the chat's session (`session.resume`
   with `eager_build`), and the resident registry's actor IS that session (closing one closes the
   other). Not retired, with the reason:
   - `chat_root_send_queue` / `chat_root_send_runner`: the durable admission ahead of the engine. The
     engine's queue is in memory; retiring the durable one means a boot replay over the journal,
     which is the same durable queue under another name. Owner decision.
   - `execute.py` / `_default_agent_factory`: the door (3) runs them on the engine's turn; moving the
     same calls into bind/reset changes no engine. RECOMMENDED: keep, awaiting the owner.

## Fold and delete (2026-11-21, w1118a-enginefold)

Owner rulings 2026-11-21: keep the durable send queue ("yes"); fold and delete the old turn code ("if
its not used it should be removed no?", then "Yes, fold and delete"). Item 7's `execute.py` hold is
lifted; the send queue stays. Every duty of `AgentRunExecution` and `_default_agent_factory`, by where
it now lives:

| duty | the gateway already does it? | now |
|---|---|---|
| the chat's resident actor | yes: the session record holds the agent | the session is the actor; the registry only pools sessions (signature rebuild, bounds, observations, chat delete) |
| one turn at a time on a chat | yes: the session's `running` admission and queued prompt | the gateway's; `root_run_lock` stays in the scopes, since it also orders the acquisition and the prewarm, which are not gateway turns |
| who builds the agent | yes: `_make_agent` | `_make_agent` → `operator_agent` → `OperatorTurn.construct_agent` → `operator_turn_policy.build_agent`, the one builder (was `runner._default_agent_factory`) |
| the turn's run | yes: `_run_prompt_submit` → `run_conversation` | the engine's; the door runs `OperatorTurn.converse` around the real call. The second execution (`given_agent` / `acquired`) and the direct converse of a request with no chat root are deleted: such a request is refused |
| prewarm | partly: `session.resume` with `eager_build` builds the agent | `OperatorTurn.prewarm` opens the session through the registry and stashes the first prompt; `persona_chat_actor_prewarm` stays as the scheduler (byte-match signature, yields to turns) — nothing upstream opens a session before a chat's first message |
| scopes (turnstile, root lock, posix home, persona profile, workdir, tool / chat-root / approval / envelope / skill scopes, MCP stack) | no: the gateway binds the store's profile, not the persona's | `OperatorTurn.scopes`, entered in the door (inside the gateway's own profile binding) |
| credential refusal, runtime resolve + memo, wall checkpoint + timers, MCP admission + call budget, the turn's callbacks, reasoning, speed, chat-root binding, compaction threshold, tool block, steer notice, live turn, idle keeper, agent ready, usage ledger, model-input observability | no | `operator_turn_policy.OperatorTurn` and `operator_turn_runtime` (operator rules) |
| construction policy (cache scope id, blocked-tool prune, chat-lane defer, MCP refresh off, checkpoint kwargs, skill scope) | no | `build_agent` / `construct_agent` |
| durable admission of a busy chat's sends | no: the gateway's queue is in memory | `chat_root_send_queue` / `chat_root_send_runner`, kept (owner: "yes") |

Deleted: `profile_runner/execute.py`, `profile_runner/resident_actor.py`, `runner._default_agent_factory`,
the second (acquisition) execution and the non-chat direct path. Nothing in the list was deletable in
favour of an upstream copy without changing what a turn does: each remaining duty is the operator
chat's own rule, and each now runs inside the engine's turn or build. No upstream file changed.

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
