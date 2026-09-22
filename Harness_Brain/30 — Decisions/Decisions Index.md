---
type: moc
tags: [moc, adr]
---

# Decisions — Index

ADR-style notes for load-bearing fork rulings whose **WHY** is not recoverable from `docs/` or `git log` (and, since the 2026-09-15 history reconstruction, often not from `git log` at all). Backfilled 2026-09-21 from the operator's session memory and the canon's ruling stamps; each names its date and the evidence that bought it.

> [!example] ADR shape
> Frontmatter `type: adr`, `id`, `status` (proposed | accepted | superseded-by-NNNN), `date`, `tags`. Body: **Context** · **Decision** · **Consequences** · **Alternatives**.

## ADRs

```dataview
TABLE id, status, date
FROM "30 — Decisions"
WHERE type = "adr"
SORT id asc
```

Pointers, in case Dataview is off:

- [[0001 — Fork boundary, PUSH vs RPC union]] — 2026-08-13
- [[0002 — No push gates, checks are tests]] — 2026-09-03
- [[0003 — RPC route first]] — 2026-09-05
- [[0004 — Fable plans first, Opus builds, field notes per lane]] — 2026-08-24
- [[0005 — Fork history reconstruction 2026-09-15]] — 2026-09-15
- [[0006 — Upstream sync is a real merge, per-file reconciliation retired]] — 2026-09-21
- [[0007 — Flat 800-line ceiling and bulk mode]] — 2026-09-21
- [[0008 — Chat is the only lane]] — 2026-07-30
- [[0009 — Profile declaration is the sole MCP admission authority]] — 2026-08
- [[0010 — Stale sweep and ratchets first, never baseline]] — 2026-09-02
- [[0011 — One brain per repo, one Mission Control queue in the launcher]] — 2026-09-21 (queue clause amended by 0012)
- [[0012 — The hermes half of Mission Control is queued here, split by ownership]] — 2026-09-22
