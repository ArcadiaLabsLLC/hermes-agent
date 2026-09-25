---
type: moc
tags: [moc, initiative]
---

# Initiatives — Index

Snapshots of what is mid-flight in the FORK (not the runtime — runtime initiatives are plans under `docs/agent-runtime-harness/planned/` and rows in [[runtime-queue]]). Which of these is live work is the queue's answer, not this index's.

```dataview
TABLE program, status, blocking
FROM "20 — Active Initiatives"
WHERE type = "initiative"
SORT status asc
```

Pointers, in case Dataview is off:

- [[upstream-merge-2026-09-21]] — the running merge lane (3,002 commits, 40 files).
- [[downstream-god-file-refactor]] — the 13-lane program, planned, not dispatched; refreshed 2026-09-24 to 62 files + the owner's enterprise bar by `docs/agent-runtime-harness/planned/god-file-program-2026-09-24.md` (design branch `docs/god-file-design-2026-09-24`).

The queues: [[runtime-queue]] (Mission Control, hermes half) · [[fork-hygiene-queue]] · [[dead-code-burn-down-queue]] (the god-file program's deletion register).
