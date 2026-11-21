"""Display labels never become provider routing identities."""

from hermes_cli.harness_parts.provider_visibility import _provider_visibility_auth_logins
from hermes_cli.provider_login_catalog import provider_login_catalog


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


def test_a_switched_off_provider_is_left_out_of_the_logins_before_its_probe(monkeypatch):
    """RT-FU-A-SWITCHED-OFF-PROVIDER-STAYS-OUT-OF-THE-PROVIDER-LISTS-SIGN-INS: with
    ``providers.qwen-oauth.enabled: false`` (both bundle profiles) the provider list carries no
    ``qwen-oauth`` login and the Qwen CLI's file is never probed; the other three still are.

    Killing mutation: drop the ``provider_disabled`` skip in ``_provider_visibility_auth_logins``
    -> red (qwen-oauth listed and probed)."""
    import json
    from pathlib import Path

    from hermes_cli import auth
    from hermes_constants import get_hermes_home

    probed: list[str] = []
    for name in ("get_codex_auth_status", "get_minimax_oauth_auth_status",
                 "get_nous_auth_status", "get_qwen_auth_status"):
        monkeypatch.setattr(auth, name, lambda name=name: probed.append(name) or {"logged_in": False})

    # Positive control: by default Qwen's login is probed and listed.
    assert "qwen-oauth" in {row["id"] for row in _provider_visibility_auth_logins()}
    assert "get_qwen_auth_status" in probed

    home = Path(get_hermes_home())
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        json.dumps({"providers": {"qwen-oauth": {"enabled": False}}}), encoding="utf-8")
    probed.clear()
    rows = _provider_visibility_auth_logins()
    assert {row["id"] for row in rows} == {"nous", "openai-codex", "minimax-oauth"}
    assert "get_qwen_auth_status" not in probed and len(probed) == 3
