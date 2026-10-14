"""Redo restores native rows and snapshots; no model execution or copied history."""
from contextlib import closing
import pytest

from hermes_state import SessionDB
from tools.checkpoint_manager import CheckpointManager
from tests.agent_runtime.test_operator_turn_undo import setup_turn, messages
from tests.agent_runtime.test_operator_conversation_attachment import call


def undone(tmp_path, monkeypatch, mode="both"):
    target, work, manager, _, undo = setup_turn(tmp_path, monkeypatch)
    original = messages(tmp_path, target)
    result = call("undo.apply", {**undo, "mode": mode})
    assert result["result"]["state"] == "completed", result
    preview = call("redo.preview", target)
    assert "result" in preview, preview
    redo = {**target, "preview_token": preview["result"]["preview_token"], "operation_id": "reviewed-redo-request"}
    return target, work, manager, original, redo


@pytest.mark.parametrize("mode", ["chat", "files", "both"])
def test_exact_native_rows_and_files_return_once_after_reopen(tmp_path, monkeypatch, mode):
    target, work, _, original, request = undone(tmp_path, monkeypatch, mode)
    assert call("redo.available", target)["result"]["available"]
    applied = call("redo.apply", request)
    assert applied["result"]["state"] == "completed", applied
    assert messages(tmp_path, target) == original
    assert (work / "one.txt").read_text() == "after one\n"
    assert call("redo.apply", request)["result"]["state"] == "completed"
    assert call("undo.status", request)["result"]["result"]["direction"] == "redo"
    assert call("history.pending", target)["result"]["pending"] is None
    assert not call("redo.available", target)["result"]["available"]


@pytest.mark.parametrize("change", ["human_file", "agent_file", "new_turn", "archived_payload"])
def test_intervening_changes_refuse_before_writing(tmp_path, monkeypatch, change):
    target, work, manager, _, request = undone(tmp_path, monkeypatch)
    if change.endswith("file"):
        (work / "one.txt").write_text("keep my change")
        if change == "agent_file":
            manager.record_agent_write(str(work / "one.txt"))
    else:
        with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
            if change == "new_turn":
                db.append_message(target["session_id"], "user", "another question")
            else:
                db._execute_write(lambda conn: conn.execute(
                    "UPDATE messages SET content = 'modified archive' WHERE session_id = ? AND active = 0",
                    (target["session_id"],)))
    before = messages(tmp_path, target)
    reviewed_again = call("redo.preview", target)
    assert reviewed_again["error"]["data"]["reason"] in {"workspace_changed", "history_changed"}, reviewed_again
    result = call("redo.apply", request)
    assert result["error"]["data"]["reason"] in {"workspace_changed", "history_changed"}, result
    assert messages(tmp_path, target) == before
    assert (work / "two.txt").read_text() == "before two\n"
    assert call("history.pending", target)["result"]["pending"] is None


def test_pruning_and_gc_cannot_expire_retained_backup(tmp_path, monkeypatch):
    target, work, manager, original, request = undone(tmp_path, monkeypatch)
    manager.max_snapshots = 1
    for i in range(3):
        manager.new_turn()
        (work / "unrelated.txt").write_text(str(i))
        assert manager.ensure_checkpoint(str(work))
    from tools.checkpoint_maintenance import prune_checkpoints
    assert prune_checkpoints(delete_orphans=False)["errors"] == 0
    # Re-review ignores unrelated paths but still pins the affected ones.
    preview = call("redo.preview", target)
    assert "result" in preview, preview
    result = call("redo.apply", {**request, "preview_token": preview["result"]["preview_token"]})
    assert result["result"]["state"] == "completed", result
    assert messages(tmp_path, target) == original
    assert (work / "unrelated.txt").read_text() == "2"


