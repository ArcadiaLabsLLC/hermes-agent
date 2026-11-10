"""The phone's ``psutil``: a process table that is always empty, under psutil's own names.

A profile that ships no ``psutil`` (the bundled phone: it starts no sibling process, and the
distribution is compiled) still keeps upstream modules that ``import psutil`` inside the
function that reads a process — ``hermes_cli/process_identity.py``'s birth/boot/spawn-tag reads,
``hermes_constants_scratch.py``'s scratch-prune reap. Each used to carry its own
``except ImportError`` guard in upstream's file (lane s2-g2, the v0.23.1 merge). This module
retires them as a class, as :mod:`agent_runtime.provider_sdk_shim` does for ``openai``
(FH-FOOTPRINT-PHONE-PSUTIL-STUB): :func:`ensure_psutil_stand_in` registers one ``psutil`` module
whose answers are exactly what each guard returned —

* no platform flag is set (``MACOS``/``LINUX``/``WINDOWS`` false), so a birth read is the plain
  ``create_time()`` and a boot start is ``None``;
* ``Process(pid)`` raises :class:`NoSuchProcess`, which every reader already catches (a spawn tag
  is "not ours", a lineage walk is empty);
* ``process_iter()`` is empty, so the scratch reap finds no process and signals nothing;
* ``pid_exists`` is the stdlib probe (:func:`hermes_cli._subprocess_compat.pid_exists_stdlib`).

Phone-only, never a shadow: it installs only when the profile ships no provider SDK
(``agent.provider_sdks: false``, the phone's switch, as the ``openai`` shim) AND no real
``psutil`` is importable; the phone entry (``EmbeddedServe.start``) calls it beside that shim.
The module carries no ``__spec__``, so ``importlib.util.find_spec("psutil")`` still reads
"not installed".
"""

from __future__ import annotations

import importlib.util
import sys
import types

__layer__ = "lanes"

__all__ = ["STAND_IN_MARKER", "ensure_psutil_stand_in", "is_stand_in", "stand_in_modules"]

#: Set on the module this installs, so a census can tell it from the real distribution.
STAND_IN_MARKER = "__hermes_psutil_stand_in__"


class Error(Exception):
    """Base of every stand-in error, as ``psutil.Error``."""


class NoSuchProcess(Error):
    def __init__(self, pid=None, name=None, msg=None):
        super().__init__(msg or "process table not available on this device")
        self.pid, self.name = pid, name


class ZombieProcess(NoSuchProcess):
    pass


class AccessDenied(Error):
    def __init__(self, pid=None, name=None, msg=None):
        super().__init__(msg or "access denied")
        self.pid, self.name = pid, name


class TimeoutExpired(Error):
    def __init__(self, seconds=None, pid=None, name=None):
        super().__init__(f"timeout after {seconds} seconds")
        self.seconds, self.pid, self.name = seconds, pid, name


class Process:
    """No process can be opened: every construction raises :class:`NoSuchProcess`."""

    def __init__(self, pid=None):
        raise NoSuchProcess(pid)


def process_iter(attrs=None, ad_value=None):
    return iter(())


def pids() -> list[int]:
    return []


def pid_exists(pid: int) -> bool:
    from hermes_cli._subprocess_compat import pid_exists_stdlib

    return pid_exists_stdlib(pid)


def wait_procs(procs, timeout=None, callback=None):
    return [], list(procs)


def stand_in_modules() -> dict[str, types.ModuleType]:
    """The ``sys.modules`` entry this registers (the packaging closure asks it too)."""
    module = types.ModuleType("psutil", "Hermes phone stand-in for psutil: an empty process table.")
    module.__spec__ = None
    setattr(module, STAND_IN_MARKER, True)
    for name, value in {
        "MACOS": False, "LINUX": False, "WINDOWS": False, "OSX": False, "POSIX": False,
        "Error": Error, "NoSuchProcess": NoSuchProcess, "ZombieProcess": ZombieProcess,
        "AccessDenied": AccessDenied, "TimeoutExpired": TimeoutExpired, "Process": Process,
        "process_iter": process_iter, "pids": pids, "pid_exists": pid_exists, "wait_procs": wait_procs,
    }.items():
        setattr(module, name, value)
    return {"psutil": module}


def is_stand_in(module) -> bool:
    return bool(getattr(module, STAND_IN_MARKER, False))


def _real_psutil_importable() -> bool:
    if "psutil" in sys.modules:
        return sys.modules["psutil"] is not None
    try:
        return importlib.util.find_spec("psutil") is not None
    except (ImportError, ValueError):
        return False


def ensure_psutil_stand_in() -> bool:
    """Register the stand-in when this profile ships no ``psutil``; True when it is in place."""
    if is_stand_in(sys.modules.get("psutil")):
        return True
    from agent.transports.httpx_client import provider_sdks_enabled

    if provider_sdks_enabled() or _real_psutil_importable():
        return False
    sys.modules.update(stand_in_modules())
    return True
