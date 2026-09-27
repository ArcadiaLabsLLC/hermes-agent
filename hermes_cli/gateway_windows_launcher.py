"""Fork-owned half of ``hermes_cli/gateway_windows.py`` (class G11): the named-profile
wrapper pin, reading the launcher's interpreter back, and detecting a Scheduled Task
still bound to the legacy visible-console ``.cmd`` action.

Moved out of the upstream module by lane FOOTPRINT-DROP (2026-09-27); it re-exports
these names in one import line, so callers and patches keep spelling them
``gateway_windows.<name>``. Upstream names are read through the module at call time
for the same reason. Retires with the G11 upstream PR.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _gw():
    from hermes_cli import gateway_windows

    return gateway_windows


class GatewayWrapperNotPinned(RuntimeError):
    """A wrapper for a named profile would have been written without the flag."""


def _assert_named_profile_wrapper_is_pinned(hermes_home: str, profile_arg: str) -> None:
    """Refuse to write a single-pinned wrapper for a NAMED profile.

    The wrapper is a persistence artifact: whatever it says is what every future
    boot does, for months. ``set HERMES_HOME=<...>/profiles/<name>`` alone is a
    SINGLE pin, and a single pin is load-bearing on ``main.py``'s rung 2 — the
    rung that returns early and never consults the sticky ``active_profile``
    marker. Double-pinning (env AND ``--profile <name>``) is what makes the boot
    survive an env that has been mangled in transit.

    This can genuinely fire: ``_profile_arg()`` returns ``""`` for any home that
    is not exactly ``<default_root>/profiles/<name>``, and
    ``update_cmd._refresh_windows_gateway_launchers`` re-renders the wrapper
    from the UPDATING process's home. Refusing beats silently regenerating
    today's healthy double-pinned wrapper into the vulnerable single-pinned
    form.

    Homes that are not named profiles (the default root, custom/hash roots) are
    left alone — ``--profile`` has no name to carry there, and that is correct,
    not a defect.
    """
    home = Path(hermes_home)
    try:
        is_named_profile = home.parent.name == "profiles" and bool(home.name)
    except (OSError, ValueError):
        return
    if not is_named_profile:
        return
    if f"--profile {home.name}" in profile_arg:
        return
    raise GatewayWrapperNotPinned(
        f"refusing to write a gateway wrapper for profile '{home.name}' whose "
        f"argv lacks '--profile {home.name}' (profile_arg={profile_arg!r}); a "
        "wrapper pinned only by HERMES_HOME rides main.py's early-return rung "
        "and cannot recover from an environment mangled in transit"
    )


def launcher_interpreter(script_text: str) -> str | None:
    """Extract the interpreter a rendered ``gateway.cmd`` launcher invokes.

    The launcher's whole job is to name an interpreter, so that name is the
    one thing worth reading back out of it: an install whose launcher points
    at an unmanaged Python boots the gateway against a package set no update
    ever syncs, and nothing says so until an import fails at some later boot.

    Returns None when no ``hermes_cli.main`` invocation is present.
    """
    for raw in script_text.splitlines():
        line = raw.strip()
        if "-m hermes_cli.main" not in line:
            continue
        if line.startswith('"'):
            end = line.find('"', 1)
            if end == -1:
                return None
            return line[1:end]
        return line.split(" ", 1)[0]
    return None


def installed_launcher_interpreter() -> str | None:
    """The interpreter named by the launcher on disk, or None if unreadable."""
    try:
        script_path = _gw().get_task_script_path()
        if not script_path.exists():
            return None
        return launcher_interpreter(script_path.read_text(encoding="utf-8"))
    except OSError:
        return None


def _task_action_is_console_less(query_output: str, script_path: Path) -> bool | None:
    """Classify a ``schtasks /Query`` dump by which launcher the action names.

    Locale-independent on purpose: Windows translates the *field labels*
    (``Task To Run``) but never the *path* inside them, so we look for the
    launcher path itself rather than parsing key/value pairs.

    Returns True for the console-less ``.vbs`` (run through ``wscript.exe``),
    False for the legacy ``.cmd`` (run through ``cmd.exe``, which owns a
    visible console window), and None when neither path appears — an action
    we don't recognise, which we must not report as either.
    """
    text = query_output.lower()
    if str(script_path.with_suffix(".vbs")).lower() in text:
        return True
    if str(script_path.with_suffix(".cmd")).lower() in text:
        return False
    return None


def task_action_is_console_less() -> bool | None:
    """Whether the REGISTERED Scheduled Task launches the console-less ``.vbs``.

    ``_write_task_script`` regenerates the launcher *files*, but a task
    registered before #45610 has its action bound to the ``.cmd``. Rewriting
    the files cannot retarget that: cmd.exe owns a **visible console window**,
    so the live gateway dies with ``STATUS_CONTROL_C_EXIT`` (0xC000013A) the
    moment that window is closed or receives a stray console-control
    broadcast — and, since the only trigger is ONLOGON, it stays down until
    the next login. Re-registering the action needs ``schtasks /Create``
    (elevation), which ``hermes update`` deliberately does not do, so the only
    way a pre-#45610 install ever escapes this is if someone is *told*.

    Returns True (console-less), False (legacy visible console), or None when
    there is no task, its definition can't be read, or its action is
    unrecognised.
    """
    if sys.platform != "win32":
        return None
    gw = _gw()
    code, out, _err = gw._exec_schtasks(["/Query", "/TN", gw.get_task_name(), "/V", "/FO", "LIST"])
    if code != 0:
        return None
    return gw._task_action_is_console_less(out, gw.get_task_script_path())


def print_console_task_warning() -> None:
    """``gateway status``: say so when the registered task still owns a visible console."""
    if _gw().task_action_is_console_less() is False:
        print("  ⚠ Task launches a VISIBLE console window (legacy .cmd action).")
        print("    Closing that window kills the gateway; nothing restarts it")
        print("    until the next login. Re-register with: hermes gateway install")


def write_task_script_or_warn() -> bool:
    """``hermes update``'s launcher refresh: rewrite the task script, or say why not.

    A launcher is persisted, so an unresolvable managed interpreter leaves the one on
    disk unchanged (and says so) rather than stamping a guess into it."""
    from hermes_cli.gateway import ManagedPythonUnavailable

    try:
        _gw()._write_task_script()
    except ManagedPythonUnavailable as exc:
        print(f"  ⚠ Left the Windows gateway launcher unchanged: {exc}")
        print("    Re-run from the Hermes environment: hermes gateway install")
        return False
    return True


def warn_legacy_console_task() -> None:
    """Tell the operator when the registered task still runs a visible console.

    Re-registering the action requires ``schtasks /Create`` (elevation), which
    the update path deliberately avoids — so a pre-#45610 install cannot heal
    itself here. What it *can* do is stop being silent: a gateway launched
    through the ``.cmd`` dies with ``STATUS_CONTROL_C_EXIT`` (0xC000013A) the
    moment its console window is closed, and the ONLOGON-only trigger means it
    stays down until the next login.
    """
    gateway_windows = _gw()
    if gateway_windows.task_action_is_console_less() is not False:
        return
    task_name = gateway_windows.get_task_name()
    print(f"  ⚠ Scheduled Task {task_name!r} still launches the gateway in a VISIBLE console window.")
    print("    Closing that window (or a stray console-control broadcast) kills the")
    print("    gateway outright, and nothing restarts it until the next login.")
    print("    Re-register it on the console-less launcher — approve the UAC prompt:")
    print("      hermes gateway install")
