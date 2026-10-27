**BUILT — archived 2026-10-27 by triage lane w1027j-h-tri-a; landing commits 4a8167c3a0, d476fa8675, c04528d99a, e972746e82, 7481ec678f.**
All six proposals ruled and landed; §1's live A/B is owned by `p10-agent-2026-10-19.md` and row RT-VERIFY-IMPROVE-FIRST-RESPONSE.

# Planned — agent behaviour and policy rows: proposals for the owner (r-agent, 2026-10-18)

**Owner domain:** the chat turn lane ([05-chat-turn-lane.md](../05-chat-turn-lane.md))
**Status:** proposals, nothing built. Each section is the evidence note one runtime-queue row
points at. A section ends in the decision the owner makes or the plan a lane writes next.
**Measured / read:** 2026-10-18 against `origin/main` c31397c492.

## 1. First-response selection of the Launcher's generated-content tools

**What is true.** The tools are in view (Launcher declares all five `alwaysLoaded`, which feeds
`tools/tool_search_downstream.py::never_defer_tool_names`) and the miss is still a plain Markdown
answer with `tool_turns=0` (live 2026-10-15). The WHEN text the model reads beside them is the
host's: `agent_runtime/launcher_app_functions.py::app_function_guidance_lines` renders each
registered entry's `guidance`, which the Launcher writes
(`EterniaLauncher/lib/core/services/hermes/runtime/data/capabilities/harness_generated_capabilities.dart`).
Hermes owns no wording here, and must not grow a second copy of the rule.

**Proposal.**

1. Launcher: the comparison trigger goes into the create tool's `guidance`, stated as an
   instruction with an object — "When the user asks to compare, contrast, rank or tabulate two or
   more things, answer with `<create tool>` (a Composition / Table), not a Markdown table." One
   line, under 60 tokens; the refusal wording the qualification doc keeps stays as it is.
2. Hermes: an A/B harness under `evals/` that replays a fixed set of ordinary-language
   comparison prompts (ten, none naming the tool) on the owner's QA serve, per agent and
   provider, guidance on vs. off, recording the first tool called and `tool_turns` from the turn
   record. It reads receipts; it starts no serve of its own.
3. Budget: the guidance line's tokens are read from the model-input receipt
   (`final_model_input`), before/after, and reported with the A/B numbers.

**Plan owed:** the eval's prompt set and its pass bar (e.g. ≥ 8/10 first-tool hits per
provider), then the Launcher wording lands first and the eval runs against it.

## 2. Long tool calls move to the background (DESIGN)

**What already exists.** Three ways a finished background thing re-enters a conversation, all on
`process_registry.completion_queue`: a background `terminal` (`notify_on_complete`), an async
`delegate_task`, and an MCP job wake (`tools/mcp_job_wake.py`). Fork event types are one table
(`tools/fork_completion_events.py`: format + settle per type; the gateway and CLI/TUI drains read
it), and the serve drain forges a continuation turn through the mission-chat door
(`agent_runtime/dispatch_delivery/completions.py`). Running work is projected per kind
(`agent_runtime/running_work/`).

**Proposal.**

- **Promotion.** The dispatch bracket the fork already keeps in `tools/registry.py` (MCP
  progress) runs a promotable call on a worker. Past a threshold — a tool's declared
  `long_running`, else 45 s — or on the operator's "Send to background", the call returns a
  synthetic result `{"status": "running_in_background", "handle": "bg:<id>"}`. The provider
  contract (one tool_result per tool_use) is met; the turn ends normally and the agent may keep
  talking. Nothing is promoted while it holds a terminal envelope grant or an approval prompt.
- **Re-entry.** On completion the worker puts a `tool_call_finished` event on the completion queue
  — one new row in the fork table (format: tool, handle, outcome, redacted tail; settle: retire
  the running-work row). Every surface already drains it; the serve forges the continuation turn.
- **Await semantics.** No turn blocks on a promoted call. A later turn that needs the result
  reads it from the wake; a second promotion of the same tool+args while one runs returns the
  existing handle.
- **Console.** A running card per handle (kind `tool_call`) with Send to background (before the
  threshold) and Cancel (cooperative interrupt to the worker; the wake then carries
  `cancelled`).
- **Seams.** Upstream: the existing `tools/registry.py` bracket only. Fork: the worker, the
  table row, a `running_work` lane, `runtime.work.background.cancel` / `.promote` RPC methods.

**Decision owed:** threshold and default (45 s proposed), which tools may never be promoted
(proposed: `clarify`, approval-bearing terminal calls, anything mutating the conversation), and
whether the agent may itself request promotion.

