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

    def driver(verify, flow, expiry=None):
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

    def driver(verify, flow, expiry=None):
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


def test_a_wrong_anthropic_paste_asks_again_and_a_failed_exchange_says_so(monkeypatch, caplog, no_subprocess):
    """RT-ANTHROPIC-WRONG-PASTE-ENDS-THE-SIGN-IN: the real driver over upstream's PKCE login, offline."""
    from urllib.parse import parse_qs, urlsplit

    from agent import anthropic_credentials

    exchanged: list[dict] = []

    def no_network(data, **_kwargs):
        exchanged.append(json.loads(data))
        raise TimeoutError("SENTINEL exchange body")

    monkeypatch.setattr(anthropic_credentials, "_post_oauth_token", no_network)
    caplog.set_level(logging.INFO, logger=provider_signin.__name__)
    signins = provider_signin.ProviderSignIns(spawn=provider_signin.run_login_in_process)
    login_id = signins.begin("anthropic")["login_id"]
    view = _wait(signins, login_id, {"awaiting_code"})
    state = parse_qs(urlsplit(view["verification_uri"]).query)["state"][0]
    assert "code_refusal" not in view

    signins.complete(login_id, "somecode#not-the-state")
    view = _wait(signins, login_id, {"awaiting_code", "failed"})
    assert (view["state"], view.get("code_refusal")) == ("awaiting_code", "code_mismatch")

    signins.complete(login_id, "   ")
    view = _wait(signins, login_id, {"awaiting_code", "failed"})
    assert (view["state"], view.get("code_refusal")) == ("awaiting_code", "code_empty")
    assert exchanged == []  # a refused paste never reaches the token endpoint

    assert "code_refusal" not in signins.complete(login_id, f"right-code#{state}")
    view = _wait(signins, login_id, {"succeeded", "failed"})
    assert (view["state"], view.get("error_code")) == ("failed", "exchange_failed")
    assert [(e["code"], e["state"]) for e in exchanged] == [("right-code", state)]
    logged = caplog.text
    assert f"{login_id} (anthropic) failed: exchange_failed" in logged
    assert f"{login_id} (anthropic) code refused: code_mismatch" in logged
    assert "SENTINEL" not in logged and "right-code" not in logged and "somecode" not in logged
