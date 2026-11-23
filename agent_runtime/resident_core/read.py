"""A one-shot hydrate answered from the resident core, never from a build of its own.

``harness stream --max-frames 1`` (Eternia's forced refresh and its resync) and a
hub generation's boot hydrate both used to start, or ride, a full build: 3-10 s,
9.2 s once on the owner's box. With the resident core held and applied through
the log's end, the answer is the held core, at once. Applied only up to an
earlier offset, the reader waits for the hub's pending apply — milliseconds for a
patch, the hub's own build for a demote — and never builds beside it. With no
resident core, or no live producer to apply the gap, the caller builds as before.

At launch, before any full core is held, a one-shot is answered from the SAVED
core, labeled stale, while the boot's rebuild runs behind it — the first launch
after a hermes update shows the agent list at once instead of after a 9-18 s
build (row RT-FU-ETERNIA-SHOWS-THE-SAVED-AGENT-LIST-AT-LAUNCH-EVEN-AFTER-AN-UPDATE).
The saved core is refused only for a schema, root or home change
(``core_cache.read.STALE_PAINTABLE_REASONS``), and it seeds the resident slot
(``holder.seed_saved``) until the hub's first full core replaces it.
"""

from __future__ import annotations

from typing import Any

from .holder import (
    BUILD_ROLE_RESIDENT,
    logger,
    producer_live,
    resident_core_enabled,
    root_held,
    seed_saved,
    wait_through,
)

__layer__ = "lanes"

__all__ = ["BUILD_ROLE_SAVED", "PENDING_APPLY_WAIT_S", "answer_hydrate"]

#: A ``snapshot_build`` receipt's role for a one-shot answered from the saved core.
BUILD_ROLE_SAVED = "saved"

#: How long a one-shot waits for the hub to apply up to the log's end: past a
#: demote build's worst seen (10 s), short of Eternia's 20 s hydrate deadline.
PENDING_APPLY_WAIT_S = 12.0

#: The hub's own boot does not wait: the producer that would apply the gap is
#: the one booting.
_NO_WAIT_CALLERS = frozenset({"hub"})


def _saved_core_at_launch(caller: str) -> dict[str, Any] | None:
    """The launch's saved core, stale, while the rebuild runs; else ``None``.

    Both conditions are the boot window's: the cache lane is armed until this
    process completes a full build, and a build is in flight to replace what is
    painted. A process with no rebuild running (a plain CLI one-shot) builds.
    """

    from ..core_cache import lane as cache_lane
    from ..snapshot.build import build_in_flight

    # MUTATION: drop ``build_in_flight()`` and
    # test_a_one_shot_with_no_rebuild_running_builds_rather_than_paint_the_saved_core reddens.
    if not cache_lane.lane_armed() or not build_in_flight():
        return None
    held = root_held()
    if held is not None and held.stale:
        return held.core
    core = cache_lane.take_stale_first_core(caller=caller)
    if core is None:
        return None
    seed_saved(core)
    return core


def answer_hydrate(
    *, caller: str, build_info: dict[str, Any] | None, one_shot: bool = False
) -> dict[str, Any] | None:
    """The resident core when it is applied through the log's end now (or after
    the pending apply); for a one-shot at launch, the saved core while the
    rebuild runs; else ``None`` and the caller builds."""

    if not resident_core_enabled():
        return None
    from ..parity import events_position
    from ..snapshot.build_log import _record_build_info

    held = root_held()
    if one_shot and (held is None or held.stale):
        # MUTATION: drop this arm and
        # test_a_one_shot_at_launch_after_an_update_is_the_saved_core_marked_stale reddens.
        saved = _saved_core_at_launch(caller)
        if saved is not None:
            _record_build_info(build_info, role=BUILD_ROLE_SAVED, caller=caller, generation=None, snapshot=saved)
            return saved
    floor = events_position().get("event_offset")
    if floor is None or held is None or held.stale:
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
