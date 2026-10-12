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

Eleven rows under "Filed on arrival — 2026-10-12 (upstream capability audit)" in
`runtime-queue.md` § Fork-owned: the loop host (one decision, both loops); Work submit
without `goal_mode` / `completion_contract`; the hygiene union admitting no per-profile
`kanban_*` exemption; `APPLY_WITH_REVIEW` with no reader; no review door; `verify_on_stop` measurement; `cronjob` absent and no cron event on the drain;
`worktree_isolation` flip plus the landing verb; helper routing guidance; the blocked-card
PM router aimed at a mothballed role; memory with no read surface and `background_review`
unmeasured. The launcher halves (a Review action, Work submit fields, memory view) are
named in their rows and filed in the launcher's `mission-control-queue.md` once the hermes
door each one waits on lands.

## 8. Where we are today, the three loop-host options, and value against friction (owner ask, 2026-10-12)

**Today is none of the three options.** Companion is a separate repository, never part of
the Launcher; its headless Work engine (its own daemon and ledger, which did not care where
work started) was NOT imported by the 2026-09-30 ruling. Only its presentation was reused
(`eternia_workbench_ui`, from Companion `5629016153de`). What
replaced it is the STORE half of upstream kanban — `runtime.work.start` writes a `ready`
row into the native database — with no engine behind it, because the engine is a loop in
upstream's gateway process and the Launcher runs `hermes harness serve`. A card submitted
today stays `ready` forever. The persona chat lane is unaffected: a chat turn runs at once,
and its background helpers and terminal jobs complete back into the chat, which is headless
work in Companion's sense, but per turn and not durable.

| | engine code | where it runs | second authority? | what the operator sees |
|---|---|---|---|---|
| Companion (separate repo, engine not imported) | Companion's own | Companion's daemon | yes (its own ledger) | Work rows, in Companion |
| today | none | nowhere | no | Work rows that never move |
| option 1 (recommended) | upstream's dispatcher, unchanged | inside `hermes harness serve`, scoped to Launcher-owned boards/profiles | no | the same Work rows, moving; workers visible in running-work |
| option 2 | upstream's dispatcher, unchanged | a separate `hermes kanban dispatch` process the Launcher supervises | no | rows move; workers invisible to running-work (other process) |
| option 3 ("our own kanban") | fork-written scheduler | anywhere | yes — the thing the ruling forbids | rows move; two systems disagree about what is running |

Option 1 is the closest in SHAPE to Companion: a headless loop that pulls from one shared
table regardless of how the row got there (the Work form, a chat, a later agent verb), and
nobody has to look at a board. The board is the table, not a surface.

### Value and friction, the very-high and high rows

Three audiences: **everyday** (talks to a persona, never opens settings), **developer**
(bound repo slot, edits code with the persona), **power user** (several personas, several
repos, runs Hermes from a terminal too).

**Loop host (option 1).** Value: Work becomes real — a card from any surface runs without
the operator doing anything, survives a Launcher restart (the store is durable, the loop
restarts with the runtime), and its worker shows in running-work as live. Friction:
everyday — nothing to configure; the only visible change is that cards move. Developer —
the loop claims only Launcher-owned boards or `kanban.dispatch_profiles`, so a developer
who also runs upstream's gateway in a terminal for their own boards gets no double
dispatch. Power user — may keep a separate dispatcher for other boards; the scope keeps
them apart; `kanban.max_in_progress` caps worker spend. Design item it must respect: the
build-behind restart fence (RL-20) drains workers before the serve recycles.

**Work submit carries `goal_mode` / `goal_max_turns` / `completion_contract`.** Value: the
"Plan your task" acceptance criteria become judged criteria; a card keeps iterating until
the judge agrees or parks it `blocked` for a human; a quality gate makes "done" mechanical
for a code card. Friction: everyday — optional; a plain brief stays one-shot and the form
already exists. Developer — the gate is their own test command; judge cost is paid only on
goal-mode cards. Power user — turn budget and PR contract exposed per card.

**Review door.** Value: an independent second model reads the diff, runs the tests, and
posts its verdict back into the same chat; no board involved; one button. Friction:
everyday — a button they can ignore; the result is a message. Developer — costs one
delegated subagent per press; `auxiliary.review` pins a different model. Power user — a
stronger or cheaper reviewer per profile; later, the same engine behind the Work review
lane.

**Worktree isolation for delegated children.** Mechanism
(`tools/subagent_worktree.py`): with `delegation.worktree_isolation: true`, each
`delegate_task` child that starts inside a git repo gets its own worktree at
`<repo>/.worktrees/subagent-<id>` on branch `hermes-subagent/<id>`; the persona's OWN
foreground edits stay in the bound slot as today; outside a git repo nothing changes;
docker/ssh backends skip it. On exit a worktree with zero commits and a clean tree is
pruned; anything else is kept and reported. Value: parallel helpers stop overwriting each
other and the operator's tree; a helper's result is a branch that can be reviewed before
it lands. Friction: everyday — invisible; their persona rarely delegates into a repo, and
when it does the only trace is a `.worktrees/` folder, which must be gitignored and
surfaced. Developer — their own flow is unchanged (the parent edits in place); what is new
is a branch per helper, and today nothing merges it, so the developer or the parent
persona must `git merge` or discard it. That is the landing-verb row: until it lands, the
dev persona's prompt should say "merge or report the branch", and the delegation
completion should name the branch and its diff stat. Power user — this is who it is for:
N children on one repo without stomping; disk is one checkout per child (shared `.git`);
`.worktrees/` under the repo needs the gitignore.

