"""Fork-owned tests beside ``tests/hermes_cli/test_dashboard_unified_launch.py`` (lane CARRY2A).

``cmd_dashboard`` re-execs through ``os.execvpe`` on POSIX but through
``subprocess.Popen`` + ``sys.exit(proc.wait())`` on Windows. Upstream's tests stub
only ``execvpe``, so on Windows the re-exec spawns a REAL dashboard child (the
fork's live-system guard refuses it); that upstream test is a strict xfail on
win32 by id (``tests/_downstream/id_markers.py``), and its copy here stubs both
branches. The other two are the fork-retained re-exec pins upstream pruned.
The upstream file is byte-identical to upstream; its ``main_mod`` fixture and
``_args`` helper are imported by name.
"""
import sys

import pytest
from hermes_cli import main_dashboard

from tests.hermes_cli.test_dashboard_unified_launch import (  # noqa: F401 — upstream fixture + helper
    _args,
    main_mod,
)


def _capture_reexec(main_mod, monkeypatch):
    """Stub BOTH platform branches of the machine-dashboard re-exec.

    ``cmd_dashboard`` re-execs through ``os.execvpe`` on POSIX but through
    ``subprocess.Popen`` + ``sys.exit(proc.wait())`` on Windows (``execvpe``
    does not truly replace the process there and can crash with
    STATUS_ACCESS_VIOLATION under Python 3.14+ — see the comment at the
    call site in ``hermes_cli/main.py``).

    A test that stubs only ``os.execvpe`` is therefore vacuous on Windows:
    the win32 branch spawns a REAL ``python -m hermes_cli.main ... dashboard``
    child, which runs ``npm install`` + ``vite build`` and then serves
    forever, while the parent blocks in ``proc.wait()``. That hangs the whole
    pytest process (pytest-timeout's thread method then kills the run, so a
    single test takes the entire file's results with it).

    Returning one ``calls`` list for both branches lets the assertions below
    describe the same re-exec on either platform — the recorded tuple is
    always ``(executable, argv, env)``.
    """
    calls: list[tuple[str, list[str], dict]] = []

    def fake_exec(exe, argv, env):
        calls.append((exe, list(argv), env))
        raise SystemExit(0)  # execvpe never returns

    class _FakePopen:
        def __init__(self, argv, *_a, env=None, **_kw):
            calls.append((argv[0], list(argv), env if env is not None else {}))

        def wait(self):
            return 0

    monkeypatch.setattr(main_dashboard.os, "execvpe", fake_exec)
    monkeypatch.setattr(main_dashboard.subprocess, "Popen", _FakePopen)
    return calls


class TestUnifiedDashboardRouting:
    def test_profile_launch_reexecs_machine_dashboard(self, main_mod, monkeypatch):
        monkeypatch.delenv("HERMES_HOME", raising=False)
        monkeypatch.setattr(
            "hermes_cli.profiles.get_active_profile_name", lambda: "worker_x"
        )
        monkeypatch.setattr(main_dashboard, "_dashboard_listening", lambda host, port: False)
        execs = _capture_reexec(main_mod, monkeypatch)

        with pytest.raises(SystemExit):
            main_mod.cmd_dashboard(_args())

        assert len(execs) == 1
        exe, argv, env = execs[0]
        assert exe == sys.executable
        # Pinned to the default profile + launching profile preselected.
        assert "-p" in argv and argv[argv.index("-p") + 1] == "default"
        assert "--open-profile" in argv
        assert argv[argv.index("--open-profile") + 1] == "worker_x"
        # The child is pinned to the machine ROOT, not the launching profile's
        # HERMES_HOME.  For a standard install (HERMES_HOME unset) that root is
        # the platform-native default (~/.hermes), NOT dropped — see the Docker
        # test below for why we resolve explicitly instead of popping.
        from hermes_constants import get_default_hermes_root
        assert env.get("HERMES_HOME") == str(get_default_hermes_root())

    # Fork-retained: same _capture_reexec reason as above; upstream pruned it.
    def test_reexec_pins_docker_machine_root(self, main_mod, monkeypatch):
        """In the Docker layout (HERMES_HOME=/opt/data, profiles under
        /opt/data/profiles/<name>) the reroute must pin the child to the
        machine root /opt/data — NOT drop HERMES_HOME.

        Dropping it makes the child fall back to $HOME/.hermes
        (= /opt/data/.hermes), an empty auto-seeded home, so the dashboard
        shows only the default profile and the .install_method stamp is
        missing (which also misfires the Docker update-button guard).
        Regression test for the support report.
        """
        monkeypatch.setenv("HERMES_HOME", "/opt/data/profiles/oracle")
        monkeypatch.setattr(
            "hermes_cli.profiles.get_active_profile_name", lambda: "oracle"
        )
        monkeypatch.setattr(main_dashboard, "_dashboard_listening", lambda host, port: False)
        execs = _capture_reexec(main_mod, monkeypatch)

        with pytest.raises(SystemExit):
            main_mod.cmd_dashboard(_args())

        assert len(execs) == 1
        _exe, _argv, env = execs[0]
        # get_default_hermes_root() strips the trailing profiles/<name>, so the
        # child binds /opt/data — where the real default/oracle/saga profiles
        # and the .install_method stamp actually live. Rendered through Path so
        # the assertion also holds on native Windows (where the resolver returns
        # the same location spelled with backslashes).
        from pathlib import Path

        assert env.get("HERMES_HOME") == str(Path("/opt/data"))

    def test_reexec_child_does_not_reroute(self, main_mod, monkeypatch):
        """The re-exec'd child carries --open-profile; the guard must treat
        that as 'already routed' and never re-exec again (no exec loop)."""
        monkeypatch.setattr(
            "hermes_cli.profiles.get_active_profile_name", lambda: "worker_x"
        )
        execs = _capture_reexec(main_mod, monkeypatch)
        monkeypatch.setitem(sys.modules, "fastapi", None)

        with pytest.raises((SystemExit, AttributeError, ImportError, TypeError)):
            main_mod.cmd_dashboard(_args(open_profile="worker_x"))
        assert execs == []
