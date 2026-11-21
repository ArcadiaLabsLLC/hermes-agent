"""Provider sign-in runs inside the running Hermes: the in-process runner behind ``ProviderSignIns``.

RT-PROVIDER-SIGN-IN-RUNS-INSIDE-THE-RUNNING-HERMES: every profile's registry runs
``run_browser_login`` on a thread of the serve (``run_login_in_process``); no sign-in child
and no warm child exist. Only the provider grant is faked (the driver in ``_DRIVERS``);
the session state machine, the NDJSON events, the pasted-code path, the thread-scoped
silence, the stop and the per-context routing of the Anthropic paste are the real ones.

Killing mutations (applied, red recorded, reverted — see the commit message):

* ``_ThreadChild._run`` drops ``quiet=quiet_current_thread`` (the process-wide silence) -> red
  (the host's own print is swallowed with the driver's).
* ``_QuietThreadStream.write`` forwards every thread                                -> red.
* ``ProviderSignIns``'s default runner anything but ``run_login_in_process``            -> red.
* ``_ThreadChild.terminate`` not raising into the driver's thread                     -> red (the
  driver's poll runs on past the cancel and its ``finally`` never runs).
* ``_route``'s stand-in calling the route whatever the context                       -> red (another
  thread's ``input`` reads the sign-in's paste queue).
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


def test_every_profile_signs_in_inside_this_hermes():
    assert provider_signin.ProviderSignIns()._spawn is provider_signin.run_login_in_process
    assert provider_signin.registry()._spawn is provider_signin.run_login_in_process


def test_cancel_stops_the_driver_where_it_stands(monkeypatch, no_subprocess):
    """A cancelled poll stops at once: its ``finally`` runs (a listener closes) and it saves nothing."""
    released, saved = threading.Event(), []

    def driver(verify, flow, expiry=None):
        verify("https://provider.example/device", "ABCD-EFGH")
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:  # a device-code poll, or the loopback wait
                time.sleep(0.05)
            saved.append("grant")
        finally:
            released.set()

    monkeypatch.setitem(wire._DRIVERS, "xai-oauth", driver)
    signins = provider_signin.ProviderSignIns(spawn=provider_signin.run_login_in_process)
    login_id = signins.begin("xai-oauth")["login_id"]
    _wait(signins, login_id, {"awaiting_user"})
    started = time.monotonic()
    assert signins.cancel(login_id)["state"] == "cancelled"
    assert released.wait(5), "the driver ran on past its cancel"
    assert time.monotonic() - started < 5
    assert saved == []
    assert signins.poll(login_id)["state"] == "cancelled"


def test_a_routed_name_is_the_original_outside_the_sign_in(monkeypatch):
    """The Anthropic paste routes ``input`` for its own context only; every other caller is untouched."""
    import builtins

    from agent import anthropic_credentials

    wire._route(anthropic_credentials, "input")
    monkeypatch.setattr(builtins, "input", lambda prompt="": "operator typed")
    seen: list[str] = []
    bound = wire._ROUTES.set({wire._route_key(anthropic_credentials, "input"): lambda prompt="": "pasted"})
    try:
        other = threading.Thread(target=lambda: seen.append(anthropic_credentials.input()))
        other.start()
        other.join(5)
        assert anthropic_credentials.input() == "pasted"
    finally:
        wire._ROUTES.reset(bound)
    assert seen == ["operator typed"]
    assert anthropic_credentials.input() == "operator typed"


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
