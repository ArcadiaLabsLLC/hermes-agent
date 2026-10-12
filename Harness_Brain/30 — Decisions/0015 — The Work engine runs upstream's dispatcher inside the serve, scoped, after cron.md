---
type: adr
id: 0015
status: proposed
date: 2026-10-12
tags: [adr, work, kanban, cron, mission-control]
---

# 0015 — The Work engine runs upstream's dispatcher inside the serve, scoped, after cron

> [!summary]
> Proposed for the owner. Since the 2026-09-30 ruling native kanban is the only task store, and the Launcher's Work form writes `ready` cards into it; nothing the Launcher runs executes them, because the engine is a loop inside upstream's gateway process and the Launcher runs `hermes harness serve`. The proposal: run upstream's own dispatch tick (`hermes_cli/kanban_db_dispatch.py::dispatch_once`, the function the gateway embeds) inside the serve as a boot phase, scoped to Launcher-owned boards and profiles, after the cron lane lands and only when Work submit is opened. Never a fork-written scheduler. Evidence: `docs/agent-runtime-harness/planned/upstream-capability-audit-2026-10-12.md` §0, §1, §8.

## Context

- **The store is adopted, the engine is not.** `agent_runtime/work/native.py` writes through `hermes_cli.kanban_db`; `runtime.work.start` creates a `ready` card. `hermes_cli/harness_parts/serve/boot_phases.py` starts the socket, the peer listener and the dispatch-store restore, and neither the kanban dispatcher nor the cron ticker. The Work slice's receipt (`docs/downstream/hermes-work-view-2026-09-30.md`) says so: "The native dispatcher must already be running … This slice does not auto-start it", for one stated reason — auto-starting could dispatch unrelated native tasks on a shared home.
- **"Board" means the table.** Upstream's board is a named SQLite file plus a slug; `default` always exists. The dashboard is an optional plugin, not installed, not needed. The Launcher's Work viewer (Companion's presentation, reused) is the surface.
- **The engine is most of what the owner's table asks for.** Durable workers (one OS process per card, heartbeats, claims) and crash recovery (stale reclaim, bounded retry, circuit breaker, rate-limit requeue, terminal-provider block) ARE the dispatcher. Dependency scheduling, Triage auto-decomposition (`kanban.auto_decompose`, on by default, runs beside the tick) and goal-mode cards with the judge and quality gates (`hermes_cli/goals.py`) are engine features waiting on a producer: Work submit fields, or a persona-side submit verb.
- **Mobile.** The dispatcher spawns a process per worker; cron is a thread. `agent_runtime/bundle_profiles/bundled-phone.yaml` already excludes both and the Work adapter. A phone is a client of a paired host over the multi-device lane.
- **Everyday users.** Owner principle 2026-10-12 (audit §8): capability by persona profile, controls only on developer and power-user modes. The engine is invisible to a chatting user: "I'm on it", then a result, even after a restart.

## Decision

Proposed, in this order; the owner rules each step:

1. **Cron first** (lane filed 2026-10-12, this session): upstream's `InProcessCronScheduler` on a supervised thread inside the serve, off by `cron.serve_ticker: false` on phone bundles; `cronjob` joins `harness_core`; a job's finish wakes the persona chat that created it through the existing completion drain. No process is spawned. This is the loop for "remind me", "every morning", and one-shot "do this later".
2. **The engine when Work submit opens** (option 1 of audit §8): a serve boot phase runs `dispatch_once` per Launcher-owned board on `kanban.dispatch_interval_seconds`, under upstream's own single-dispatcher lock, with `kanban.dispatch_profiles` set to this install's persona profiles (fail-closed: an empty list claims nothing), so a developer's own gateway on the same home is never double-dispatched. `runtime.work.context.can_start` flips true in the same landing, not before — a Work form writing cards into a store nothing empties is worse than no form. The serve's drain and build-behind restart hand running workers off before recycling. `running_work` gains a kanban-worker lane with a durable view (the board's `running` rows).
3. **Then the producers**: `runtime.work.start` carries `parents`, a Triage flag, `goal_mode`, `goal_max_turns`, `completion_contract`; a fork `work_submit` tool over `agent_runtime/work/service.py::execute("start")` lets a persona file a card from any chat, voice turn or surface, with the same authorization as the RPC and no change to registry hygiene.

Enforced by: nothing yet. Each step lands with its red-first tests; step 2's gate is a test that proves a `ready` card on a Launcher-owned board is claimed by the serve's tick and a card on a foreign board is not.

## Value to the Eternia harness

| who | what they get | what they never see |
|---|---|---|
| everyday / small-business-in-a-loop | a task that keeps going after the app closes; a morning check that arrives as a message | a board, a worker, a setting |
| developer | a card per job with retry, a review lane, a PR completion contract; their own gateway untouched | double dispatch |
| power user | N workers on one install, bounded by `kanban.max_in_progress`; other boards left to other dispatchers | a second scheduler |

## Consequences

Positive: one task authority (the ruling holds); upstream fixes to the dispatcher arrive free; the fork's two kanban hooks (blocked-card PM router, crash evidence) start firing; the Work viewer's rows move; the same code serves a hosted runtime for mobile-only users.

Negative, and owned: one more process per running card (CPU, tokens — capped by config); the restart fence must drain workers (design item in the loop-host row); the decomposer and the judge are extra model calls, paid only by cards that ask; a shared-home install must set `dispatch_profiles` or the fail-closed default claims nothing and the owner reads "cards never move" as a bug.

## Alternatives

- **Option 2 — a separate `hermes kanban dispatch` process the Launcher supervises.** Same upstream code; one more process to reap and restart; invisible to `running_work`'s live lanes. Rejected for the extra lifecycle, kept as the fallback if the serve's restart fence cannot hand workers off.
- **Option 3 — a fork-written headless scheduler ("our own kanban").** Reverses the 2026-09-30 ruling: two systems answering "what is running and who owns it". Rejected.
- **Cron only, no engine.** Keeps the loop, loses the durable one-off: a cron job is a thread that a runtime restart interrupts. Acceptable as the first step, not as the end state; requires `can_start` to stay false.
- **Orchestration via `delegate_task` only.** Already on the lane; fine for work that finishes while the user is present; a fan-out dies with the turn and has no recovery. Not a substitute.
