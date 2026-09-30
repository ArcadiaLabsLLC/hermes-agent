"""``harness_core`` — the ONE toolset an Eternia persona profile declares, defined by the fork.

It used to be a literal appended to upstream's ``toolsets.py``; since lane h11-fp (2026-09-29) it
is registered through upstream's own public door, ``toolsets.create_custom_toolset``, so
``toolsets.py`` keeps upstream's bytes. Membership is by toolset, so a tool registered into one of
these later joins without an edit here. :func:`ensure_harness_core` is idempotent and is called by
everything that reads the name: the eternia-harness plugin's ``register`` (every process that
resolves tools discovers plugins first), :mod:`agent_runtime.toolset_names` (the static name
expansion the serve's persona prewarm reads without importing ``model_tools``) and the bundle
profile validator.
"""

from __future__ import annotations

__layer__ = "models"
__all__ = ["HARNESS_CORE", "HARNESS_CORE_INCLUDES", "ensure_harness_core"]

HARNESS_CORE = "harness_core"

_DESCRIPTION = (
    "Mission Control harness lane: the fork's agent-to-agent chat and board tools plus the "
    "conversational core. The ONE toolset an Eternia persona profile declares; integrations "
    "(spotify, discord, homeassistant, yuanbao, bfl, video_gen, computer_use, cronjob, image_gen) "
    "are opt-in by name beside it. Membership is by toolset so a tool registered into one of "
    "these later joins without an edit here."
)

HARNESS_CORE_INCLUDES: tuple[str, ...] = (
    "agent_chat", "board", "clarify", "delegation", "terminal", "file", "web", "browser",
    "browser-cdp", "skills", "memory", "todo", "session_search", "vision", "code_execution",
)


def ensure_harness_core() -> None:
    """Define ``harness_core`` in upstream's ``TOOLSETS`` unless it is already there."""
    import toolsets

    if HARNESS_CORE not in toolsets.TOOLSETS:
        toolsets.create_custom_toolset(HARNESS_CORE, _DESCRIPTION, [], list(HARNESS_CORE_INCLUDES))
