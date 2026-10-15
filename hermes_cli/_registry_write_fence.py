r"""A sandboxed process never writes the real Windows registry — fork-owned, stdlib only.

``HERMES_REGISTRY_WRITE_FENCE=1`` in a process's environment makes ``hermes_bootstrap``
(which every entry point imports first) add an audit hook refusing ``winreg`` writes —
``winreg.SetValue`` (raised by ``SetValue`` and ``SetValueEx``), ``DeleteValue``,
``CreateKey``, ``DeleteKey`` — with ``PermissionError``, the ``OSError`` every writer
already handles as "could not write". Reads pass. The marker is an environment variable
on purpose: a child inherits it, so a test's whole process tree is fenced, ``-I``
children included (``-I`` drops ``PYTHON*`` variables, not this one).

Why it exists: a fresh ``HERMES_HOME`` makes the boot bootstrap run upstream's
``expose_cli`` (``hermes_cli/post_update.py::BOOT_HOME_STEPS``), which on Windows puts
``<home>\bin`` on the user's real ``HKCU\Environment\Path`` — the launcher's real-serve
sandboxes (``p-l-longrun-*``, which spawn ``python -m hermes_cli.main harness serve``) did
exactly that through 2026-10-02. The pytest
process carries its own in-process fence (``tests/_downstream/registry_write_fence.py``),
which sets this marker so every child it spawns inherits the refusal.

One fence per process: a process that already carries one (the same ``sys`` sentinel the
test fence sets) gets no second.

The PATH fence (always on, owner decision 2026-10-03): every other process gets
:func:`install_path_fence`, which refuses only a user-``Path`` write that ADDS an entry
under this process's Hermes root (``get_default_hermes_root()`` — the root upstream's
``hermes_cli/_launchers.py::_expose_windows_user_bin`` registers ``<root>\bin`` for) when
that root is not installer-owned. Installer-owned means the platform-native root, or the
root of the ``HERMES_HOME`` persisted in ``HKCU\Environment`` — the home every fresh user
process inherits, which is where an installer that took a custom home records it. A QA
seeded home, a test sandbox or a temp root sets ``HERMES_HOME`` in a process environment
only, so its ``bin`` never reaches the user PATH. Removals, entries outside the root, and
every other registry write pass. The refusal is logged and raised as ``PermissionError``.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

ENV_VAR = "HERMES_REGISTRY_WRITE_FENCE"
WRITE_EVENTS = frozenset({"winreg.SetValue", "winreg.DeleteValue", "winreg.CreateKey", "winreg.DeleteKey"})
_SENTINEL = "_hermes_registry_write_fence"
_PATH_SENTINEL = "_hermes_path_write_fence"
_log = logging.getLogger(__name__)


def _refuse_registry_write(event: str, args: tuple) -> None:
    if event in WRITE_EVENTS:
        raise PermissionError(f"registry fence: {event} refused — {ENV_VAR}=1 (hermes_cli/_registry_write_fence.py)")


def requested(environ=None) -> bool:
    """Does *environ* (default: this process's) ask for the fence?"""
    return (os.environ if environ is None else environ).get(ENV_VAR) == "1"


def install_if_requested(environ=None) -> bool:
    """Fence this process when asked and not already fenced; True iff a hook was added.

    An audit hook cannot be removed, so this is one-way and idempotent.
    """
    if not requested(environ) or getattr(sys, _SENTINEL, False):
        return False
    sys.addaudithook(_refuse_registry_write)
    setattr(sys, _SENTINEL, True)
    return True


def _norm(entry: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.expandvars(entry.strip().strip('"')))).rstrip("\\/")


def _entries(value: str) -> list[str]:
    return [_norm(part) for part in str(value or "").split(";") if part.strip()]


def _under(entry: str, root: str) -> bool:
    return entry == root or entry.startswith(root + os.sep)


def _persisted_user_home() -> str:
    """``HERMES_HOME`` as stored for the user (``HKCU\\Environment``), or ``""``."""
    try:
        import winreg  # type: ignore

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _kind = winreg.QueryValueEx(key, "HERMES_HOME")
    except (ImportError, OSError):
        return ""
    return os.path.expandvars(str(value)).strip()


def installer_owned_roots(persisted_home=None) -> set[str]:
    """Normalized roots that may own a user-PATH ``bin``: native, plus the persisted home's."""
    from hermes_constants import get_default_hermes_root

    roots = {_norm(str(get_default_hermes_root(home="")))}  # an empty home is the native root
    home = _persisted_user_home() if persisted_home is None else persisted_home
    if home:
        roots.add(_norm(str(get_default_hermes_root(home=home))))
    return roots


def path_write_refusal(new_value, current_value, *, process_root=None, owned_roots=None):
    """Why writing user ``Path`` = *new_value* over *current_value* is refused, or ``None``."""
    if process_root is None:
        from hermes_constants import get_default_hermes_root

        process_root = get_default_hermes_root()
    root = _norm(str(process_root))
    before = set(_entries(current_value))
    added = [entry for entry in _entries(new_value) if entry not in before and _under(entry, root)]
    if not added:
        return None
    owned = installer_owned_roots() if owned_roots is None else {_norm(str(r)) for r in owned_roots}
    if root in owned:
        return None
    return (f"PATH fence: refused adding {added[0]} to the user Path — Hermes root {root} is not "
            "installer-owned (neither the native root nor the persisted HERMES_HOME's); "
            "hermes_cli/_registry_write_fence.py")


def _current_path(handle) -> str:
    try:
        import winreg  # type: ignore

        return str(winreg.QueryValueEx(handle, "Path")[0])
    except (ImportError, OSError, TypeError):
        return ""


def _refuse_foreign_path_write(event: str, args: tuple) -> None:
    if event != "winreg.SetValue" or len(args) < 4:
        return
    handle, name, _kind, value = args[:4]
    if not isinstance(name, str) or name.casefold() != "path" or not isinstance(value, str):
        return
    reason = path_write_refusal(value, _current_path(handle))
    if reason is not None:
        _log.warning(reason)
        raise PermissionError(reason)


def install_path_fence() -> bool:
    """Always-on PATH fence; True iff a hook was added (one per process, never under the full fence)."""
    if getattr(sys, _SENTINEL, False) or getattr(sys, _PATH_SENTINEL, False):
        return False
    sys.addaudithook(_refuse_foreign_path_write)
    setattr(sys, _PATH_SENTINEL, True)
    return True


def install(environ=None) -> str | None:
    """Bootstrap entry: the full fence when requested, else the PATH fence. Which one was added."""
    if install_if_requested(environ):
        return "registry"
    if requested(environ):
        return None
    return "path" if install_path_fence() else None
