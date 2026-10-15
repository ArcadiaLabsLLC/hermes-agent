"""Processes a gate run started that outlive it: named, never killed (fork-hygiene row 2026-10-15).

``tests/scripts/desktop_update/test_desktop_update_windows_marker.py`` (upstream) can
detach a REAL ``hermes update --yes --gateway …``; two such processes were still
running 11 h and 13 h after the 2026-10-11 whole-tree gate, parents gone, and
nothing in the run said so. At the end of a bundled run this module lists every
live process that STARTED during the run, whose parent is gone, and whose command
line is a hermes update — the shapes the escape used: ``-m hermes_cli.main update``,
the desktop hand-off's ``-c "…hermes_bootstrap…runpy hermes_cli.main"`` spelling,
and a ``hermes`` launcher with ``update``.

It reports; it does not kill. Another lane's run on the same box can start the
same shape in the same window, so a name is evidence to read, not a verdict to act on.
``match`` is pure (tests feed it rows); ``scan`` reads the box through psutil and
returns nothing when psutil is missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence

#: a slack for clock granularity between the runner's clock and the OS start time
_SLACK_SECONDS = 1.0


@dataclass(frozen=True)
class Proc:
    pid: int
    started: float  # epoch seconds
    cmdline: Sequence[str]
    parent_alive: bool


def is_hermes_update(cmdline: Sequence[str]) -> bool:
    """A command line that runs ``hermes … update``, in any of the spellings above."""

    words = [str(word) for word in cmdline]
    text = " ".join(words).replace("\\", "/").lower()
    entry = "hermes_cli.main" in text or "hermes_cli/main.py" in text or any(
        word.replace("\\", "/").lower().rsplit("/", 1)[-1] in ("hermes", "hermes.exe") for word in words
    )
    if entry and any(word.lower() == "update" for word in words):
        return True
    return "hermes_bootstrap" in text and "hermes_cli.main" in text


def match(procs: Iterable[Proc], run_started: float) -> list[Proc]:
    """The orphaned hermes updates that started at or after ``run_started``."""

    return sorted(
        (p for p in procs
         if p.started + _SLACK_SECONDS >= run_started and not p.parent_alive and is_hermes_update(p.cmdline)),
        key=lambda p: p.pid,
    )


def scan(run_started: float) -> list[Proc]:
    """The box's processes through psutil, matched; [] when psutil is unavailable."""

    try:
        import psutil
    except ImportError:
        return []
    rows = []
    for proc in psutil.process_iter(["pid", "create_time", "cmdline", "ppid"]):
        try:
            info = proc.info
            cmdline = info.get("cmdline") or []
            ppid = info.get("ppid")
            alive = bool(ppid) and psutil.pid_exists(ppid)
            rows.append(Proc(int(info["pid"]), float(info.get("create_time") or 0.0), cmdline, alive))
        except (psutil.Error, OSError, KeyError, TypeError, ValueError):
            continue
    return match(rows, run_started)


def lines(found: Sequence[Proc]) -> list[str]:
    if not found:
        return []
    out = [f"=== ⚠ OUTLIVED THE RUN: {len(found)} hermes update process(es) started during it, parent gone ==="]
    for proc in found:
        out.append(f"  pid {proc.pid}: {' '.join(str(w) for w in proc.cmdline)[:300]}")
    out.append("  a test detached a real `hermes update`: make it reap its children and pin HERMES_HOME "
               "(fork-hygiene row 2026-10-15); this run does not kill them")
    return out
