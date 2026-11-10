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
