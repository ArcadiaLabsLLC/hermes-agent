# Planned — The batch dispatcher and its three libraries: SOURCE, EXECUTOR, SCHEDULER (q/dispatch-design, 2026-10-18)

**Owner domain:** transport and wire ([03-transport-and-wire.md](../03-transport-and-wire.md) § Native
Work methods), the chat lane ([05](../05-chat-lane.md)), the office and board
([06-office-and-board.md](../06-office-and-board.md)), multi-device ([09](../09-multi-device-runtime.md)).
**Builds on:** [work-on-markdown-2026-10-18.md](work-on-markdown-2026-10-18.md) (W1–W5; the board, the
writer, the engine). **Status:** scoped, nothing built. One doc, no code.
**Measured / read:** 2026-10-18 against hermes `origin/main` d518fa0963, the chat-wake branch
`origin/ccr-cc6cbc42-w6ahvk` (`598bedea`), and `EterniaLauncher` `origin/main` (read with `git show` /
`git grep`, never checked out).

## 0. Rulings this plan is bound by

- `RULED 2026-10-18: owner — own batch dispatcher, manual by default (the operator starts a batch;
  automation is opt-in later); upstream engines only behind persona-keyed doors` (`RT-WORK-BATCH-DEPLOY`).
- `RULED 2026-10-18: owner — compatible with the Launcher's scheduler and upstream's; scrap the upstream
  cron integration if it is not worth it` (`RT-SCHEDULING-ONE-MODEL`).
- `RT-D1` refuse script-only cron jobs; `RT-D3` a cron wake reaching a busy persona chat is held until idle,
  never steered; `RT-D5` `cron.max_parallel_jobs` default 4, `0` = unlimited, over-cap jobs queue with a
  receipt; `RT-D6` land `598bedea` with D1/D3/D5 built in — each `BLOCKED` on this plan's verdict (§3).
- `RT-GOAL-ENGINE-DOOR`: build `runtime.chat.goal.*` over `GoalManager` once Work carries `goal_mode`.
- W1–W5 rulings (`work-on-markdown` §0, §8): Work = the workspace's todo board, worked by persona instances,
  written by hermes's own worktree with replay-by-ID; done = row deleted; claim-only first; engine the only
  agent-side writer first.
- The playbook (`EterniaLauncher/docs/tooling/SUBAGENT_DEPLOYMENT_PLAYBOOK_2026-09-21.md`, restated in
  `Harness_Brain/50 — Agent Handoffs/Dispatching a lane.md`): thick lanes by domain, one landing per batch,
  light ≤ 6 / heavy 1, quiet-box lanes only on an idle box, lanes report tool-call counts, briefs ≤ 40 lines.

## 1. What is true today (file::symbol)

**The Work engine W3 (designed, not built).** `agent_runtime/work_store/engine.py` — the tick: READY rows
with a persona assignee → `TAKEN … persona:<instance_id>` → hand-off as that instance's chat turn → write
back by ID; cap `agent_runtime/models.py::Workspace.max_concurrent_lanes` (exists, `int | None`); "built
behind an executor interface so batch lanes and upstream engines plug in later" (`RT-WORK-W3-ENGINE`). The
writer is `work_store/writer.py` (W2, §5 of the Work plan): fetch → reset the hermes worktree → op by ID
with tip-checked typed refusals (`row_gone`, `already_taken`, `not_claimant`, `id_exists`,
`push_contended`) → one commit → fast-forward push → replay. Today's `agent_runtime/work/model.py::Reason`
has six values (`INVALID, OWNER_CHANGED, UNAVAILABLE, CONFLICT, DENIED, UNKNOWN`) and `rpc.py::register`
mounts `runtime.work.<op>` at `TIER_CONSOLE`.

**The persona instance.** `agent_runtime/models.py::PersonaInstance {id, persona_id, role, display_name,
profile_id, runtime_root, state: WorkerSessionState, mode, goal_id, realm_id, workspace_id, spawned_by,
steered_by, …}`; `Persona.hermes_profile` / `OfficeActor.backing_profile` name the upstream profile that
BACKS it. An instance's chat has one root session; sends to a root serialise through
`agent_runtime/chat_root_send_queue.py::enqueue` and run through
`chat_root_send_runner.py::QueuedSendRunner.dispatch_once` (`_root_is_idle` is the gate). A turn forged by
the runtime goes through `agent_runtime/mission_chat_door.py::run_mission_chat_turn` — the door the
delivery drain uses (`dispatch_delivery/forge.py::forge_delivery_turn`, `drain.py::DispatchDrain.own →
probe → claim → forge_turn → settle`, with `forge.py::DrainPolicy.sender_is_idle` the hold-until-idle
seam). Receipts go through `agent_runtime/receipt_sink.py::ReceiptSink.receipt`.

