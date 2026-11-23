"""The ONE resident core a serve keeps, and the offset it is applied through.

Seeded from every full core the serve hub fans out (a ``hydrate``, a ``delta``,
the core half of a ``fold_variants`` envelope) and moved by every frame the hub
fans out after it, by the rules Eternia folds them by (:mod:`.fold`). A frame
that does not chain from the held offset, or that the fold cannot apply, DROPS
the core until the next full one: the resident is either exactly what a fold
client holds or absent, never a guess.

Behind ``snapshot.resident_core`` (default off) until it is read live.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from .fold import apply_patch_row, apply_persona_chat_turn, apply_running_work_section

__layer__ = "lanes"

__all__ = [
    "BUILD_ROLE_RESIDENT",
    "ResidentCore",
    "drop",
    "held",
    "observe",
    "producer_live",
    "resident_core_enabled",
    "root_held",
    "wait_through",
]

logger = logging.getLogger("agent_runtime.resident_core")

_FRAME_HYDRATE = "hydrate"
_FRAME_DELTA = "delta"
_FRAME_PATCH = "patch"
_FRAME_TURN = "persona_chat_turn"
_FRAME_RUNNING_WORK = "running_work"
_FRAME_FOLD_VARIANTS = "fold_variants"

#: A ``snapshot_build`` receipt's role for a core answered from the resident one.
BUILD_ROLE_RESIDENT = "resident"

#: The hub beats every 5 s while idle; a producer silent for two beats is gone,
#: and a reader must not wait for an apply nobody will make.
_PRODUCER_LIVE_S = 10.0

#: When the hub last handed ``observe`` a frame, any frame (monotonic seconds).
_last_seen = 0.0


def resident_core_enabled() -> bool:
    """``snapshot.resident_core`` in the serve's config; off unless set."""

    from hermes_cli.config_switches import config_switch

    return config_switch("snapshot", "resident_core", default=False)


@dataclass(frozen=True)
class ResidentCore:
    """A held core and the stream offset it is applied through.

    ``core`` is never mutated after it is held: a fold builds the next core by
    copy-on-write, so a reader that was handed one keeps a consistent copy.
    """

    core: dict[str, Any]
    offset: int
    source: str
    seeded_at: float


class _Holder:
    def __init__(self) -> None:
        self._changed = threading.Condition(threading.Lock())
        self._by_root: dict[str, ResidentCore] = {}

    def held(self, root: str) -> ResidentCore | None:
        with self._changed:
            return self._by_root.get(root)

    def put(self, root: str, resident: ResidentCore | None) -> None:
        with self._changed:
            if resident is None:
                self._by_root.pop(root, None)
            else:
                self._by_root[root] = resident
            self._changed.notify_all()

    def wait_through(self, root: str, floor: int, timeout_s: float) -> ResidentCore | None:
        """The held core once it is applied through ``floor``, or ``None`` at the deadline."""

        deadline = time.monotonic() + max(0.0, timeout_s)
        with self._changed:
            while True:
                resident = self._by_root.get(root)
                if resident is not None and resident.offset >= floor:
                    return resident
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._changed.wait(remaining)


_HOLDER = _Holder()


def _root_key() -> str:
    from agent_runtime import paths

    return str(paths.store_root())


def held() -> ResidentCore | None:
    """This profile root's resident core, or ``None``."""

    return _HOLDER.held(_root_key())


root_held = held


def producer_live() -> bool:
    """Whether a hub producer handed ``observe`` a frame in the last two beats."""

    return time.monotonic() - _last_seen < _PRODUCER_LIVE_S


def wait_through(floor: int, timeout_s: float) -> ResidentCore | None:
    return _HOLDER.wait_through(_root_key(), floor, timeout_s)


def drop(reason: str) -> None:
    """Forget this root's resident core until the next full one, and say why."""

    root = _root_key()
    had = _HOLDER.held(root)
    _HOLDER.put(root, None)
    if had is not None:
        logger.info("resident_core drop reason=%s offset=%d", reason, had.offset)


def _frame_offset(frame: dict[str, Any]) -> int | None:
    watermark = frame.get("watermark")
    value = watermark.get("event_offset") if isinstance(watermark, dict) else None
    return None if value is None or isinstance(value, bool) else int(value)


def _is_stale(core: dict[str, Any]) -> bool:
    parity = core.get("parity") if isinstance(core.get("parity"), dict) else {}
    freshness = parity.get("freshness") if isinstance(parity.get("freshness"), dict) else {}
    return freshness.get("state") == "stale" or parity.get("core_stale") is True


def _seed(root: str, frame: dict[str, Any]) -> None:
    core = frame.get("core")
    offset = _frame_offset(frame)
    if not isinstance(core, dict) or offset is None or _is_stale(core):
        # A stale-first core is not authority, and a core with no position cannot
        # be chained from: either way nothing is held until a full one is.
        _HOLDER.put(root, None)
        return
    _HOLDER.put(root, ResidentCore(core=core, offset=offset, source=str(frame.get("type")), seeded_at=time.monotonic()))


