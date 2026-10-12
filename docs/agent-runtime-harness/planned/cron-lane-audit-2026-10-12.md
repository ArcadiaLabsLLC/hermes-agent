# Cron lane audit — what upstream cron is, what a serve-hosted lane changes, what the owner decides

**Status: MEASURED 2026-10-12, read-only.** Owner ask: "first audit before you start — don't
implement until we have the full picture." A reference implementation of the lane exists as ONE
commit on the feature branch (`598bedea`, branch `ccr-cc6cbc42-w6ahvk`), not on `main`; this
note judges it and names what it does not cover. Evidence is cited by file and symbol. Companion
notes: `upstream-capability-audit-2026-10-12.md` (§3, §8) and ADR 0015.

## 1. What a cron job is (upstream, `cron/`)

- **A record** in `<home>/cron/jobs.json`, one store per profile home (`cron.jobs.use_cron_store`).
  `cron.jobs.create_job` fields: `prompt`, `schedule` (cron expression, interval, or a one-shot
  `run_at`), `name`, `repeat`, `deliver`, `origin`, `skill`/`skills`, `model`/`provider`/
  `base_url`, `script`, `context_from`, `enabled_toolsets`, `workdir`, `no_agent`,
  `attach_to_session`, `monitor_script`/`monitor_url`, `reasoning_effort`, `failure_deliver`,
  `paused`, `pinned`, `interpreter`.
