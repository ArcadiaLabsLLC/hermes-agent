"""How a finished tool call ended, carried from one record of it to the next.

``profile_runner.tool_payloads._outcome_fields`` decides the word once, on ``run.tool.finished``
(``passed`` / ``failed`` / ``timed_out`` / ``stopped``; ``timed_out: true`` beside a Hermes deadline).
Every later record of the call — the stored turn element, the persona history's trace row (from the
event or from the turn journal), the operator conversation's ``tool_call`` — copies it through
:func:`carried_tool_outcome` and never works it out again from a status word or an exit code: a stopped
call keeps ``status: failed`` for older readers, and exit 130 alone is a command's own business
(RT-STOPPED-TOOL-CALL-STORED-CHAT-SAYS-FAILED).
"""

from __future__ import annotations

from typing import Any, Mapping

from .serde import safe_assignment_token

__layer__ = "models"
__all__ = ["carried_tool_outcome"]


def carried_tool_outcome(source: Mapping[str, Any]) -> dict[str, Any]:
    """``outcome`` and ``timed_out: true`` as ``source`` states them; a source without them adds no key."""

    carried: dict[str, Any] = {}
    outcome = safe_assignment_token(source.get("outcome"))
    if outcome:
        carried["outcome"] = outcome
    if source.get("timed_out") is True:
        carried["timed_out"] = True
    return carried
