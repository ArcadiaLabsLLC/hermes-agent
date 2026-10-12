# Upstream capability audit — what the persona lane does not use or expose

**Status: MEASURED 2026-10-12, no code touched.** Evidence note for the runtime-queue rows
filed with it (`Harness_Brain/20 — Active Initiatives/runtime-queue.md`, "Filed on arrival —
2026-10-12 (upstream capability audit)"). Measured on fork `8a5d6114` with the upstream
manifest at `tests/fixtures/upstream_manifest.txt` (last upstream merge v0.21.6). The
companion note at tool-schema level is `upstream-tool-dividend-2026-09-03.md`; this one is at
capability level, against the seven-row priority table the owner supplied.

Every claim below names the file and symbol it was read from. "The lane" means the persona
chat lane the Launcher's Agent Console drives through `hermes harness serve`.

## 0. How the lane admits capability — the facts every row rests on

- **Declaration.** The bound profile's top-level `toolsets:` is the one declaration
  (`agent_runtime/personas.py`, `HARNESS_LANE_DEFAULT_TOOLSETS`). A profile that declares
  nothing gets `harness_core`, whose members are `agent_runtime/harness_toolset.py::
  HARNESS_CORE_INCLUDES`: `agent_chat, board, clarify, delegation, terminal, file, web,
  browser, browser-cdp, skills, memory, todo, session_search, vision, code_execution`.
  **Not members: `cronjob`, `kanban`.**
- **Blocklist.** `personas.py::_BOUNDED_LANE_BLOCKED_TOOLS` is `delegate_task, clarify,
  memory, send_message, cronjob, cronjob_manage`; `REGISTRY_HYGIENE_BLOCKED_TOOLSETS` is
  `kanban, feishu_doc, feishu_drive`. `chat_lane_scope.py::_blocked_tool_names_for_chat`
  returns `[]` on the unbounded mode and only re-adds `clarify` on bounded.
- **The shipped posture is unbounded.** `permission_modes.py::SHIPPED_DEFAULT_PERMISSION_MODE
  = PERMISSION_MODE_UNBOUNDED`. So on a default install the bounded blocklist and the
  chat-lane cost policy (`chat_lane_toolsets.py::DEFAULT_CHAT_LANE_EXCLUDED_TOOLSETS`:
  browser, vision, code_execution, debugging, file, terminal) are **off**; only registry
  hygiene stands. `delegate_task` and `memory` ARE on the lane; `cronjob` is not (not a
  `harness_core` member); `kanban_*` never (hygiene, unioned at
  `profile_runner/execute.py` so no lane opts out).
- **Defer.** `config/knobs.py::chat_lane_defer_tools` moves per-persona names behind
  `tool_search`; it hides, it does not block.
- **Processes.** The Launcher spawns `hermes harness serve`, never upstream's `hermes gateway`.
  `hermes_cli/harness_parts/serve/boot_phases.py` starts the socket, the peer gateway
  listener and the dispatch-store restore; **it starts neither upstream's cron ticker
  (`cron/scheduler.py`) nor the kanban dispatcher (`hermes_cli/kanban_db_dispatch.py`)**.
  The fork's `running_work` projection says the same from the other side: its cron lane is
  "live-only" and reports nothing unless `_upstream_doors.cron_pools_present` finds pools in
  THIS process (`running_work/__init__.py`).
- **Work.** Owner ruling 2026-09-30 made native kanban the only task store: `agent_runtime/
  work/native.py` imports `hermes_cli.kanban_db` (the one exemption in
  `tests/agent_runtime/test_no_kanban_dependency.py`), and `work/rpc.py` registers
  `runtime.work.{capabilities,context,list,inspect,start}` plus `serve_rpc/work.py`'s
  `runtime.work.{cancel,restart}`. `docs/downstream/hermes-work-view-2026-09-30.md`: "The native dispatcher must
  already be running to execute queued work. This slice does not auto-start it."

That last pair of facts is the audit's spine: **the fork already adopted upstream's board
as its task store, and nothing the Launcher runs executes that store.**

## 1. "Take this goal and own it until finished" — claim holds; the gap is narrower than stated

**Upstream has** (all upstream-owned files): decomposition
(`hermes_cli/kanban_db.py::specify_triage_task`, `hermes_cli/kanban_db_graph.py::
decompose_triage_task`, `auxiliary.kanban_decomposer`); dependency scheduling
(`kanban_db.py` parents → `ready` promotion, `kanban_link`, `kanban.auto_promote_children`);
durable workers with crash recovery (`kanban_db_dispatch.py`: claim, stale reclaim, respawn
guard, circuit breaker, `protocol_violation`; `agent/kanban_stop.py` terminal-call nudge;
`agent/kanban_turn_recovery.py` in-place retry); goal loops with a judge
(`hermes_cli/goals.py` — Ralph loop, `auxiliary.goal_judge`, quality gates that run a shell
command before the judge, parking on a background process; `kanban_db.py` `goal_mode` /
`goal_max_turns` columns); scheduled starts (`kanban_schedule`, `scheduled_at`); PR
completion contracts (`completion_contract`, the `complete_task` boundary reading required
checks through `gh`).

**The fork has:** `flow_graph.py` (steering edges only — "Ingest never creates, starts, or
deletes an instance"); `tools/board_tool.py` cards ("ADVISORY … never starts tracked work");
`coordinator_permissions.py` ("advisory, never authorization"); `AutonomyLevel` whose
`APPLY_WITH_REVIEW` member is read by nothing but `snapshot/summaries.py` and
`config/persona_records.py`; the Work slice above; and two kanban hooks the eternia-harness
plugin registers (`on_kanban_dispatch_tick` → `hermes_cli/kanban_blocked_pm_tick.py`,
`on_kanban_worker_exited` → `kanban_crash_evidence.py`), both inert without a dispatcher.
`kanban_blocked_pm.py` routes blocked cards to `pm_assignee="pm"` by default — the one role
`persona_lifecycle.MOTHBALLED_ROLE_TOKENS` retires.

**Correction to the table.** "Adopting it requires reconciling the existing authorities" is
half done: the store authority was reconciled on 2026-09-30 (native kanban, no second task
store). What is unreconciled is (a) **who runs the loops** — no process the Launcher owns
ticks the dispatcher; (b) **tool exposure** — hygiene blocks every `kanban_*` verb on every
lane, so a persona cannot create, link or complete a card even when the Launcher's Work
viewer shows it one; (c) **the goal engine** — `runtime.work.start` carries neither
`goal_mode` nor `completion_contract`, and nothing on the lane reaches `/goal`.

**Recommendation.** Do not unblock the `kanban` toolset wholesale. First the owner picks
the loop host (one decision covers the dispatcher AND cron, see §3): a serve boot phase that
runs upstream's two tick functions under the serve's profile set, or the Launcher running
`hermes gateway` headless beside the serve. Then expose `kanban_create / kanban_link /
kanban_show / kanban_comment` to a NAMED orchestrator profile through its own `toolsets:`
(hygiene stays for everyone else — this needs the hygiene union to admit a declared
exemption, which it does not today). Then `runtime.work.start` grows `goal_mode`,
`goal_max_turns`, `completion_contract`; the Launcher's "Plan your task" acceptance criteria
are exactly the body the judge reads. Re-aim or delete the blocked-card PM router.

## 2. "Check your work before telling me it's done" — claim holds

**Upstream has:** the `/review` engine (`agent/review_engine.py::start_review` — an
independent reviewer on the async delegation rail, `auxiliary.review` model, result
re-enters the session as a delegation completion); board review (`kanban_request_review`,
`kanban_request_changes`, `kanban.review_dispatch` default `True` spawning the assignee
with the bundled `skills/sdlc-review`); completion contracts (§1); verify-on-stop
(`agent/verification_stop.py`, `agent/verification_evidence.py`, `agent.verify_on_stop`
default `False`; `auto` resolves ON for every non-messaging surface — a harness persona
turn qualifies); prompt-level discipline on by default (`task_completion_guidance`,
`execution_guidance: auto`, `intent_ack_continuation: auto`, `stall_guards`).

**The fork has:** a `review` column kind on the Mission Board
(`board_models.py::COLUMN_KINDS`) with advisory cards; no `runtime.*` method touching
review or goals (`agent_runtime/serve_rpc/` has none); no review affordance in the Launcher
console (grep `lib/features/agent_console`, `lib/features/mission_control`: none); the
completion drain that would carry a reviewer's verdict back into a busy turn already exists
(`dispatch_delivery/completions.py`, `_PROCESS_LIKE_EVENTS`).

**Recommendation.** A fork-owned `runtime.chat.review` method that calls
`review_engine.start_review` with the turn's agent and messages (additive — no upstream
edit; the engine is a plain function) and delivers the result through the existing drain;
a Review action on the console (launcher half). Decide `verify_on_stop` per persona profile
after measuring the nudge cost on five dev-persona turns — it is one config line. Make
`APPLY_WITH_REVIEW` the switch that requires the review before a Work card can complete, or
delete the member with a tombstone; today it is a label.

## 3. "Follow up without making me remind you" — claim holds, and it is the same decision as §1

**Upstream has:** the `cron/` package (scheduler, occurrences, delivery, incidents,
`cron.failure_repeat_alert_hours`, preflight); the `cronjob` toolset (`cronjob_manage`),
policy-denied inside cron runs unless `cron.allow_agent_scheduling`; `kanban_schedule`;
background completions (`delegate_task(background=True)`, `notify_on_complete`,
`watch_patterns`); goal parking on a background process.

**The fork has:** the continuation after background completions the table credits —
verified: `dispatch_delivery/completions.py` steers a finished background `terminal`, an
MCP job wake (`mcp_job_finished`) and a delegation completion into the persona's turn.
It has no cron: `cronjob` is not in `harness_core`, is in the bounded blocklist, no
scheduler runs in the serve (§0), and the drain knows no cron event type. The Launcher
already carries the display vocabulary (`mission_activity_chip_model.dart` names cron).

**Recommendation.** The loop-host decision from §1 is the prerequisite; a scheduler the
Launcher never runs cannot fire a reminder. After it: `cronjob` on supervisor profiles with
upstream's `allow_agent_scheduling` semantics kept, and a `cron_job_finished` event on the
drain so a job's output reaches the console the way a QA build's does.

## 4. Fast, affordable everyday interaction — not an upstream feature; already queued

Agreed with the table. The queue carries it: the `turn_context_ms` baseline row, the
cold-snapshot-sections row (`agents_readiness` 10.6 s, `prompt_observability` 7.3 s on a
process's first build), the `chat_lane_defer_tools` lane and the per-parameter-prose ruling.
No new row from this audit; one adjacent cost is named in §6.

## 5. Safe concurrent coding — claim holds; the flip is config, the landing verb is design

**Upstream has:** `delegation.worktree_isolation` (default `False`;
`tools/subagent_worktree.py`: one worktree per child under `<repo>/.worktrees/subagent-<id>`,
branch `hermes-subagent/<id>`, pruned only on proof); per-turn filesystem `checkpoints` with
`/rollback` (opt-in); per-card kanban workspaces (`HERMES_KANBAN_WORKSPACE`).

**The fork has:** the repo-slot overlay for commands a chat turn spawns
(`agent_runtime/workspace_slot_overlay.py`), `mission_chat_workdir.py`, and it already
knows the key (`bundle_profiles/manifest.py` maps `delegation.worktree_isolation` to
`tools/delegate_tool_config.py::_get_worktree_isolation`) — reading `False`. There is no
verb that lands a child's branch; the worktree discipline in `CLAUDE.md` binds humans and
orchestrators, not delegated children.

**Recommendation.** Set `worktree_isolation: true` in each dev persona's profile config (no
code), then design the landing verb — who merges `hermes-subagent/<id>`, and how a
`pruned only on proof` leftover is surfaced (the Launcher's sandbox-leak row shows the
class).

## 6. Context and memory — claim holds; the missing half is a read surface

**Upstream has:** the `memory` block (`memory_enabled`, `write_approval`,
`nudge_interval`, provider plugins); the post-turn self-improvement fork
(`agent/background_review.py`, `auxiliary.background_review.enabled` default `True`);
`coding_context: auto` (coding brief + git snapshot), `coding_instructions`,
`environment_hint`, `checkpoint_required`.

**The fork has:** `memory` in `harness_core`; `include_profile_memory=True` on every
profile-minted persona (`persona_profiles.py`); the assigned-repository context through the
slot overlay; the console's AGENTS-context and session-rules settings (launcher side). No
`runtime.memory.*` method exists, so the console cannot show what a persona remembers or
stage a `write_approval`. Whether `background_review` forks after every persona turn in the
serve is unmeasured — no fork file references it, so upstream's default (`True`) governs,
and it is a daemon thread replaying the conversation per turn (a §4 cost).

**Recommendation.** Measure `background_review` on persona turns (cost, and whether its
memory writes are the ones operators see); then a read-only `runtime.memory.read` method
and a `write_approval` posture per persona.

## 7. Small helpers — claim holds; the gap is a paragraph

`delegate_task` is a `harness_core` member (`delegation`) and unblocked on the shipped
posture; `delegation.max_spawn_depth` 1, `oneshot_max_children` 2,
`independent_completions False`. The fork's persistent-teammate lane is `agent_chat_send`;
its durable lane is a Work card. Upstream's own routing table ("Kanban vs. `delegate_task`",
`website/docs/user-guide/features/kanban.md`) is the guidance the table asks for; nothing on
the lane states it. The plugin already owns a prompt section
(`eternia-harness.tool-guidance`); the rule is one paragraph there, token cost measured the
way `h-prompt-brief` measured descriptions.

