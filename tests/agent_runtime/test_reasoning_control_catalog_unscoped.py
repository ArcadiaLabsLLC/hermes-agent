"""The end-of-turn ``session.info`` must not raise on a multiplexed serve.

Seen 2026-11-22 on the owner's serve (hermes 1c98abe30bbb, ``tui_gateway_crash.log``, thread
``prompt-turn-*``): after every finished turn of an openai-codex chat with an effort set,
``prompt_turn.run_body`` -> ``session_workdir._emit_settled_session_info`` -> ``server._session_info``
-> ``route_supported_efforts`` -> ``reasoning_control_catalog._control_catalog_key`` ->
``get_secret('NOUS_INFERENCE_BASE_URL')`` raised ``UnscopedSecretError``: the turn had already
released its secret scope (``prompt_turn._release_turn_scopes``) while its HERMES_HOME override was
still bound, and the serve multiplexes. Every RPC ``session.info`` read reaches the same key unscoped.

Covers ``agent_runtime/reasoning_control_catalog.py::_control_catalog_key`` (its
``profile_secret_fallback`` around the env reads) through ``tui_gateway/server.py::_session_info`` and
``tui_gateway/session_workdir.py::_emit_settled_session_info``.

Killing mutation, red recorded 2026-11-22: drop the ``with profile_secret_fallback(home):`` in
``_control_catalog_key`` (read the env dict bare). All three tests go red with
``UnscopedSecretError: Hermes could not read this profile's NOUS_INFERENCE_BASE_URL``.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import secret_scope
from agent_runtime.reasoning_control_catalog import cached_control_capabilities, record_control_catalog
from hermes_constants import get_hermes_home, reset_hermes_home_override, set_hermes_home_override

_MODEL = "future-codex-model"


def _codex_agent() -> SimpleNamespace:
    return SimpleNamespace(reasoning_config={"enabled": True, "effort": "high"}, service_tier=None,
                           model=_MODEL, provider="openai-codex", session_id="sess-key", api_mode=None)


def _record_inside(secrets: dict, *, profile_home: str | None = None) -> None:
    """What a scoped turn does: write the catalog under the secret scope it bound."""
    token = secret_scope.set_secret_scope(secrets, profile_home=profile_home)
    try:
        record_control_catalog("openai-codex", [{"slug": _MODEL, "supported_reasoning_levels": ["low", "high"]}])
    finally:
        secret_scope.reset_secret_scope(token)


@pytest.fixture
def multiplexed():
    secret_scope.set_multiplex_active(True)
    yield
    secret_scope.set_multiplex_active(False)


def test_settled_session_info_emit_after_the_turn_released_its_scope(monkeypatch, multiplexed):
    # ``session_workdir.register`` rebinds its helpers onto the server namespace; the turn calls that copy.
    from tui_gateway import server

    (get_hermes_home() / ".env").write_text("NOUS_INFERENCE_BASE_URL=https://inference.example/v1\n")
    from tui_gateway.launch_profile_policy import launch_secret_scope
    _record_inside(launch_secret_scope(get_hermes_home()))
    emitted = []
    monkeypatch.setattr(server, "_emit", lambda event, sid, payload: emitted.append((event, payload)),
                        raising=False)
    monkeypatch.setattr(server, "_reconcile_session_cwd_from_terminal", lambda session: False,
                        raising=False)
    assert secret_scope.current_secret_scope() is None  # the state the turn's finally leaves
    server._emit_settled_session_info("sid-1", {"session_key": "sess-key"}, _codex_agent())
    [(event, info)] = emitted
    assert event == "session.info"
    assert info["reasoning_effort_wire"] == "high"


def test_unscoped_read_finds_the_catalog_the_scoped_turn_wrote_for_a_profile_home(tmp_path: Path, multiplexed):
    """Positive control for the key: the fallback reads the SAME home's secrets the turn bound, so the
    settled read (home override still bound, secret released) hits what the turn recorded."""
    profile = tmp_path / "profiles" / "coder"
    profile.mkdir(parents=True)
    (profile / ".env").write_text("NOUS_INFERENCE_BASE_URL=https://coder.example/v1\n")
    home_token = set_hermes_home_override(str(profile))
    try:
        _record_inside(secret_scope.build_profile_secret_scope(profile), profile_home=str(profile))
        assert secret_scope.current_secret_scope() is None
        caps = cached_control_capabilities("openai-codex", _MODEL)
        assert caps is not None and caps["supported_efforts"] == ["low", "high"]
    finally:
        reset_hermes_home_override(home_token)


def test_rpc_session_info_with_no_scope_at_all(multiplexed):
    from tui_gateway.server import _session_info

    info = _session_info(_codex_agent(), {"session_key": "sess-key"})
    assert info["reasoning_effort"] == "high"
    assert info["reasoning_effort_wire"]  # the static Codex ladder answers when no catalog is cached
