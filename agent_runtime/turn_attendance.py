"""Whether a person is reading the Mission Control chat turn that is running (RT-MC-TURN-READS-UNATTENDED).

Upstream decides attendance from the session source (``agent.session_source.is_attended``:
``tui`` / ``desktop`` / ``cli`` / ``acp``). A Mission Control chat turn builds its agent with
``platform="tool"`` (``persona_runtime.PERSONA_CHAT_SCRATCH_SOURCE``) and sets no session source, so
every console turn read as UNATTENDED — and the free tier's ``free_tier_cooldown_ends_turn`` slept a
1069 s cooldown on a turn the operator was watching stream in the Agent Console.

The chat lane knows who asked for the turn (``requested_by``) and binds the answer for the turn's
width; ``is_attended`` reads it through one fork seam. Ruling (2026-11-02, lane w1101f-h): a turn a
PERSON asked for is attended — the console (``launcher``, ``operator``), the argv default
(``cli``), a paired device (``dev_<hex>``). A machine-origin turn is not: every machine provenance
is a ``<kind>:`` prefix (``agent:`` relays, ``harness-delivery:``, ``lens-episode:``, ``work:``,
``schedule:``, ``messaging:``, ``discussion:``, ``coordinator:``).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

__layer__ = "policy"
__all__ = ["attended_for_requester", "attended_override", "attended_turn"]

_ATTENDED: ContextVar[bool | None] = ContextVar("mission_chat_turn_attended", default=None)
#: ``<kind>:`` — the shape of every machine provenance a chat turn's ``requested_by`` carries.
_MACHINE_ORIGIN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*:")


def attended_for_requester(requested_by: object) -> bool:
    """True when a person asked for the turn; False for a machine origin or no requester at all."""

    text = requested_by.strip() if isinstance(requested_by, str) else ""
    return bool(text) and _MACHINE_ORIGIN.match(text) is None


def attended_override() -> bool | None:
    """The bound answer for the running turn; None outside a chat turn (upstream's rule decides)."""

    return _ATTENDED.get()


@contextmanager
def attended_turn(attended: bool | None) -> Iterator[None]:
    """Bind the turn's attendance for the width of the block (None binds nothing)."""

    token = _ATTENDED.set(attended)
    try:
        yield
    finally:
        _ATTENDED.reset(token)
