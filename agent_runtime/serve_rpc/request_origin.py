"""Who in Eternia asked: a request's optional ``origin``, carried onto the serve's lane receipts.

Row ``RT-FU-EVERY-REQUEST-SAYS-WHO-IN-ETERNIA-ASKED-AND-HOW-LONG-IT-WAITED``. The owner's
``agent.log`` named a slow request by its method alone, so the 15-20 reads around one send could
not be traced to the Eternia action that set them off. A JSON-RPC request may now carry, beside
``params``, an ``origin`` object of ids only — ``{"action": <id>, "caller": <provider or port tag>,
"trigger": "user:<action>" | "frame" | "event:<kind>" | "timer:<name>" | "invalidate:<site>"}``
(Eternia's recorder, launcher ``MC-AGENT-VIEWS-EVERY-CALL-TO-HERMES-IS-RECORDED-WITH-WHO-ASKED-AND-WHY``).

It rides the ENVELOPE, never ``params``, so no method's parameter checks see it, a request without
it is unchanged, and an older serve ignores the member. :func:`origin_token` reduces it to one
bounded log token (``<action>/<caller>/<trigger>``, each part at most :data:`PART_LIMIT` characters
of ``[A-Za-z0-9_.:-]``, anything else ``_``; ``-`` for an absent part); never text, never params.
:func:`handle_request` sets it for the handler's thread (:func:`origin_scope`), and
``protocol.deferred_reply`` stamps it on the deferred build, so the worker lane's
``shared_lane_slow`` / ``lane_held_for_turn`` lines and the per-minute ``lane_rollup`` name it.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

__layer__ = "lanes"

__all__ = ["NO_ORIGIN", "PART_LIMIT", "current_origin", "origin_scope", "origin_token"]

#: The token a request without an origin logs.
NO_ORIGIN = "-"
#: Each part's bound, in characters.
PART_LIMIT = 64
_PARTS = ("action", "caller", "trigger")
_UNSAFE = re.compile(r"[^A-Za-z0-9_.:\-]")

_current: ContextVar[str] = ContextVar("serve_rpc_request_origin", default=NO_ORIGIN)


def origin_token(req: Any) -> str:
    """``req``'s ``origin`` as one log token, or :data:`NO_ORIGIN` when it carries none usable."""

    origin = req.get("origin") if isinstance(req, dict) else None
    if not isinstance(origin, dict):
        return NO_ORIGIN
    parts = [_part(origin.get(name)) for name in _PARTS]
    if all(part == NO_ORIGIN for part in parts):
        return NO_ORIGIN
    return "/".join(parts)


def _part(value: Any) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return NO_ORIGIN
    # MUTATION: drop the substitution and test_an_origin_is_reduced_to_one_bounded_token reddens.
    text = _UNSAFE.sub("_", str(value).strip())[:PART_LIMIT]
    return text or NO_ORIGIN


def current_origin() -> str:
    """The origin token of the request this thread is answering (:data:`NO_ORIGIN` outside one)."""

    return _current.get()


@contextmanager
def origin_scope(token: str) -> Iterator[None]:
    reset = _current.set(token or NO_ORIGIN)
    try:
        yield
    finally:
        _current.reset(reset)
