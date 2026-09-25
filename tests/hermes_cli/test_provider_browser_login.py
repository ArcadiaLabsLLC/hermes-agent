"""Machine auth uses real scoped persistence; only provider network grants are replaced."""

from __future__ import annotations

import importlib
import json
import logging
from types import SimpleNamespace

import pytest

from hermes_cli import provider_browser_login as wire


def events(capsys):
    captured = capsys.readouterr()
    assert "SENTINEL" not in captured.out + captured.err
    return [json.loads(line) for line in captured.out.splitlines()]


def test_catalog_advertises_only_real_machine_methods():
    from hermes_cli.provider_catalog import provider_login_catalog

    catalog = {row["id"]: row for row in provider_login_catalog()}
    supported = {key for key, row in catalog.items() if row["browser_login"]}
    assert supported == {"openai-codex", "xai-oauth", "minimax-oauth", "nous"}
    assert catalog["openai-codex"]["browser_login_methods"] == ["browser", "device_code"]
    for provider in supported - {"openai-codex"}:
        assert catalog[provider]["browser_login_methods"] == ["device_code"]
    assert not catalog["qwen-oauth"]["browser_login_methods"]


@pytest.mark.parametrize("failure", [False, True])
def test_wire_has_one_terminal_and_never_serializes_helper_output(monkeypatch, capsys, failure):
    original_disable = logging.root.manager.disable

    def driver(verify, flow):
        assert flow == "browser"
        verify("https://provider.example/authorize", "USER-CODE")
        print("SENTINEL printed access token")
        logging.critical("SENTINEL logged refresh token")
        if failure:
            raise RuntimeError("SENTINEL exception response")

    monkeypatch.setitem(wire._DRIVERS, "openai-codex", driver)
    result = wire.browser_login_command("openai-codex", home="selected", flow="browser")
    assert result == int(failure)
    rows = events(capsys)
    assert [row["event"] for row in rows] == ["code", "pending", "error" if failure else "done"]
    assert all(row["home"] == "selected" for row in rows)
    assert rows[-1]["ok"] is not failure
    assert logging.root.manager.disable == original_disable


def test_unknown_method_never_enters_auth(monkeypatch, capsys):
    monkeypatch.setitem(wire._DRIVERS, "nous", lambda *_: pytest.fail("Unsupported flow ran"))
    assert wire.browser_login_command("nous", home="selected", flow="browser") == 1
    assert events(capsys)[0]["code"] == "unsupported_flow"


@pytest.mark.parametrize("provider,module_name,grant_name,method", [
    ("openai-codex", "auth_codex", "_codex_device_code_login", "device_code"),
    ("openai-codex", "auth_codex_browser", "_codex_browser_login", "browser"),
    ("xai-oauth", "auth_xai", "_xai_oauth_device_code_login", "device_code"),
    ("minimax-oauth", "auth_minimax", "_minimax_oauth_login", "device_code"),
    ("nous", "auth_nous", "_nous_device_code_login", "device_code"),
])
def test_real_drivers_persist_a_b_a_without_switching_models(
    provider, module_name, grant_name, method, tmp_path, monkeypatch, capsys
):
    from hermes_cli.auth_noninteractive import auth_login_command
    from hermes_constants import get_hermes_home

    module = importlib.import_module(f"hermes_cli.{module_name}")
    calls = []

    def grant(*, on_verification, **options):
        assert options.get("open_browser", False) is False
        if provider == "minimax-oauth":
            assert options["persist"] is False
        on_verification("https://provider.example/sign-in", "USER-CODE")
        name = get_hermes_home().name
        calls.append(name)
        tokens = {"access_token": f"SENTINEL-{name}", "refresh_token": f"SENTINEL-refresh-{name}"}
        return {**tokens, "tokens": tokens, "last_refresh": "2026-09-25T00:00:00Z",
                "portal_base_url": "https://provider.example", "expires_at": "2099-01-01T00:00:00Z"}

    monkeypatch.setattr(module, grant_name, grant)
    roots = {name: tmp_path / name for name in ["a", "b"]}
    for root in roots.values():
        root.mkdir()
        (root / "auth.json").write_text(json.dumps({"version": 1, "active_provider": "openrouter", "providers": {}}))
        (root / "config.yaml").write_text("model:\n  provider: openrouter\n  default: keep-model\n")
    snapshots = {}
    for name in ["a", "b", "a"]:
        root = roots[name]
        monkeypatch.setenv("HERMES_HOME", str(root))
        monkeypatch.setenv("HERMES_AUTH_HOME", str(root))
        assert auth_login_command(SimpleNamespace(provider=provider, flow=method, profile=None, json=True)) == 0
        rows = events(capsys)
        assert rows[-1] == {"event": "done", "ok": True, "home": str(root)}
        stored = json.loads((root / "auth.json").read_text())
        assert stored["active_provider"] == "openrouter"
        saved = stored["providers"][provider]
        assert saved.get("tokens", saved)["access_token"] == f"SENTINEL-{name}"
        assert (root / "config.yaml").read_text() == "model:\n  provider: openrouter\n  default: keep-model\n"
        for other, content in snapshots.items():
            if other != name:
                assert (roots[other] / "auth.json").read_bytes() == content
        snapshots[name] = (root / "auth.json").read_bytes()
    assert calls == ["a", "b", "a"]


def test_failed_persistence_is_never_done(tmp_path, monkeypatch, capsys):
    from hermes_cli import auth, auth_xai
    monkeypatch.setattr(auth_xai, "_xai_oauth_device_code_login", lambda **_: {"access_token": "SENTINEL"})

    def refuse(*_):
        raise OSError("SENTINEL disk write failed")

    monkeypatch.setattr(auth, "persist_provider_login", refuse)
    assert wire.browser_login_command("xai-oauth", home=str(tmp_path)) == 1
    assert [row["event"] for row in events(capsys)] == ["error"]


def test_nous_guest_uses_canonical_upgrade_not_a_second_login(monkeypatch):
    from hermes_cli import anon_auth, auth_nous
    monkeypatch.setattr(anon_auth, "current_nous_state", lambda: {"guest": True})
    monkeypatch.setattr(anon_auth, "is_guest_state", lambda _: True)
    monkeypatch.setattr(anon_auth, "run_sign_in", lambda: iter([SimpleNamespace(terminal=True, ok=True)]))
    monkeypatch.setattr(auth_nous, "_nous_device_code_login", lambda **_: pytest.fail("Guest bypassed canonical upgrade"))
    auth_nous.login_nous_account(lambda *_: pytest.fail("No code emitted by fixture"))
