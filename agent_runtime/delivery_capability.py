"""Explicit async-delivery declarations over upstream's session contextvar.

Upstream's ``gateway.session_context`` owns ``_SESSION_ASYNC_DELIVERY`` and its
``_UNSET`` sentinel and exposes ``declare_stateless_channel`` /
``async_delivery_supported``. The harness needs the other two halves — a
positive declaration and "was it declared at all" — so they live here and read
the same contextvar. Importing the two module-private names edits no upstream
file; they retire with a two-function upstream PR (ledger row
``gateway/session_context.py``).
"""

from __future__ import annotations

from gateway.session_context import _SESSION_ASYNC_DELIVERY, _UNSET


def declare_async_delivery_channel() -> None:
    """Declare that this session CAN receive an async background completion.

    The symmetric partner of ``declare_stateless_channel``: "True by default" and
    "True because a drain is actually running" are different facts that
    ``async_delivery_supported`` cannot tell apart. A caller uses this only when
    it can name the consumer that will do the delivering (serve's
    dispatch-delivery drain). Like its counterpart, it does NOT latch
    ``_session_context_engaged``.
    """
    _SESSION_ASYNC_DELIVERY.set(True)


def async_delivery_declared() -> bool:
    """Whether this session EXPLICITLY declared its delivery capability.

    ``async_delivery_supported`` answers True for an unbound session — "nobody
    said" and "yes, a consumer exists" come back as one answer. A caller about to
    make a DURABLE promise on a lane it does not control reads the silence as a
    no. Same contextvar, read for whether it was bound at all.
    """
    return _SESSION_ASYNC_DELIVERY.get() is not _UNSET
