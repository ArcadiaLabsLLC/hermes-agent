"""Conversation-scoped Work on the todo board: existing conversation authorities resolve every
reference; an operator conversation's persona instance IS the assignee (plan
``work-on-markdown-2026-10-18.md`` §6.2, doc 03 § Conversation-scoped Work)."""
from types import SimpleNamespace

import pytest

from agent_runtime.call_authorization import STDIO_OWNER
from agent_runtime.conversations import binding
from agent_runtime.conversations.model import caller_scope
from agent_runtime.conversations.store import ConversationStore
from agent_runtime.work import service
from agent_runtime.work.model import Reason, WorkRefused
from tests.agent_runtime.persona_instance_mint import mint_free_floating
from tests.agent_runtime.test_work_service import call, rows_of, start, work  # noqa: F401


@pytest.fixture
def chat(work, tmp_path, monkeypatch):
    home = tmp_path / "profile-home"
    home.mkdir()
    store = ConversationStore(tmp_path / "routes.db")
    owner = caller_scope(STDIO_OWNER, "account", "default")
    route, _ = store.reserve(owner, "chat-a", str(tmp_path), str(home.resolve()))
    route = store.replace_unused(route, "native-a")
    service_owner = SimpleNamespace(install_id=work.scope["install_id"], store=store,
                                    profile_home=lambda profile: home)
    monkeypatch.setattr(binding, "get_service", lambda: service_owner)
    reference = {"kind": "native", "profile": "default", "profile_home": str(home), "session_id": route.id}
    return SimpleNamespace(work=work, store=store, route=route, reference=reference, home=home)


def test_empty_chat_browses_and_cannot_start_until_it_has_a_turn(chat):
    context = call(chat.work, "context", conversation=chat.reference)
    assert context["can_start"] is False and context["assignee"] is None
    with pytest.raises(WorkRefused) as refused:
        start(chat.work, conversation=chat.reference)
    assert refused.value.reason is Reason.UNAVAILABLE
    chat.store.admit(chat.route, "first-turn", {"text": "Hello"})
    assert call(chat.work, "context", conversation=chat.reference)["can_start"] is True


def test_reference_never_crosses_account_profile_home_or_conversation(chat):
    chat.store.admit(chat.route, "first-turn", {"text": "Hello"})
    for change in ({"client_scope": "different"}, {"conversation": {**chat.reference, "profile": "other"}},
                   {"conversation": {**chat.reference, "profile_home": str(chat.store.path.parent)}},
                   {"conversation": {**chat.reference, "session_id": "missing"}}):
        with pytest.raises(WorkRefused) as refused:
            start(chat.work, **{"conversation": chat.reference, **change})
        assert refused.value.reason is Reason.OWNER_CHANGED


def test_operator_reference_names_its_instance_as_the_assignee(work, monkeypatch):
    from agent_runtime import operator_conversation

    alice = mint_free_floating("alice")
    reference = {"kind": "operator", "workspace_id": work.ws, "persona_id": alice.persona_id,
                 "persona_instance_id": alice.id, "session_id": "operator-session"}
    calls = []
    monkeypatch.setattr(operator_conversation, "validate_operator_conversation", lambda value: calls.append(value))
    context = call(work, "context", conversation=reference)
    assert context["scopes"] == ["conversation", "all"] and context["agent_profile"] is None
    assert context["assignee"] == f"persona:{alice.id}"
    assert calls == [{**reference, "install_id": work.scope["install_id"]}]
    started = start(work, "q1", conversation=reference)["task"]  # started here: taken here
    assert started["taken"]["who"] == f"persona:{alice.id}" and started["in_conversation"] is True
    later = start(work, "q2", title="Picked up later")["task"]["id"]
    start(work, "q3", title="Someone else's")
    claimed = call(work, "claim", request_id="c1", slot="brain", task_id=later, conversation=reference)["task"]
    assert claimed["taken"]["who"] == f"persona:{alice.id}" and claimed["in_conversation"] is True
    rows = rows_of(call(work, "list", view="conversation", conversation=reference))
    assert sorted(row["id"] for row in rows) == sorted([started["id"], later])

    def refuse(value):
        raise operator_conversation.OperatorConversationRefused("foreign_session")

    monkeypatch.setattr(operator_conversation, "validate_operator_conversation", refuse)
    with pytest.raises(WorkRefused) as refused:
        call(work, "list", view="all", conversation=reference)
    assert refused.value.reason is Reason.OWNER_CHANGED


def test_context_and_view_cannot_silently_fall_back_to_all_work(work):
    for params in ({"view": "conversation"}, {"view": "unsupported"},
                   {"conversation": {"kind": "unknown"}}):
        with pytest.raises(WorkRefused) as refused:
            service.execute("list", {**work.scope, **params}, STDIO_OWNER)
        assert refused.value.reason is Reason.INVALID
