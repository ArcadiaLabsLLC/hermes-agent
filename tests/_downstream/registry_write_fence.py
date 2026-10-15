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
fences that child through ``hermes_cli/_registry_write_fence.py``. A child spawned with
an environment built from scratch is not reached.
"""

from __future__ import annotations

import os
import sys

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


def install() -> None:
    """Add the hook once per process. An audit hook cannot be removed, so this is idempotent."""

    if os.environ.get(_E2E_OWNS_THE_REGISTRY) != "1":
        os.environ[CHILD_FENCE_ENV] = "1"  # every child this process spawns inherits the refusal
    if getattr(sys, "_hermes_registry_write_fence", False):
        return
    sys.addaudithook(_refuse_registry_write)
    sys._hermes_registry_write_fence = True