- **Kinds.** One-shot or recurring; paused (a safe canary); `no_agent` (a script IS the job, its
  stdout delivered verbatim, no model call); monitor mode (`cron/monitor.py`: a cheap source is
  hashed each tick and the agent runs only when it changed); skill-backed; `context_from` (another
  job's latest output injected). Event-triggered jobs (a webhook fires `cron_job`) are a gateway
  feature and do not apply to the serve.
- **Outputs and ledgers.** Each run's final response is saved to
  `<home>/cron/output/<job_id>/<stamp>.md` (`cron.jobs.save_job_output`, `cron.output_retention`
  50 per job). Every attempt is a row in `cron/executions.db` (`cron/executions.py`); failures
  group into incidents keyed by `(job, error signature)` with alert-once and acknowledge
  (`cron/incidents.py`, `cron.failure_repeat_alert_hours` 6).

## 2. How a run executes

- **The ticker.** `cron.scheduler_provider.InProcessCronScheduler.start` on a daemon thread
  (`cron/scheduler_thread.py::SupervisedTickerThread`, restarts a crashed ticker), every 60 s,
  under a per-home file lock `cron/.tick.lock` (`cron.scheduler._acquire_tick_lock`: a serve
  beside a gateway never double-fires). Multiplex: with `profile_homes` it scopes each profile
  home in turn (`_profile_cron_scope` sets the hermes-home override and `use_cron_store`), writes a
  per-home heartbeat (`record_ticker_heartbeat`, writer pid included). `can_dispatch` is a drain
  gate: a False leaves due jobs for the next allowed tick. Misfires: one catch-up fire per job
  (`cron.jobs._classify_dispatch_lateness`: on_time / late / catch_up), never one per missed
  tick; `cron.catch_up_missed` default on.
- **The run** (`cron.scheduler.run_job`). Preflight first (`cron/scheduler_preflight.py`: the
  provider key resolves, attached skills exist, delivery targets are configured; failure =
  `blocked_config`, one alert, NO model call). Then a fresh `AIAgent` with session id
  `cron_<job>_<stamp>` and its own SessionDB rows (searchable later), in the job's `workdir`.
  Model at fire time: per-job pin → `cron.model` → the profile's main model; the agent's tool
  cannot set model/provider/base_url/reasoning (user-owned; `tools/cronjob_tools.py`
  `_HANDLER_FORWARDED_ARGS` comment). Toolsets: the profile's normal static list minus
  `messaging`, `clarify` and `cronjob` (`cron.scheduler._resolve_cron_disabled_toolsets`;
  `cron.allow_agent_scheduling: true` lifts only `cronjob`), minus `agent.disabled_toolsets`; a
  per-job `enabled_toolsets` can only narrow. Approvals: `approvals.cron_mode: deny` blocks a
  dangerous command instantly, the agent finds another way (`hermes_cli/config_defaults.py`).
  Unattended hard stops are on (`non_interactive_hard_stop_enabled`). Quota walls park the job's
  `next_run_at` (`cron/quota_hold.py`); an unreachable model re-runs (`cron/unreachable_retry.py`).
- **Where it runs.** Under a systemd gateway a job can be an external worker process in a
  transient scope so a gateway restart does not kill it; everywhere else, including the serve
  lane, it is a thread in the ticker's pool. **A serve restart kills a running job**; on the next
  boot `recover_interrupted` marks the attempt `unknown` in the ledger. `cron.max_parallel_jobs`
  is `None` (unbounded) by default.

## 3. How a persona creates one (the lane the reference implementation opens)

- **The tool.** `cronjob_manage` (upstream's rename of `cronjob`; one tool in the `cronjob`
  toolset: create / list / update / remove / run / pause / resume, `tools/cronjob_tools.py`
  `CRONJOB_SCHEMA`). Guards at create: the prompt scan (`tools/cronjob_prompt_scan.py::_scan_cron_prompt`
  — invisible unicode, threat and exfiltration patterns), the script path confined to
  `<home>/scripts/` (`tools/cronjob_job_args.py::_validate_cron_script_path`), the lifecycle guard
  (no "restart the gateway" jobs, `cron/lifecycle_guard.py`), bot-chat target validation.
- **Which home.** A persona turn flips `HERMES_HOME` to the persona's profile home
  (`agent_runtime/profile_context.py`), so the job lands in THAT profile's store and runs with
  that profile's model, config and skills. The multiplex ticker ticks every profile home.
- **The liveness notice.** `cronjob_manage` appends `_gateway_liveness_notice` to every create;
  it reads `hermes_cli.cron._builtin_gateway_liveness`, which since upstream #121881 accepts "an
  in-process ticker inside `hermes serve`" proven by a fresh per-home heartbeat whose writer pid
  is alive. Under the serve ticker the tool should therefore NOT warn "gateway not running".
  Read, not run: a live-turn check is owed (row).
- **The local-delivery notice.** With no `HERMES_SESSION_PLATFORM` on the persona lane the job
  gets no `origin`, `deliver` defaults to `local`, and `_local_delivery_notice` tells the model
  the output "is never delivered back into the session". Under the chat wake that sentence is
  false and the persona will relay it. (Finding; row.)

## 4. Delivery — the actual fork work

- **Upstream's lane** delivers to messaging platforms (adapters, relay), `bot-chat`, or a file.
  Platforms are a `Platform` enum resolved through `gateway/delivery.py::resolve_delivery_transport`
  and `gateway/platform_registry` (a plugin may register one with `cron_deliver_env_var`). The
  serve has no adapters and does not run the gateway's asyncio loop. Making "the persona chat" a
  platform would pull the gateway's platform machinery into the serve; rejected in the reference
  implementation.
- **The reference implementation** (`agent_runtime/cron_wake.py`, the `tools/mcp_job_wake.py`
  shape): bind the `job_id` to the `persona_chat_` root at the `cronjob_manage` create result
  (plugin `post_tool_call` observer; checkpoint `<background-work home>/cron_jobs.json`); the
  delivery drain polls each pass (`dispatch_delivery/drain.py::_poll_cron_wakes`), reads the job
  from its own home, and a `last_run_at` past the cursor queues ONE `cron_job_finished` event per
  run with the saved output's redacted tail; `_PROCESS_LIKE_EVENTS` admits it, so it rides the
  same lane as a finished background `terminal`: steered into a busy turn, a turn on an idle one,
  dropped loudly when the persona instance is gone. The Launcher renders that turn as it renders
  every delivery (`agent_console_senders.dart`: "Delivered result").
- **Not covered by it:** upstream's continuable deliveries (`cron.mirror_delivery`, gateway
  threads), `attach_to_session`, `failure_deliver`, `deliver=all`, push notifications
  (`cron.delivery.notify`). The persona's own reply to the wake is the delivery.

## 5. What the Launcher already has

The activity chips count cron rows as "unowned work" with their own number
(`mission_activity_chip_model.dart::unowned`), `running_work`'s cron lane reports live rows once
the ticker's pools exist in the serve (`agent_runtime/running_work/lanes_process.py::_cron_owned_here`),
and a delivered result renders as "Delivered result". There is no cron list or editor in the
Launcher, which matches the owner principle (no control for the everyday user; a developer/power
mode later, if ever).

## 6. Mobile

