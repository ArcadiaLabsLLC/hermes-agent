"""Work on the workspace todo boards — the brain queue notes of every repo the workspace binds.

Plan ``docs/agent-runtime-harness/planned/work-on-markdown-2026-10-18.md`` (§2 model, §6.1 W1).
A row in the ADR 0011 grammar IS a task; nothing is copied into a second store.

reasons: every Work refusal (one ``Reason`` enum) and ``WorkRefused``;
grammar: the Python twin of the launcher's ``WorkQueueRowParser`` and the pure one-line row edit;
board: a workspace's boards (one per live slot) and the rows read from them;
default_brain: the brain a workspace with no repo brain gets, and the commit identity pairs;
writer: the one write path (§5) — a row op per commit in hermes's own worktree, pushed fast-forward;
receipts: the one log line each write emits;
executor: the EXECUTOR contract (dispatcher plan §2.2) — who runs a claimed row;
persona_turn: ``PersonaTurnExecutor`` — a claimed row as one queued chat turn of the claiming instance;
engine: the serve's Work engine — run records, the tick, the write-back table.
"""

__layer__ = "models"
__all__: list[str] = []
