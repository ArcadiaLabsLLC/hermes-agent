"""The phone credentials seam and history storage seam (embedded-hermes Stage 2 steps 5 and 9).

Against the fake host store (``agent_runtime.host_store.fake``): after a session with
a signed-in provider and a chat, a byte scan of the app folder finds no secret and no
chat text; a second profile or a second install reads neither the first's credentials
nor its history; the machine-wide borrowed CLI logins are refused. Every scan runs
with a POSITIVE CONTROL — the same scenario unbound must leak the same needles, so
the scan is proven to look where the bytes would be.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_runtime.host_store import binding, envelope, history, secret_files
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
NEEDLES = (ACCESS, REFRESH, API_KEY, PKCE, MCP, HMAC, PAIRING, CHAT, DUMP)


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
    webhook._save_subscriptions({"route": {"secret": HMAC}})

    db = SessionDB(home / "state.db")
    try:
        db.create_session("s1", source="cli")
        db.append_message("s1", role="user", content=f"remember the {CHAT} please")
        assert db.search_messages(CHAT.split("-")[0])  # FTS5 answers inside the image
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

    assert _leaks(root) == set()
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
    assert DUMP in history.read_records(home / "sessions" / "s1.jsonl")[0]
    assert not list(home.glob("state.db-*")), "a journal sidecar reached the disk"


def test_positive_control_the_same_session_unbound_leaks_every_needle(app):
    root, home = app
    _session(home)
    assert _leaks(root) == set(NEEDLES)


def test_a_second_profile_or_install_reads_neither_credentials_nor_history(app):
    root, home = app
    host = FakeHostSecureStore()
    host.bind(profile="phone-a", store_root=root)
    _session(home)
    sealed = (home / "state.db").read_bytes()
    binding.unbind_host_store()

    from hermes_cli import auth, config
    from hermes_state import SessionDB

    for other in (lambda: host.bind(profile="phone-b", store_root=root),  # second profile, same host
                  lambda: FakeHostSecureStore().bind(profile="phone-a", store_root=root)):  # second install
        other()
        assert auth._load_auth_store().get("providers") == {}
        assert config.load_env() == {}
        with pytest.raises(history.HistoryUnreadable):
            SessionDB(home / "state.db")
        assert (home / "state.db").read_bytes() == sealed, "a key mismatch overwrote the other history"
        binding.unbind_host_store()

    # Positive control: the first profile, rebound, reads both.
    host.bind(profile="phone-a", store_root=root)
    assert auth._load_auth_store()["providers"]["nous"]["access_token"] == ACCESS
    db = SessionDB(home / "state.db")
    try:
        assert db.get_messages("s1")
    finally:
        db.close()


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


def test_a_deleted_session_is_gone_from_the_sealed_image(app):
    root, home = app
    FakeHostSecureStore().bind(profile="phone-a", store_root=root)
    from hermes_state import SessionDB

    db = SessionDB(home / "state.db")
    try:
        db.create_session("gone", source="cli")
        db.append_message("gone", role="user", content=f"forget the {CHAT}")
        # Positive control: before the delete, the decrypted image carries the text.
        assert CHAT.encode() in history.read_blob(home / "state.db")
        db.delete_session("gone")
    finally:
        db.close()
    assert CHAT.encode() not in history.read_blob(home / "state.db")


def test_erase_history_removes_every_history_file(app):
    root, home = app
    FakeHostSecureStore().bind(profile="phone-a", store_root=root)
    _session(home)
    removed = history.erase_history(home)
    assert home / "state.db" in removed and home / "sessions" / "s1.jsonl" in removed
    assert not (home / "state.db").exists() and not list((home / "sessions").glob("*"))


def test_the_envelope_refuses_a_wrong_key_a_wrong_slot_and_a_tampered_byte():
    key = bytes(range(32))
    blob = envelope.seal(key, b"hello history", aad=b"slot-a")
    assert envelope.open_(key, blob, aad=b"slot-a") == b"hello history"
    with pytest.raises(envelope.EnvelopeError):
        envelope.open_(bytes(32), blob, aad=b"slot-a")
    with pytest.raises(envelope.EnvelopeError):
        envelope.open_(key, blob, aad=b"slot-b")
    tampered = bytearray(blob)
    tampered[len(envelope.MAGIC) + envelope.NONCE_BYTES] ^= 1
    with pytest.raises(envelope.EnvelopeError):
        envelope.open_(key, bytes(tampered), aad=b"slot-a")
    assert b"hello history" not in blob


def test_unbound_is_upstream():
    from hermes_state import SessionDB

    probe = Path("x") / "auth.json"
    assert secret_files.view(probe) is probe
    assert history.session_db_class(SessionDB) is SessionDB


def _pending_delegation(home: Path) -> None:
    """One abandoned delegation row, written through the ledger's own writer (bound or not)."""
    from tools import async_delegation

    async_delegation._persist_dispatch({"delegation_id": "d-1", "session_key": "s1", "dispatched_at": 1.0,
                                        "goal": f"summarise {CHAT}"})
    with async_delegation._DB_LOCK, async_delegation._transaction() as conn:  # its owner has since died
        conn.execute("UPDATE async_delegations SET owner_pid=?, owner_started_at=? WHERE delegation_id='d-1'",
                     (2 ** 22 + 7, 1.0))


