---
type: adr
id: 0015
status: accepted
date: 2026-10-17
tags: [adr, tests, boot, upstream]
---

# 0015 — Upstream features the fork does not ship leave the suite and the boot path

> [!summary]
> Owner ruling 2026-10-17: the fork never uses, in production, upstream's **desktop/Electron app and
> installers**, **upstream updater and release tooling** (the launcher owns updates), **kanban**, and
> the **messaging platform adapters** (Telegram, Discord, Slack, Matrix, Signal, WhatsApp, Feishu,
> WeCom, DingTalk), and **upstream's Docker image** (owner, 2026-10-17; the Docker *terminal backend* of the
> agent's terminal tool is a separate feature and stays).
> Also unused for TESTS only: the **gateway relay** (its code stays: cron imports it). Also unused:
> **upstream's gateway as a system service** (systemd/launchd/s6): it only works as upstream's product,
> without Mission Control; the owner's headless gateway for the persona system will be the fork's own.
> Platform adapters not named above (webhook, A2A, IRC, Buzz, Photon, Teams, ntfy, SimpleX…) count as
> messaging adapters; `bundled-phone.yaml` lists the ones the fork's phone build leaves out.
> Their upstream test files leave the regular suite (an `unused` reason on the upstream skip list;
> they run only when named), and, except for the relay, the fork's serve and CLI stop importing
> or discovering them (bundle profiles; an import-graph check first). **Cron stays**: standard cron is
> used on desktop today; a launcher-clock cron that also works on mobile may replace it later.

## Context

A whole-tree gate (v0.22.2, 2026-10-16) took 9,657 s at 8 workers; upstream test files are 31,504 of
the 38,887 serial seconds in the gate store. The owner is cutting whole-tree cost by refining the
downstream suite, and asked that production never run features the fork does not ship. Sizing from
`durations.json` by file name (overlapping): desktop ~737 s, update/install/release ~3,050 s,
kanban ~1,300 s, messaging adapters ~610 s. Evidence for the wider suite timing:
[[r-perf-2026-10-17]].

## Rules

- A feature on this list is "unused". Its upstream test files go on
  `tests/fixtures/upstream_skip_list.txt` with `why` starting `unused` and this ADR cited; nothing
  runs them unless named ([[0016 — No whole-tree run, ever]]); a release merge lists the unused files
  upstream added or removed.
- Code the fork ships that imports an unused feature keeps it importable; a test of that import
  stays in the suite. The production cut is decided by the resolved import graph, never by a name
  match.
- Adding a feature to this list, or taking one off (cron when the launcher-clock cron lands), is an
  owner ruling recorded here.
- Kanban is unused for fork code too (2026-10-18, Work W5): the fork's kanban modules (`hermes_cli/kanban_blocked_pm.py`, `kanban_blocked_pm_tick.py`, `kanban_crash_evidence.py`) and the plugin's two `on_kanban_*` hooks are deleted; Work is the markdown todo board (`docs/agent-runtime-harness/planned/work-on-markdown-2026-10-18.md`), guarded by `tests/plugins/test_eternia_harness_registers_no_kanban_hook.py` and `tests/agent_runtime/test_no_kanban_dependency.py`.
