"""h-title-defer: a turn's title upgrade starts at its ``request_sent``, never before (2026-10-06).

``agent.title_generator.maybe_auto_title`` starts the model title upgrade (an ``auto-title``
thread) at the START of turns 1-3, inside the turn's anchor -> ``request_sent`` window: live
2026-10-06 17:05 it began 600-850 ms after the anchor, and it checked a pre-opened socket out of
the process-shared pool the turn's own request was about to want (turn 1 ``conn=new``).

Upstream already holds the thread unstarted when the title call would share a self-hosted
endpoint with the turn (``title_upgrade_must_wait_for_turn``, #117296) and starts it at
``finalize_turn`` (``agent.turn_context.start_deferred_title_upgrade``). The fork holds it the
same way on the one path whose ``request_sent`` it observes -- the Responses stream, where
``agent_runtime.transport_phase_trace`` announces the body leaving the process -- and starts it
there. Upstream's own fallback still starts it at ``finalize_turn`` if no request was sent, so the
title lands within the same turn either way. ONE state: upstream's ``_deferred_title_upgrade``
attribute, a thread this module tags; an untagged hold (upstream's self-hosted one) is left for
``finalize_turn``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

__layer__ = "policy"

logger = logging.getLogger(__name__)

#: The ``api_mode`` whose requests carry the fork's transport trace (``agent/codex_runtime.py``).
TRACED_API_MODE = "codex_responses"
#: Set on an upgrade thread the fork held, so ``request_sent`` starts only those.
_HELD_MARK = "_hermes_start_on_request_sent"

TITLE_STARTED_RECEIPT = "title_upgrade_started session=%s on=request_sent"


def hold_title_upgrade(upgrade: Any, main_runtime: Optional[dict]) -> bool:
    """True (the caller returns *upgrade* unstarted) when the turn's request_sent will start it."""

    try:
        if str((main_runtime or {}).get("api_mode") or "") != TRACED_API_MODE:
            return False
        setattr(upgrade, _HELD_MARK, True)
        return True
    except Exception:
        logger.debug("title upgrade hold skipped", exc_info=True)
        return False


def start_held_title_upgrade(agent: Any) -> bool:
    """Start the title upgrade this module held for *agent*'s turn. Never raises; True when started."""

    try:
        upgrade = getattr(agent, "_deferred_title_upgrade", None)
        if upgrade is None or not getattr(upgrade, _HELD_MARK, False):
            return False
        from agent.turn_context import start_deferred_title_upgrade

        start_deferred_title_upgrade(agent)
        logger.info(TITLE_STARTED_RECEIPT, getattr(agent, "session_id", None))
        return True
    except Exception:
        logger.debug("held title upgrade start failed", exc_info=True)
        return False


__all__ = ["TITLE_STARTED_RECEIPT", "TRACED_API_MODE", "hold_title_upgrade", "start_held_title_upgrade"]
