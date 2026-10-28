"""The bundled harness supervises its launcher (plan ``launcher-mutual-supervision-2026-10-27``).

``contract`` parses the ``launcher_beat`` op, ``policy`` is the pure transition table, ``watchdog``
wires it to the parent watch and the beat clock. Slice W1: beats, the re-targeted watch, and Quit vs
crash vs hang recorded; relaunch (W2), the game watch (G1) and the play-session handback (P1) follow.
"""

from __future__ import annotations

from .contract import BeatRefused, LauncherBeat, LauncherState, parse_beat
from .policy import END_LAUNCHER_QUIT, END_PARENT_EXITED, Decision, Record, SupervisionState
from .watchdog import LauncherWatchdog, SupervisionEffects

__layer__ = "lanes"

__all__ = [
    "END_LAUNCHER_QUIT",
    "END_PARENT_EXITED",
    "BeatRefused",
    "Decision",
    "LauncherBeat",
    "LauncherState",
    "LauncherWatchdog",
    "Record",
    "SupervisionEffects",
    "SupervisionState",
    "parse_beat",
]
