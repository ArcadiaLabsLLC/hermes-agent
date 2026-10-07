---
type: adr
id: 0014
status: accepted
date: 2026-10-07
tags: [adr, latency, observability, chat]
---

# 0014 — Live chat latency is checked against committed budgets

> [!summary]
> Owner ruling 2026-10-07: "make sure we don't regress". **Run `hermes harness observe turn-timing --check` after any rebuild that touches the chat path**, after a few live turns. It judges the newest turns' receipts against `agent_runtime/turn_latency_budgets.json` and exits 1 on any FAIL. The budgets and the baseline they came from live in that file; the command is described in `docs/agent-runtime-harness/07-observability.md` (the turn-timing paragraph).

## Context

Offline guards (`test_turn_cost_guard_downstream.py`) passed while live turns regressed: on
2026-10-06 the pre-request span went 0.4 → 1.2 s on real data and the Launcher redrew. Nothing
told the operator after a rebuild whether the live path was still as fast as last time.

## Baseline (2026-10-07 00:41–00:43 local, hermes 91cb3156e22, launcher c238636bad)

Four turns on one chat, the first of them the serve's first turn after boot:

| span | baseline | budget |
| --- | --- | --- |
| accept → anchor (warm) | 27–73 ms | ≤ 150 ms |
| send_prep total (warm) | 460–780 ms | ≤ 900 ms |
| provider connection (warm) | reused 4/4 | = reused |
| launcher send → admit | 97–173 ms | ≤ 250 ms |
| launcher ui_build_max | 96–143 ms | ≤ 180 ms |
| launcher ui_build_sum | 954–1,162 ms | ≤ 1,500 ms |
| launcher ui_apply → paint | 21–55 ms | ≤ 100 ms |
| provider server_wait, first event → text | 658–920 ms, 110–209 ms | reported, never failed (not ours) |

## Decision

- Turns fall in three groups. **cold** (the first turn after a serve boot, a turn within 120 s
  of one, or a Launcher `send=first_in_process`): warm-only budgets are reported, not judged.
  **after-idle** (warm, but the previous turn on the same chat ended over 30 s earlier): judged
  with the same budgets, as its own group, so the 2026-10-07 00:44:30 / 00:45:07 class
  (send_prep 1,139 / 1,729 ms, conn=new; lane h-idle-turn) is caught if it comes back.
  **warm**: everything else.
- A budget changes only with a new measured baseline written beside it in the same commit.
  Loosening a budget to make a run pass is baselining to pass ([[0010 — Stale sweep and ratchets first, never baseline]]).
- Observability stays in logs and the CLI; no parity-envelope keys.

## Consequences

- A rebuild of the chat path is not done until `--check` reads PASS on a few live turns.
- The check reads the serve home's `agent.log` AND every profile's: the accept receipt logs
  under the serve home, `send_prep` / `send_window` / `stream_gap` under the persona's profile.
