"""Fork-owned tests moved out of ``tests/hermes_cli/test_doctor.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

import io
import contextlib
from argparse import Namespace

from hermes_cli import doctor as doctor_mod
from hermes_cli import doctor_tools
from tools import browser_tool_install as bt_install


class TestDoctorResolvesTheHomeAtCallTime:
    """The home doctor reports on is the one live when it RUNS.

    Red before the binding moved: ``HERMES_HOME`` was a module constant
    resolved at doctor's import, and under pytest that import happens at
    COLLECTION -- before the autouse hermetic-home fixture has redirected
    anything. Every path check below therefore read the operator's live store,
    which is why every other test in this file had to reach in and monkeypatch
    a production module's constant to be isolated at all.

    Asserted on a FILE the run has to have read, not on the printed home:
    ``_DHH`` is a separate, still-frozen label and asserting on it would only
    prove the label was patched.
    """

    @staticmethod
    def _hub(home, installed: int):
        hub = home / "skills" / ".hub"
        hub.mkdir(parents=True)
        (hub / "lock.json").write_text(
            '{"installed": {%s}}'
            % ", ".join(f'"skill{i}": {{}}' for i in range(installed)),
            encoding="utf-8",
        )

    def _run(self, monkeypatch, home):
        monkeypatch.setenv("HERMES_HOME", str(home))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            doctor_mod.run_doctor(Namespace(fix=False))
        return buf.getvalue()

    def test_the_env_var_alone_redirects_every_profile_relative_read(
        self, monkeypatch, tmp_path
    ):
        home = tmp_path / "late-home"
        home.mkdir()
        self._hub(home, 3)

        out = self._run(monkeypatch, home)

        assert "Lock file OK (3 hub-installed skill(s))" in out

    def test_a_second_call_follows_a_second_home(self, monkeypatch, tmp_path):
        """One process, two homes -- the read cannot be cached anywhere."""
        first = tmp_path / "first"
        first.mkdir()
        self._hub(first, 1)
        second = tmp_path / "second"
        second.mkdir()
        self._hub(second, 7)

        assert "Lock file OK (1 hub-installed skill(s))" in self._run(
            monkeypatch, first
        )
        assert "Lock file OK (7 hub-installed skill(s))" in self._run(
            monkeypatch, second
        )


class TestDoctorAgentBrowserProbe:
    """Doctor asks upstream's ``agent_browser_runnable`` about a resolved install.

    Lane ADOPT (2026-09-24) retired the fork's ``browser_probe_scope`` seam; a
    test controls the probe where ``_check_agent_browser`` reads it,
    ``hermes_cli.doctor_tools.agent_browser_runnable``. The two cases are each
    other's control: one bytes-identical resolution, only the probe's answer
    changes, and the report must change with it.
    """

    @staticmethod
    def _report(monkeypatch, runnable: bool) -> str:
        monkeypatch.setattr(
            bt_install, "_find_agent_browser", lambda **_kw: "/opt/node/bin/agent-browser"
        )
        seen = []

        def probe(candidate):
            seen.append(candidate)
            return runnable

        monkeypatch.setattr(doctor_tools, "agent_browser_runnable", probe)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            doctor_tools._check_agent_browser(False)
        assert seen == ["/opt/node/bin/agent-browser"]
        return buf.getvalue()

    def test_a_runnable_install_reports_browser_automation(self, monkeypatch):
        out = self._report(monkeypatch, runnable=True)
        assert "(browser automation)" in out
        assert "not runnable" not in out

    def test_an_unrunnable_install_reports_the_broken_symlink(self, monkeypatch):
        out = self._report(monkeypatch, runnable=False)
        assert "agent-browser found but not runnable" in out
        assert "(browser automation)" not in out
