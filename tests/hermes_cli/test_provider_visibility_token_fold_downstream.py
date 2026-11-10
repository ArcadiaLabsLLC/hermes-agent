"""A static env token one profile's pool refused reads expired in every profile (RT-CONNECTIONS-SHOWS-EXPIRED-LOGIN-CONNECTED).

Live 2026-11-08: Connections showed "Connected · ANTHROPIC_TOKEN" in profile ``base``
while profile ``neko``'s pool had recorded that same May token dead; the ``.env``
line was copied into ten profiles, and each pool judged it alone. Sign-out then
called that line "another sign-in" without saying where it lives.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import hermes_constants
from agent import credential_pool
from agent_runtime import provider_account
from hermes_cli.harness_parts import provider_visibility

SECRET = "SENTINEL-ENV-TOKEN-0000000000"


def _store(path, provider: str, *entries: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"providers": {}, "credential_pool": {provider: list(entries)}}), encoding="utf-8")


def _env_entry(status: str | None, code: int | None = None, token: str = SECRET) -> dict:
    return {"id": "e1", "label": "ANTHROPIC_TOKEN", "auth_type": "api_key", "source": "env:ANTHROPIC_TOKEN",
            "access_token": token, "last_status": status, "last_error_code": code,
            "last_error_reason": "invalid_grant" if status else None, "last_status_at": None}


def _namespace(tmp_path, monkeypatch, *, neko_status: str | None, neko_code: int | None = None):
    root = tmp_path / "root"
    _store(root / "profiles" / "base" / "auth.json", "anthropic", _env_entry(None))
    _store(root / "profiles" / "neko" / "auth.json", "anthropic", _env_entry(neko_status, neko_code))
    monkeypatch.setattr(hermes_constants, "get_default_hermes_root", lambda home=None: root)
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: root / "profiles" / "base")
    return root


class _Pool:
    def __init__(self, *entries):
        self._entries = list(entries)

    def entries(self):
        return list(self._entries)

    def peek(self):
        return self._entries[0] if self._entries else None


def _pool_entry(source: str = "env:ANTHROPIC_TOKEN", token: str = SECRET):
    return SimpleNamespace(id="e1", label="ANTHROPIC_TOKEN", auth_type="api_key", source=source,
                           access_token=token, last_status=None, last_error_code=None, last_error_reason=None,
                           last_error_message=None, last_error_reset_at=None, last_status_at=None)


def _anthropic_health(monkeypatch, entry) -> dict:
    monkeypatch.setattr(credential_pool, "load_pool",
                        lambda provider: _Pool(entry) if provider == "anthropic" else _Pool())
    monkeypatch.setattr(credential_pool, "list_custom_pool_providers", list)
    payload = provider_visibility.build_provider_visibility()
    assert SECRET not in json.dumps(payload)
    row = next(row for row in payload["providers"] if row["id"] == "anthropic")
    return row["credentials"][0]["health"]


def test_a_token_a_sibling_profile_found_dead_reads_expired_here(tmp_path, monkeypatch):
    """Killing mutation: ``"health": _credential_health(entry)`` (no fold) -> healthy, red."""
    _namespace(tmp_path, monkeypatch, neko_status=credential_pool.STATUS_DEAD, neko_code=401)
    health = _anthropic_health(monkeypatch, _pool_entry())
    assert (health["state"], health["reason"], health["code"]) == ("dead", "login_expired", 401)
    assert "neko" in health["message"]


def test_a_rate_limited_sibling_leaves_the_token_healthy(tmp_path, monkeypatch):
    """A 429 is the account's window, not the token. Killing mutation: ``rate_limited`` in
    ``_REFUSED_STATES`` -> expired, red."""
    _namespace(tmp_path, monkeypatch, neko_status=credential_pool.STATUS_EXHAUSTED, neko_code=429)
    assert _anthropic_health(monkeypatch, _pool_entry()) == {"state": "healthy"}


def test_a_401_sibling_counts_and_a_different_token_does_not(tmp_path, monkeypatch):
    """Killing mutation: match by source instead of token digest -> the other token reads expired, red."""
    _namespace(tmp_path, monkeypatch, neko_status=credential_pool.STATUS_EXHAUSTED, neko_code=401)
    assert _anthropic_health(monkeypatch, _pool_entry())["reason"] == "login_expired"
    assert _anthropic_health(monkeypatch, _pool_entry(token="ANOTHER-TOKEN-1111111111")) == {"state": "healthy"}


def test_only_env_tokens_fold(tmp_path, monkeypatch):
    """A stored login refreshes per profile; only a copied env line is one credential.
    Killing mutation: drop the ``env:`` guard in ``_folded_health`` -> red."""
    _namespace(tmp_path, monkeypatch, neko_status=credential_pool.STATUS_DEAD, neko_code=401)
    monkeypatch.setattr(credential_pool, "load_pool", lambda provider: _Pool(
        _pool_entry(), _pool_entry(source="manual")) if provider == "anthropic" else _Pool())
    monkeypatch.setattr(credential_pool, "list_custom_pool_providers", list)
    payload = provider_visibility.build_provider_visibility()
    env, manual = next(row for row in payload["providers"] if row["id"] == "anthropic")["credentials"]
    assert (env["health"]["reason"], manual["health"]) == ("login_expired", {"state": "healthy"})


def test_the_anthropic_key_row_reports_expired(tmp_path, monkeypatch):
    """Killing mutation: ``"expired": False`` on the Anthropic api_keys row -> red."""
    from hermes_cli import auth

    _namespace(tmp_path, monkeypatch, neko_status=credential_pool.STATUS_DEAD, neko_code=401)
    monkeypatch.setattr(auth, "get_anthropic_key", lambda: SECRET)
    rows = provider_visibility._provider_visibility_api_keys()
    assert SECRET not in json.dumps(rows)
    assert next(r for r in rows if r["name"] == "Anthropic") == {"name": "Anthropic", "configured": True,
                                                                 "expired": True}
    monkeypatch.setattr(auth, "get_anthropic_key", lambda: "ANOTHER-TOKEN-1111111111")
    assert next(r for r in provider_visibility._provider_visibility_api_keys()
                if r["name"] == "Anthropic")["expired"] is False


def test_signout_names_the_env_files_that_still_hold_the_token(tmp_path, monkeypatch):
    """Killing mutation: ``_env_tokens_left`` answering ``[]`` -> red; a value read out -> SECRET leaks, red."""
    from hermes_cli import auth, auth_commands

    root = _namespace(tmp_path, monkeypatch, neko_status=None)
    (root / ".env").write_text(f"ANTHROPIC_TOKEN={SECRET}\n", encoding="utf-8")
    (root / "profiles" / "neko" / ".env").write_text(f"OTHER=1\nexport ANTHROPIC_TOKEN={SECRET}\n",
                                                     encoding="utf-8")
    (root / "profiles" / "base" / ".env").write_text("ANTHROPIC_TOKEN_OLD=1\n", encoding="utf-8")
    monkeypatch.setattr(auth_commands, "auth_logout_command", lambda args: None)
    monkeypatch.setattr(auth, "get_auth_status", lambda provider: {"logged_in": True})
    monkeypatch.setattr(credential_pool, "load_pool", lambda provider: _Pool(_pool_entry()))
    result = provider_account.provider_signout("anthropic")
    assert SECRET not in json.dumps(result)
    assert result["env_tokens"] == [{"variable": "ANTHROPIC_TOKEN", "files": [".env", "profiles/neko/.env"]}]
