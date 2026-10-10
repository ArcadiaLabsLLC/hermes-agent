"""Real RPC + SQLite + native Git snapshots, including interruption windows."""
from contextlib import closing
import pytest
from hermes_state import SessionDB
from tools.checkpoint_manager import CheckpointManager
from agent_runtime.turn_checkpoints import TurnCheckpointRecorder
from tests.agent_runtime.test_operator_conversation_attachment import fixture, call


def setup_turn(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    from agent_runtime.models import AgentPersona
    from agent_runtime.store import AgentStore
    AgentStore().save(AgentPersona(id="builder", display_name="Builder", role="builder",
        model=None, provider=None, api_mode=None, system_prompt_path=""))
    work = tmp_path / "work"
    work.mkdir()
    (work / "package.json").write_text("{}")
    (work / "one.txt").write_text("before one\n")
    (work / "two.txt").write_text("before two\n")
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        db.clear_messages(target["session_id"])
        db.update_session_cwd(target["session_id"], str(work))
        for turn in ("first", "second"):
            db.append_message(target["session_id"], "user", turn, platform_message_id=turn)
            db.append_message(target["session_id"], "assistant", "Done " + turn, platform_message_id=turn)
    manager = CheckpointManager(enabled=True)
    manager.history_observer = TurnCheckpointRecorder(target["session_id"], "first", manager)
    assert manager.ensure_checkpoint(str(work))
    for name in ("one", "two"):
        path = work / (name + ".txt")
        path.write_text("after " + name + "\n")
        manager.record_agent_write(str(path))
    plan = call("undo.preview", {**target, "client_message_id": "first"})
    assert "result" in plan, plan
    request = {**target, "client_message_id": "first", "preview_token": plan["result"]["preview_token"],
               "mode": "both", "operation_id": "combined-undo-request"}
    return target, work, manager, plan["result"], request


def messages(tmp_path, target):
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        return db.get_messages(target["session_id"])


@pytest.mark.parametrize("mode, retained, content", [("both", 0, "before one\n"), ("chat", 0, "after one\n"), ("files", 4, "before one\n")])
def test_reviewed_scope_applies_once_with_durable_receipt(tmp_path, monkeypatch, mode, retained, content):
    target, work, manager, plan, request = setup_turn(tmp_path, monkeypatch)
    assert {row["path"] for row in plan["files"]} == {"one.txt", "two.txt"}
    result = call("undo.apply", {**request, "mode": mode})
    assert "result" in result, result
    assert result["result"]["state"] == "completed", result
    assert len(messages(tmp_path, target)) == retained
    assert (work / "one.txt").read_text() == content
    assert call("undo.apply", {**request, "mode": mode})["result"]["state"] == "completed"
    assert call("history.pending", target)["result"]["pending"] is None


def test_branch_here_includes_selected_reply_and_links_origin(tmp_path, monkeypatch):
    target, work, manager, _, _ = setup_turn(tmp_path, monkeypatch)
    params = {**target, "action": "branch", "boundary": "after_reply", "client_message_id": "first"}
    preview = call("history.preview", params)["result"]
    result = call("history.apply", {**params, "preview_token": preview["preview_token"], "operation_id": "branch-after-reply"})
    assert "result" in result, result
    child = result["result"]["result_session_id"]
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        assert [row["content"] for row in db.get_messages(child)] == ["first", "Done first"]
    assert len(messages(tmp_path, target)) == 4
    assert call("history.origin", {**target, "session_id": child})["result"]["origin"]["session_id"] == target["session_id"]


def test_partial_restore_survives_status_and_can_rollback(tmp_path, monkeypatch):
    import tools.checkpoint_manager as checkpoints
    target, work, manager, _, request = setup_turn(tmp_path, monkeypatch)
    original = checkpoints._run_git
    def fail_one(args, *a, **kw):
        if "checkout" in args and args[-1] == "two.txt":
            return False, "", "simulated sharing violation"
        return original(args, *a, **kw)
    with monkeypatch.context() as patch:
        patch.setattr(checkpoints, "_run_git", fail_one)
        partial = call("undo.apply", request)["result"]
    assert partial["state"] == "partial", partial
    assert partial["files"]["restored_files"] == ["one.txt"]
    assert len(messages(tmp_path, target)) == 4
    discovered = call("history.pending", target)["result"]["pending"]
    assert discovered["operation_id"] == request["operation_id"]
    partial = call("undo.status", request)["result"]["result"]
    recovered = call("undo.recover", {**target, "operation_id": request["operation_id"],
        "direction": "rollback", "recovery_revision": partial["recovery_revision"]})
    assert recovered["result"]["state"] == "rolled_back", recovered
    assert (work / "one.txt").read_text() == "after one\n"
    stale_finish = call("undo.recover", {**target, "operation_id": request["operation_id"],
        "direction": "finish", "recovery_revision": partial["recovery_revision"]})
    assert stale_finish["result"]["state"] == "rolled_back"
    assert len(messages(tmp_path, target)) == 4


def test_crash_after_files_before_coordinator_receipt_is_recoverable(tmp_path, monkeypatch):
    import agent_runtime.operator_undo as undo
    target, work, _, _, request = setup_turn(tmp_path, monkeypatch)
    save = undo._save
    def crash_after_files(db, params, record):
        if record.get("files"):
            raise OSError("simulated process death")
        save(db, params, record)
    with monkeypatch.context() as patch:
        patch.setattr(undo, "_save", crash_after_files)
        lost = call("undo.apply", request)
    assert lost["error"]["data"]["reason"] == "turn_outcome_unknown"
    assert (work / "one.txt").read_text() == "before one\n"
    assert len(messages(tmp_path, target)) == 4
    current = call("undo.status", request)["result"]["result"]
    result = call("undo.recover", {**target, "operation_id": request["operation_id"],
        "direction": "finish", "recovery_revision": current["recovery_revision"]})
    assert result["result"]["state"] == "completed", result
    assert messages(tmp_path, target) == []


def test_other_chat_write_is_not_eligible_for_this_turn_undo(tmp_path, monkeypatch):
    target, work, manager, _, _ = setup_turn(tmp_path, monkeypatch)
    manager.history_observer = None
    (work / "one.txt").write_text("another chat wrote this")
    manager.record_agent_write(str(work / "one.txt"))
    preview = call("undo.preview", {**target, "client_message_id": "first"})["result"]
    files = {row["path"]: row for row in preview["files"]}
    assert not files["one.txt"]["eligible"]
    assert files["two.txt"]["eligible"]


def test_cancel_unapplied_tombstone_refuses_a_delayed_request(tmp_path, monkeypatch):
    target, _, _, _, request = setup_turn(tmp_path, monkeypatch)
    cancelled = call("history.cancel_unapplied", {**target, "action": "undo", "operation_id": request["operation_id"]})
    assert cancelled["result"]["cancelled"], cancelled
    refused = call("undo.apply", request)
    assert refused["error"]["data"]["reason"] == "operation_cancelled"
    assert len(messages(tmp_path, target)) == 4
