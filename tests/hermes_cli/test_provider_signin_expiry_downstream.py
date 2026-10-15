"""Sign-in deadlines come from the selected provider flow, never the registry cap."""
import json
from types import SimpleNamespace

import pytest

from agent_runtime import provider_signin
from hermes_cli import provider_browser_login as wire


def test_registry_keeps_provider_deadline_and_unknown_nulls():
    registry = provider_signin.ProviderSignIns(clock=lambda: 1000)
    session = provider_signin._Session("id", "nous", "device_code", None, 900)
    assert session.view()["provider_started_at"] is None
    assert session.view()["provider_expires_at"] is None
    registry._apply(session, json.dumps({"event": "expiry", "provider_started_at": 1000, "provider_expires_at": 1120}))
    assert session.view()["provider_started_at"] == 1000
    assert session.view()["provider_expires_at"] == 1120
    for value in (None, "SENTINEL", False, float("nan"), float("inf"), -1):
        registry._apply(session, json.dumps({"event": "expiry", "provider_started_at": 1000, "provider_expires_at": value}))
        assert session.view()["provider_expires_at"] == 1120


@pytest.mark.parametrize("duration", [None, 120])
def test_real_codex_device_code_deadline_uses_provider_response(monkeypatch, duration):
    from hermes_cli import auth_codex as source
    data = {"user_code": "code", "device_auth_id": "id", "interval": 3}
    if duration is not None:
        data["expires_in"] = duration
    monkeypatch.setattr(source, "_codex_request_device_code", lambda *args: data)
    monkeypatch.setattr(source, "_codex_poll_authorization_code", lambda *args, **kw: {})
    monkeypatch.setattr(source, "_codex_exchange_authorization_code", lambda *args: {})
    monkeypatch.setattr(source.time, "time", lambda: 1000)
    seen = []
    source._codex_device_code_login(on_expiry=lambda *args: seen.append(args))
    assert seen == ([] if duration is None else [(1000, 1120)])


def test_browser_deadline_is_the_actual_callback_timeout(monkeypatch):
    from hermes_cli import auth_codex_browser as source
    monkeypatch.setattr(source.secrets, "token_urlsafe", lambda *args: "state")
    monkeypatch.setattr(source, "_bind_loopback_callback_server", lambda *args, **kw: SimpleNamespace(server_address=("127.0.0.1", 1455)))
    monkeypatch.setattr(source, "_serve_loopback_callback", lambda *args, **kw: {"state": "state", "code": "code"})
    monkeypatch.setattr(source, "_codex_browser_exchange_code", lambda *args, **kw: {})
    monkeypatch.setattr(source.time, "time", lambda: 1000)
    seen = []
    source._codex_browser_login(open_browser=False, timeout_seconds=75, on_expiry=lambda *args: seen.append(args))
    assert seen == [(1000, 1075)]


@pytest.mark.parametrize("provider,module_name,grant_name,method", [
    ("openai-codex", "auth_codex", "_codex_device_code_login", "device_code"),
    ("openai-codex", "auth_codex_browser", "_codex_browser_login", "browser"),
    ("xai-oauth", "auth_xai", "_xai_oauth_device_code_login", "device_code"),
    ("minimax-oauth", "auth_minimax", "_minimax_oauth_login", "device_code"),
    ("nous", "auth_nous", "_nous_device_code_login", "device_code"),
])
def test_expiry_crosses_the_real_machine_driver(monkeypatch, provider, module_name, grant_name, method):
    import importlib
    from hermes_cli import anon_auth
    module = importlib.import_module("hermes_cli." + module_name)
    def grant(*, on_expiry, on_verification, **kw):
        on_expiry(1000, 1120)
        on_verification("https://example.invalid", "code")
        return {"tokens": {}, "last_refresh": None}
    monkeypatch.setattr(module, grant_name, grant)
    monkeypatch.setattr(wire, "_persist", lambda *args: None)
    monkeypatch.setattr(anon_auth, "current_nous_state", lambda: None)
    from hermes_cli import auth_codex, auth_nous
    monkeypatch.setattr(auth_codex, "_save_codex_tokens", lambda *args, **kw: None)
    monkeypatch.setattr(auth_nous, "_sync_nous_pool_from_auth_store", lambda: None)
    events = []
    assert wire.run_browser_login(provider, home="fixture", flow=method, emit=events.append) == 0
    assert events[0] == {"event": "expiry", "provider_started_at": 1000, "provider_expires_at": 1120, "home": "fixture"}
    registry = provider_signin.ProviderSignIns(clock=lambda: 1000)
    session = provider_signin._Session("id", provider, method, None, 900)
    for event in events:
        registry._apply(session, json.dumps(event))
    assert session.view()["provider_expires_at"] - session.view()["provider_started_at"] == 120
