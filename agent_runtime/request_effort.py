"""The reasoning effort an assembled provider request carries, as the one word a receipt logs.

Each transport writes the effort into its own wire shape (``agent/transports/*``,
``agent/anthropic_adapter.py``); this reads the request back rather than re-resolving config, so
the receipt names what was SENT on that call — a fallback re-resolve or a mid-turn switch included.
"""

from __future__ import annotations

from typing import Any, Mapping

__layer__ = "models"

__all__ = ["request_effort"]

#: No effort field on the request: the provider's default applies.
NO_EFFORT = "-"


def _effort_in(reasoning: Any) -> str | None:
    if not isinstance(reasoning, Mapping):
        return None
    if reasoning.get("enabled") is False:
        return "none"
    effort = reasoning.get("effort")
    return str(effort) if effort else None


def _thinking_effort(thinking: Any) -> str | None:
    if not isinstance(thinking, Mapping):
        return None
    kind = str(thinking.get("type") or "")
    if kind == "disabled":
        return "none"
    budget = thinking.get("budget_tokens")
    return f"budget:{budget}" if kind == "enabled" and budget else None


def request_effort(request: Any) -> str:
    """``request``'s reasoning effort: ``low`` / ``high`` / ``none`` / ``budget:<n>``, else ``-``."""
    if not isinstance(request, Mapping):
        return NO_EFFORT
    extra = request.get("extra_body") if isinstance(request.get("extra_body"), Mapping) else {}
    for found in (
        request.get("reasoning_effort") or None,
        _effort_in(request.get("reasoning")),
        _effort_in(extra.get("reasoning")),
        extra.get("reasoning_effort") or None,
        _effort_in(request.get("output_config")),
        _thinking_effort(request.get("thinking")),
    ):
        if found:
            return str(found)
    return NO_EFFORT
