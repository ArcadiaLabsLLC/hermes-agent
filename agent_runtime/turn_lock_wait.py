"""The ``turn_root_lock_wait`` receipt: how long a chat turn waited for its chat's run lock, and on what.

A chat root runs one thing at a time (``profile_runner.workdir.root_run_lock``). The first message
in a new chat used to wait seconds on that lock with nothing in ``agent.log`` naming the wait: the
chat's prewarm held it while it built the agent (owner 2026-11-23, row
``RT-FU-THE-FIRST-MESSAGE-IN-A-NEW-CHAT-STARTS-WITHOUT-A-THREE-SECOND-WAIT``; read 21:43:47-56: 9.1 s
from accept to the prewarm's ``phase=agent_acquired`` stand-down). One INFO line per turn that
waited, keyed like every other turn receipt: ``turn`` is the client message id, ``root`` the chat.
``held_by`` is what held the lock when the turn arrived (``prewarm`` / ``turn`` / ``run``);
``stage`` is the turn's step that waited (``acquire``: the agent before the submit; ``converse``:
the conversation itself). Timings and ids only; observability lands as a log receipt.
"""

from __future__ import annotations

import logging
from typing import Any

__layer__ = "policy"

logger = logging.getLogger(__name__)

TURN_ROOT_LOCK_WAIT_RECEIPT = "turn_root_lock_wait root=%s turn=%s stage=%s waited_ms=%d held_by=%s"
#: A wait under this is the lock's own cost, not a wait on anything.
MIN_WAIT_MS = 5


def log_root_lock_wait(request: Any, *, stage: str) -> None:
    """Receipt the run lock wait this thread just paid, for a real turn (never a prewarm)."""

    if getattr(request, "prewarm_only", False):
        return
    from agent_runtime.profile_runner.workdir import last_root_lock_wait

    waited_ms, held_by = last_root_lock_wait()
    if waited_ms < MIN_WAIT_MS:
        return
    logger.info(
        TURN_ROOT_LOCK_WAIT_RECEIPT,
        getattr(request, "root_chat_session_id", None) or "-",
        getattr(request, "client_message_id", None) or getattr(request, "turn_id", None) or "-",
        stage,
        waited_ms,
        held_by or "-",
    )