**Cron on supervisor profiles plus a console route.** Value: "remind me", "check the
build every morning", "follow up on that PR Friday" become jobs the persona owns, delivered
into the same chat. Friction: everyday — they ask in plain language; the delivery arrives
as a message; upstream's `cron.allow_agent_scheduling` default keeps a job from scheduling
jobs. Developer — a job runs under the persona's profile and model; the incident dedupe
(one alert per failure signature, then silence for `failure_repeat_alert_hours`) stops a
broken job from spamming. Power user — jobs listed and managed per profile; `cron.model`
decouples the fleet's model from chat; `max_parallel_jobs` bounds spend.

### Owner principle, 2026-10-12: complexity under the hood, simplicity on the surface

"Everyday" above is wider than "not a developer": it is the non-technical business user,
the lifestyle user, the streamer, the gamer — everyone for whom a control they do not need
is complexity, noise and friction. For them every row in this note is a BEHAVIOUR of their
persona, never a control. The rule each row must satisfy before it lands:

| row | what the everyday user sees | what they never see |
|---|---|---|
| loop host | "I'm on it", then a result in the chat, even after a restart | a board, a column, a worker, a dispatcher setting |
| goal fields on Work submit | the persona keeps going until the thing is done, or says plainly why it cannot | goal mode, judge turns, completion contract — these fields show only on developer and power personas (launcher half) |
| review door | the persona double-checks before saying done, when its profile says it should | a Review button; review-on-done is persona-profile policy, surfaced as a control only on dev/power personas |
| worktree isolation | nothing — no repository, no surface | `.worktrees/`, branches |
| cron | "I'll check back Friday", then the check-back as a message; a failing job stays quiet unless it matters | a jobs list, a schedule editor, an incident log |

Capability is admitted by the persona's PROFILE (`toolsets:`, review policy, scheduling
allowed); controls are rendered by the Launcher only for the developer and power-user
persona kinds. The Launcher's standing "no fake buttons" rule already holds the other half:
a control that exists must do something, and a control that would only do something for a
developer does not appear for anyone else.

**Roles are scenarios, not users (owner, 2026-10-12).** The same person is an everyday
user in one chat and a developer in the next; onboarding has zero friction and the runtime
transition between modes is a scenario change, not an account change. So "dev/power
persona kinds" above means the MODE a surface is in, decided per persona profile and per
scenario, never a label on the user. Agents can do all of it; the surface shows the part
the scenario needs.
The canonical everyday case is not a lesser developer: it is a person who just chats
and wants a small task done, or runs a small business in a loop — a recurring check, a
follow-up, a thing that takes longer than one reply. That case is served entirely by the
engine, cron and the persona-side submit verb, with no control on the surface at all.

**Work is already multi-surface, and the engine is not.** The Launcher mounts one Work
lane (`eternia_work_experience` ports, `eternia_workbench_ui` presentation,
`lib/app/work` composition) on the Agent Console chat frame, the operator conversation
panel and the Intelligence conversation panel; there is no second lane and no second
engine. Through chat, voice or any route, a persona itself cannot yet put work in the
store (every `kanban_*` verb is hygiene-blocked); the persona-side submit verb row is
re-ranked HIGH for that reason, with a fork `work_submit` tool over the existing Work
service preferred to a kanban exemption.

**Option 1, mechanically.** A fork-owned serve boot phase (beside the socket and peer
listener phases in `hermes_cli/harness_parts/serve/boot_phases.py`), on by a runtime
config switch, runs two upstream functions on their own intervals: the kanban tick
(`hermes_cli/kanban_db_dispatch.py::dispatch_once`, the same function the gateway embeds
in `gateway/kanban_watchers.py`, under upstream's own single-dispatcher lock and
`kanban.dispatch_profiles` allowlist, set to the Launcher's persona profiles) and the cron
ticker (`cron/scheduler.py::InProcessCronScheduler.start`, the call `gateway/run.py`
makes). Workers are upstream's worker processes; the fork's two kanban hooks start firing
because the tick fires them; the serve's drain and build-behind restart hand running
workers off before recycling; `running_work` gains a kanban-worker lane with a durable
view (the board's `running` rows) like the terminal and delegation lanes. No upstream file
changes. The 2026-09-30 ruling is fulfilled, not revisited: native kanban still owns
tasks, dispatch and execution; the only thing superseded is the Work slice's own scope
note ("does not auto-start it"), whose stated worry the profile allowlist answers.

### The mobile constraint (owner ask, 2026-10-12)

The kanban engine spawns one OS process per worker (`hermes_cli/kanban_db_dispatch.py`,
`_default_spawn`). Cron does not: the ticker is a daemon thread (`cron/scheduler_thread.py`)
and jobs run in a thread pool in the same process. The phone bundle
(`agent_runtime/bundle_profiles/bundled-phone.yaml`) already excludes both — `kanban` and
`cronjob` dropped, no background ticker, `delegate_task` a placeholder, no subprocess
workers — and phone bundles omit the Work adapter. So option 1's boot phase is bundle-gated
and OFF on phone; the phone stays a client of a paired host over the multi-device lane
(canon 09; the Launcher's `WorkDestination.remoteInstallation`). The engine and cron run
where a process can live: desktop, home box, or a hosted runtime.

Open product question, not answered by option 1: a mobile-only user with no host has no
engine, so the small-business-in-a-loop case needs a hosted runtime for them. Option 1 is
the same code on that server when it exists.