## Corrections and confirmations of the supplied table

| table says | measured |
|---|---|
| Eternia blocks the upstream Kanban toolset on persona lanes | True for the TOOLS (hygiene, every lane). The STORE is adopted: native kanban is the Work store since 2026-09-30. |
| its graph remains advisory | True: `flow_graph.py` steers, `board_tool.py` cards are advisory, `coordinator_permissions.py` is a self-declared budget. |
| Eternia already continues work after background completions | True: `dispatch_delivery/completions.py`. |
| Eternia enables memory for profile-derived personas | True: `include_profile_memory=True`, `memory` in `harness_core`. No read surface. |
| Both already have `delegate_task` | True on the shipped unbounded posture; on `bounded` it is blocked (`_BOUNDED_LANE_BLOCKED_TOOLS`). |
| helper isolation defaults to false in both trees | True: `_get_worktree_isolation` reads `False`; the fork maps the key and leaves it. |
| upstream's verification-on-stop is off by default | True: `verify_on_stop: False`; `auto` would be ON for persona turns. |
| not stated | Nothing the Launcher runs ticks the kanban dispatcher or the cron scheduler. This is the prerequisite for rows 1, 2 (board review) and 3. |

## Rows filed from this note

Ten rows under "Filed on arrival — 2026-10-12 (upstream capability audit)" in
`runtime-queue.md` § Fork-owned: the loop host (one decision, both loops); Work submit
without `goal_mode` / `completion_contract`; `APPLY_WITH_REVIEW` with no reader; no review
door; `verify_on_stop` measurement; `cronjob` absent and no cron event on the drain;
`worktree_isolation` flip plus the landing verb; helper routing guidance; the blocked-card
PM router aimed at a mothballed role; memory with no read surface and `background_review`
unmeasured. The launcher halves (a Review action, Work submit fields, memory view) are
named in their rows and filed in the launcher's `mission-control-queue.md` once the hermes
door each one waits on lands.
