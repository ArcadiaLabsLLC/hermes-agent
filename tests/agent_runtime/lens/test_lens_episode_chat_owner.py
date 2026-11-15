"""RT-LENS-ALERT-CHAT-NO-CLIENT-SCOPE: an Episode's chat is owned by the operator's client.

The chat a Lens Episode opens for its unattended turn was minted with no ``client_scope``, so the
operator client's conversation directory never listed it and Eternia's Lens receipt "Open chat"
could not open it (Eternia w1108a-live-a §3). It now carries the client scope of the persona's
current chat — the operator who reads that persona — and stays unscoped when there is none.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from agent_runtime import persona_open_chat, tool_permissions
from agent_runtime.lens import trigger
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_history import messages

SCOPE = "a" * 64


def _episode():
    return SimpleNamespace(id="ep_1", monitor_id="mon_1", rule_id="alert", sequence=1)


def _capture_mint(monkeypatch) -> list[dict]:
    minted: list[dict] = []

    def mint(params, *, select_session):
        minted.append(dict(params))
        return SimpleNamespace(refusal=None, result={"session_id": "persona_chat_lens_1"})

    monkeypatch.setattr(persona_open_chat, "perform_persona_instance_open_chat", mint)
    monkeypatch.setattr(tool_permissions.ChatToolPermissionStore, "set", lambda self, **kw: None)
    monkeypatch.setattr(trigger, "episode_title", lambda episode: "mon · alert · #1")
    return minted


@pytest.mark.parametrize("owner", [SCOPE, None])
def test_the_episode_chat_is_minted_with_the_operators_scope_or_none(monkeypatch, owner):
    minted = _capture_mint(monkeypatch)
    monkeypatch.setattr(trigger, "_operator_client_scope", lambda persona_id: owner)

    session_id, refused = trigger._open_episode_chat("profile_base", _episode(), "ep_1")

    assert (session_id, refused) == ("persona_chat_lens_1", {})
    assert minted[-1].get("client_scope") == owner
    assert ("client_scope" in minted[-1]) is (owner is not None)


def _instance(monkeypatch, session_id):
    seen: list[str] = []

    def get(self, instance_id):
        seen.append(instance_id)
        return SimpleNamespace(default_chat_session_id=session_id)

    monkeypatch.setattr(PersonaInstanceStore, "__init__", lambda self, *a, **kw: None)
    monkeypatch.setattr(PersonaInstanceStore, "get", get)
    return seen


def _session_owner(monkeypatch, owner, *, fails=False):
    read: list[str] = []

    @contextmanager
    def existing(*, session_id, client_scope=None):
        read.append(session_id)
        if fails:
            raise messages.ChatSessionReadRefused({"ok": False, "error_kind": "session_not_found"})
        yield SimpleNamespace(owner=owner)

    monkeypatch.setattr(messages, "existing_chat_session", existing)
    return read


def test_the_operator_scope_is_the_canonical_instances_current_chat_owner(monkeypatch):
    seen = _instance(monkeypatch, "persona_chat_personainst_profile_base_7ae1189a")
    read = _session_owner(monkeypatch, SCOPE)

    assert trigger._operator_client_scope("profile_base") == SCOPE
    assert seen == ["personainst_profile_base"]
    assert read == ["persona_chat_personainst_profile_base_7ae1189a"]


def test_no_current_chat_or_a_failed_read_is_unscoped(monkeypatch):
    _instance(monkeypatch, None)
    read = _session_owner(monkeypatch, SCOPE)
    assert trigger._operator_client_scope("profile_base") is None
    assert read == []

    _instance(monkeypatch, "persona_chat_gone")
    _session_owner(monkeypatch, SCOPE, fails=True)
    assert trigger._operator_client_scope("profile_base") is None


# --- RT-LENS-EPISODE-CHAT-OWNED-BY-THE-MONITORS-ACCOUNT ---------------------------------------------
# A monitor records the account that sealed it; its Episode chats open for that account even when the
# account had no chat with the persona yet. Only a scope the server verified for the seal is stored.

OTHER = "b" * 64


def _manifest(monitor_id="status") -> dict:
    return {"version": 1, "monitor_id": monitor_id, "persona_id": None, "rules": [],
            "feeds": [{"version": 1, "id": "api", "kind": "http_json", "interval_ms": 5000,
                       "source": {"url": "https://status.example.invalid/health", "selector": "$.cpu"}}],
            "automation": {"level": "notify", "when": "urgent", "daily_turn_cap": 0}}


def _call(method: str, params: dict) -> dict:
    from agent_runtime import serve_rpc

    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def _seal(params: dict, *, device_scope=None, device=False) -> dict:
    from agent_runtime.call_authorization import CALLER_DEVICE, RpcCaller
    from agent_runtime.serve_rpc import channel
    from agent_runtime.serve_rpc.lens import _runtime_lens_seal
    from agent_runtime.serve_rpc.protocol import RpcContext

    if not device:
        return _call("runtime.lens.seal", params)
    original = channel._device_identity
    channel._device_identity = lambda device_id: ("phone", device_scope)
    try:
        caller = RpcCaller(kind=CALLER_DEVICE, device_id="dev_1", device_tier="console")
        return _runtime_lens_seal(1, params, RpcContext(caller=caller))
    finally:
        channel._device_identity = original


def _created(monitor_id="status") -> None:
    assert _call("runtime.lens.create", {"manifest": _manifest(monitor_id)})["result"]["state"] == "draft"


def test_a_monitor_sealed_by_a_scoped_client_mints_episode_chats_for_that_account(monkeypatch):
    _created()
    assert _seal({"monitor_id": "status", "client_scope": SCOPE})["result"]["sealed"]["revision"] == 1
    minted = _capture_mint(monkeypatch)
    # The persona has no current chat: the borrow finds no owner (the row's live symptom).
    monkeypatch.setattr(trigger, "_operator_client_scope", lambda persona_id: None)

    episode = SimpleNamespace(id="ep_1", monitor_id="status", rule_id="alert", sequence=1)
    assert trigger._open_episode_chat("profile_base", episode, "ep_1") == ("persona_chat_lens_1", {})
    assert minted[-1]["client_scope"] == SCOPE


def test_the_sealing_account_wins_over_the_persona_current_chat_owner(monkeypatch):
    _created()
    _seal({"monitor_id": "status", "client_scope": SCOPE})
    minted = _capture_mint(monkeypatch)
    monkeypatch.setattr(trigger, "_operator_client_scope", lambda persona_id: OTHER)

    episode = SimpleNamespace(id="ep_1", monitor_id="status", rule_id="alert", sequence=1)
    trigger._open_episode_chat("profile_base", episode, "ep_1")
    assert minted[-1]["client_scope"] == SCOPE


def test_an_unscoped_seal_keeps_the_current_chat_fallback(monkeypatch):
    _created()
    _seal({"monitor_id": "status"})
    minted = _capture_mint(monkeypatch)
    monkeypatch.setattr(trigger, "_operator_client_scope", lambda persona_id: OTHER)

    episode = SimpleNamespace(id="ep_1", monitor_id="status", rule_id="alert", sequence=1)
    trigger._open_episode_chat("profile_base", episode, "ep_1")
    assert minted[-1]["client_scope"] == OTHER


def test_a_malformed_scope_is_refused_and_nothing_is_sealed():
    _created()
    for bad in ("not-a-digest", None, 7):
        refused = _seal({"monitor_id": "status", "client_scope": bad})["error"]
        assert refused["data"] == {"reason": "invalid_client_scope", "detail": ""}
    assert _call("runtime.lens.get", {"monitor_id": "status"})["result"]["sealed"] is None


def test_a_scoped_reseal_never_moves_another_accounts_monitor():
    from agent_runtime.lens.store_owner import monitor_client_scope

    _created()
    _seal({"monitor_id": "status", "client_scope": SCOPE})
    _created()  # the next revision's draft
    refused = _seal({"monitor_id": "status", "client_scope": OTHER})["error"]
    assert refused["data"] == {"reason": "conversation_owner_changed", "detail": ""}
    assert monitor_client_scope("status") == SCOPE
    # An unscoped native operator's re-seal keeps the recorded owner rather than clearing it.
    assert _seal({"monitor_id": "status"})["result"]["sealed"]["revision"] == 2
    assert monitor_client_scope("status") == SCOPE


def test_a_paired_device_is_held_to_its_pairing_scope():
    from agent_runtime.lens.store_owner import monitor_client_scope

    _created()
    # Naming another account than the one its pairing bound: refused, nothing sealed.
    refused = _seal({"monitor_id": "status", "client_scope": OTHER}, device=True, device_scope=SCOPE)["error"]
    assert refused["data"] == {"reason": "conversation_owner_changed", "detail": ""}
    # A device with no bound scope cannot name one.
    refused = _seal({"monitor_id": "status", "client_scope": SCOPE}, device=True, device_scope=None)["error"]
    assert refused["data"] == {"reason": "conversation_owner_changed", "detail": ""}
    assert monitor_client_scope("status") is None
    # Naming nothing: the pairing's own scope is what is recorded.
    assert _seal({"monitor_id": "status"}, device=True, device_scope=SCOPE)["result"]["sealed"]["revision"] == 1
    assert monitor_client_scope("status") == SCOPE
