---
type: queue
program: fixture
status: open
---

<!-- One row per task defect (ADR 0025's 2026-11-09 amendment), each named by
its ID's tail. Read by test/tool/queue_grammar_tasks_test.dart. -->

- **`FX-TWO-TASKS-A` — First task for one slug** · task: twice · READY 2026-11-09
- **`FX-TWO-TASKS-B` — Second task for the same slug** · task: twice · READY 2026-11-09
- **`FX-GROUP-NO-TASK` — A subtask of a slug nobody owns** · group: orphan.child · READY 2026-11-09
- **`FX-PREFIX-NOT-DOTTED` — A slug that only shares letters with a task** · group: twicefold · READY 2026-11-09
- **`FX-ROW-NO-TASK` — A row under no task** · `tool/x.dart` · READY 2026-11-09
- **`FX-TITLE-CODE` — Make `close_row` close the task** · task: title-code · READY 2026-11-09
- **`FX-TITLE-PATH` — Fix tool/queue/close_row.dart for tasks** · task: title-path · READY 2026-11-09
- **`FX-TITLE-ID` — Finish what BRAIN-QUEUE-TASKS-S1 started** · task: title-id · READY 2026-11-09
- **`FX-TITLE-LONG` — A plain-English title that goes on and on well past the hundred characters a task title may hold today** · task: title-long · READY 2026-11-09
