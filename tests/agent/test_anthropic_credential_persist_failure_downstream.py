"""Fork-owned half of ``tests/agent/test_anthropic_credential_persist_failure.py``.

Upstream's ``test_reauthentication_clears_the_persist_failure_quarantine`` calls ``monkeypatch.undo()`` mid-test, which unwinds the
shared per-test MonkeyPatch (the root conftest's hermetic pins included) and is
red under the fork's ``_shared_monkeypatch_pin_tripwire``; it is a skip row in
``tests/_downstream/id_markers.py``. This is the same test with the patch
in a scoped ``monkeypatch.context()``. Helpers and fixtures are upstream's,
imported by name.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agent import anthropic_credentials as AA
from agent.credential_pool import STATUS_DEAD, CredentialPool, load_pool

from tests.agent.test_anthropic_credential_persist_failure import (  # noqa: F401 — upstream names the moved tests use
    _break_durable_write,
    _clean_spent_registry,
    _entry,
    _read_claude_pair,
    _rotating_refresh,
    claude_credentials,
    hermes_home,
)

pytestmark = pytest.mark.allow_claude_code_credentials_file


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)


def test_reauthentication_clears_the_persist_failure_quarantine(
    hermes_home, claude_credentials, monkeypatch
):
    """The quarantine is terminal for the spent pair, not for the account.

    Re-running ``claude setup-token`` rewrites the singleton with a genuinely
    new access token; ``_upsert_entry`` sees the token change and clears the
    terminal status, so the user recovers without hand-editing auth.json.
    """
    monkeypatch.setattr(AA, "refresh_anthropic_oauth_pure", _rotating_refresh)
    with monkeypatch.context() as broken_write:
        _break_durable_write(broken_write)
        entry = _entry("claude_code")
        pool = CredentialPool("anthropic", [entry])
        assert pool._refresh_entry(entry, force=True) is None
        assert pool.entries()[0].last_status == STATUS_DEAD

    # Restore only the failed write, preserving the enclosing isolation fixtures,
    # then simulate the re-login with a genuinely new pair.
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_TOKEN", raising=False)
    monkeypatch.setattr(
        "hermes_cli.auth.is_provider_explicitly_configured", lambda pid: True
    )
    monkeypatch.setattr(AA, "claude_code_credentials_path", lambda: claude_credentials)
    monkeypatch.setattr(AA, "_read_claude_code_credentials_from_keychain", lambda: None)
    claude_credentials.write_text(
        json.dumps(
            {
                "claudeAiOauth": {
                    "accessToken": "sk-ant-oat01-relogin",
                    "refreshToken": "sk-ant-ort01-relogin",
                    "expiresAt": int(time.time() * 1000) + 3_600_000,
                    "scopes": ["user:inference", "user:profile"],
                }
            }
        ),
        encoding="utf-8",
    )

    reloaded = [
        e for e in load_pool("anthropic").entries() if e.source == "claude_code"
    ]
    assert reloaded
    assert reloaded[0].refresh_token == "sk-ant-ort01-relogin"
    assert reloaded[0].last_status != STATUS_DEAD