def _stamped(core: dict[str, Any], frame: dict[str, Any], offset: int) -> dict[str, Any]:
    """``core`` with the frame's position as its own: ``parity.watermark`` and
    ``event_log_bytes``, exactly what a build at that offset would carry."""

    parity = core.get("parity") if isinstance(core.get("parity"), dict) else {}
    watermark = frame.get("watermark") if isinstance(frame.get("watermark"), dict) else {}
    return {**core, "parity": {**parity, "watermark": dict(watermark), "event_log_bytes": offset}}


def _fold_patch(working: dict[str, Any], frame: dict[str, Any]) -> str | None:
    for row in frame.get("patches") or ():
        hazard = apply_patch_row(working, row) if isinstance(row, dict) else "patch_malformed:row"
        if hazard is not None:
            return hazard
    return None


#: The sequenced frames a fold client consumes, and how each moves the core.
_FOLDS = {
    _FRAME_PATCH: _fold_patch,
    _FRAME_TURN: apply_persona_chat_turn,
    _FRAME_RUNNING_WORK: apply_running_work_section,
}


def _fold(held_core: ResidentCore, frame: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """The core after ``frame``, or the hazard that stops it."""

    fold = _FOLDS.get(frame.get("type"))
    if fold is None:
        return None, f"unknown_frame:{frame.get('type')}"
    working = dict(held_core.core)
    hazard = fold(working, frame)
    return (None, hazard) if hazard is not None else (working, None)


def observe(frame: dict[str, Any]) -> None:
    """One frame the hub fans out, applied to the resident core. Never raises."""

    global _last_seen
    _last_seen = time.monotonic()
    try:
        _observe(frame)
    except Exception:  # health: allow BLE001 -- an instrument beside the fan-out must not stop it
        logger.warning("resident_core observe failed; dropping", exc_info=True)
        try:
            drop("observe_failed")
        except Exception:  # health: allow BLE001 -- see above
            pass


def _observe(frame: dict[str, Any]) -> None:
    if isinstance(frame, dict):
        _OBSERVERS.get(frame.get("type"), _observe_sequenced)(frame)


def _observe_variants(frame: dict[str, Any]) -> None:
    """The core half is exact when it IS a core; a heartbeat there (a two-root
    turn batch's first envelope) leaves the patch half as the batch's carrier."""

    core_half = frame.get("core")
    if isinstance(core_half, dict) and isinstance(core_half.get("core"), dict):
        _observe(core_half)
    elif isinstance(frame.get("patch"), dict):
        _observe(frame["patch"])


def _observe_core(frame: dict[str, Any]) -> None:
    _seed(_root_key(), frame)


def _observe_running_work(frame: dict[str, Any]) -> None:
    """The sequenced section folds like a patch; the ``as_of_offset`` overlay is a
    section read now that moves no position, so it replaces the section in place."""

    if "base_offset" in frame:
        _observe_sequenced(frame)
        return
    root = _root_key()
    held_core = _HOLDER.held(root)
    if held_core is not None and isinstance(frame.get("running_work"), dict):
        _HOLDER.put(root, ResidentCore(
            core={**held_core.core, "running_work": frame["running_work"]},
            offset=held_core.offset, source=held_core.source, seeded_at=held_core.seeded_at,
        ))


def _observe_sequenced(frame: dict[str, Any]) -> None:
    """A frame carrying ``base_offset``: folded when it chains from the held offset."""

    if "base_offset" not in frame:
        return  # a heartbeat, or a frame that moves no position
    root = _root_key()
    held_core = _HOLDER.held(root)
    if held_core is None:
        return
    offset = _frame_offset(frame)
    base = frame.get("base_offset")
    if offset is None or not isinstance(base, int) or base != held_core.offset:
        drop(f"gap:base={base} held={held_core.offset}")
        return
    started = time.perf_counter()
    folded, hazard = _fold(held_core, frame)
    if folded is None:
        drop(hazard or "fold_failed")
        return
    _HOLDER.put(root, ResidentCore(
        core=_stamped(folded, frame, offset), offset=offset, source=held_core.source, seeded_at=held_core.seeded_at,
    ))
    logger.debug(
        "resident_core fold type=%s offset=%d rows=%d ms=%.1f",
        frame.get("type"),
        offset,
        len(frame.get("patches") or ()),
        (time.perf_counter() - started) * 1000,
    )


_OBSERVERS = {
    _FRAME_FOLD_VARIANTS: _observe_variants,
    _FRAME_HYDRATE: _observe_core,
    _FRAME_DELTA: _observe_core,
    _FRAME_RUNNING_WORK: _observe_running_work,
}
