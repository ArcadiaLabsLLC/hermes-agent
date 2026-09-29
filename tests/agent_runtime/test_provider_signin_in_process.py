"""Provider sign-in with no subprocess: the in-process runner behind ``ProviderSignIns(spawn=…)``.

The phone profile (``auth.subprocess_signin: false``) may not spawn ``hermes auth
login``; the registry binds ``run_login_in_process`` instead, which runs the same
``run_browser_login`` on a thread. Only the provider grant is faked (the driver in
``_DRIVERS``); the session state machine, the NDJSON events, the pasted-code path
and the thread-scoped silence are the real ones.

Killing mutations (applied, red recorded, reverted — see the commit message):

* ``_ThreadChild._run`` drops ``quiet=quiet_current_thread`` (the process-wide silence) -> red
  (the host's own print is swallowed with the driver's).
* ``_QuietThreadStream.write`` forwards every thread                                -> red.
* ``select_login_runner`` always returns ``spawn_login_child``                          -> red.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from pathlib import Path

import pytest

from agent_runtime import provider_signin
from hermes_cli import provider_browser_login as wire

pytestmark = pytest.mark.timeout(60)


def _wait(signins, login_id, states):
    deadline = time.monotonic() + 20
    while (view := signins.poll(login_id))["state"] not in states:
        assert time.monotonic() < deadline, view
        time.sleep(0.02)
    return view


@pytest.fixture
def no_subprocess(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("the in-process sign-in started a subprocess")

    monkeypatch.setattr(subprocess, "Popen", refuse)


def test_paste_code_sign_in_runs_on_a_thread_in_the_callers_home(monkeypatch, capsys, no_subprocess):
    from hermes_constants import get_hermes_home

    ran: dict = {}

    def driver(verify, flow):
        ran["home"] = str(get_hermes_home())
        verify("https://provider.example/authorize?state=s", "")
        print("SENTINEL printed access token")
        logging.getLogger("provider").critical("SENTINEL logged refresh token")
        ran["code"] = wire._read_pasted_line()

    monkeypatch.setitem(wire._DRIVERS, "anthropic", driver)
    signins = provider_signin.ProviderSignIns(spawn=provider_signin.run_login_in_process)
    login = signins.begin("anthropic")
    view = _wait(signins, login["login_id"], {"awaiting_code"})
    assert view["verification_uri"] == "https://provider.example/authorize?state=s"
    print("host output survives")  # positive control: only the sign-in thread is silenced
    signins.complete(login["login_id"], "CODE-1")
    assert _wait(signins, login["login_id"], {"succeeded", "failed"})["state"] == "succeeded"
    assert ran == {"home": str(get_hermes_home()), "code": "CODE-1\n"}
    out = capsys.readouterr()
    assert "SENTINEL" not in out.out + out.err
    assert "host output survives" in out.out
    assert not isinstance(__import__("sys").stdout, wire._QuietThreadStream)  # unwrapped after


def test_cancel_ends_the_session_and_fails_the_pending_paste(monkeypatch, no_subprocess):
    finished = threading.Event()

    def driver(verify, flow):
        verify("https://provider.example/authorize", "")
        try:
            if not wire._read_pasted_line():
                raise EOFError
        finally:
            finished.set()

    monkeypatch.setitem(wire._DRIVERS, "anthropic", driver)
    signins = provider_signin.ProviderSignIns(spawn=provider_signin.run_login_in_process)
    login = signins.begin("anthropic")
    _wait(signins, login["login_id"], {"awaiting_code"})
    assert signins.cancel(login["login_id"])["state"] == "cancelled"
    assert finished.wait(10)
    assert signins.poll(login["login_id"])["state"] == "cancelled"


def test_the_profile_switch_picks_the_runner():
    from hermes_constants import get_hermes_home

    assert provider_signin.select_login_runner() is provider_signin.spawn_login_child  # desktop control
    home = Path(get_hermes_home())
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(json.dumps({"auth": {"subprocess_signin": False}}), encoding="utf-8")
    assert provider_signin.select_login_runner() is provider_signin.run_login_in_process
