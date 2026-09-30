"""Fork-owned half of ``hermes_cli/gateway_windows.py`` (class G11): the named-profile
wrapper pin, and reading the launcher's interpreter back. The legacy visible-console ``.cmd``
task warning is gone: upstream's Scheduled Task drift reconcile (#113670) names and
repairs that action (lane h13-del).

Moved out of the upstream module by lane FOOTPRINT-DROP (2026-09-27); it re-exports
these names in one import line, so callers and patches keep spelling them
``gateway_windows.<name>``. Upstream names are read through the module at call time
for the same reason. Retires with the G11 upstream PR.
"""

from __future__ import annotations

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
