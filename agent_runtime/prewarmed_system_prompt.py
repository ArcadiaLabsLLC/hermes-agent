"""The system prompt a chat-actor prewarm builds, and the first turn that adopts it.

h-turn1 A3 (``docs/agent-runtime-harness/planned/turn-latency-h-turn1-2026-10-05.md``).
A prewarmed resident actor is constructed but carries no prompt: upstream builds
it inside the conversation (``agent/conversation_loop.py::
_restore_or_build_system_prompt``), and with no history that function never
reads the session row, so every first turn paid the 1.1-1.6 s build even on a
warm actor. The prewarm now builds it on the actor it leaves resident
(:func:`stash_prewarmed_system_prompt`) and the first turn adopts it through one
guarded call in that upstream function (:func:`take_prewarmed_system_prompt`).

ONE state, ONE module: the stash is written here and consumed here, always
popped, so a prompt can be adopted at most once and never leaks into a later
turn. It lives in the agent's ``__dict__`` (never read with ``getattr``), so a
``MagicMock`` agent never reads as carrying one.

A stash is adopted only when everything the build took is the same:
* the turn has no history (a first turn — exactly the case upstream builds);
* the turn's ``system_message`` is byte-equal to the one the prewarm built with
  (the chat's surface prompt and workspace content ride it);
* upstream's own runtime-identity check (model, provider, session id, cwd) passes
  on the prompt, as it does for a stored prompt.
Anything else discards it with a ``system_prompt_prewarm_discarded`` receipt, and
upstream builds exactly as it always did.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

__layer__ = "policy"

logger = logging.getLogger(__name__)

_STASH = "_prewarmed_system_prompt"

#: Receipt for a stash the first turn could not use. ``reason`` is one of
#: :data:`DISCARD_REASONS`.
PREWARM_DISCARDED_RECEIPT = "system_prompt_prewarm_discarded session=%s reason=%s"

DISCARD_HISTORY_PRESENT = "history_present"
DISCARD_SYSTEM_MESSAGE_CHANGED = "system_message_changed"
DISCARD_RUNTIME_IDENTITY_CHANGED = "runtime_identity_changed"
DISCARD_REASONS = (
    DISCARD_HISTORY_PRESENT,
    DISCARD_SYSTEM_MESSAGE_CHANGED,
    DISCARD_RUNTIME_IDENTITY_CHANGED,
)

#: ``profile_timing`` key the prewarm writes when it built a prompt.
PREWARM_SYSTEM_PROMPT_BUILD_MS = "prewarm_system_prompt_build_ms"


def stash_prewarmed_system_prompt(
    agent: Any, system_message: Optional[str], timing: dict[str, Any]
) -> bool:
    """Build ``agent``'s first-turn system prompt now and keep it for that turn.

    Called by the prewarm (``AgentRunExecution.run``'s ``prewarm_only`` branch),
    inside the run's scope stack, so the build sees the profile, workdir and MCP
    admission the turn will see. Skipped when the actor already has a prompt (it
    ran a turn) or a stash for the same ``system_message``. Fail-open: a build
    that raises leaves no stash, and the turn builds as it always did.
    """

    if getattr(agent, "_cached_system_prompt", None) is not None:
        return False
    held = vars(agent).get(_STASH)
    if isinstance(held, tuple) and held[0] == system_message:
        return False
    started = time.perf_counter()
    try:
        prompt = agent._build_system_prompt(system_message)
    except Exception:
        logger.debug("prewarm system prompt build failed", exc_info=True)
        vars(agent).pop(_STASH, None)
        return False
    if not isinstance(prompt, str) or not prompt:
        vars(agent).pop(_STASH, None)
        return False
    vars(agent)[_STASH] = (system_message, prompt)
    timing[PREWARM_SYSTEM_PROMPT_BUILD_MS] = max(
        0, int((time.perf_counter() - started) * 1000)
    )
    return True


def take_prewarmed_system_prompt(
    agent: Any,
    system_message: Optional[str],
    conversation_history: Any,
    matches_runtime: Callable[[Any, str], bool],
) -> Optional[str]:
    """The prewarm's prompt for this turn, or None (build as upstream does).

    Always consumes the stash. ``matches_runtime`` is upstream's own
    stored-prompt identity check, passed in by the one call site so this module
    imports no private upstream name.
    """

    try:
        held = vars(agent).pop(_STASH, None)
    except TypeError:
        return None
    if not isinstance(held, tuple) or len(held) != 2:
        return None
    built_with, prompt = held
    reason = None
    if conversation_history:
        reason = DISCARD_HISTORY_PRESENT
    elif built_with != system_message:
        reason = DISCARD_SYSTEM_MESSAGE_CHANGED
    elif not matches_runtime(agent, prompt):
        reason = DISCARD_RUNTIME_IDENTITY_CHANGED
    if reason is not None:
        logger.info(PREWARM_DISCARDED_RECEIPT, getattr(agent, "session_id", None), reason)
        return None
    return prompt


# ── h-turn1-conn: the adopted turn's persist writes go after ``request_sent`` ──
#
# A first turn persists its system prompt and its ``tools[]`` pin to the session
# row before it builds the request (``_persist_system_prompt(...,
# persist_tools=True)``): two write transactions, each with a sweep of the
# content-addressed prompt table, ~30 ms of the turn-cost guard's turn-0 lag
# (stack-sampled: ``update_system_prompt`` + ``update_session_tool_names``) and
# more on a large live store. Nothing on the way to the provider reads them --
# the NEXT turn restores from them. So a turn that adopted a prewarmed prompt
# hands the write here, and it runs when the request is on the wire
# (:func:`run_deferred_turn_persist` from the transport trace's ``request_sent``),
# or when the run ends if no request was ever sent. ONE state, popped once.

_DEFERRED = "_deferred_first_turn_persist"

DEFERRED_PERSIST_RECEIPT = "first_turn_persist_deferred session=%s ran_on=%s elapsed_ms=%d"

RAN_ON_REQUEST_SENT = "request_sent"
RAN_ON_RUN_END = "run_end"


def defer_prewarmed_turn_persist(agent: Any, prewarmed: Optional[str], persist: Callable[[], None]) -> bool:
    """Hold *persist* until the turn's request is sent, when the turn adopted a prewarmed prompt.

    Returns False (the caller persists now, as upstream does) for every turn
    that built its own prompt.
    """

    if prewarmed is None:
        return False
    try:
        vars(agent)[_DEFERRED] = persist
    except TypeError:
        return False
    return True


def run_deferred_turn_persist(agent: Any, ran_on: str = RAN_ON_REQUEST_SENT) -> bool:
    """Run the held persist, once. Never raises; True when one ran."""

    try:
        persist = vars(agent).pop(_DEFERRED, None)
    except TypeError:
        return False
    if persist is None:
        return False
    started = time.perf_counter()
    try:
        persist()
    except Exception:
        logger.warning("deferred first-turn persist failed for session %s", getattr(agent, "session_id", None),
                       exc_info=True)
    elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
    setattr(agent, "_hermes_deferred_persist_ms", elapsed_ms)
    logger.info(DEFERRED_PERSIST_RECEIPT, getattr(agent, "session_id", None), ran_on, elapsed_ms)
    return True


def deferred_turn_persist_duration_ms(agent: Any) -> int | None:
    """The duration from the same measurement used by the persistence receipt."""
    return getattr(agent, "_hermes_deferred_persist_ms", None)


__all__ = [
    "DEFERRED_PERSIST_RECEIPT",
    "RAN_ON_REQUEST_SENT",
    "RAN_ON_RUN_END",
    "defer_prewarmed_turn_persist",
    "run_deferred_turn_persist",
    "DISCARD_REASONS",
    "PREWARM_DISCARDED_RECEIPT",
    "PREWARM_SYSTEM_PROMPT_BUILD_MS",
    "stash_prewarmed_system_prompt",
    "take_prewarmed_system_prompt",
]