**Built, runtime half (lane w2-turn, 2026-10-18; owner approved the design the same day).**
`tools/long_tool_calls.py` (the bracket, the `tool_call_finished` row in
`tools/fork_completion_events.py`, `tool_calls.json`); `running_work`'s `BackgroundToolCallLane`
(kind `tool_call`, `background: true`, source `tool_call`); the chat-turn row's
`current_tool.promotable`; `runtime.work.background.promote` (Send to background) and the existing
`runtime.work.cancel` (Cancel; a promoted row cancels through the worker's interrupt bit). Armed
only on a live serve turn's tool thread; `NEVER_PROMOTE` = `clarify`, `terminal` (its own
`background=true` door), `process`, `delegate_task`, `execute_code`, `todo`, `memory`; the agent
cannot request promotion itself (not ruled). The launcher card is the launcher's row.

## 3. `AutonomyLevel.APPLY_WITH_REVIEW`

**What is true.** `agent_runtime/personas.py::AutonomyLevel` has three members; the stored field
is a free string (`models.py` defaults it to `"review"`, a fourth spelling outside the enum). The
one behaviour reader is `agent_runtime/coordinator_permissions.py::scope_for_persona`:
`review` / `propose_only` → no spawn or kill budget; anything else, `apply_with_review`
included, → the full coordinator grant. So `apply_with_review` behaves exactly like
`autonomous`; the rest of the readers are display (`snapshot/summaries.py`) and config carry.
Making it "review before a Work card completes" needs a review door the lane does not have
(upstream `agent/review_engine.py` is unreachable from `runtime.chat.*`).

**Decision owed.** Recommend: delete `APPLY_WITH_REVIEW` with a tombstone, map a stored
`apply_with_review` to `autonomous` on read (it already behaves so), and make the enum the
field's type with `review` as the `propose_only` alias — one vocabulary, one reader. Revisit a
review-gated level when the review door exists.

## 4. `agent.verify_on_stop` on persona turns

**What is true.** Upstream defaults it OFF and its migrations 30→31→32 turned it off on purpose
("more noise than signal"). `agent/verification_stop.py::verify_on_stop_enabled` reads the env
var, then the profile config, at call time; `auto` is ON for any non-messaging surface. The nudge
only fires after a turn that edited files, so on a turn with no edits it costs nothing. The cost
on a dev persona's editing turns is unmeasured, and measuring it needs live turns on the owner's
QA serve.

**RULED 2026-10-18 (owner): OFF everywhere.** Measured on the QA serve, an editing turn cost
11.8 calls / 234k input tokens / 77 s ON against 2.6 / 44k / 28 s OFF, and outside a repo the
nudge never fired. No dev-persona opt-in is shipped; the upstream default (`False`) stands and an
operator's explicit `agent.verify_on_stop` key or `HERMES_VERIFY_ON_STOP` still works.
`tests/agent_runtime/test_verify_on_stop_off_downstream.py` pins it.

## 5. When to delegate, send or submit Work

**What is true.** The harness's tool guidance is one prompt section
(`plugins/eternia-harness/__init__.py::render_tool_guidance`, lines gated on the tools present,
texts in `agent_runtime/prompt_guidance.py`). Submitting Work is not a tool a persona can call
today: the whole `kanban` toolset is withheld on every lane
(`agent_runtime/personas.py::REGISTRY_HYGIENE_BLOCKED_TOOLSETS`), so a paragraph naming it would
describe a door the model cannot open.

**Proposal.** One line, rendered when `delegate_task` and `agent_chat_send` are both present
(302 chars, ~75 tokens by the 4-chars heuristic; the venv has no tokenizer):

> Pick the hand-off by its lifetime: `delegate_task` for a bounded side job whose result you need
> back in this turn; `agent_chat_send` to ask a persistent teammate who keeps their own context
> and answers later; submit Work for a durable task another agent owns, that must survive a
> restart or a hand-off.

The Work clause renders only once a kanban verb is admitted on the lane; until then the line
stops after the `agent_chat_send` clause (~45 tokens).

**Plan owed:** the constant, the gating row in `_TOOL_GUIDANCE` (two-tool gate), and the token
cost read off the model-input receipt the way h-prompt-brief measured descriptions.

## 6. A door to upstream's goal engine on the persona chat lane

**What is true.** `hermes_cli/goals.py::GoalManager(session_id)` is complete and persisted in
SessionDB: `set` / `pause` / `resume` / `clear` / `status_line`, subgoals, gates, contract,
`evaluate_after_turn` (the judge) and `next_continuation_prompt`. The CLI, TUI and gateway hold
one per live session; the runtime holds none, so a persona chat cannot keep going until done.

**Proposal.**

- RPC: `runtime.chat.goal.set | status | pause | resume | clear`, keyed by the persona chat
  root (resolved to its session id at call time), each a thin call into `GoalManager`.
- Loop: after a terminal turn on a root with an active goal, the serve calls
  `evaluate_after_turn`; on `should_continue` it forges the continuation prompt through the
  mission-chat door the delivery drain already uses (the operator's own send wins the slot; a
  continuation never preempts an operator turn). The turn budget and judge are upstream's.
- Surfaces: everyday none (the persona just keeps going); developer mode a status line from
  `status_line()`.

**Decision owed.** Recommend building it as above, after the kanban/Work rows that share the
judge (`runtime.work.start` carrying `goal_mode`) so one goal vocabulary serves chat and Work.
