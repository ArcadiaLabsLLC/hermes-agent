"""The ``launcher_beat`` op's wire shape: the frozen value a beat parses into.

Contract: ``docs/agent-runtime-harness/planned/launcher-mutual-supervision-2026-10-27.md`` §2,
confirming the launcher's ``EterniaLauncher/docs/mission_control/planned/LAUNCHER_HARNESS_SUPERVISION_2026-10-27.md``
unchanged. A beat is ``{"op": "launcher_beat", seq, pid, state, window_visible, executable, build,
supervise[, game]}``; a field this module cannot read refuses the WHOLE beat (``invalid_launcher_beat``
naming the field) rather than supervising on a guess.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__layer__ = "models"

__all__ = ["BeatRefused", "LauncherBeat", "LauncherState", "parse_beat"]


class LauncherState(StrEnum):
    """What the launcher says it is doing, on every beat."""

    RUNNING = "running"
    SUSPENDED = "suspended"
    CLOSING_FOR_GAME = "closing_for_game"
    QUITTING = "quitting"


#: The states a ``game`` object may ride (§2: ``closing_for_game``, and hermes also accepts ``suspended``).
_GAME_STATES = frozenset({LauncherState.CLOSING_FOR_GAME, LauncherState.SUSPENDED})


@dataclass(frozen=True, slots=True)
class LauncherBeat:
    seq: int
    pid: int
    state: LauncherState
    window_visible: bool
    executable: str
    build: Any
    supervise: bool
    game: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class BeatRefused:
    """A beat this runtime will not act on; ``field`` names the first unreadable one."""

    field: str
    detail: str


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_beat(message: Mapping[str, Any]) -> LauncherBeat | BeatRefused:
    """One beat frame → :class:`LauncherBeat`, or the :class:`BeatRefused` naming why not."""

    seq, pid = _int(message.get("seq")), _int(message.get("pid"))
    if seq is None or seq < 0:
        return BeatRefused("seq", "seq is a non-negative integer")
    if pid is None or pid <= 0:
        return BeatRefused("pid", "pid is a positive integer")
    try:
        state = LauncherState(message.get("state"))
    except ValueError:
        return BeatRefused("state", f"state is one of {sorted(member.value for member in LauncherState)}")
    for name in ("window_visible", "supervise"):
        if not isinstance(message.get(name), bool):
            return BeatRefused(name, f"{name} is a boolean")
    executable = message.get("executable")
    if not isinstance(executable, str) or not executable.strip():
        return BeatRefused("executable", "executable is the running launcher's absolute path")
    game = message.get("game")
    if game is not None and (not isinstance(game, Mapping) or state not in _GAME_STATES):
        return BeatRefused("game", "game is an object, sent only with closing_for_game or suspended")
    return LauncherBeat(seq=seq, pid=pid, state=state, window_visible=message["window_visible"],
                        executable=executable, build=message.get("build"),
                        supervise=message["supervise"], game=game)