@pytest.mark.parametrize("direction", ["finish", "rollback"])
def test_partial_redo_uses_existing_recovery_after_review_closes(tmp_path, monkeypatch, direction):
    target, work, _, original, request = undone(tmp_path, monkeypatch)
    write = CheckpointManager._checkout_restore_paths
    def fail_second(self, working_dir, commit, paths, **kwargs):
        return (False, "", "sharing violation") if paths == ["two.txt"] else write(self, working_dir, commit, paths, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(CheckpointManager, "_checkout_restore_paths", fail_second)
        partial = call("redo.apply", request)["result"]
    assert partial["state"] == "partial"
    assert messages(tmp_path, target) == []
    assert call("history.pending", target)["result"]["pending"]["action"] == "redo"
    current = call("undo.status", request)["result"]["result"]
    result = call("undo.recover", {**target, "operation_id": request["operation_id"],
        "direction": direction, "recovery_revision": current["recovery_revision"]})
    assert result["result"]["state"] == ("completed" if direction == "finish" else "rolled_back"), result
    assert messages(tmp_path, target) == (original if direction == "finish" else [])
    assert (work / "one.txt").read_text() == ("after one\n" if direction == "finish" else "before one\n")
    assert call("history.pending", target)["result"]["pending"] is None


def test_crash_after_chat_commit_is_reconciled_without_replaying_files(tmp_path, monkeypatch):
    import agent_runtime.operator_undo as undo
    target, work, _, original, request = undone(tmp_path, monkeypatch)
    save = undo._save
    def crash(db, params, record):
        if record.get("direction") == "redo" and record.get("state") == "completed":
            raise OSError("process died after SQLite commit")
        return save(db, params, record)
    with monkeypatch.context() as patch:
        patch.setattr(undo, "_save", crash)
        assert "error" in call("redo.apply", request)
    (work / "one.txt").write_text("later human change")
    result = call("undo.status", request)["result"]["result"]
    assert result["state"] == "completed"
    assert messages(tmp_path, target) == original
    assert (work / "one.txt").read_text() == "later human change"


def test_expiry_refuses_and_maintenance_releases_only_completed_lease(tmp_path, monkeypatch):
    import agent_runtime.operator_redo as redo
    from tools.checkpoint_maintenance import prune_checkpoints
    from tools.checkpoint_manager import _store_path, _run_git
    _target, work, _, _, request = undone(tmp_path, monkeypatch)
    now = redo.time.time()
    monkeypatch.setattr(redo.time, "time", lambda: now + redo.REDO_RETENTION_SECONDS + 1)
    result = call("redo.apply", request)
    assert result["error"]["data"]["reason"] == "redo_expired"
    assert prune_checkpoints(delete_orphans=False)["errors"] == 0
    ok, refs, _ = _run_git(["for-each-ref", "--format=%(refname)", "refs/operator-restore/"], _store_path(), str(work))
    assert ok and not refs.strip()
    assert (work / "one.txt").read_text() == "before one\n"


def test_redo_recovers_creation_and_deletion_without_touching_unrelated_files(tmp_path, monkeypatch):
    target, work, manager, _, undo = setup_turn(tmp_path, monkeypatch)
    added = work / "added.bin"
    added.write_bytes(b"\x00saved bytes\xff")
    manager.record_agent_write(str(added))
    (work / "two.txt").unlink()
    manager.record_agent_write(str(work / "two.txt"))
    undo["preview_token"] = call("undo.preview", {**target, "client_message_id": "first"})["result"]["preview_token"]
    result = call("undo.apply", undo)
    assert result["result"]["state"] == "completed", result
    assert not added.exists() and (work / "two.txt").exists()
    (work / "human.txt").write_text("unrelated draft")
    preview = call("redo.preview", target)["result"]
    result = call("redo.apply", {**target, "operation_id": "redo-added-and-deleted", "preview_token": preview["preview_token"]})
    assert result["result"]["state"] == "completed", result
    assert added.read_bytes() == b"\x00saved bytes\xff"
    assert not (work / "two.txt").exists()
    assert (work / "human.txt").read_text() == "unrelated draft"


def test_redo_cancellation_fences_delayed_apply_and_rejects_changed_id_payload(tmp_path, monkeypatch):
    target, work, _, _, request = undone(tmp_path, monkeypatch)
    assert call("history.cancel_unapplied", {**target, "action": "redo", "operation_id": request["operation_id"]})["result"]["cancelled"]
    assert call("redo.apply", request)["error"]["data"]["reason"] == "operation_cancelled"
    applied = {**request, "operation_id": "another-redo-request"}
    assert call("redo.apply", applied)["result"]["state"] == "completed"
    assert call("redo.apply", {**applied, "preview_token": "different"})["error"]["data"]["reason"] == "operation_payload_changed"
    assert (work / "one.txt").read_text() == "after one\n"


def test_failed_undo_does_not_replace_last_completed_undo(tmp_path, monkeypatch):
    target, _work, _manager, _, _ = undone(tmp_path, monkeypatch, mode="files")
    preview = call("redo.preview", target)["result"]
    from agent_runtime import operator_undo
    # A later command that rolls back before touching chat preserves the source.
    with monkeypatch.context() as patch:
        def fail_chat(*args):
            raise OSError("chat writer unavailable")
        patch.setattr(operator_undo, "_rewind", fail_chat)
        undo = call("undo.preview", {**target, "client_message_id": "first"})["result"]
        partial = call("undo.apply", {**target, "client_message_id": "first", "mode": "chat",
            "operation_id": "refused-later-undo", "preview_token": undo["preview_token"]})
    assert partial["result"]["state"] == "partial", partial
    rolled_back = call("undo.recover", {**target, "operation_id": "refused-later-undo", "direction": "rollback",
        "recovery_revision": partial["result"]["recovery_revision"]})
    assert rolled_back["result"]["state"] == "rolled_back"
    assert call("redo.preview", target)["result"]["undo_operation_id"] == preview["undo_operation_id"]


def test_newer_completed_undo_supersedes_source_even_after_old_status_poll(tmp_path, monkeypatch):
    target, _, _, _, _ = setup_turn(tmp_path, monkeypatch)
    for prompt, operation in (("second", "undo-second-prompt"), ("first", "undo-first-prompt")):
        preview = call("undo.preview", {**target, "client_message_id": prompt})["result"]
        result = call("undo.apply", {**target, "client_message_id": prompt, "mode": "chat",
            "operation_id": operation, "preview_token": preview["preview_token"]})
        assert result["result"]["state"] == "completed", result
    assert call("undo.status", {**target, "operation_id": "undo-second-prompt"})["result"]["result"]["state"] == "completed"
    preview = call("redo.preview", target)["result"]
    assert preview["undo_operation_id"] == "undo-first-prompt"
    result = call("redo.apply", {**target, "operation_id": "redo-only-last-undo", "preview_token": preview["preview_token"]})
    assert result["result"]["state"] == "completed", result
    assert [row["content"] for row in messages(tmp_path, target)] == ["first", "Done first"]
