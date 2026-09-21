---
type: moc
tags: [moc, initiative]
---

# Initiatives — Index

Snapshots of what is mid-flight in the FORK (not the runtime — runtime initiatives are plans under `docs/agent-runtime-harness/planned/` and rows in the launcher's Mission Control queue). Which of these is live work is the queue's answer, not this index's.

```dataview
TABLE program, status, blocking
FROM "20 — Active Initiatives"
WHERE type = "initiative"
SORT status asc
```

Pointers, in case Dataview is off:

- [[upstream-merge-2026-09-21]] — the running merge lane (3,002 commits, 40 files).
- [[downstream-god-file-refactor]] — the 13-lane program, planned, not dispatched.

The queue: [[fork-hygiene-queue]].