def test_the_delegation_ledger_writes_the_sealed_image_not_a_plaintext_database(app):
    """``tools.process_registry``'s import-time recovery (``restore_undelivered_completions``) opens
    ``state.db`` beside ``SessionDB``. Bound, it must write the sealed image: once it won the race
    it wrote a plaintext database, which ``SessionDB`` then refused ("not a history envelope")."""
    import queue

    from hermes_state import SessionDB
    from tools import async_delegation

    import sqlite3

    root, home = app
    FakeHostSecureStore().bind(profile="p1", store_root=root)
    _pending_delegation(home)  # before any SessionDB: the ledger alone creates the state DB
    assert not (home / "state.db").read_bytes().startswith(b"SQLite format 3")
    db = SessionDB(home / "state.db")  # the sealed store opens what the ledger wrote, and stays open
    try:
        db.create_session("s1", source="cli")
        restored = queue.Queue()
        async_delegation.restore_undelivered_completions(restored)
        # The ledger's write reached the disk while SessionDB still holds the image: sealed, and
        # it decrypts to the settled row.
        blob = (home / "state.db").read_bytes()
        assert not blob.startswith(b"SQLite format 3") and CHAT.encode() not in blob
        image = sqlite3.connect(":memory:")
        try:
            image.deserialize(history.read_blob(home / "state.db"))
            row = image.execute("SELECT state FROM async_delegations WHERE delegation_id='d-1'").fetchone()
        finally:
            image.close()
        assert row == ("unknown",)
    finally:
        db.close()
    # Positive control: the recovery really ran over the ledger row (it settled and re-queued it).
    event = restored.get_nowait()
    assert event["delegation_id"] == "d-1" and event["status"] == "unknown" and CHAT in event["goal"]


def test_file_logs_are_sealed_records_when_bound(app):
    import logging

    import hermes_logging

    root, home = app
    FakeHostSecureStore().bind(profile="p1", store_root=root)
    hermes_logging._reset_queued_handlers()
    hermes_logging._logging_initialized = False
    hermes_logging.setup_logging(hermes_home=home, log_level="INFO", force=True)
    try:
        logging.getLogger("agent.turn_context").info("turn opens with %s", CHAT)
        logging.getLogger("agent.turn_context").warning("provider said %s", DUMP)
        hermes_logging.flush_log_queue()
        logs = sorted(p.name for p in (home / "logs").iterdir())
        assert {"agent.log", "errors.log"} <= set(logs)
        for name in ("agent.log", "errors.log"):
            data = (home / "logs" / name).read_bytes()
            assert CHAT.encode() not in data and DUMP.encode() not in data
        # Positive control: the records decrypt, through the bound store, to the lines logged.
        agent = history.read_records(home / "logs" / "agent.log")
        assert any(CHAT in r for r in agent) and any(DUMP in r for r in agent)
        assert any(DUMP in r for r in history.read_records(home / "logs" / "errors.log"))
    finally:
        hermes_logging._reset_queued_handlers()
        hermes_logging._logging_initialized = False


def test_the_state_db_readers_beside_session_db_read_the_sealed_image(app):
    """The raw readers of ``state.db`` outside ``SessionDB`` — the running-work delegation lane, the
    dispatch store (which also writes), the readiness probe and the doctor's stats — read the sealed
    image when bound. Before the seam each opened the envelope as SQLite and got "file is not a
    database" (the lane reported the store unreadable; the dispatch store wrote a plaintext DB)."""
    import sqlite3
    import time

    from agent_runtime.dispatch_store import db as dispatch_db
    from agent_runtime.dispatch_store import record_dispatch
    from agent_runtime.running_work.lanes_chat import DelegationLane
    from gateway.readiness import _probe_state_db
    from hermes_state_dbfile import collect_state_db_stats

    root, home = app
    FakeHostSecureStore().bind(profile="p1", store_root=root)
    _pending_delegation(home)
    record_dispatch(dispatch_id="x-1", sender_session_id="s1", target_persona="helper", ask=f"find {CHAT}")
    db_path = home / "state.db"
    assert not db_path.read_bytes().startswith(b"SQLite format 3") and CHAT.encode() not in db_path.read_bytes()

    rows, refusal = DelegationLane(now=time.time(), accountant=None).read_durable(db_path)
    assert refusal is None and [row[0] for row in rows] == ["d-1"]
    assert [row["dispatch_id"] for row in dispatch_db.running_dispatches()] == ["x-1"]
    assert _probe_state_db(home) == {"status": "ok"}
    assert collect_state_db_stats(db_path)["page_count"]

    # Positive control: the file really is an envelope a raw sqlite3 reader cannot open.
    with pytest.raises(sqlite3.DatabaseError):
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        try:
            conn.execute("SELECT name FROM sqlite_master").fetchall()
        finally:
            conn.close()


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
