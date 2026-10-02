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
"""

from __future__ import annotations

import os
import sys

ENV_VAR = "HERMES_REGISTRY_WRITE_FENCE"
WRITE_EVENTS = frozenset({"winreg.SetValue", "winreg.DeleteValue", "winreg.CreateKey", "winreg.DeleteKey"})
_SENTINEL = "_hermes_registry_write_fence"


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
