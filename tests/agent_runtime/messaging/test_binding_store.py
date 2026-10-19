"""p10-messaging M1: a binding POINTS AT a persona instance and carries no session; operators fail closed.

The session chain (``tests/conftest.py``) gives every test its own Hermes home, so the store root is
this test's own.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime import paths
from agent_runtime.messaging.bindings import FIELDS, Binding, BindingStore
from agent_runtime.messaging.models import MessagingRefused, Platform, Reason
from agent_runtime.messaging.operators import Operator, OperatorStore

TG = Platform.TELEGRAM


def _binding(chat="-1001", thread=None, instance="inst-alice"):
    return Binding(TG, chat, thread, instance, "rpc:stdio_owner", "2026-10-19T00:00:00+00:00")


def test_binding_is_a_pointer_not_a_session():
    """Killing mutation: ``Binding.wire`` adds ``session_id`` (a root pinned per chat) → red."""
    BindingStore().set(_binding())
    (path,) = (paths.messaging_bindings_dir() / "telegram").glob("*.json")
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert set(on_disk) == FIELDS == {"platform", "chat_id", "thread_id", "persona_instance_id", "bound_by",
                                      "bound_at"}
    assert not [key for key in on_disk if "session" in key or "root" in key]


def test_a_session_key_planted_on_disk_is_never_read_back():
    store = BindingStore()
    store.set(_binding())
    (path,) = (paths.messaging_bindings_dir() / "telegram").glob("*.json")
    planted = json.loads(path.read_text(encoding="utf-8")) | {"session_id": "sess-pinned"}
    path.write_text(json.dumps(planted), encoding="utf-8")
    got = store.get(TG, "-1001")
    assert got == _binding() and "session_id" not in got.wire()


def test_set_get_clear_list_by_chat_and_thread():
    store = BindingStore()
    store.set(_binding())
    store.set(_binding(thread="7", instance="inst-bob"))
    assert store.get(TG, -1001).persona_instance_id == "inst-alice"  # an int chat id is the same chat
    assert store.get(TG, "-1001", 7).persona_instance_id == "inst-bob"
    assert store.get(TG, "-1002") is None
    assert [b.thread_id for b in store.list()] == [None, "7"]
    assert store.clear(TG, "-1001", "7") is True and store.clear(TG, "-1001", "7") is False
    assert [b.persona_instance_id for b in store.list(TG)] == ["inst-alice"]


def test_an_unreadable_binding_routes_nothing(caplog):
    store = BindingStore()
    store.set(_binding())
    (path,) = (paths.messaging_bindings_dir() / "telegram").glob("*.json")
    path.write_text("{not json", encoding="utf-8")
    assert store.get(TG, "-1001") is None and store.list() == []


def test_a_blank_chat_id_is_refused():
    with pytest.raises(MessagingRefused) as refused:
        BindingStore().get(TG, "  ")
    assert refused.value.reason is Reason.INVALID and refused.value.detail == "chat_id"


def test_operators_fail_closed_and_revoke():
    store = OperatorStore()
    assert store.is_allowed(TG, "42") is False and store.list() == []
    store.allow(Operator(TG, "42", "Max", "rpc:stdio_owner", "2026-10-19T00:00:00+00:00"))
    assert store.is_allowed(TG, 42) is True
    assert store.is_allowed(TG, "../42") is False  # never a path outside the operators directory
    assert [o.display for o in store.list(TG)] == ["Max"]
    assert store.revoke(TG, "42") is True and store.is_allowed(TG, "42") is False
