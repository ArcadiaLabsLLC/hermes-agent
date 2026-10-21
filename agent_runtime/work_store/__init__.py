"""Work on the workspace todo boards — the brain queue notes of every repo the workspace binds.

Plan ``docs/agent-runtime-harness/planned/work-on-markdown-2026-10-18.md`` (§2 model, §6.1 W1).
A row in the ADR 0011 grammar IS a task; nothing is copied into a second store.

reasons: every Work refusal (one ``Reason`` enum) and ``WorkRefused``;
models: the value types the lower layers share (``Verdict``, ``Brief``, ``Domain``, ``Claimant``);
grammar: the Python twin of the launcher's ``WorkQueueRowParser`` and the pure one-line row edit;
board: a workspace's boards (one per live slot) and the rows read from them;
default_brain: the brain a workspace with no repo brain gets, and the commit identity pairs;
writer: the one write path (§5) — a row op per commit in hermes's own worktree, pushed fast-forward;
receipts: the one log line each write emits;
source: the SOURCE contract (dispatcher plan §2.1) — rows from the boards, the batching ``Domain``;
executor: the EXECUTOR contract (dispatcher plan §2.2) — who runs a claimed row;
scheduler: the SCHEDULER contract (dispatcher plan §2.3) and ``ManualScheduler``, the default;
schedule_store: armed schedules on disk, ``store/schedules/<key>.json`` (B4);
serve_scheduler: ``ServeTickScheduler`` — the serve's scheduler and its ticker thread (B4);
schedule_ops: the ``arm | disarm | list`` verbs ``runtime.schedule.*`` and the tool share (B4);
schedule_tool: ``schedule_manage``, the opt-in ``schedule`` toolset's one tool (B4);
persona_turn: ``PersonaTurnExecutor`` — a claimed row as one queued chat turn of the claiming instance;
engine: the serve's Work engine — run records, the tick, the write-back table.
"""

__layer__ = "models"
__all__: list[str] = []
