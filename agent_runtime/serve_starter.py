"""Who STARTED this serve, read once at boot — never the process that merely adopted it.

``starter_pid`` (the registry row and the three greeting frames, ``serve_registry`` L-h) tells an
attaching client which process started the runtime. ``os.getppid()`` answers that only while the
starter lives: on POSIX a process whose parent exits is reparented to the nearest child subreaper
(``systemd --user`` on a Linux desktop) or to init, and a detached spawn (Dart's
``ProcessStartMode.detached``: fork, ``setsid``, fork, the intermediate exits) is reparented before
Python even starts. Recording that adopter as the starter made the launcher's reap target
``systemd --user`` and take the owner's desktop session down (Eternia QA-SERVE-STARTER-ROW-NAMES-SUBREAPER,
hermes RT-SERVE-STARTER-PID-NOT-THE-SUBREAPER). The answer is ``None`` then: no starter is a true
fact, a wrong pid is a kill target.

The tell is the session. A forked child inherits its forker's session unless it leads its own, so a
process that does not lead its session but whose parent sits in ANOTHER session (or is gone) was not
forked by that parent: it was adopted. A session leader carries no such evidence and keeps its
parent. Windows has no ``getsid``; there ``getppid`` names the creating process and is kept as it
always was.
"""

from __future__ import annotations

import os

__layer__ = "models"

__all__ = ["boot_starter_pid"]


def boot_starter_pid() -> int | None:
    """The parent pid when it is the process that forked this one; ``None`` when it only adopted it."""

    try:
        parent = int(os.getppid())
    except Exception:  # pragma: no cover - os.getppid exists everywhere we run
        return None
    getsid = getattr(os, "getsid", None)
    if getsid is None:
        return parent
    try:
        own = getsid(0)
        if own == os.getpid():
            return parent  # leads its own session: the session says nothing about who forked it
        if getsid(parent) != own:
            return None
    except OSError:  # the parent is gone, or (macOS) sits in a session this process may not ask about
        return None
    return parent
