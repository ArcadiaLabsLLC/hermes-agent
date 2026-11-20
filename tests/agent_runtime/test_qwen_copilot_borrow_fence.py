"""A QA copy never borrows this computer's own Qwen or Copilot command-line login.

Row RT-FU-A-QA-COPYS-QWEN-AND-COPILOT-SIGN-INS-COME-FROM-THIS-COMPUTERS-OWN-CLI-LOGINS (review w1118a.66 D3):
a QA copy Eternia spawns runs with the machine user's HOME (Eternia's ``linux_direct_launch.dart`` passes
the parent's HOME through), so ``~/.qwen/oauth_creds.json`` and the Copilot CLI's login are the owner's.
The fence is the one per-provider table ``agent_runtime.provider_credential_source.BORROWED_LOGINS``
(HERMES_LAUNCHER_SPAWNED=1). A temp HOME holds a FAKE Qwen CLI login read by upstream's real reader;
every secret here is fake text.
"""

from __future__ import annotations

import json
import pathlib
import time

import pytest

BORROWED = "fake-qwen-cli-owner-login-0000"
POOLED = "fake-qwen-pool-own-row-0000"


@pytest.fixture
def home(tmp_path, monkeypatch):
    root, qwen = tmp_path / "hermes", tmp_path / ".qwen"
    root.mkdir()
    qwen.mkdir()
    # Expired, so an unfenced read would refresh (rotate) it: the fenced one must never get that far.
    (qwen / "oauth_creds.json").write_text(json.dumps({
        "access_token": BORROWED, "refresh_token": "fake-qwen-refresh",
        "expiry_date": int(time.time() * 1000) + 3_600_000}))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setenv("HERMES_LAUNCHER_SPAWNED", "1")
    for var in ("HERMES_AUTH_HOME", "HERMES_QWEN_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    import hermes_constants
    hermes_constants._default_hermes_root_memo = None  # type: ignore[attr-defined]
    (root / "auth.json").write_text(json.dumps({"version": 1, "providers": {}}))
    (root / "config.yaml").write_text("model:\n  provider: qwen-oauth\n", encoding="utf-8")
    return root


def _pool_row(root, source: str, token: str) -> None:
    (root / "auth.json").write_text(json.dumps({"version": 1, "providers": {}, "credential_pool": {"qwen-oauth": [{
        "id": "qwen01", "label": "Qwen", "auth_type": "oauth", "priority": 0, "source": source,
        "access_token": token, "expires_at_ms": int(time.time() * 1000) + 3_600_000}]}}))


def _qwen_rows() -> list[str]:
    from agent.credential_pool import load_pool

    return [str(entry.source) for entry in load_pool("qwen-oauth").entries()]


def _turn_token() -> str | None:
    from hermes_cli.auth import AuthError
    from hermes_cli.runtime_provider import resolve_runtime_provider

    try:
        return resolve_runtime_provider(requested="qwen-oauth").get("api_key")
    except AuthError:
        return None


def _qwen_login_reads_signed_in() -> bool:
    from hermes_cli.harness_parts.provider_visibility import _provider_visibility_auth_logins

    return next(row["logged_in"] for row in _provider_visibility_auth_logins() if row["id"] == "qwen-oauth")


def test_qwen_cli_login_borrow_fence(home):
    """Fenced: no pool row, no turn token, signed out on both Connections facts, the CLI's file untouched.
    Mutation: drop ``qwen-oauth`` from ``BORROWED_LOGINS`` -> every assertion here reds."""
    from agent_runtime.provider_account import _signed_in

    before = (pathlib.Path.home() / ".qwen" / "oauth_creds.json").read_bytes()
    assert _qwen_rows() == []
    assert _turn_token() is None
    assert _signed_in("qwen-oauth") is False
    assert _qwen_login_reads_signed_in() is False
    assert (pathlib.Path.home() / ".qwen" / "oauth_creds.json").read_bytes() == before


def test_a_qwen_cli_row_an_earlier_cli_run_persisted_is_never_spent(home):
    """A ``qwen-cli`` row a CLI run seeded before the fence never seeds back, shows or leases."""
    from agent_runtime.provider_account import _signed_in

    _pool_row(home, "qwen-cli", BORROWED)
    assert "qwen-cli" not in _qwen_rows()
    assert _turn_token() is None
    assert _signed_in("qwen-oauth") is False


def test_the_pools_own_qwen_row_connects_and_is_what_a_turn_spends(home):
    """The shared QA pool's own row (what ``hermes auth add qwen-oauth`` wrote there) is the sign-in."""
    from agent_runtime.provider_account import _signed_in

    _pool_row(home, "manual:qwen_cli", POOLED)
    assert _qwen_rows() == ["manual:qwen_cli"]
    assert _turn_token() == POOLED
    assert _signed_in("qwen-oauth") is True


def test_outside_eternia_qwen_reads_the_cli_login_as_upstream_does(home, monkeypatch):
    monkeypatch.delenv("HERMES_LAUNCHER_SPAWNED")
    assert _qwen_rows() == ["qwen-cli"]
    assert _turn_token() == BORROWED
    assert _qwen_login_reads_signed_in() is True


def test_copilot_acp_reads_not_connected_on_its_cli_login(home, monkeypatch):
    """Upstream reads an ACP provider signed in when its CLI resolves (the CLI owns its own login). Fenced,
    Copilot ACP is connected only through its pool. Mutation: answer None for a non-Anthropic fenced
    provider in ``account_signed_in`` -> the fenced assertion reds."""
    import hermes_cli.auth as auth
    from agent_runtime.provider_account import _signed_in

    monkeypatch.setattr(auth, "get_auth_status", lambda provider=None: {"logged_in": True, "auth_verified": True})
    assert _signed_in("copilot-acp") is False
    monkeypatch.delenv("HERMES_LAUNCHER_SPAWNED")
    assert _signed_in("copilot-acp") is True


def test_the_fence_is_one_table_per_provider():
    from agent_runtime.provider_credential_source import BORROWED_LOGINS, BORROWED_SOURCES

    assert BORROWED_LOGINS == {
        "anthropic": frozenset({"claude_code"}),
        "qwen-oauth": frozenset({"qwen-cli"}),
        "copilot-acp": frozenset(),
    }
    assert BORROWED_SOURCES == {"claude_code", "qwen-cli"}
