---
type: queue
program: fixture
status: open
---

<!-- One row per failure arm the grammar gate reds on. -->

- **`FX-NO-STATUS` — No status row** · surface · the plan is written
- **`FX-TWO-STATUSES` — Two statuses row** · READY 2026-10-16 · BLOCKED 2026-10-16: backend — row
- **`FX-UNKNOWN-REASON` — Unknown reason row** · BLOCKED 2026-10-16: vibes — nothing
- **`FX-NO-DATE` — Status word without a date row** · READY
- **No ID row** · READY 2026-10-16
- **`FX-DUPLICATE` — Duplicate ID row, first** · READY 2026-10-16
- **`FX-DUPLICATE` — Duplicate ID row, second** · READY 2026-10-16
- **`FX-WRAPPED` — Wrapped row** · the text runs on
  to a second line · READY 2026-10-16
- **`FX-BAD-ASSIGNEE` — Bad assignee row** · assignee: bob · READY 2026-10-18
- **`FX-TWO-ASSIGNEES` — Two assignees row** · assignee: persona:alice · assignee: persona:bob · READY 2026-10-18
- **`WORK-ABCDE` — Short engine-minted ID row** · READY 2026-10-18
- **`FX-BARE-SKILL` — Bare skill row** · skills: git-workflow · READY 2026-10-19
- **`FX-TWO-SKILLS` — Two skills segments row** · skills: `a` · skills: `b` · READY 2026-10-19
