"""History edits against actual scoped SQLite stores and the serve dispatcher."""
from contextlib import closing
import json

import pytest

from hermes_state import SessionDB
from hermes_state_history_controls import HistoryControlError
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_continuity.lease import persona_chat_root_lease
from tests.agent_runtime.test_operator_conversation_attachment import call, fixture


def setup(tmp_path, monkeypatch, action="branch", index=10):
    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        rows = db.get_messages(target["session_id"])
    preview = call("history.preview", {**target, "action": action, "row_id": rows[index]["id"]})
    assert "result" in preview, preview
    plan = preview["result"]
    request = {**target, "action": action, "row_id": plan["row_id"],
               "preview_token": plan["preview_token"], "operation_id": "history-operation-one"}
    return target, rows, plan, request


def test_branch_copies_exact_prefix_leaves_source_and_default_binding_and_replays(tmp_path, monkeypatch):
    target, before, plan, request = setup(tmp_path, monkeypatch)
    result = call("history.apply", request)
    assert "result" in result, result
    result = result["result"]
    child = result["result_session_id"]
    assert child != target["session_id"]
    assert result["draft"] == before[10]["content"]
    assert plan["earlier_turns"] == 5
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        assert db.get_messages(target["session_id"]) == before
        assert db.get_session(target["session_id"])["ended_at"] is None
        copied = db.get_messages(child)
        assert [(row["role"], row["content"]) for row in copied] == [(row["role"], row["content"]) for row in before[:10]]
        config = json.loads(db.get_session(child)["model_config"])
        assert config["_branched_from"] == target["session_id"]
        assert config["mission_chat_root_id"] == child
    assert PersonaInstanceStore().get(target["persona_instance_id"]).default_chat_session_id == target["session_id"]
    again = call("history.apply", request)["result"]
    assert again["result_session_id"] == child and again["replayed"]
    status = call("history.status", {**target, "operation_id": request["operation_id"]})["result"]
    assert status["state"] == "applied" and status["result"]["branch"]["session_id"] == child


def test_rewind_archives_instead_of_deleting_and_receipt_survives_restart(tmp_path, monkeypatch):
    target, before, _, request = setup(tmp_path, monkeypatch, "rewind")
    from agent_runtime.persona_chat_session import _persona_chat_native_revision
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        old_revision = _persona_chat_native_revision(db, target["session_id"])
    result = call("history.apply", request)
    assert "result" in result, result
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        assert len(db.get_messages(target["session_id"])) == 10
        assert len(db.get_messages(target["session_id"], include_inactive=True)) == len(before)
        assert db.get_session(target["session_id"])["rewind_count"] == 1
        assert _persona_chat_native_revision(db, target["session_id"]) != old_revision
    assert call("history.apply", request)["result"]["replayed"]
    altered = call("history.apply", {**request, "row_id": before[8]["id"]})
    assert altered["error"]["data"]["reason"] == "operation_payload_changed"


@pytest.mark.parametrize("action", ["branch", "rewind"])
def test_stale_preview_and_busy_root_never_mutate(tmp_path, monkeypatch, action):
    target, before, _, request = setup(tmp_path, monkeypatch, action)
    with persona_chat_root_lease(target["session_id"]):
        refused = call("history.apply", request)
        assert refused["error"]["data"]["reason"] == "conversation_busy"
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        db.append_message(target["session_id"], "user", "new work")
    stale = call("history.apply", request)
    assert stale["error"]["data"]["reason"] == "history_changed"
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        assert len(db.get_messages(target["session_id"])) == len(before) + 1


def test_accepted_send_blocks_history_before_worker_has_started(tmp_path, monkeypatch):
    target, _, _, request = setup(tmp_path, monkeypatch, "rewind")
    sent = call("message", {**target, "message": "queued", "turn_request_id": "queued-turn"}, spawn=lambda *args: None)
    assert sent["result"]["accepted"]
    assert call("history.apply", request)["error"]["data"]["reason"] == "conversation_busy"


def test_native_branch_revision_pin_is_checked_inside_writer(tmp_path):
    with closing(SessionDB(db_path=tmp_path / "state.db")) as db:
        db.create_session("source", source="mission_chat")
        db.append_message("source", "user", "original")
        row = db.get_messages("source")[0]
        revision = db.history_control_revision("source")
        db.append_message("source", "assistant", "late reply")
        with pytest.raises(HistoryControlError, match="history_changed"):
            db.branch_before_message("source", row["id"], child_session_id="child", expected_history_digest=revision,
                operation_receipt=("receipt", "{}"), model_config={}, title="Branch")
        assert db.get_session("child") is None
        assert db.get_meta("receipt") is None


def test_profile_switch_rejects_old_install_and_can_return_to_original(tmp_path, monkeypatch):
    a, _, _, request = setup(tmp_path, monkeypatch)
    fixture(tmp_path / "other", monkeypatch, "Other")
    assert call("history.apply", request)["error"]["data"]["reason"] == "installation_changed"
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "home" / "runtime"))
    assert call("history.apply", request)["result"]["session_id"] == a["session_id"]


def test_archived_marker_is_hidden_and_branch_keeps_inherited_trace(tmp_path, monkeypatch):
    from agent_runtime.mission_chat_turns import persist_mission_chat_turn
    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    root = target["session_id"]
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        db.clear_messages(root)
        db.append_message(root, "user", "first", platform_message_id="first")
        db.append_message(root, "assistant", "done", platform_message_id="first")
        db.append_message(root, "user", "second", platform_message_id="second")
    persist_mission_chat_turn(session_id=root, client_message_id="first", turn_id="first", state="completed",
        elements=[{"kind": "segment", "id": "first-thought", "turn_id": "first", "seq": 1,
                   "state": "done", "seg_type": "plan", "text": "Saved reasoning"}])
    persist_mission_chat_turn(session_id=root, client_message_id="second", turn_id="second", state="interrupted", elements=[])
    plan = call("history.preview", {**target, "action": "branch", "client_message_id": "second"})
    assert "result" in plan, plan
    request = {**target, "action": "branch", "row_id": plan["result"]["row_id"],
               "preview_token": plan["result"]["preview_token"], "operation_id": "branch-with-trace-one"}
    branch = call("history.apply", request)
    assert "result" in branch, branch
    child = branch["result"]["result_session_id"]
    read = call("read", {**target, "session_id": child})["result"]
    assert any(row.get("turn_elements") for row in read["messages"])
    rewind = call("history.preview", {**target, "action": "rewind", "client_message_id": "second"})["result"]
    result = call("history.apply", {**request, "action": "rewind", "preview_token": rewind["preview_token"],
                                    "operation_id": "rewind-with-marker-one"})
    assert "result" in result, result
    visible = call("read", target)["result"]["messages"]
    assert not any(row.get("client_message_id") == "second" for row in visible)
    after_source_rewind = call("read", {**target, "session_id": child})["result"]
    assert after_source_rewind["messages"] == read["messages"]


def test_compacted_or_attached_targets_are_explicit_refusals(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        db.clear_messages(target["session_id"])
        row = db.append_message(target["session_id"], "user", "Question\n[Operator attached image: image.png]")
    refused = call("history.preview", {**target, "action": "rewind", "row_id": row})
    assert refused["error"]["data"]["reason"] == "prompt_attachments_not_restorable"
    # The native alternating-turn repair must never silently merge two prompts.
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        second = db.append_message(target["session_id"], "user", "Second question")
    refused = call("history.preview", {**target, "action": "rewind", "row_id": second})
    assert refused["error"]["data"]["reason"] == "target_requires_compaction_review"
