"""The phone credentials seam (embedded-hermes Stage 2 step 5).

Against the fake host store (``agent_runtime.host_store.fake``): after a session with
a signed-in provider and a chat, a byte scan of the app folder finds no secret; a second
profile or a second install cannot read the first's credentials; the machine-wide
borrowed CLI logins are refused. Every scan runs with a POSITIVE CONTROL — the same
scenario unbound must leak the same needles, so the scan is proven to look where the
bytes would be.

Chat history is upstream's own files, bound or not (owner ruling 2026-09-30: no
app-level seal; the phone host puts the OS's file protection on the history folder —
``tests/agent_runtime/test_embedded_phone_session.py`` pins that the phone boot asks).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_runtime.host_store import binding, secret_files
from agent_runtime.host_store.fake import FakeHostSecureStore

ACCESS = "hsec-access-token-5d1f"
REFRESH = "hsec-refresh-token-9a2c"
API_KEY = "sk-or-hsec-api-key-7e3b"
PKCE = "hsec-anthropic-pkce-0c4d"
MCP = "hsec-mcp-oauth-token-2b8e"
HMAC = "hsec-webhook-hmac-6f1a"
PAIRING = "hsec-pairing-code-3c9d"
CHAT = "periwinkle-zeppelin-marmalade"
DUMP = "tangerine-obelisk-quartet"
SECRETS = (ACCESS, REFRESH, API_KEY, PKCE, MCP, HMAC, PAIRING)
HISTORY = (CHAT, DUMP)
NEEDLES = SECRETS + HISTORY


@pytest.fixture(autouse=True)
def _unbound_after():
    binding.unbind_host_store()
    yield
    binding.unbind_host_store()


@pytest.fixture()
def app(tmp_path, monkeypatch):
    root = tmp_path / "app"
    home = root / "hermes"
    home.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_SHARED_AUTH_DIR", str(home / "shared"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return root, home


def _session(home: Path) -> None:
    """A signed-in provider, an API key, the other census stores, and one chat — through the real writers."""
    from agent.anthropic_credentials import _write_hermes_oauth_credentials
    from gateway import pairing
    from hermes_cli import auth, auth_nous, config, webhook
    from hermes_state import SessionDB, divert_session_transcript_jsonl
    from tools import mcp_oauth

    store = auth._load_auth_store()
    store.setdefault("providers", {})["nous"] = {"access_token": ACCESS, "refresh_token": REFRESH}
    auth._save_auth_store(store)
    auth_nous._write_shared_nous_state({"access_token": ACCESS, "refresh_token": REFRESH})
    config.save_env_value("OPENROUTER_API_KEY", API_KEY)
    _write_hermes_oauth_credentials(PKCE, PKCE + "-r", 1)
    mcp_oauth._write_json(mcp_oauth._get_token_dir() / "srv.json", {"access_token": MCP})
    pairing._save_json_file(home / "pairing" / "pending.json", {"code": PAIRING})
    webhook._mutate_subscriptions(lambda subs: subs.update({"route": {"secret": HMAC}}))

    db = SessionDB(home / "state.db")
    try:
        db.create_session("s1", source="cli")
        db.append_message("s1", role="user", content=f"remember the {CHAT} please")
        assert db.search_messages(CHAT.split("-")[0])
    finally:
        db.close()
    divert_session_transcript_jsonl("s1", [{"role": "assistant", "content": DUMP}])
    os.environ.pop("OPENROUTER_API_KEY", None)


def _leaks(root: Path) -> set:
    found = set()
    for path in root.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            found.update(n for n in NEEDLES if n.encode("utf-8") in data or n.encode("utf-16-le") in data)
    return found


def test_a_session_leaves_no_secret_and_no_chat_text_on_disk(app):
    root, home = app
    store = FakeHostSecureStore()
    store.bind(profile="phone-a", store_root=root)
    _session(home)

    # No secret on disk; the history is upstream's plain files (the OS protects the folder).
    assert _leaks(root) == set(HISTORY)
    assert (home / "state.db").read_bytes().startswith(b"SQLite format 3")
    # ...and every store still answers through the seam.
    from agent.anthropic_credentials import read_hermes_oauth_credentials
    from hermes_cli import auth, config
    from hermes_state import SessionDB

    assert auth._load_auth_store()["providers"]["nous"]["refresh_token"] == REFRESH
    assert config.load_env()["OPENROUTER_API_KEY"] == API_KEY
    assert read_hermes_oauth_credentials()["accessToken"] == PKCE
    db = SessionDB(home / "state.db")
    try:
        assert CHAT in db.get_messages("s1")[0]["content"]
    finally:
        db.close()
    assert DUMP in (home / "sessions" / "s1.jsonl").read_text(encoding="utf-8")


def test_positive_control_the_same_session_unbound_leaks_every_needle(app):
    root, home = app
    _session(home)
    assert _leaks(root) == set(NEEDLES)


def test_a_second_profile_or_install_cannot_read_the_credentials(app):
    root, home = app
    host = FakeHostSecureStore()
    host.bind(profile="phone-a", store_root=root)
    _session(home)
    binding.unbind_host_store()

    from hermes_cli import auth, config

    for other in (lambda: host.bind(profile="phone-b", store_root=root),  # second profile, same host
                  lambda: FakeHostSecureStore().bind(profile="phone-a", store_root=root)):  # second install
        other()
        assert auth._load_auth_store().get("providers") == {}
        assert config.load_env() == {}
        binding.unbind_host_store()

    # Positive control: the first profile, rebound, reads them.
    host.bind(profile="phone-a", store_root=root)
    assert auth._load_auth_store()["providers"]["nous"]["access_token"] == ACCESS


def test_borrowed_machine_wide_logins_are_refused_when_bound(app, tmp_path, monkeypatch):
    root, _home = app
    user = tmp_path / "user"
    (user / ".qwen").mkdir(parents=True)
    (user / ".qwen" / "oauth_creds.json").write_text(json.dumps({"access_token": "q"}), encoding="utf-8")
    (user / ".claude").mkdir()
    (user / ".claude" / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {}}), encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: user))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

    from agent import anthropic_credentials as ac
    from agent.credential_sources import adopt_external_logins_enabled
    from hermes_cli import auth_qwen, copilot_auth

    monkeypatch.setattr(copilot_auth, "_probe_gh_cli_token", lambda: "gho_borrowed")
    copilot_auth._invalidate_gh_cli_token_cache()
    claude_file = ac.claude_code_credentials_path()

    # Positive control: unbound, every borrowed store is reachable.
    assert adopt_external_logins_enabled() is True
    assert auth_qwen._read_qwen_cli_tokens()["access_token"] == "q"
    assert copilot_auth._try_gh_cli_token() == "gho_borrowed"
    assert ac._load_json_if_exists(claude_file, "claude") is not None

    FakeHostSecureStore().bind(profile="phone-a", store_root=root)
    copilot_auth._invalidate_gh_cli_token_cache()
    assert adopt_external_logins_enabled() is False
    with pytest.raises(Exception, match="not found"):
        auth_qwen._read_qwen_cli_tokens()
    assert copilot_auth._try_gh_cli_token() is None
    assert ac._load_json_if_exists(claude_file, "claude") is None


def test_a_write_outside_the_store_root_is_refused(app, tmp_path):
    root, _home = app
    FakeHostSecureStore().bind(profile="phone-a", store_root=root)
    from hermes_cli import auth

    outside = tmp_path / "elsewhere" / "auth.json"
    with pytest.raises(binding.OutsideStoreRoot):
        auth._save_auth_store({"providers": {"x": {"access_token": ACCESS}}}, target_path=outside)
    assert not outside.exists()


def test_slots_are_keyed_by_profile_and_exact_auth_home(app):
    root, home = app
    host = FakeHostSecureStore()
    current = host.bind(profile="phone-a", store_root=root)
    assert current.slot(home / "auth.json") == "hermes/v1/phone-a/hermes/auth.json"
    assert current.slot(home / "profiles" / "coder" / "auth.json") != current.slot(home / "auth.json")


def test_unbound_is_upstream():
    probe = Path("x") / "auth.json"
    assert secret_files.view(probe) is probe


def test_the_bound_pairing_store_lists_platforms_held_in_slots(app):
    """``PairingStore.list_pending()`` / ``list_approved()`` with no platform enumerated the pairing
    dir with ``iterdir``; bound, every ``<platform>-pending.json`` lives in a host-store slot, so the
    listing was empty while the codes and approvals were there."""
    from gateway.pairing import PairingStore

    root, home = app
    FakeHostSecureStore().bind(profile="p1", store_root=root)
    store = PairingStore()
    assert store.generate_code("telegram", "u-1", "Ada")
    assert store.generate_code("slack", "u-2", "Bob")
    code = store.generate_code("discord", "u-3", "Cy")
    assert store.approve_code("discord", code)
    # Positive control: nothing is on disk for a directory walk to find.
    assert not [p for p in store._dir.iterdir() if p.name.endswith(".json")]

    assert sorted(row["platform"] for row in store.list_pending()) == ["slack", "telegram"]
    assert [row["platform"] for row in store.list_approved()] == ["discord"]
    assert store.clear_pending() == 2 and store.list_pending() == []
