"""The harness query package: one read-only core for roster / instance / sessions / live QA.

Owner rows: hermes ``runtime-queue.md`` HQ1 (the core, the tool, the verb) and
HQ2 (the skill that routes agents to it). Evidence: launcher
``docs/mission_control/SIX_SCREENSHOT_FINDINGS_2026-10-01.md`` F1-F5 — a lookup
turn spent 126 s on three 907 KB snapshots and then claimed a QA session no
receipt named.

Modules (lowest first):

* ``core`` (lanes) — the four questions, answered from the first-class readers.
* ``serve_route`` (lanes) — carries a CLI's question to the running serve,
  which alone observes hot/busy/cold.

Doors onto it: the in-turn tool ``harness_query`` (``tools/harness_query_tool.py``,
in-process, so it is the serve answering whenever the turn runs in the serve)
and the verb ``hermes harness query`` (serve first, direct read otherwise).
Stores written: none.
"""

from __future__ import annotations

from typing import Any

from .core import LIVE_RUNTIME_STATES, QA_PERSONA_ID, QUESTIONS, answer, observer, resolve_instance
from .serve_route import query_argv, query_via_serve

__layer__ = "lanes"

__all__ = [
    "LIVE_RUNTIME_STATES",
    "QA_PERSONA_ID",
    "QUESTIONS",
    "answer",
    "answer_routed",
    "observer",
    "query_argv",
    "query_via_serve",
    "resolve_instance",
]


def answer_routed(
    question: str, *, instance: str | None = None, limit: int | None = None, direct: bool = False
) -> dict[str, Any]:
    """The serve's answer when one is live, else this process's; ``answered_by`` says which."""

    if not direct:
        payload, answered_by = query_via_serve(question, instance, limit)
        if payload is not None:
            return {**payload, "answered_by": answered_by}
    else:
        answered_by = {"lane": "direct_read", "serve_fallback": "direct_requested"}
    return {**answer(question, instance=instance, limit=limit), "answered_by": answered_by}
