"""The bundled harness supervises its launcher (plan ``launcher-mutual-supervision-2026-10-27``).

``contract`` parses the ``launcher_beat`` op, ``policy`` is the pure transition table, ``relaunch`` is the
process I/O (identity, the one-pid kill, the detached spawn), ``watchdog``
wires it to the parent watch and the beat clock, ``game_watch`` watches a handed-over game. Slices W1
(beats, the re-targeted watch, Quit vs crash vs hang), W2 (relaunch, the hang kill, the restart budget)
and G1 (the game watch, resumed after a harness restart) are built; the play-session handback (P1)
follows.
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
