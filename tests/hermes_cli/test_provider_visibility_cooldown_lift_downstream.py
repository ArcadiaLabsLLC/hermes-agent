"""Connections must not report a cooldown the pool would lift on selection (w1015b-con-x).

Live 2026-10-15: ``launcher.connections.list`` showed ChatGPT/Codex "Temporarily limited"
until 2026-10-21 while its usage read healthy and a turn answered. The list read never
selected, so nothing ran the lift selection runs (``lift_reopened_cooldowns``).
"""

from __future__ import annotations

from types import SimpleNamespace

from agent import credential_pool
from hermes_cli.harness_parts import provider_visibility


class _Pool:
    def __init__(self, status):
        self.entry = SimpleNamespace(id="e1", label="device", auth_type="oauth", source="device_code",
                                     last_status=status, last_error_code=429, last_error_reason="rate_limit",
                                     last_error_message="rate limited", last_error_reset_at=None,
                                     last_status_at=None, access_token="", runtime_api_key="")
        self.lifts = 0

    def entries(self):
        return [self.entry]

    def peek(self):
        return self.entry

    def lift_reopened_cooldowns(self, *, model=None):
        self.lifts += 1
        self.entry.last_status = credential_pool.STATUS_OK
        return True


def _codex_health(monkeypatch, pool):
    monkeypatch.setattr(credential_pool, "load_pool", lambda provider: pool if provider == "openai-codex" else _Empty())
    monkeypatch.setattr(credential_pool, "list_custom_pool_providers", list)
    monkeypatch.setattr(provider_visibility, "_credential_token_preview", lambda entry: None)
    payload = provider_visibility.build_provider_visibility()
    rows = [row for row in payload["providers"] if row["id"] == "openai-codex"]
    return rows[0]["credentials"][0]["health"]


class _Empty:
    def entries(self):
        return []


def test_a_cooldown_the_pool_lifts_reads_healthy(monkeypatch):
    pool = _Pool(credential_pool.STATUS_EXHAUSTED)
    assert _codex_health(monkeypatch, pool) == {"state": "healthy"}
    assert pool.lifts == 1


def test_a_healthy_pool_is_never_probed(monkeypatch):
    """Positive control: no entry in cooldown -> no lift (the probe is network-bound)."""
    pool = _Pool(credential_pool.STATUS_OK)
    assert _codex_health(monkeypatch, pool) == {"state": "healthy"}
    assert pool.lifts == 0
