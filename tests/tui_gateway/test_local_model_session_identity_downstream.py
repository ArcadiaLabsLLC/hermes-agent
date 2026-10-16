"""An unbuilt session reports its selected model; a compute host's identity and a queued switch keep
their precedence (fork shared-provider regression, 2026-09-29; moved out of upstream's
``test_local_model_session_identity.py``)."""
import pytest

from hermes_cli import runtime_provider as rp
from hermes_cli.local_runtime import endpoint
from tui_gateway import server


@pytest.fixture
def local_route(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_hermes_home", tmp_path)
    cfg = {"model": {"provider": "anthropic", "default": "claude-test"},
           "local_runtime": {"enabled": True}}
    monkeypatch.setattr(rp, "load_config", lambda: cfg)
    monkeypatch.setattr(rp, "_get_model_config", lambda: cfg["model"])
    monkeypatch.setattr("hermes_cli.config.load_config", lambda: cfg)
    monkeypatch.setattr(server, "_load_cfg", lambda: cfg)
    route = {"base_url": "http://127.0.0.1:18434/v1", "api_key": "local-test-key"}
    monkeypatch.setattr(endpoint, "_state_endpoint", lambda: route)
    monkeypatch.setattr(endpoint, "resolve_llamacpp_endpoint", lambda **kw: route)
    monkeypatch.setattr(server, "_probe_credentials", lambda agent: None)
    monkeypatch.setattr("hermes_cli.banner.get_update_result", lambda **kw: None)
    monkeypatch.setattr("hermes_cli.banner.get_available_skills", dict)
    return route, {"cwd": str(tmp_path), "session_key": "local-identity"}


def test_unbuilt_session_reports_its_selected_model(local_route):
    _, session = local_route
    session["model_override"] = {"model": "selected", "provider": "custom:local-test"}
    info = server._session_info(None, session)
    assert (info["model"], info["provider"]) == ("selected", "custom:local-test")
    recovery = server._fallback_session_info(session)
    assert (recovery["model"], recovery["provider"]) == ("selected", "custom:local-test")
    # A compute host's live identity and a queued switch retain their precedence.
    session["_metadata_mirror"] = {"model": "running", "provider": "custom:remote"}
    info = server._session_info(None, session)
    assert (info["model"], info["provider"]) == ("running", "custom:remote")
    session["pending_model_switch"] = {"display_model": "next", "display_provider": "anthropic"}
    info = server._session_info(None, session)
    assert (info["model"], info["provider"]) == ("next", "anthropic")
