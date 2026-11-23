"""Which agents a build readies: Home's agent, and every agent someone asked for.

Owner ruling 2026-11-22: "Agent readiness it should only ready the first one in
the drop down and then the rest on first message". Readiness here means the two
halves of the snapshot's ``agents_readiness`` section — the readiness walk
(``profile_readiness_for_persona``) and the tool-visibility resolve — which a
cold first build paid for EVERY agent (5.3-7.3 s on the owner's box, rows
RT-FU-THE-FIRST-AGENT-LIST-AFTER-AN-UPDATE-WAITS-SEVEN-SECONDS-ON-AGENT-READINESS
and RT-FU-PERSONA-PREWARM-PAYS-SECONDS-FOR-EVERY-AGENT-TYPE).

* :func:`home_agent_persona_id` is the ONE ordering of Home's agent — Neko Mission
  Lead, else Base, else the only agent. Eternia reads its answer off the
  ``home_agent`` key of that agent's row and keeps no ordering of its own.
* :func:`mark_readied` is the demand: ``runtime.persona.prewarm`` (Eternia sends
  it when an agent is selected or opened) and a chat turn's admission call it.
  It is state, not a cache: it says only which agents were asked for, and the
  serve's process holds it for its life.
* A build walks Home's agent and the readied set; every other agent's row says
  ``not_checked`` (:data:`READINESS_NOT_CHECKED`), which Eternia renders as
  "Not checked yet", available and neutral — never as a problem.

The snapshot worker builds in another process, so the serve hands it the set on
every build request (:func:`readied_for_worker`) and the worker reads it back
through :func:`recorded_readied`.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from .process_state import register_process_state

__layer__ = "stores"

#: The readiness of an agent no one has asked for yet. Not a problem and not a
#: verdict: its row carries no walk and no tool resolution.
READINESS_NOT_CHECKED = "not_checked"
READINESS_NOT_CHECKED_SUMMARY = "Not checked yet"

#: Home's agent, in this order (owner 2026-11-19 for Neko first; 2026-11-22 for
#: hermes owning the pick).
NEKO_PERSONA_ID = "neko_supervisor"
BASE_PERSONA_ID = "base"

_LOCK = threading.Lock()
_READIED: set[str] = set()
_RECORDED: ContextVar[frozenset[str] | None] = ContextVar("readied_recorded", default=None)


def home_agent_candidates(personas: Sequence[Any]) -> list[Any]:
    """Home's agent candidates in the one order: Neko, else Base, else the only agent."""

    def pid(persona: Any) -> str:
        return str(getattr(persona, "id", "") or "")

    neko = [p for p in personas if pid(p) == NEKO_PERSONA_ID]
    base = [
        p for p in personas
        if pid(p) == BASE_PERSONA_ID or str(getattr(p, "hermes_profile", "") or "") == BASE_PERSONA_ID
    ]
    only = list(personas) if len(personas) == 1 else []
    seen: set[str] = set()
    ordered: list[Any] = []
    for persona in (*neko, *base, *only):
        if pid(persona) not in seen:
            seen.add(pid(persona))
            ordered.append(persona)
    return ordered


def home_agent_persona_id(personas: Sequence[Any]) -> str | None:
    """The agent Home starts on and the build readies at boot: the first candidate.

    Not readiness-dependent on purpose: a build, a patch and a worker all answer
    it from the persona list alone, so the ``home_agent`` mark cannot move
    between a core and a patch. An unready Home agent shows its problem in
    Eternia's picker rather than Home silently starting on another agent.
    """

    candidates = home_agent_candidates(personas)
    return str(getattr(candidates[0], "id", "") or "") or None if candidates else None


def mark_readied(persona_id: str) -> bool:
    """Ask for ``persona_id``'s readiness from now on; ``True`` when it was not asked for before."""

    text = str(persona_id or "").strip()
    if not text:
        return False
    with _LOCK:
        if text in _READIED:
            return False
        _READIED.add(text)
        return True


def readied_for_worker() -> list[str]:
    """The readied set, as a snapshot worker's build request carries it."""

    with _LOCK:
        return sorted(_READIED)


def readied_persona_ids() -> frozenset[str]:
    """The agents asked for: the serve's own set, or the one a worker build was handed."""

    recorded = _RECORDED.get()
    if recorded is not None:
        return recorded
    with _LOCK:
        return frozenset(_READIED)


@contextmanager
def recorded_readied(ids: Iterable[str] | None) -> Iterator[None]:
    """Build with the serve's readied set (the worker's side); ``None`` = this process's own."""

    token = _RECORDED.set(None if ids is None else frozenset(str(i) for i in ids))
    try:
        yield
    finally:
        _RECORDED.reset(token)


def not_checked_readiness() -> dict[str, Any]:
    """The readiness row of an agent nobody asked for yet."""

    return {
        "readiness": READINESS_NOT_CHECKED,
        "summary": READINESS_NOT_CHECKED_SUMMARY,
        "missing_skills": [],
        "effective_required_mcp_servers": [],
        "missing_mcp_servers": [],
        "skill_hash_mismatches": [],
        "skill_hash_absent": [],
    }


def _reset() -> None:
    with _LOCK:
        _READIED.clear()


register_process_state(__name__, _reset, holds=("_READIED",))
