---
type: moc
tags: [moc, todo]
---

# TODO — the master pointer list

**This file contains no work.** It contains pointers to the queues that do. A master list that carries item text becomes a second copy of every queue, and a second copy of a fact is free to disagree with the first. The rule is the launcher's ADR 0025 (`EterniaLauncher/Launcher_Brain/30 — Decisions/0025 — One master TODO, domain queues, reports split on arrival.md`), adopted here by [[0011 — One brain per repo, one Mission Control queue in the launcher]].

**If you are starting work:** open the queue for your domain, not this file and not a report. Then **claim the row before you touch anything** — fetch, append `**TAKEN <date> <who>**` to the row's line, commit that alone and push it. A row already marked `TAKEN` is not yours.

**If you are landing a report, audit or agent finding:** split it into the queue on arrival. The report stays as EVIDENCE and the rows point at it.

## The queues

Work is filed by the SURFACE it serves, never the layer it lives in and never the lane that found it. The hermes fork serves two surfaces:

- **Mission Control** (the runtime's only product surface) — `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md`. **Both repos.** Runtime rows (serve, chat turn, snapshot, office, board, realm sync, multi-device, prep cost, restart fence, boot sweep) go THERE, in the launcher's vault, because the domain is the surface and the surface is the launcher's. Do not open a second Mission Control queue here.
- **Fork hygiene** (the repository itself as a fork: upstream sync, the fork boundary, CI, the suite, docs gates, the god-file refactor, the brain) — [[fork-hygiene-queue]]. This is the only queue this vault holds.

Program notes in `10 — Programs/` carry a cursor, never rows. Field notes under `docs/agent-runtime-harness/planned/` carry evidence, never rows.
