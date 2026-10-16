"""Fork: ``resolve_codex_runtime_credentials``' pool fallback honours the pool's own cooldown.

``CredentialPool._available_entries`` refuses an EXHAUSTED row until
``_exhausted_until`` (``last_error_reset_at``, else ``last_status_at`` + the
status TTL). The pool-only fallback used to read ``last_error_reset_at`` alone,
so a row the pool had just declared exhausted without a reset stamp was served.

Killing mutation: drop ``_codex_pool_row_refused`` from ``_pool_codex_credential``
-> ``test_a_row_exhausted_without_a_reset_stamp_is_not_served`` reds.
"""

from __future__ import annotations

import json
import time

import hermes_cli.auth as auth_mod
from hermes_cli import auth_codex
from hermes_cli.auth import resolve_codex_runtime_credentials


def _row(row_id: str, token: str, priority: int, **status) -> dict:
    return {"id": row_id, "label": row_id, "auth_type": "oauth", "priority": priority,
            "source": "device_code", "access_token": token, **status}


def _exhausted(at: float) -> dict:
    return {"last_status": "exhausted", "last_status_at": at, "last_error_code": 429,
            "last_error_reason": "usage_limit_reached"}


def _resolve(tmp_path, monkeypatch, rows: list[dict]) -> dict:
    home = tmp_path / "hermes"
    home.mkdir(parents=True, exist_ok=True)
    store = {"version": 1, "providers": {}, "credential_pool": {"openai-codex": rows}}
    (home / "auth.json").write_text(json.dumps(store), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(auth_mod, "_probe_codex_quota_restored", lambda token, **kw: False)
    monkeypatch.setattr(auth_codex, "_probe_codex_quota_restored", lambda token, **kw: False)
    return resolve_codex_runtime_credentials()


def test_a_row_exhausted_without_a_reset_stamp_is_not_served(tmp_path, monkeypatch):
    rows = [_row("frozen", "tok-frozen", 0, **_exhausted(time.time())), _row("spare", "tok-spare", 1)]
    resolved = _resolve(tmp_path, monkeypatch, rows)
    assert resolved["api_key"] == "tok-spare"
    assert resolved["source"] == "credential_pool"


def test_a_row_whose_status_ttl_elapsed_is_served_again(tmp_path, monkeypatch):
    # Positive control: the same row, its cooldown long over, is the first choice again.
    rows = [_row("frozen", "tok-frozen", 0, **_exhausted(time.time() - 30 * 24 * 3600)),
            _row("spare", "tok-spare", 1)]
    assert _resolve(tmp_path, monkeypatch, rows)["api_key"] == "tok-frozen"


def test_a_dead_row_is_not_served(tmp_path, monkeypatch):
    dead = {"last_status": "dead", "last_status_at": time.time(), "last_error_code": 401}
    rows = [_row("revoked", "tok-revoked", 0, **dead), _row("spare", "tok-spare", 1)]
    assert _resolve(tmp_path, monkeypatch, rows)["api_key"] == "tok-spare"
