"""Fork-owned tests moved out of ``tests/hermes_cli/test_doctor.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

import io
import contextlib
import sys
import types
from argparse import Namespace

import pytest

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


@pytest.mark.parametrize(
    ("base_url", "expects_warning"),
    [
        ("http://localhost:20128/v1", False),
        ("https://api.openai.com/v1", True),
    ],
)
def test_run_doctor_vendor_slug_policy_for_openai_api_endpoint(
    monkeypatch, tmp_path, base_url, expects_warning
):
    """Upstream's #69912 case with the home selected the way the fork resolves it.

    ``hermes_cli.doctor_config`` reads ``config.yaml`` from ``get_hermes_home()``
    at call time, so upstream's ``monkeypatch.setattr(doctor, "HERMES_HOME", ...)``
    no longer steers it: the check reads the hermetic home's config and never
    sees the slug. ``HERMES_HOME`` in the environment is the selector here; the
    two parameters are each other's control (same slug, only the endpoint moves).
    """
    home = tmp_path / ".hermes"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        "model:\n"
        "  provider: openai-api\n"
        "  default: nvidia/z-ai/glm-5.2\n"
        f"  base_url: {base_url}\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(doctor_mod, "PROJECT_ROOT", tmp_path / "project")
    monkeypatch.setattr(doctor_mod, "_DHH", str(home))
    (tmp_path / "project").mkdir(exist_ok=True)

    fake_model_tools = types.SimpleNamespace(
        check_tool_availability=lambda *a, **kw: ([], []),
        TOOLSET_REQUIREMENTS={},
    )
    monkeypatch.setitem(sys.modules, "model_tools", fake_model_tools)

    from hermes_cli import auth as _auth_mod

    monkeypatch.setattr(_auth_mod, "get_nous_auth_status_local", lambda: {})
    monkeypatch.setattr(_auth_mod, "get_codex_auth_status", lambda: {})
    monkeypatch.setattr(_auth_mod, "get_xai_oauth_auth_status", lambda: {})

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        doctor_mod.run_doctor(Namespace(fix=False))

    warning = (
        "model.default 'nvidia/z-ai/glm-5.2' uses a vendor/model slug "
        "but provider is 'openai-api'"
    )
    out = buf.getvalue()
    assert (warning in out) is expects_warning
