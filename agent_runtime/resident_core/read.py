"""A one-shot hydrate answered from the resident core, never from a build of its own.

``harness stream --max-frames 1`` (Eternia's forced refresh and its resync) and a
hub generation's boot hydrate both used to start, or ride, a full build: 3-10 s,
9.2 s once on the owner's box. With the resident core held and applied through
the log's end, the answer is the held core, at once. Applied only up to an
earlier offset, the reader waits for the hub's pending apply — milliseconds for a
patch, the hub's own build for a demote — and never builds beside it. With no
resident core, or no live producer to apply the gap, the caller builds as before.
"""

from __future__ import annotations

from typing import Any

from .holder import BUILD_ROLE_RESIDENT, logger, producer_live, resident_core_enabled, root_held, wait_through

__layer__ = "lanes"

__all__ = ["PENDING_APPLY_WAIT_S", "answer_hydrate"]

#: How long a one-shot waits for the hub to apply up to the log's end: past a
#: demote build's worst seen (10 s), short of Eternia's 20 s hydrate deadline.
PENDING_APPLY_WAIT_S = 12.0

#: The hub's own boot does not wait: the producer that would apply the gap is
#: the one booting.
_NO_WAIT_CALLERS = frozenset({"hub"})


def answer_hydrate(*, caller: str, build_info: dict[str, Any] | None) -> dict[str, Any] | None:
    """The resident core when it is applied through the log's end now (or after
    the pending apply), else ``None`` and the caller builds."""

    if not resident_core_enabled():
        return None
    from ..parity import events_position
    from ..snapshot.build_log import _record_build_info

    floor = events_position().get("event_offset")
    held = root_held()
    if floor is None or held is None:
        return None
    wait_s = 0.0 if caller in _NO_WAIT_CALLERS or not producer_live() else PENDING_APPLY_WAIT_S
    resident = held if held.offset >= floor else wait_through(int(floor), wait_s)
    if resident is None:
        logger.info(
            "resident_core miss caller=%s floor=%d held=%d waited_s=%.1f", caller, floor, held.offset, wait_s
        )
        return None
    _record_build_info(build_info, role=BUILD_ROLE_RESIDENT, caller=caller, generation=None, snapshot=resident.core)
    return resident.core
