"""Real native result producers/stores, both harness owners, and read-only history."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_state import SessionDB
from tools import async_delegation as ad
from tools.delegate_tool_child_run import _build_result_entry, _SchemaOutcome
from tests.waiting import wait_until
from agent_runtime.conversations.model import ConversationScope, ConversationError
from agent_runtime.conversations.service import ConversationService
from agent_runtime.subagents.model import Refusal, SubagentError
from agent_runtime.subagents.history import inspect_history
from tests.agent_runtime.test_operator_session_inspection import target, inspect
from tests.agent_runtime.test_serve_rpc_open_chat import qa_persona, placed_agent, _device
from tests.agent_runtime.test_instance_conversation_owner import chat_head, OTHER


def native_result(summary="Native result", *, schema=False):
    child = SimpleNamespace(model="recorded-model", session_prompt_tokens=41,
        session_completion_tokens=17, session_estimated_cost_usd=.0123, session_cost_status="estimated")
    return _build_result_entry(child, {"final_response": summary, "completed": False, "api_calls": 2,
        "messages": []}, 0, 1.5, _SchemaOutcome({} if schema else None, False if schema else None, ["expected object"] if schema else [], 1 if schema else 0))


def store_result(db, session_id, summary="Native result"):
    return db.append_message(session_id, "tool", json.dumps(native_result(summary, schema=True)),
                             tool_name="delegate_task", tool_call_id="result-call")


def capture_history(path, call):
    roster = call("history", {})
    frames = {"history": roster}
    for kind, plural in (("result", "results"), ("tree", "trees")):
        frames[kind] = call(kind, {"expected_generation": roster["generation"],
                                  "history_ref": roster[plural][0]["history_ref"]})
    path.write_text(json.dumps(frames, indent=2), encoding="utf-8")


@pytest.fixture
def stored(tmp_path, monkeypatch):
    home = tmp_path / "profile"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    db = SessionDB(db_path=home / "state.db")
    db.create_session("parent", "test")
    db.create_session("foreign", "test")
    db.create_session("nested", "test", parent_session_id="parent", model_config={"_delegate_from": "parent"})
    db.create_session("branch", "test", parent_session_id="parent", model_config={"_branched_from": "parent"})
    yield home, db
    db.close()


def history_call(home, db, operation="history", params=None, owner="owner", session_id="parent", revalidate=lambda: None):
    return inspect_history(operation, params or {}, owner=owner, db=db, session_id=session_id,
                           home=home, revalidate=revalidate)


def test_results_use_native_fields_and_exact_lineage_without_other_conversations(stored):
    home, db = stored
    store_result(db, "parent", "Delivered api_key=secret123")
    store_result(db, "nested", "Nested result")
    store_result(db, "branch", "OTHER_BRANCH")
    store_result(db, "foreign", "FOREIGN")
    roster = history_call(home, db)
    assert len(roster["results"]) == 2
    results = [history_call(home, db, "result", {"expected_generation": roster["generation"],
        "history_ref": row["history_ref"]})["result"] for row in roster["results"]]
    serialized = json.dumps(results)
    assert "Nested result" in serialized and "Delivered" in serialized
    assert all(secret not in serialized for secret in ("FOREIGN", "OTHER_BRANCH", "secret123"))
    result = results[0]
    assert (result["status"], result["exit_reason"], result["schema_valid"]) == ("completed", "max_iterations", False)
    assert (result["input_tokens"], result["output_tokens"], result["cost_usd"]) == (41, 17, .0123)
    assert result["timeout_seconds"] is None
    params = {"expected_generation": roster["generation"], "history_ref": roster["results"][0]["history_ref"]}
    with pytest.raises(SubagentError):
        history_call(home, db, "result", params, owner="other-install")
    with pytest.raises(SubagentError):
        history_call(home, db, "tree", params)


def test_async_completion_is_read_without_delivery_ack_or_worker(stored):
    home, db = stored
    ad._reset_for_tests()
    try:
        handle = ad.dispatch_async_delegation(goal="Recorded goal", context=None, toolsets=None, role="worker",
            model="model", session_key="parent", parent_session_id="parent", origin_session_id="parent",
            runner=lambda: native_result())
        assert handle["status"] == "dispatched"
        wait_until(lambda: (ad.get_durable_delegation(handle["delegation_id"]) or {}).get("state") == "completed")
        before = ad.get_durable_delegation(handle["delegation_id"])
        roster = history_call(home, db)
        assert len(roster["results"]) == 1
        assert roster["results"][0]["goal"] == "Recorded goal"
        assert ad.get_durable_delegation(handle["delegation_id"]) == before
    finally:
        ad._reset_for_tests()


def test_native_route_history_never_acquires_an_execution_worker(stored, tmp_path):
    home, db = stored
    store_result(db, "parent")
    def forbidden_worker(*args, **kwargs):
        pytest.fail("history started an execution worker")
    service = ConversationService(tmp_path / "runtime", "install", profile_home=lambda _: home, worker_factory=forbidden_worker)
    scope = ConversationScope("actor", "client", "profile")
    route, _ = service.store.reserve(scope, "chat", str(tmp_path), str(home))
    route = service.store.replace_unused(route, "parent")
    try:
        reply = service.subagents(scope, route.id, "history", {})
        assert reply["session_id"] == route.id and len(reply["results"]) == 1
        saved_tree(home)
        capture_history(tmp_path / "native-history.json", lambda op, args: service.subagents(scope, route.id, op, args))
        for wrong in (ConversationScope("other", "client", "profile"), ConversationScope("actor", "other", "profile"),
                      ConversationScope("actor", "client", "other")):
            with pytest.raises(ConversationError):
                service.subagents(wrong, route.id, "history", {})
    finally:
        service.close()


def saved_tree(home, session="parent", name="saved.json"):
    directory = home / "spawn-trees" / session
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps({"session_id": session, "label": "Review", "finished_at": 10,
        "subagents": [{"subagent_id": "child", "parent_id": None, "status": "completed", "goal": "Review",
                       "child_ref": "NEVER_EXECUTABLE", "controllable": True}]}), encoding="utf-8")
    return path


def test_saved_tree_owner_reference_and_containment(stored):
    home, db = stored
    saved_tree(home)
    foreign = saved_tree(home, "foreign")
    roster = history_call(home, db)
    assert len(roster["trees"]) == 1
    params = {"expected_generation": roster["generation"], "history_ref": roster["trees"][0]["history_ref"]}
    tree = history_call(home, db, "tree", params)["tree"]
    assert tree["children"][0]["child_ref"] is None and tree["children"][0]["controllable"] is False
    with pytest.raises(SubagentError):
        history_call(home, db, "tree", {**params, "history_ref": str(foreign)})
    forged = home / "spawn-trees" / "parent" / "forged.json"
    forged.write_bytes(foreign.read_bytes())
    assert len(history_call(home, db)["trees"]) == 1


def test_symlink_snapshot_is_never_loaded(stored, tmp_path):
    home, db = stored
    valid = saved_tree(home)
    outside = tmp_path / "outside.json"
    outside.write_bytes(valid.read_bytes())
    link = valid.with_name("linked.json")
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"Host cannot create a file symlink: {exc}")
    assert len(history_call(home, db)["trees"]) == 1


def test_changed_result_or_owner_during_read_refuses(stored):
    home, db = stored
    message_id = store_result(db, "parent")
    roster = history_call(home, db)
    params = {"expected_generation": roster["generation"], "history_ref": roster["results"][0]["history_ref"]}
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("UPDATE messages SET content=? WHERE id=?", (json.dumps(native_result("changed")), message_id))
    with pytest.raises(SubagentError, match="stale"):
        history_call(home, db, "result", params)
    def changed():
        raise SubagentError(Refusal.WRONG_OWNER)
    with pytest.raises(SubagentError, match="owner_changed"):
        history_call(home, db, revalidate=changed)


def test_operator_history_uses_the_existing_console_owner(placed_agent, tmp_path):
    from agent_runtime.persona_chat_durability import default_persona_session_db
    params = target(placed_agent["persona_instance_id"])
    with closing(default_persona_session_db()) as db:
        store_result(db, params["session_id"])
        saved_tree(Path(db.db_path).parent, params["session_id"])
    reply = inspect("subagents.history", params)
    assert "result" in reply, reply
    roster = reply["result"]
    assert len(roster["results"]) == 1
    selected = {**params, "expected_generation": roster["generation"], "history_ref": roster["results"][0]["history_ref"]}
    assert inspect("subagents.result", selected)["result"]["result"]["input_tokens"] == 41
    for key, value in (("install_id", "other"), ("workspace_id", "other"), ("persona_id", "other"),
                       ("persona_instance_id", "other"), ("session_id", "other"), ("client_scope", OTHER)):
        assert "error" in inspect("subagents.history", {**params, key: value})
        assert "error" in inspect("subagents.result", {**selected, key: value})
    assert "error" in inspect("subagents.history", params, _device("read"))
    capture_history(tmp_path / "operator-history.json", lambda op, args: inspect(f"subagents.{op}", {**params, **args})["result"])


def test_grouped_async_results_keep_absolute_goal_indexes(stored):
    home, db = stored
    ad._reset_for_tests()
    try:
        entry = {**native_result(), "task_index": 2}
        handle = ad.dispatch_async_delegation_batch(goals=["First", "Other", "Third"], task_indexes=[2],
            context=None, toolsets=None, role="worker", model="model", session_key="parent",
            parent_session_id="parent", runner=lambda: {"results": [entry]})
        wait_until(lambda: (ad.get_durable_delegation(handle["delegation_id"]) or {}).get("state") == "completed")
        assert history_call(home, db)["results"][0]["goal"] == "Third"
    finally:
        ad._reset_for_tests()


def test_native_async_head_store_and_profile_transcript_are_both_read(stored, tmp_path, monkeypatch):
    home, db = stored
    head = tmp_path / "operator-head"
    head.mkdir()
    monkeypatch.setenv("HERMES_HEAD_HOME", str(head))
    store_result(db, "parent", "Synchronous")
    ad._reset_for_tests()
    service = ConversationService(tmp_path / "runtime", "install", profile_home=lambda _: home,
        worker_factory=lambda *args, **kwargs: pytest.fail("borrowed worker"))
    scope = ConversationScope("actor", "client", "profile")
    route, _ = service.store.reserve(scope, "chat", str(tmp_path), str(home))
    route = service.store.replace_unused(route, "parent")
    try:
        handle = ad.dispatch_async_delegation(goal="Async head", context=None, toolsets=None, role="worker",
            model="model", session_key="parent", parent_session_id="parent", runner=lambda: native_result())
        wait_until(lambda: (ad.get_durable_delegation(handle["delegation_id"]) or {}).get("state") == "completed")
        reply = service.subagents(scope, route.id, "history", {})
        assert len(reply["results"]) == 2
        assert {row["source"] for row in reply["results"]} == {"delegation", "transcript"}
    finally:
        service.close()
        ad._reset_for_tests()


def test_native_completion_process_facts_and_bounded_content(stored):
    home, db = stored
    entry = native_result("x" * 70000)
    entry.update(missed_steer=True, stall_phase="in_tool", stalled_after_quiet_seconds=450,
        handed_off_processes=[{"session_id": "process", "command": "api_key=secret123", "note": "Review"}],
        orphaned_processes=[{"runtime_seconds": 3}], unread_completions=[{"exit_code": -1, "output_tail": "output"}],
        tool_trace=[{"tool": "terminal", "args_bytes": 12, "result_bytes": 21}])
    db.append_message("parent", "tool", json.dumps(entry), tool_name="delegate_task")
    roster = history_call(home, db)
    result = history_call(home, db, "result", {"expected_generation": roster["generation"],
        "history_ref": roster["results"][0]["history_ref"]})["result"]
    assert result["content_truncated"] and result["missed_steer"]
    assert len(result["summary"]) == 65536
    assert len(result["processes"]) == 3
    assert result["processes"][-1]["exit_code"] == -1
    assert result["tool_trace"][0]["args_bytes"] == 12
    assert result["stall_phase"] == "in_tool" and result["stalled_after_quiet_seconds"] == 450
    assert "secret123" not in json.dumps(result)


def test_history_source_failure_is_not_an_empty_success(stored):
    home, db = stored
    saved_tree(home)
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("ALTER TABLE messages RENAME TO unreadable_messages")
    reply = history_call(home, db)
    assert not reply["results_available"] and reply["trees_available"]
    assert len(reply["trees"]) == 1
