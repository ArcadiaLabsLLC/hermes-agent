"""Work on the workspace todo boards — the brain queue notes of every repo the workspace binds.

Plan ``docs/agent-runtime-harness/planned/work-on-markdown-2026-10-18.md`` (§2 model, §6.1 W1).
A row in the ADR 0011 grammar IS a task; nothing is copied into a second store.

reasons: every Work refusal (one ``Reason`` enum) and ``WorkRefused``;
grammar: the Python twin of the launcher's ``WorkQueueRowParser`` and the pure one-line row edit;
board: a workspace's boards (one per live slot) and the rows read from them;
default_brain: the brain a workspace with no repo brain gets, and the commit identity pairs.
"""

__layer__ = "models"
__all__: list[str] = []
