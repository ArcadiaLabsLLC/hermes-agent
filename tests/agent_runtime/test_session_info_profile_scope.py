"""A chat's ``session.info`` is built under that chat's own profile scope, whoever asks for it.

Row RT-FU-A-CHATS-STATUS-READ-OUTSIDE-ITS-TURN-RUNS-UNDER-NO-PROFILE-SCOPE: upstream's
``tui_gateway/server.py::_session_info`` has ~30 callers and the RPC dispatcher binds no profile scope for
them, so on a multiplexed serve a second profile's chat had its status built against the LAUNCH home (its
reasoning catalog missed; any secret read raised ``UnscopedSecretError``). Covers the fork seam
``agent_runtime/gateway/session_info_scope.py::register`` (installed by ``agent_runtime.gateway_extensions``)
through the real RPC path (``server.handle_request`` -> ``session.cwd.set`` -> ``_cwd_info`` -> ``_session_info``).

Killing mutations, reds recorded 2026-11-23 (see the commit body):
- drop ``session_info_scope.register(server)`` from ``gateway_extensions.register``: all three red;
- bind ``{"profile_home": None}`` instead of the session's home in the wrapper: all three red;
- drop the wrapper's ``if session is None`` lookup: ``test_agent_only_lookup_...`` red.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import secret_scope
from agent_runtime.reasoning_control_catalog import record_control_catalog
from hermes_constants import get_hermes_home

_MODEL = "future-codex-model"


def _codex_agent() -> SimpleNamespace:
    return SimpleNamespace(reasoning_config={"enabled": True, "effort": "high"}, service_tier=None,
                           model=_MODEL, provider="openai-codex", session_id="beta-key", api_mode=None)


@pytest.fixture
def two_profiles(tmp_path: Path):
    """Launch home and a second profile, each with its own secret; multiplexing on, as on a serve that
    hosts both. The second profile's catalog says its route sends at most ``medium``."""
    (get_hermes_home() / ".env").write_text("PROBE_SECRET=launch-secret\n")
    beta = tmp_path / "profiles" / "beta"
    beta.mkdir(parents=True)
    (beta / ".env").write_text("PROBE_SECRET=beta-secret\n")
    from tui_gateway import server
    with server._session_profile_runtime_scope({"profile_home": str(beta)}, hydrate_secrets=False):
        record_control_catalog("openai-codex", [{"slug": _MODEL, "supported_reasoning_levels": ["low", "medium"]}])
    secret_scope.set_multiplex_active(True)
    yield beta
    secret_scope.set_multiplex_active(False)


@pytest.fixture
def probe(monkeypatch):
    """What ``_session_info``'s own body sees: the home it runs under and the profile secret it can read."""
    from tui_gateway import server
    from hermes_constants import get_hermes_home as home_now
    seen: list[tuple[Path, str]] = []
    real = server._display_cfg

    def _display_cfg():
        try:
            secret = secret_scope.get_secret("PROBE_SECRET") or ""
        except secret_scope.UnscopedSecretError:
            secret = "<unscoped>"
        seen.append((Path(home_now()), secret))
        return real()

    monkeypatch.setattr(server, "_display_cfg", _display_cfg)
    return seen


def _live_session(monkeypatch, sid: str, profile_home: Path | None, agent) -> dict:
    from tui_gateway import server
    session = {"session_key": "beta-key", "agent": agent, "running": False,
               "profile_home": str(profile_home) if profile_home else None}
    monkeypatch.setitem(server._sessions, sid, session)
    return session


def test_rpc_session_info_for_a_second_profile_chat_reads_that_profile(monkeypatch, two_profiles, probe, tmp_path):
    from tui_gateway import server
    _live_session(monkeypatch, "sid-beta", two_profiles, _codex_agent())
    emitted = []
    monkeypatch.setattr(server, "_emit", lambda event, sid, payload: emitted.append((event, sid, payload)))
    monkeypatch.setattr(server, "_set_session_cwd", lambda session, raw: raw)  # the cwd write is not under test

    response = server.handle_request({"jsonrpc": "2.0", "id": 7, "method": "session.cwd.set",
                                      "params": {"session_id": "sid-beta", "cwd": str(tmp_path)}})

    assert "error" not in response, response
    info = response["result"]
    assert info["reasoning_effort"] == "high"
    assert info["reasoning_effort_wire"] == "medium"  # beta's catalog; the launch home's static ladder sends high
    assert probe and all(seen == (two_profiles, "beta-secret") for seen in probe), probe
    assert [e[0] for e in emitted] == ["session.info"]


def test_settled_emit_for_a_second_profile_chat_after_the_turn_released_its_secret(monkeypatch, two_profiles,
                                                                                    probe):
    """The turn's end-of-turn emit runs with no secret scope bound (``prompt_turn._release_turn_scopes``)."""
    from tui_gateway import server
    session = _live_session(monkeypatch, "sid-beta", two_profiles, _codex_agent())
    emitted = []
    monkeypatch.setattr(server, "_emit", lambda event, sid, payload: emitted.append(payload))
    monkeypatch.setattr(server, "_reconcile_session_cwd_from_terminal", lambda session: False)
    assert secret_scope.current_secret_scope() is None

    server._emit_settled_session_info("sid-beta", session, session["agent"])

    [info] = emitted
    assert info["reasoning_effort_wire"] == "medium"
    assert probe == [(two_profiles, "beta-secret")]


def test_agent_only_lookup_finds_the_session_and_its_profile_scope(monkeypatch, two_profiles, probe):
    """Callers passing only the agent (``_session_info(agent)``): the scope comes from the session upstream's
    own lookup finds, so a second profile's chat still reads that profile."""
    from tui_gateway import server
    agent = _codex_agent()
    _live_session(monkeypatch, "sid-beta", two_profiles, agent)

    info = server._session_info(agent)

    assert info["reasoning_effort_wire"] == "medium"
    assert probe == [(two_profiles, "beta-secret")]
