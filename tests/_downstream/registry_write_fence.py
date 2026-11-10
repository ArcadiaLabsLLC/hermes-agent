r"""No test writes the REAL Windows registry (fork-hygiene, lane w5-fh 2026-10-02).

Measured: ``tests/hermes_cli/test_update_launch_completion.py`` (upstream bytes) put
four ``<tmp>\home\bin`` entries into the operator's real ``HKCU\Environment\Path``
on every run — 13 by 2026-09-30, until vcvarsall's 8,191-character line broke the
launcher's engine build (`EterniaLauncher/docs/tooling/WINDOWS_ENGINE_BUILD_DIAGNOSIS_2026-09-30.md`
§4.3). The writer is upstream's ``hermes_cli/_launchers.py::_register_windows_user_path``
(``venv_sync`` -> ``expose_cli`` -> ``_expose_windows_user_bin``), which imports
``winreg`` inside the function, so no module attribute a fixture could swap reaches it.

The fence is an audit hook, the one door every ``winreg`` write walks through
whatever module imported it and however: ``winreg.SetValue`` (raised by both
``SetValue`` and ``SetValueEx``), ``DeleteValue``, ``CreateKey`` and ``DeleteKey``
are refused with ``PermissionError`` — the ``OSError`` production already handles
as "could not write". Reads pass. An in-memory fake (``test_windows_env.py``'s
``FakeWinreg``) raises no audit event and is untouched. ``HERMES_E2E_WINDOWS_INSTALL=1``
(``tests/e2e/core/windows_update/_machine.py::OPT_IN_ENV``) is the one suite that owns
the machine's registry and restores it, so it is let through.

Children: an audit hook does not cross a process boundary, and the launcher's real-serve
sandboxes (``p-l-longrun-*``) put ``<sandbox>\home\bin`` on the real Path from a
``python -m hermes_cli.main`` child — the boot bootstrap's ``expose_cli`` step. So
``install`` also sets ``HERMES_REGISTRY_WRITE_FENCE=1`` in this process's environment;
every child inherits it, and ``hermes_bootstrap`` (first import of every entry point)
fences that child through ``hermes_cli/_registry_write_fence.py``.

A child spawned with an environment built from SCRATCH (``env={"HERMES_HOME": tmp, ...}``)
inherits nothing, so on Windows ``install`` also wraps ``subprocess.Popen.__init__``
(:func:`fence_scratch_child_envs`): an explicit ``env`` mapping that lacks the marker gets it
added; one that spells it (a positive control's ``"0"``) is left alone. ``asyncio``'s
Windows children are ``subprocess.Popen`` too. Without it a scratch-env
``python -m hermes_cli.main`` or ``install.ps1`` child under a temp home put
``<tmp>\home\bin`` on the user Path (FH-PYTEST-HOME-BIN-LEAKS-INTO-USER-PATH, dozens of
entries on the owner's box 2026-11-08).
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping

_WRITE_EVENTS = frozenset({"winreg.SetValue", "winreg.DeleteValue", "winreg.CreateKey", "winreg.DeleteKey"})
_E2E_OWNS_THE_REGISTRY = "HERMES_E2E_WINDOWS_INSTALL"
#: ``hermes_cli._registry_write_fence.ENV_VAR``, spelled here so the plugin imports no Hermes package.
CHILD_FENCE_ENV = "HERMES_REGISTRY_WRITE_FENCE"

#: Every refused write as ``(test node id, event)``, for a reader who wants to know who tried.
REFUSED: list[tuple[str, str]] = []


def _refuse_registry_write(event: str, args: tuple) -> None:
    if event not in _WRITE_EVENTS or os.environ.get(_E2E_OWNS_THE_REGISTRY) == "1":
        return
    REFUSED.append((os.environ.get("PYTEST_CURRENT_TEST", "?"), event))
    raise PermissionError(
        f"test fence: {event} refused — no test writes the real Windows registry "
        "(tests/_downstream/registry_write_fence.py)"
    )


#: ``subprocess.Popen.__init__``'s positional index of ``env`` (``args`` is index 0).
_POPEN_ENV_INDEX = 10


def marked_env(env: Mapping[str, str] | None) -> Mapping[str, str] | None:
    """*env* with the child fence marker added when it names none.

    ``None`` (inherit) is returned as is, and so is a map that already spells the marker: ``"1"``
    is fenced already, and any other value is the caller's deliberate choice — a positive control
    that must watch an unfenced child write (``"0"``), like an operator's own value in
    ``hermes_cli/_namespace_bootstrap.py``. Only a map that never mentions it was built from scratch.
    """
    if env is None or os.environ.get(_E2E_OWNS_THE_REGISTRY) == "1" or CHILD_FENCE_ENV in env:
        return env
    return {**env, CHILD_FENCE_ENV: "1"}


def fence_scratch_child_envs(popen: type = subprocess.Popen) -> bool:
    """Wrap ``popen.__init__`` so an explicit child ``env`` carries the marker; True iff wrapped now."""
    original = popen.__init__
    if getattr(original, "_hermes_scratch_env_fence", False):
        return False

    def __init__(self, *args, **kwargs):
        if "env" in kwargs:
            kwargs["env"] = marked_env(kwargs["env"])
        elif len(args) > _POPEN_ENV_INDEX:
            args = (*args[:_POPEN_ENV_INDEX], marked_env(args[_POPEN_ENV_INDEX]), *args[_POPEN_ENV_INDEX + 1:])
        original(self, *args, **kwargs)

    __init__._hermes_scratch_env_fence = True
    __init__.__wrapped__ = original
    popen.__init__ = __init__
    return True


def install() -> None:
    """Add the hook once per process. An audit hook cannot be removed, so this is idempotent."""

    if os.environ.get(_E2E_OWNS_THE_REGISTRY) != "1":
        os.environ[CHILD_FENCE_ENV] = "1"  # every child this process spawns inherits the refusal
    if sys.platform == "win32":
        fence_scratch_child_envs()  # ... and a child given a scratch environment gets it too
    if getattr(sys, "_hermes_registry_write_fence", False):
        return
    sys.addaudithook(_refuse_registry_write)
    sys._hermes_registry_write_fence = True
