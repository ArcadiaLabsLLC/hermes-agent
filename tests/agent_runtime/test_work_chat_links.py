"""Native tasks and existing conversation receipts are the only durable owners."""
from types import SimpleNamespace

import pytest

from agent_runtime.call_authorization import STDIO_OWNER
from agent_runtime.conversations import binding
from agent_runtime.conversations.model import caller_scope
from agent_runtime.conversations.store import ConversationStore
from agent_runtime.work import service
from agent_runtime.work.model import Reason, WorkRefused
from hermes_cli import kanban_db as tasks
from hermes_cli.kanban_db_connect import connect_closing
from tests.agent_runtime.test_work_service import work, start  # noqa: F401


@pytest.fixture
def chat(work, tmp_path, monkeypatch):
    scope, home = work
    store = ConversationStore(tmp_path / "routes.db")
    owner = caller_scope(STDIO_OWNER, "account", "default")
    route, _ = store.reserve(owner, "chat-a", str(tmp_path), str(home.resolve()))
    route = store.replace_unused(route, "native-a")
    service_owner = SimpleNamespace(install_id=scope["install_id"], store=store,
                                    profile_home=lambda profile: home)
    monkeypatch.setattr(binding, "get_service", lambda: service_owner)
    reference = {"kind": "native", "profile": "default", "profile_home": str(home), "session_id": route.id}
    return scope, store, route, reference


def test_empty_chat_browses_without_minting_tasks_and_rechecks_eligibility(chat):
    scope, store, route, reference = chat
    params = {**scope, "client_scope": "account", "conversation": reference}
    assert service.execute("context", params, STDIO_OWNER)["can_start"] is False
    assert service.execute("list", {**params, "view": "conversation"}, STDIO_OWNER)["tasks"] == []
    with pytest.raises(WorkRefused, match=Reason.UNAVAILABLE):
        start(scope, conversation=reference)
    store.admit(route, "first-turn", {"text": "Hello"})
    assert service.execute("context", params, STDIO_OWNER)["can_start"] is True


def test_submission_and_agent_created_work_share_native_origin(chat):
    scope, store, route, reference = chat
    store.admit(route, "first-turn", {"text": "Hello"})
    receipt = start(scope, conversation=reference)
    task_id = receipt["task"]["id"]
    with connect_closing(board="default") as conn:
        task = tasks.get_task(conn, task_id)
        assert task.session_id == route.native_id
        agent_task = tasks.create_task(conn, title="Agent task", assignee="default", session_id=route.native_id)
        outside = tasks.create_task(conn, title="Other chat", assignee="default", session_id="native-b")
    params = {**scope, "client_scope": "account", "conversation": reference}
    rows = service.execute("list", {**params, "view": "conversation"}, STDIO_OWNER)["tasks"]
    assert {row["id"] for row in rows} == {task_id, agent_task}
    assert all(row["in_conversation"] for row in rows)
    agent_rows = service.execute("list", {**params, "view": "agent"}, STDIO_OWNER)["tasks"]
    assert {row["id"] for row in agent_rows} == {task_id, agent_task, outside}
    assert next(row for row in agent_rows if row["id"] == outside)["in_conversation"] is False
    inspected = service.execute("inspect", {**params, "task_id": task_id}, STDIO_OWNER)
    assert inspected["task"]["id"] == task_id
    assert inspected["task"]["in_conversation"] is True
    assert start(scope, conversation=reference)["task"]["id"] == task_id


def test_reference_never_crosses_account_profile_home_or_conversation(chat):
    scope, store, route, reference = chat
    store.admit(route, "first-turn", {"text": "Hello"})
    for change in ({"client_scope": "different"}, {"conversation": {**reference, "profile": "other"}},
                   {"conversation": {**reference, "profile_home": str(store.path.parent)}},
                   {"conversation": {**reference, "session_id": "missing"}}):
        with pytest.raises(WorkRefused, match=Reason.OWNER_CHANGED):
            start(scope, **{"conversation": reference, **change})


def test_saved_request_cannot_be_relinked_to_another_chat(chat):
    scope, store, route, reference = chat
    store.admit(route, "first-turn", {})
    start(scope, conversation=reference)
    other, _ = store.reserve(caller_scope(STDIO_OWNER, "account", "default"), "chat-b", route.cwd, route.home)
    other = store.replace_unused(other, "native-b")
    store.admit(other, "first-turn", {})
    with pytest.raises(WorkRefused, match=Reason.CONFLICT):
        start(scope, conversation={**reference, "session_id": other.id})
    with pytest.raises(WorkRefused, match=Reason.CONFLICT):
        start(scope)


def test_operator_reference_uses_its_exact_authority_without_profile_impersonation(work, monkeypatch):
    from agent_runtime import operator_conversation
    scope, _ = work
    reference = {"kind": "operator", "workspace_id": "workspace-a", "persona_id": "persona-a",
                 "persona_instance_id": "instance-a", "session_id": "operator-session"}
    calls = []
    monkeypatch.setattr(operator_conversation, "validate_operator_conversation", lambda value: calls.append(value))
    params = {**scope, "client_scope": "account", "conversation": reference}
    context = service.execute("context", params, STDIO_OWNER)
    assert context["scopes"] == ["conversation", "all"]
    assert context["agent_profile"] is None
    assert calls == [{**reference, "install_id": scope["install_id"]}]
    receipt = start(scope, conversation=reference)
    with connect_closing(board="default") as conn:
        assert tasks.get_task(conn, receipt["task"]["id"]).session_id == "operator-session"
    def refuse(value):
        raise operator_conversation.OperatorConversationRefused("foreign_session")
    monkeypatch.setattr(operator_conversation, "validate_operator_conversation", refuse)
    with pytest.raises(WorkRefused, match=Reason.OWNER_CHANGED):
        service.execute("list", {**params, "view": "all"}, STDIO_OWNER)


def test_context_and_view_cannot_silently_fall_back_to_all_work(work):
    scope, _ = work
    for params in ({**scope, "view": "conversation"}, {**scope, "view": "unsupported"},
                   {**scope, "client_scope": "account", "conversation": {"kind": "unknown"}}):
        with pytest.raises(WorkRefused, match=Reason.INVALID):
            service.execute("list", params, STDIO_OWNER)
