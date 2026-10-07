"""Hermes-owned guidance for observing admitted work and retrying a busy root.

Observation expiry ends client observation only. It never abandons a turn.
"""
from __future__ import annotations

__layer__ = "policy"

BUSY_RETRY_AFTER_MS = 250
NEXT_CHECK_AFTER_MS = 5000
OBSERVATION_BUDGET_MS = 30 * 60 * 1000


def chat_observation_guidance(*, terminal: bool = False) -> dict:
    return {
        "next_check_after_ms": None if terminal else NEXT_CHECK_AFTER_MS,
        "observation_budget_ms": OBSERVATION_BUDGET_MS,
        "observation_expiry_action": "detach",
    }