The phone bundle drops the `cronjob` toolset and the `cron` package and, in the reference
implementation, sets `cron.serve_ticker: false`; a phone's reminders run on its paired host.

## 7. Risks, and the decisions the owner makes before anything lands

| # | decision | the reference implementation chose | the risk, and the alternative |
|---|---|---|---|
| D1 | **Who may schedule.** | `cronjob` in `harness_core`: every persona | A persona with `file` tools can write `<home>/scripts/x.sh` and schedule it `no_agent`: an unattended shell on a cadence, outside the terminal envelope and `approvals.cron_mode` (those govern agent tool calls, not a script-only job; `cron/scheduler_script.py` runs it by subprocess). Alternatives: (a) keep it on `harness_core` and refuse `no_agent` / `script` / `monitor_script` arguments on the persona lane through the plugin's existing `pre_tool_call` refusal; (b) supervisor profiles only (`toolsets: [harness_core, cronjob]`). Recommend (a): the everyday case needs scheduling, not scripts. |
| D2 | **Default posture.** | `cron.serve_ticker` default on; phone off | Every desktop serve starts ticking on upgrade. The ticker is idle-cheap (one lock and one `jobs.json` read per home per minute), but an install with jobs created by hand under a profile starts firing them. Alternative: default off, the Launcher turns it on per install. |
| D3 | **Delivery semantics.** | wake the creating chat; the persona answers | A wake while the chat is busy is a STEER into the running turn (drain ruling 2026-09-24): a morning brief can land inside an unrelated turn's tool result. Alternative: queue wakes until the turn ends (a drain policy change), or a dedicated "delivery" turn. Owner to rule. |
| D4 | **Restart behaviour.** | `can_dispatch` stops NEW runs once a drain begins; a running job dies with the process | The build-behind restart (RL-20) recycles the serve "when idle", and idle reads chat turns and agent runs — NOT `cron.scheduler.get_running_job_ids()`. A pull mid-job interrupts it. Fix shape: the idle probe also reads running cron ids (upstream's gateway drain does, `_drain_active_agents`). Row. |
| D5 | **Cost caps.** | upstream defaults: `max_parallel_jobs` unbounded, model = the persona's main model | Set a serve default (two parallel jobs), and decide whether `cron.model` pins the fleet to a cheaper model; measure one week of a real morning job before ruling. |
| D6 | **The tool's own words.** | unchanged upstream notices | The local-delivery notice (§3) says the output is never delivered; the persona will say so to the operator. Fix shape: the plugin's `transform_tool_result` replaces the notice on the persona lane. Row. |
| D7 | **Observability.** | the serve's `cron_lane` stderr line; `hermes cron status/list` on the CLI | No `harness` verb and no snapshot section lists a persona's jobs; the Launcher sees only running rows. Enough for the everyday case; a developer mode would want a list. Later. |
| D9 | **Delivery surface: chat, Home, or both.** | chat wake only | Cron is not chat: a run ends as a saved output file and a job record, which any surface can read. A brief on Intelligence Home or a right-panel card on open needs a `runtime.cron.*` read lane (none exists) and a Launcher view; "brief on open" can run the job now (upstream's run-now) and show the last output meanwhile. Per job or per persona: chat for "remind me Friday", a Home card for a morning brief, both from one run. Owner rules; nothing built. |
| D8 | **Keep or revert the reference commit.** | on the branch, not on main | Keep as the implementation ADR 0015 step 1 lands from, after D1–D6 are ruled; or revert on the branch. |

## 8. The reference implementation at `598bedea`, exactly

Does: boot phase `BootPhases._boot_cron_lane` → `agent_runtime/cron_lane.py::boot_serve_cron_lane`
(switch, multiplex over `hermes_cli.profiles.list_profile_names`, drain gate, one receipt
line, guarded imports); `agent_runtime/cron_wake.py` (bind, poll, wake, render; checkpoint);
`cron_job_finished` on the drain; one additive branch in `tools/process_registry_notifications.py`
(ledger row); `cronjob` in `harness_core` (inventory re-emitted 45→46 tools, 15→16 toolsets);
phone bundle off; canon 04 Stage 4b; the cron queue row discharged. Tests: 19 new, six named
killing mutations each recorded red (commit body); eight neighbouring suites green. The whole-tree
landing gate was started and STOPPED on the owner's instruction; it has not reported.

Does not: anything in D1–D7's alternatives; continuable deliveries; a cron list for the Launcher.
