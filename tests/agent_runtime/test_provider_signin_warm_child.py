"""A warm sign-in child takes the press so the browser does not wait on a cold child's imports
(RT-PROVIDER-SIGNIN-COLD-CHILD). Fakes only: no process starts, no provider is reached."""

from __future__ import annotations

import io
import json

import pytest

import hermes_constants
from agent_runtime import provider_signin, provider_signin_child, provider_signin_warm


class _FakeChild:
    started: list["_FakeChild"] = []

    def __init__(self, argv, env, home=""):
        self.argv, self.home = argv, home
        self.env_home = env.get("HERMES_HOME")
        self.written: list[str] = []
        self.live = True
        self.terminated = False
        self.broken = False
        _FakeChild.started.append(self)

    def alive(self):
        return self.live

    def write_line(self, text):
        if self.broken:
            raise BrokenPipeError
        self.written.append(text)

    def terminate(self):
        self.terminated = True
        self.live = False


@pytest.fixture
def children(monkeypatch, tmp_path):
    _FakeChild.started = []
    monkeypatch.setattr(provider_signin_child, "_PopenChild", _FakeChild)
    monkeypatch.setattr(provider_signin_child, "_WARM", None)
    home = tmp_path / "home"
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: home)
    return _FakeChild.started


def _is_warm(child) -> bool:
    return child.argv[-1] == "agent_runtime.provider_signin_warm"


def test_a_prewarmed_child_takes_the_sign_in_and_no_cold_child_starts(children):
    """Killing mutation: ``spawn_login_child`` skipping ``_take_warm`` -> a second (cold) start, red."""
    assert provider_signin_child.prewarm_login_child() is True
    child = provider_signin_child.spawn_login_child("anthropic", "paste_code", None)
    assert len(children) == 1 and child is children[0] and _is_warm(child)
    assert json.loads(child.written[0]) == {"provider": "anthropic", "flow": "paste_code", "profile": None}


def test_the_warm_child_is_single_use(children):
    """Killing mutation: ``_take_warm`` not clearing ``_WARM`` -> the second sign-in reuses a spent child, red."""
    provider_signin_child.prewarm_login_child()
    provider_signin_child.spawn_login_child("anthropic", "paste_code", None)
    cold = provider_signin_child.spawn_login_child("openai-codex", "device_code", None)
    assert len(children) == 2 and not _is_warm(cold)
    assert cold.argv[2:] == ["hermes_cli.main", "harness", "auth", "login", "openai-codex", "--json",
                             "--flow", "device_code"]


def test_prewarm_keeps_one_child_per_home(children, monkeypatch, tmp_path):
    """Killing mutation: ``prewarm_login_child`` always spawning -> two children for one home, red."""
    assert provider_signin_child.prewarm_login_child() is True
    assert provider_signin_child.prewarm_login_child() is False
    assert len(children) == 1
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path / "other")
    assert provider_signin_child.prewarm_login_child() is True
    assert children[0].terminated and len(children) == 2


def test_a_warm_child_for_another_home_is_discarded_and_the_sign_in_starts_cold(children, monkeypatch, tmp_path):
    """Killing mutation: ``_take_warm`` without the ``_same_home`` check -> the sign-in lands in the
    warm child's home, red."""
    provider_signin_child.prewarm_login_child()
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: tmp_path / "other")
    child = provider_signin_child.spawn_login_child("anthropic", "paste_code", None)
    assert children[0].terminated and children[0].written == []
    assert not _is_warm(child) and child.env_home == str(tmp_path / "other")


def test_a_dead_or_broken_warm_child_falls_back_to_cold(children):
    """Killing mutation: drop the ``alive()`` check -> the request is written to a dead child, red;
    drop the ``OSError`` fallback -> BrokenPipeError escapes, red."""
    provider_signin_child.prewarm_login_child()
    children[0].live = False
    assert not _is_warm(provider_signin_child.spawn_login_child("anthropic", "paste_code", None))
    provider_signin_child.prewarm_login_child()
    warm = children[-1]
    warm.broken = True
    child = provider_signin_child.spawn_login_child("anthropic", "paste_code", None)
    assert warm.terminated and not _is_warm(child)


def test_no_child_is_warmed_where_sign_in_runs_in_process(children, monkeypatch):
    """Killing mutation: drop the ``subprocess_signin_enabled`` guard -> a child starts on the phone, red."""
    monkeypatch.setattr(provider_signin, "subprocess_signin_enabled", lambda: False)
    assert provider_signin.prewarm_signin() is False and children == []
    monkeypatch.setattr(provider_signin, "subprocess_signin_enabled", lambda: True)
    assert provider_signin.prewarm_signin() is True and len(children) == 1


def test_list_warms_only_when_asked(monkeypatch):
    """Killing mutation: drop the ``prewarm_signin`` param check -> every list warms, red."""
    from agent_runtime.serve_rpc import provider as family
    from hermes_cli.harness_parts import provider_visibility

    calls = []
    monkeypatch.setattr(provider_signin, "prewarm_signin", lambda: calls.append(1) or True)
    monkeypatch.setattr(provider_visibility, "build_provider_visibility", lambda: {"providers": []})
    assert "result" in family._runtime_provider_list(1, {})
    assert calls == []
    assert "result" in family._runtime_provider_list(1, {"prewarm_signin": True})
    assert calls == [1]


def test_the_warm_child_runs_the_one_request_through_the_login_command(monkeypatch):
    """Killing mutation: ``main`` not forwarding the request's fields -> red; running with no
    request -> a login with no provider, red."""
    from hermes_cli import auth_noninteractive

    seen = []
    monkeypatch.setattr(provider_signin_warm, "_warm", lambda: None)
    monkeypatch.setattr(auth_noninteractive, "auth_login_command", lambda args: seen.append(args) or 7)
    request = {"provider": "anthropic", "flow": "paste_code", "profile": "neko"}
    assert provider_signin_warm.main(io.StringIO(json.dumps(request) + "\n"), idle_seconds=60) == 7
    assert (seen[0].provider, seen[0].flow, seen[0].profile) == ("anthropic", "paste_code", "neko")
    assert provider_signin_warm.main(io.StringIO(""), idle_seconds=60) == 0
    assert len(seen) == 1
