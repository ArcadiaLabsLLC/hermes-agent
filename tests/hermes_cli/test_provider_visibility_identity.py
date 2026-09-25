"""Display labels never become provider routing identities."""

from hermes_cli.harness_parts.provider_visibility import _provider_visibility_auth_logins
from hermes_cli.provider_catalog import provider_login_catalog


def test_login_health_joins_the_runtime_catalog_by_stable_id(monkeypatch):
    from hermes_cli import auth

    for name in ("get_codex_auth_status", "get_minimax_oauth_auth_status",
                 "get_nous_auth_status", "get_qwen_auth_status"):
        monkeypatch.setattr(auth, name, lambda: {"logged_in": False})
    rows = _provider_visibility_auth_logins()
    catalog = {row["id"] for row in provider_login_catalog()}
    assert {row["id"] for row in rows} == {"nous", "openai-codex", "qwen-oauth", "minimax-oauth"}
    assert all(row["id"] in catalog for row in rows)
    assert next(row for row in rows if row["id"] == "nous")["name"] == "Nous Portal"
