---
type: moc
tags: [moc, todo]
---

# TODO — the master pointer list

**This file contains no work.** It contains pointers to the queues that do. A master list that carries item text becomes a second copy of every queue, and a second copy of a fact is free to disagree with the first. The rule is the launcher's ADR 0025 (`EterniaLauncher/Launcher_Brain/30 — Decisions/0025 — One master TODO, domain queues, reports split on arrival.md`), adopted here by [[0011 — One brain per repo, one Mission Control queue in the launcher]] and split across the two repos by [[0012 — The hermes half of Mission Control is queued here, split by ownership]].

**If you are starting work:** open the queue for your domain, not this file and not a report. Then **claim the row before you touch anything** — fetch, append `**TAKEN <date> <who>**` to the row's line, commit that alone and push it. A row already marked `TAKEN` is not yours.

**If you are landing a report, audit or agent finding:** split it into the queue on arrival. The report stays as EVIDENCE and the rows point at it. A ` · VERDICT <date>:` suffix on a row is an owner decision, not lane work.

## The queues

```dataview
TABLE program, status
FROM "20 — Active Initiatives"
WHERE type = "queue"
SORT program asc
```

Pointers, in case Dataview is off — **this list is names only, never counts or status.** Counts belong to the queues, which is where they can be right.

Domain queues — work filed by the SURFACE it serves, never the layer it lives in and never the lane that found it:

- [[runtime-queue]] — Mission Control, **the hermes half**: rows whose fix lives in this repository (serve, chat turn, snapshot, office and board stores, discussions, realm sync, multi-device, prep cost, the harness CLI). Split inside by the [[Fork Boundary Map]]: fork-owned, seams in upstream files, upstream-owned.
- `EterniaLauncher/Launcher_Brain/20 — Active Initiatives/mission-control-queue.md` — Mission Control, **the launcher half**: the surface, its Flutter code and tests. A finding that needs both sides is filed on the side that must move first and names the other.
- [[fork-hygiene-queue]] — the repository as a fork: upstream sync and the boundary, CI, the suite and its gates, the mutation gate, docs gates, the god-file refactor, this vault.
- [[dead-code-burn-down-queue]] — the god-file program's deletion register (hermes half): every dead-code candidate the census and the layout sheets find, launcher format, one row per symbol; listed apart because a deletion serves no surface and its rows share one gate (the tombstone registry).

## The order of programs

When two staged plans are both ready, the order is a ruling, not a queue row: [[0013 — Seams before the god-file refactor, and main's reds classified first]] — classify `main`'s reds, then seam Stage 0b + Stage 1, then the god-file refactor Wave 0 → H4, then seam Stage 2 onward. The rows themselves live in [[fork-hygiene-queue]].

Program notes in `10 — Programs/` carry a cursor, never rows. Field notes under `docs/agent-runtime-harness/planned/` carry evidence, never rows.
