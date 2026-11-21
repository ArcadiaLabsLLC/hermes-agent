"""Conversation-scoped Work on the todo board: the operator conversation authority resolves every
reference; an operator conversation's persona instance IS the assignee (plan
``work-on-markdown-2026-10-18.md`` §6.2, doc 03 § Conversation-scoped Work)."""
import pytest

from agent_runtime.call_authorization import STDIO_OWNER
from agent_runtime.work import service
from agent_runtime.work.model import Reason, WorkRefused
from tests.agent_runtime.persona_instance_mint import mint_free_floating
from tests.agent_runtime.test_work_service import call, rows_of, start, work


def test_a_retired_native_conversation_reference_is_refused(work):
    """A ``native`` reference named a profile-scoped conversation, whose turn path is retired
    (RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT): it is an unknown kind now.
    Mutation: map ``native`` to a resolver in ``work.context.resolve``'s table -> red (owner_changed, not invalid)."""
    reference = {"kind": "native", "profile": "default", "profile_home": "/nowhere", "session_id": "chat-a"}
    for operation in ("context", "list"):
        with pytest.raises(WorkRefused) as refused:
            service.execute(operation, {**work.scope, "conversation": reference}, STDIO_OWNER)
        assert refused.value.reason is Reason.INVALID


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
    started = start(work, "q1", conversation=reference)["task"]  # started here: assigned, never taken
    assert started["assignee"] == f"persona:{alice.id}" and started["taken"] is None  # RT-WORK-START-NEVER-CLAIMS
    call(work, "claim", request_id="c0", slot="brain", task_id=started["id"], conversation=reference)
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
