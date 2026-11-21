"""The conversation worker: upstream's engine, served in THIS process for every profile.

The worker child (``python -m agent_runtime.conversations.worker_entry``) is retired
(RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT, RULED 2026-11-21 "One engine").
"""
from __future__ import annotations

__layer__ = "lanes"


def select_worker_factory():
    """The worker factory: the in-process worker, on every profile (``RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-
    INTELLIGENCE-CHAT``, RULED 2026-11-21 "One engine": the conversations run on upstream's engine inside the
    serve, as on the phone). ``conversations.subprocess_worker`` is retired: no ``worker_entry`` child."""
    from .in_process_peer import start_in_process_worker

    return start_in_process_worker
