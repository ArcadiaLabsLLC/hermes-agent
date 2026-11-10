---
type: queue
program: fixture
status: open
---

<!-- Tasks and their subtasks (ADR 0025's 2026-11-09 amendment): every row is
a task (` · task: <slug>`) or a subtask whose `group:` is a task's slug or a
dotted `<slug>.<sub>` under it. Read by
test/tool/queue_grammar_tasks_test.dart. -->

## Tasks — fixture

- **`FX-TASK` — Board pills: show each agent's work as a pill on the board** · task: board-pills · READY 2026-11-09
- **`FX-TASK-ONE-OFF` — A one-off fix is a task with one subtask** · task: one-off · READY 2026-11-09

## Subtasks

- **`FX-SUB` — The records source** · group: board-pills · `lib/core/records/board_spec.dart` · READY 2026-11-09
- **`FX-SUB-DOTTED` — The widgets, a plan's feature folded under the task** · group: board-pills.widgets · BLOCKED 2026-11-09: another lane — `FX-SUB` first
- **`FX-SUB-ONE-OFF` — The fix itself** · group: one-off · DEFERRED 2026-11-09: after release