**Upstream cron.** `cron/scheduler_provider.py::CronScheduler` (ABC: `name`, `start(stop_event, adapters,
loop, interval)`, optional `on_jobs_changed`, `register_job`, `recover_interrupted`) and
`::InProcessCronScheduler.start(…, can_dispatch, profile_homes, …)` — a 60 s ticker multiplexed over
PROFILE HOMES; `cron/scheduler.py` (4,300+ lines: `_CronJobConfig`, `_CronRunScope`, `_FireOwnership`,
`_RunDelivery`, in-flight guards, incidents) runs each job as its own agent session and delivers through
messaging adapters; `cron/jobs.py::use_cron_store(home)` keys the store per profile home,
`parse_schedule` → `{"kind": "once"|"interval"|"cron", run_at|minutes|expr}`, `claim_job_for_fire`,
`mark_job_run`; `cron.max_parallel_jobs` is a per-profile key (`scheduler.py::_get_parallel_pool`).
`tools/cronjob_tools.py::_action_create` requires `schedule`; `no_agent=True` makes the script the job.
`hermes_cli/cron.py` is the CLI (`cron_list/status/doctor/create/edit`). On `origin/main` NOTHING of this
runs in `harness serve` (no `agent_runtime/cron*`); `cronjob` is withheld. The chat-wake lane `598bedea`
(branch only) adds `agent_runtime/cron_lane.py::boot_serve_cron_lane` (upstream's ticker in the serve,
switch `cron.serve_ticker`, `can_dispatch = drain not begun`) and `agent_runtime/cron_wake.py` (a
`cron_job_finished` event the drain STEERS into the creating persona's turn — the D3 defect), puts
`cronjob` in `harness_core` (45 → 46 tools) and edits `tools/process_registry_notifications.py` (one seam).
ADR 0015 lists cron as unused: "cron when the launcher-clock cron lands" is the planned exit.

**Upstream delegation.** `tools/delegate_tool.py::delegate_task(goal|tasks, background, …, parent_agent)`
— requires a parent agent, depth-capped (`delegation.max_spawn_depth`), children built by
`_build_child_agent` in-process; `background=True` re-enters the parent's turn through
`dispatch_delivery/completions.py` (already a fork door). It is a TOOL inside a turn, never a dispatcher.

**Upstream goal engine.** `hermes_cli/goals.py::GoalManager(session_id)` — `set(goal, max_turns, contract)`,
`pause/resume/clear/mark_done`, subgoals, `add_gate(command)` + `_check_gates`, `wait_on(pid)` /
`wait_on_session` / `wait_for_seconds` (parking), `evaluate_after_turn` (the judge) and
`next_continuation_prompt`; persisted in SessionDB (`save_goal`). Reachable only as `/goal` in CLI/TUI/
gateway; the runtime holds none (`RT-GOAL-ENGINE-DOOR`; proposal §6).

**Upstream kanban dispatcher.** `gateway/kanban_watchers.py::GatewayKanbanWatchersMixin` →
`kanban_watchers_dispatcher.py::_KanbanDispatcher.tick_once_for_board` (one board at a time, a card store
`hermes_cli/kanban_db.py`, one worker SUBPROCESS per card: `kanban_db_dispatch.py::heartbeat_worker`,
`reap_terminal_workers`, `enforce_max_runtime`, `detect_stale_running`, pid fingerprints), profile-keyed
(`_default_profile_secret_scope`), `auto_decompose_tick`. Lives in `gateway/run.py`, which the Launcher
never runs. `kanban.db` holds 0 tasks.

**The Launcher's own scheduler.** There is NO job scheduler in the Launcher. What it has, each one
owner: (a) `lib/app/lifecycle/after_reply_scheduler.dart::AfterReplyScheduler.arm(kind,
unresolvedTurns, action)` — fire once the runtime's own unresolved-turn count reads zero on two
consecutive 1 s ticks, give up after 15 min, a second arm of a kind JOINS the first (owner ruling
2026-10-15: "schedule the restart for as soon as the current reply ends"); (b)
`packages/eternia_reminders_core/lib/src/reminder_coordinator.dart::ReminderCoordinator.rebuild(desired,
quietHours)` over the port `ports.dart::OsReminderScheduler {schedule, cancel, cancelAll, pending}` — a
DESIRED-SET reconcile with deterministic OS ids (`deterministic_os_id.dart`), a platform cap
(`bounded_schedule.dart`), quiet hours (`quiet_hours_resolver.dart`); the Launcher adapter is
`lib/features/calendar/services/reminders/launcher_os_reminder_scheduler.dart::LauncherOsReminderScheduler`
(`flutter_local_notifications`); (c) `lib/features/calendar/services/calendar_briefing_refresh_schedule.dart
::PeriodicCalendarBriefingRefreshSchedule.ticks` — a periodic tick STREAM as a port, dormant by default;
(d) `lib/features/account/tabs/settings/notifications/notification_schedule.dart::
NotificationScheduleController` — the account's quiet hours, "the ONLY do-not-disturb authority". The
Launcher already DISPLAYS runtime schedules: `harness_snapshot_running_work.dart::HarnessRunningWorkKind
.cronJob` (wire `cron_job`), and an unknown kind "still renders … with the raw wire word".

## 2. The three libraries — typed contracts

All three live in `agent_runtime/work_store/` (fork-owned, `__layer__ = "lanes"`), each a `Protocol` with
ONE production implementation per stage and a fake for tests. Refusals are one `StrEnum`
(`work_store/reasons.py::Reason`, superseding `work/model.py::Reason`, old values kept); every method
returns a value or raises `WorkRefused(reason)`; every state change emits ONE receipt dict through the
serve's `ReceiptSink` (`kind` below), never a frame key.

### 2.1 SOURCE — rows from the todo boards

```python
class WorkSource(Protocol):                                   # work_store/source.py
    def boards(self, workspace_id: str) -> list[Board]          # one per live slot (+ default brain), W1 board.py
    def rows(self, workspace_id: str, *, status: Status | None = None,
             slot: str | None = None, assignee: str | None = None) -> list[Row]   # read at the TIP
    def ready(self, workspace_id: str) -> list[Row]             # rows(status=READY) minus TAKEN
    def claim(self, ref: RowRef, who: Claimant, request_id: str) -> Receipt        # TAKEN <date> persona:<id>
    def release(self, ref: RowRef, who: Claimant, status: Status, reason: str) -> Receipt
    def block(self, ref: RowRef, who: Claimant, question: str, recommend: str) -> Receipt
    def done(self, ref: RowRef, who: Claimant, result: str) -> Receipt           # delete; result in commit body
    def append(self, board: Board, row: Row, request_id: str) -> Receipt
```

`Row {ref: RowRef(slot, note, id), title, segments, status, assignee, taken_by, domain: Domain(slot, note,
heading), pointers}`; `Domain` is the batching key (§3.1). Backed by W1 `board.py` + `grammar.py` (reads)
and W2 `writer.py` (every write, by ID, replay on a lost race). Refusals: `row_gone`, `already_taken`,
`not_claimant`, `id_exists`, `push_contended`, `slot_unbound` (this machine lacks the checkout),
`grammar_invalid`. Receipts: `work.row_claim | row_release | row_block | row_done | row_append`
(`{ref, who, request_id, commit}`). Nothing is cached across calls except the fetch.

### 2.2 EXECUTOR — who runs a claimed row

```python
class Executor(Protocol):                                     # work_store/executor.py
    kind: ExecutorKind                                         # PERSONA_TURN | BATCH_LANE
    def can_start(self, a: Assignment) -> Reason | None        # cheap, no side effects
    def start(self, a: Assignment) -> Run                      # exactly one Run per request_id
    def status(self, run_id: str) -> RunStatus                 # QUEUED | RUNNING | SETTLED | STOPPED
    def stop(self, run_id: str, reason: StopReason) -> Receipt
    def on_settle(self, cb: Callable[[Run, Outcome], None]) -> None
```

`Assignment {rows: list[RowRef], persona_instance_id, brief: Brief, request_id, heavy: bool,
goal_mode: GoalMode}`; `Outcome {verdict: DONE | BLOCKED | STOPPED | FAILED, per_row: dict[RowRef,
RowEnding], report: str, tool_calls: int | None, commits: list[str]}`.

- **`PersonaTurnExecutor` (B3 = W3's engine behind this contract).** `start` = `chat_root_send_queue.enqueue`
  on the instance's root with the brief as the message and `origin={"work": request_id}`; the runner's
  `_root_is_idle` gate is the hold-until-idle rule for free; the turn runs through
  `mission_chat_door.run_mission_chat_turn` exactly as `forge_delivery_turn` does; `settle` fires when the
  queued send settles (`chat_root_send_runner._settle`), reading the ending from the turn's structured
  tail (`work_report` block the brief asks for) — unparsable → `Outcome.FAILED`, rows released `NEEDS PLAN`.
  With `goal_mode=UNTIL_DONE` it sets `GoalManager(root_session).set(brief.objective, contract=
  acceptance)` first and the serve's after-turn hook (§5 B3) forges continuations through the same door.
- **`BatchLaneExecutor` (B5).** The playbook's lane: a worktree `X:/Eternia/worktrees/hermes-<lane>` cut
  via `agent_runtime/git_cmd.py::run_git` from `origin/main` (or the dependency lane's branch), a brief
  FILE written from the template in `Dispatching a lane.md` § The brief skeleton (≤ 40 lines, the one
  page named), then a `PersonaTurnExecutor` turn whose `cwd` is the worktree
  (`mission_chat_workdir.py::mission_chat_workdir_for_persona` gains a per-run override). Landing is a
  lane of the same kind with the landing brief; the push to `main` is behind `approve` (§3.3).
- Refusals: `executor_busy` (root has a running or queued turn and `heavy`), `persona_unavailable`
  (instance not `WorkerSessionState` idle/ready on THIS machine), `cap_reached`, `drain_begun`
  (`session.drain_state is not None`), `door_unbound` (`MissionChatDoorUnbound`), `worktree_failed`.
- Receipts: `work.exec_start | exec_settle | exec_stop` (`{run_id, request_id, persona_instance_id,
  rows, kind, verdict, tool_calls, elapsed_s}`).

### 2.3 SCHEDULER — when something fires

```python
class Trigger:  kind: MANUAL | AT(utc) | EVERY(minutes) | CRON(expr, tz) | WHEN_IDLE(root, settle_ticks=2)
class Scheduler(Protocol):                                    # work_store/scheduler.py
    def arm(self, key: str, trigger: Trigger, action: Action) -> Armed      # idempotent by key (joins)
    def disarm(self, key: str) -> bool
    def due(self, now: datetime) -> list[Fire]                 # pure; what would fire
    def tick(self, now: datetime) -> list[Receipt]            # fires due, advances next_fire, persists
    def armed(self) -> list[Armed]
```

`Action = StartBatch(workspace_id, plan_id) | RunAssignment(Assignment) | PersonaPrompt(persona_instance_id,
prompt)`. `Armed {key, trigger, action, next_fire, last_fire, enabled, owner_machine}`.

- **`ManualScheduler` (B1, the default).** `tick` is a no-op; the only fire is `runtime.batch.start`. This is
  "manual by default".
- **`ServeTickScheduler` (B4).** One 60 s tick on the serve's own supervised thread (the shape of
  `cron/scheduler_thread.py::SupervisedTickerThread`, re-implemented in ~60 lines; stopped by
  `liveness_stop`; `can_dispatch = drain not begun`). Armed items persist in `store/schedules/<key>.json`
  (realm-synced key-wise like `workspace_slots`), one file per key, `next_fire` written on every advance.
  `CRON` parses with `croniter` when installed, else refuses `schedule_invalid` (upstream's own rule,
  `cron/jobs.py::_ensure_croniter`). `WHEN_IDLE` is the Launcher's `AfterReplyScheduler` rule verbatim:
  the root's unresolved-turn count reads zero on two consecutive ticks, give up after 15 min
  (`schedule_abandoned` receipt). A fire that lands on a busy root is QUEUED behind the root's send queue,
  never steered (D3 by construction). Caps: `scheduler.max_parallel` default 4, `0` = unlimited; over-cap
  fires queue and the receipt logs `waited_s` (D5 by construction). An `Action` is never a script
  (D1 by construction). Quiet hours do NOT apply to work (they are the Launcher's notification authority,
  §4).
- Refusals: `schedule_invalid`, `automation_off` (the workspace's `batch_automation` is `off` and the
  action is `StartBatch`), `cap_reached`, `drain_begun`, `not_owner_machine`.
- Receipts: `schedule.arm | disarm | fire | queued | abandoned` (`{key, trigger, next_fire, action,
  waited_s}`).

## 3. The dispatcher

`agent_runtime/batch/` (fork-owned): `planner.py` (§3.1), `machine.py` (§3.2, a table), `manifest.py`
(§3.4), `rpc.py` (`runtime.batch.*`, `TIER_CONSOLE`, registered like `work/rpc.py::register`). It holds no
state of its own: a batch IS its manifest note plus the rows' claim marks; the in-memory object is a cache
rebuilt from those on boot.

### 3.1 Batching policy — thick lanes by domain

Input: `WorkSource.ready(workspace_id)`. Policy (`planner.py::plan`), deterministic, pure:

1. Group by `Domain(slot, note, heading)` — the queue heading says what a lane may edit
  (`CLAUDE.md` § Brain-routing rules). One lane per domain; never one lane per row.
2. A domain over `plan.max_rows_per_lane` (default 65, the playbook's measured ceiling) splits by the
  first pointer's top-level directory ("code lanes split by area").
3. A row whose pointer file is also named by another domain's row is SEQUENCED: the later lane is cut from
  the earlier lane's branch (`lane.after = <lane>`), never run beside it (playbook § 6).
4. Each lane takes the persona of its rows' `assignee` (all equal, else `plan_refused:mixed_assignees`);
  rows without one take the workspace roster's instance whose `role` matches the slot's `context.role`,
  else the plan asks (`lane.persona = None` → `start` refuses `persona_unresolved`).
5. `heavy` = any row whose segments name a release merge, a daily branch or a suite run; a plan has at
  most one heavy lane running at a time and never beside the landing lane.
6. The plan ends with ONE landing lane (`kind=LANDING`, `after = every lane`), the playbook's § 5 brief.

Output `Plan {id: BATCH-<6 base32>, workspace_id, lanes: list[Lane{id, domain, rows, persona, heavy,
after, brief}], landing: Lane, budget: Budget}`. `runtime.batch.plan` returns it and writes nothing.

### 3.2 The batch → lane → landing state machine

| state | who moves it | on | writes (where) | receipt |
|---|---|---|---|---|
| `PLANNED` | `runtime.batch.plan` | operator asks | nothing | `batch.planned` |
| `STARTED` | `runtime.batch.start` (manual) or `ServeTickScheduler` with `batch_automation=start` | operator / fire | manifest note appended (§3.4); every lane's rows `claim`ed in one replayed op per row | `batch.started` |
| lane `CLAIMED` | `start` | rows TAKEN | rows: `**TAKEN <date> persona:<instance_id>**` | `work.row_claim` |
| lane `RUNNING` | `Executor.start` when `can_start` is `None` and budget allows (§3.3) | slot free, `after` lanes `REPORTED` | manifest: lane line `RUNNING <run_id>` | `work.exec_start` |
| lane `REPORTED` | `Executor.on_settle` with `DONE`/`BLOCKED` | turn settles | rows: `done` (delete) / `block` / `release` per `Outcome.per_row`; manifest: lane line + tool-call count | `work.exec_settle` |
| lane `STOPPED` | `runtime.batch.stop` or `Outcome.STOPPED/FAILED` | operator / failure | rows released `DEFERRED <date>: stopped — <reason>` or `NEEDS PLAN`; claim removed | `work.exec_stop` |
| `READY_TO_LAND` | machine | every lane `REPORTED` or `STOPPED`, ≥ 1 commit | manifest | `batch.ready_to_land` |
| `LANDING` | `runtime.batch.land` → landing lane | operator (manual) | the landing lane's worktree `land/<batch>`; merges `--no-ff` in order; affected tests only | `work.exec_start` |
| `AWAITING_APPROVAL` | landing lane reports green | lane settles | manifest: gate result, red triage | `batch.awaiting_approval` |
| `LANDED` | `runtime.batch.approve` → push `HEAD:main` fast-forward | operator | manifest: landing SHA; rows of the batch already deleted by the lanes travel in the merge | `batch.landed` |
| `ABORTED` | `runtime.batch.stop --all` or approve refused | operator | every claim released with `DEFERRED`; worktrees kept (never removed while a lane could resume) | `batch.aborted` |

Transitions not in the table are refusals (`state_transition_invalid`). A second `start` of a batch whose
manifest exists is a replay (idempotent by `BATCH-<id>`), not a second batch.

### 3.3 Manual points, budgets, the one-landing rule

- **Manual points (default):** `plan` (free), `start`, `stop <lane|--all>`, `land`, `approve`. Automation is
  a per-workspace setting `batch_automation: off | plan | start` (default `off`): `plan` lets the
  scheduler produce plans the operator starts; `start` lets a fire start them. `land` and `approve` are
  NEVER automated in this plan (the push to `main` is the owner's).
- **Budget** (`Budget {max_lanes: Workspace.max_concurrent_lanes or 4, heavy_at_once: 1, light_at_once: 6,
  quiet_box: bool}`): a lane starts only when `running < max_lanes`, a heavy lane only when no heavy
  lane and no landing runs; a `quiet_box` lane (its rows judge a timeout or a flake) only when
  `BoxLoad.probe()` (CPU < 50 %, python processes < 20 — the two numbers `Dispatching a lane.md` § 2 names)
  says idle, else it waits with a `batch.waiting_box` receipt. Executors run ≤ 4 test workers
  (`scripts/run_tests.sh -j 4`) while other lanes live — stated in the brief template, not re-checked.
- **One landing per batch.** A batch has exactly one landing lane; a lane that reports after `LANDING`
  began joins the NEXT batch (its rows stay TAKEN by it until it reports). Two batches never land at once
  (`landing_in_progress` refusal across workspaces on one machine).
- **Stop semantics.** `stop <lane>` on `CLAIMED` releases at once; on `RUNNING` it asks the executor to
  stop (`QueuedSendRunner` cannot interrupt a turn: the stop takes effect at the turn's end, the lane
  ends `STOPPED`, its commits stay on its branch).

### 3.4 What is persisted where — nothing hidden

| thing | where | written by |
|---|---|---|
| claims, statuses, done | the todo rows (`<Brain>/20 — Active Initiatives/*.md`) | the W2 writer, one op per commit |
| the batch (plan, lane → persona, lane lines, landing SHA, tool-call counts) | `<brain>/50 — Agent Handoffs/batches/<BATCH-id>.md`, frontmatter `type: batch`, one line per lane per state; the brain is the workspace's default brain, or the slot brain of the first domain | the W2 writer (`append` op on a note, same replay) |
| lane briefs | `<brain>/50 — Agent Handoffs/batches/<BATCH-id>/<lane>.md` | the planner, through the writer |
| armed schedules | `store/schedules/<key>.json` | `ServeTickScheduler` |
| receipts | the serve log | `ReceiptSink` |
| lane code | its branch `q/<batch>/<lane>`, pushed per commit | the persona's turn |

No SQLite, no in-memory truth; a serve restart rebuilds every batch from the manifests and the rows'
`TAKEN` marks (a `TAKEN` with no manifest lane is a session's claim and is left alone).

### 3.5 Multi-device

A batch is OWNED by the machine whose serve started it (`manifest.owner_machine = machine_id`); only
that machine's executors run its lanes (an instance runs on one `runtime_root`). Every other machine
reads the same manifest and rows from the tip (`runtime.batch.status` is a read of the board) and may
`stop` (a release is a row op any machine's writer can replay) but not `start` lanes or `land`
(`not_owner_machine`). Claims across machines are the W2 race: exactly one `TAKEN`. The phone bundle
has no git and no executors: its Batches surface is read-only plus `start/stop/approve` sent to a desktop
runtime over the manifest's method lane, the way the Work page already aims a remote install.

## 4. Scheduling — one model, and the upstream cron verdict

**One model.** A schedule is `(key, Trigger, Action)` in hermes (§2.3). The vocabulary `AT | EVERY | CRON`
is upstream's `parse_schedule` kinds `once | interval | cron` one-to-one, so an upstream job converts
losslessly (`Trigger.from_cron_job(job)`); `WHEN_IDLE` is the Launcher's `AfterReplyScheduler` rule;
`MANUAL` is the default. Who owns what:

| schedule of | owner | surface |
|---|---|---|
| work (a batch, a row, a persona prompt) | hermes `ServeTickScheduler`, `store/schedules/` | `runtime.schedule.arm|disarm|list`; Launcher renders fires as `running_work` rows (kind `scheduled_turn`; unknown kinds already render) |
| a device notification about work ("tell me when the batch lands") | the Launcher's Reminder Core: `ReminderCoordinator.rebuild(desired)` with a `PlannedReminder` per armed hermes schedule the user opted into; quiet hours apply HERE and only here | Settings → Notifications (existing) |
| a restart after the current reply | the Launcher's `AfterReplyScheduler` (unchanged) | none |

Compatibility is by shape, not by code: hermes never imports `eternia_reminders_core`'s logic and the
Launcher never arms a hermes schedule except through `runtime.schedule.arm`.

**Upstream cron: KEEP or SCRAP.**

| | KEEP (land `598bedea` + D1/D3/D5/D6) | SCRAP (the fork's `ServeTickScheduler`, §2.3) |
|---|---|---|
| code in the boot path | `cron/` (40 modules, `scheduler.py` 4,300+ lines) + `agent_runtime/cron_lane.py` + `cron_wake.py`; `cronjob` in `harness_core` (46 tools) | `work_store/scheduler.py` (~250 lines) + `store/schedules/` + one fork tool `schedule_manage` (~120 lines) |
| keying | profile homes (`use_cron_store(home)`, multiplexed) → a persona→profile translation at every door | persona instance ids, native |
| D1 | a `pre_tool_call` refusal of `no_agent/script/monitor_script` (one plugin arm + test) | moot: an `Action` is never a script |
| D3 | change `dispatch_delivery/completions.py::_PROCESS_LIKE_EVENTS` so `cron_job_finished` is HELD, a second drain policy | moot: a fire is a queued send on the root |
| D5 | a serve default for `cron.max_parallel_jobs` per profile + a queue receipt inside upstream's `_get_parallel_pool` (an upstream edit or a wrapper) | `scheduler.max_parallel` default 4, `0` unlimited, `waited_s` on the receipt |
| D6 | `transform_tool_result` replacing `tools/cronjob_job_args.py::_local_delivery_notice` | moot: the output is the persona's own turn |
| run shape | a cron SESSION per run, its own agent, delivery adapters we do not run, incidents, in-flight guards | one persona turn in the persona's chat (the drain already does this for dispatches) |
| upstream footprint | `process_registry_notifications.py` seam + ledger row; cron tests leave the skip list (ADR 0015 amendment) | none; ADR 0015 keeps cron unused, "launcher-clock cron" = this scheduler |
| what is lost | — | upstream's cron CLI, incidents, failure-streak nudges, `kanban_schedule`; a persona cannot create a job that outlives its persona (by design) |
| mobile | no ticker on the phone bundle either way | same |

**Verdict: SCRAP.** The chat-wake lane proves the integration is possible and shows its cost: four
rulings each need a seam into upstream's cron semantics, and every one of them is moot once a fire is a
queued persona send. `598bedea` stays on its branch as evidence; D1/D3/D5/D6 close as REFUTED-by-design
when B4 lands (§7). **Recommend:** scrap; B4 builds the fork scheduler; `Trigger.from_cron_job` is the
only compatibility door.

## 5. Upstream features behind doors

- **Delegation.** Never called by the dispatcher. The lane persona may `delegate_task` inside its turn (a
  bounded side job, proposal §5's rule); `background=True` completions already re-enter through
  `dispatch_delivery/completions.py`. The door is the persona's tool list, keyed by the lane persona.
- **Goals.** `runtime.chat.goal.set | status | pause | resume | clear` over `GoalManager(root_session)`
  (RULED). `Assignment.goal_mode=UNTIL_DONE` makes the executor `set` the goal with a `GoalContract` drawn
  from the brief's `acceptance`, `add_gate` for each test command the brief names; after each terminal
  turn the serve calls `evaluate_after_turn` and forges `next_continuation_prompt` through the mission-
  chat door (an operator send wins the slot); `should_continue=False` settles the run. One goal
  vocabulary serves chat and Work.
- **Cron.** Scrapped as an engine (§4); `Trigger.from_cron_job` converts a job record; nothing of
  `cron/` runs in the serve.
- **Kanban dispatcher — not adopted.** Its unit is one card → one worker subprocess with pid liveness
  (`kanban_db_dispatch.py`), keyed by profile, stored in `kanban_db`, hosted by the gateway. The fork's
  unit is a thick lane of rows → one persona turn, keyed by instance, stored in the brain, hosted by the
  serve. The two agree on nothing but the word; W5 retires the fork's kanban code.

## 6. Stages, in order, with tests and killing mutations

Dependencies: W1 → W2 (+W5) → {W3, W4} → **B1** → {**B2**, **B4**} → **B3** → **B5** → **B6**. Each stage
is one CHANGE commit (B5 one MOVE for the workdir override), affected tests only
(`Running the tests.md` § What a lane runs).

| stage | builds | tests | killing mutation (expected red) |
|---|---|---|---|
| **B1** contracts | `work_store/{reasons,source,executor,scheduler}.py`, `ManualScheduler`, fakes; `work/model.py::Reason` re-exported | `tests/agent_runtime/work_store/test_contracts.py` | `ManualScheduler.tick` fires a `StartBatch` → `test_manual_never_fires` red; `Reason` drops `already_taken` → `test_reasons_cover_writer_refusals` red |
| **B2** planner + machine + manifest + RPC | `agent_runtime/batch/{planner,machine,manifest,rpc}.py`, `runtime.batch.plan|start|status|stop|land|approve` | `test_batch_planner.py`, `test_batch_machine.py`, `test_batch_manifest_rebuild.py` | planner groups by row instead of `Domain` → `test_one_lane_per_domain` red; machine allows `LANDED` without `AWAITING_APPROVAL` → `test_approve_is_the_only_door_to_main` red; manifest omits lane line → `test_rebuild_from_manifest_and_rows` red |
| **B3** `PersonaTurnExecutor` + goal door | W3 engine behind `Executor`; `runtime.chat.goal.*`; after-turn hook | `test_persona_turn_executor.py`, `test_chat_goal_rpc.py` | executor bypasses `chat_root_send_queue` and calls the door directly → `test_busy_root_queues_never_steers` red; hook forges while an operator send is queued → `test_operator_send_wins_slot` red |
| **B4** `ServeTickScheduler` | ticker thread, `store/schedules/`, `schedule_manage` tool, `runtime.schedule.*`, `Trigger.from_cron_job`; ADR 0015 note; D1/D3/D5/D6 closed | `test_serve_tick_scheduler.py`, `test_schedule_tool.py`, `test_trigger_from_cron_job.py` | `tick` fires with `drain_state` set → red; `max_parallel` ignored → `test_overcap_queues_with_waited_s` red; `WHEN_IDLE` fires on one idle tick → `test_when_idle_needs_two_ticks` red; `from_cron_job` drops `tz` → red |
| **B5** `BatchLaneExecutor` + landing lane | worktree cut via `run_git`, brief file, workdir override, landing brief | `test_batch_lane_executor.py` (fake git) | worktree cut inside the clone → `test_worktree_beside_clone` red; brief over 40 lines → `test_brief_cap` red; landing pushes before `approve` → red |
| **B6** Launcher | Batches panel over `runtime.batch.*` (plan/start/stop/land/approve), fires as `running_work`, opt-in reminder mirror via `ReminderCoordinator` | `batches_panel_test.dart`, `batch_manifest_projection_test.dart` | panel calls `approve` without a green gate result → red; reminder mirror arms a hermes schedule directly → red |

B6 is a launcher lane (one CHANGE); it waits on W4's slot-driven board.

## 7. Owner decisions (one line each)

- Upstream cron: keep (`598bedea` + four seams) or scrap for the fork scheduler. **Recommend: scrap (§4).**
- Where the batch manifest lives: the workspace's default brain, or the slot brain of the first domain.
  **Recommend: the default brain; one place to look.**
- Lane persona when rows carry no assignee: roster role match, or always ask. **Recommend: role match,
  ask when none.**
- `batch_automation` values: `off | plan | start`, default `off`; `land`/`approve` never automated.
  **Recommend: as stated.**
- `max_rows_per_lane` default 65 (the playbook's measured ceiling) vs 30. **Recommend: 65.**
- Stop semantics on a running lane: wait for the turn's end vs kill the turn. **Recommend: wait; a killed
  turn leaves a half-written tree.**
- Goal gates from the brief's test commands, on by default for `UNTIL_DONE`. **Recommend: yes.**
- Scheduled fires as a new `running_work` kind `scheduled_turn` vs reusing the wire word `cron_job`.
  **Recommend: `scheduled_turn`; the Launcher renders unknown kinds already.**

## 8. Rows to file (verbatim, `runtime-queue.md` § Fork-owned unless named)

- **`RT-DISPATCH-B1-CONTRACTS` — the three library contracts: `work_store/{reasons,source,executor,scheduler}.py`, `ManualScheduler`, fakes; one `Reason` enum for every Work refusal** · fork / Work · `docs/agent-runtime-harness/planned/dispatcher-and-libraries-2026-10-18.md` §2, §6 · BLOCKED 2026-10-18: another lane — `RT-WORK-W2-WRITER` lands the writer the SOURCE wraps
- **`RT-DISPATCH-B2-BATCH` — the batch dispatcher: `agent_runtime/batch/{planner,machine,manifest,rpc}.py`, thick lanes by `Domain(slot, note, heading)`, the state table, manifest notes under `50 — Agent Handoffs/batches/`, `runtime.batch.plan|start|status|stop|land|approve`, manual by default** · fork / Work · `docs/agent-runtime-harness/planned/dispatcher-and-libraries-2026-10-18.md` §3 · BLOCKED 2026-10-18: another lane — `RT-DISPATCH-B1-CONTRACTS`
- **`RT-DISPATCH-B3-PERSONA-EXECUTOR` — W3's engine as `PersonaTurnExecutor` behind the `Executor` contract, plus `runtime.chat.goal.set|status|pause|resume|clear` over `GoalManager` and the after-turn continuation hook (`RT-GOAL-ENGINE-DOOR` lands here)** · fork / Work, chat RPC · `docs/agent-runtime-harness/planned/dispatcher-and-libraries-2026-10-18.md` §2.2, §5 · BLOCKED 2026-10-18: another lane — `RT-WORK-W3-ENGINE`
- **`RT-DISPATCH-B4-SCHEDULER` — the fork's `ServeTickScheduler`: one 60 s serve tick, `store/schedules/<key>.json`, triggers `MANUAL|AT|EVERY|CRON|WHEN_IDLE`, `scheduler.max_parallel` default 4, the `schedule_manage` tool, `runtime.schedule.arm|disarm|list`, `Trigger.from_cron_job`; closes `RT-D1/D3/D5/D6` as moot and leaves cron on ADR 0015's list** · fork / scheduling · `docs/agent-runtime-harness/planned/dispatcher-and-libraries-2026-10-18.md` §2.3, §4 · BLOCKED 2026-10-18: owner decision — scrap the upstream cron integration (`598bedea` stays on its branch as evidence)? · Recommend: scrap
- **`RT-DISPATCH-B5-LANE-EXECUTOR` — `BatchLaneExecutor`: worktree beside the clone via `run_git`, brief file from the skeleton (≤ 40 lines), per-run workdir override, the landing lane, push to `main` only behind `approve`** · fork / Work · `docs/agent-runtime-harness/planned/dispatcher-and-libraries-2026-10-18.md` §2.2, §3.2 · BLOCKED 2026-10-18: another lane — `RT-DISPATCH-B2-BATCH`
- **`RT-SCHEDULE-TURN-RUNNING-WORK` — a scheduled fire reports as a `running_work` row of kind `scheduled_turn` (the Launcher renders unknown kinds with the raw wire word; no launcher change until it wants a label)** · fork / snapshot · `docs/agent-runtime-harness/planned/dispatcher-and-libraries-2026-10-18.md` §4 · BLOCKED 2026-10-18: another lane — `RT-DISPATCH-B4-SCHEDULER`
- (launcher, `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`) **`MC-BATCHES-PANEL` — the Batches panel over `runtime.batch.*` (plan / start / stop / land / approve, approve only on a green gate result) and the opt-in reminder mirror of hermes schedules through `ReminderCoordinator.rebuild`** · launcher / Mission Control · `hermes-agent/docs/agent-runtime-harness/planned/dispatcher-and-libraries-2026-10-18.md` §3.3, §4, §6 B6 · BLOCKED 2026-10-18: hermes — `RT-DISPATCH-B2-BATCH` the methods it calls
