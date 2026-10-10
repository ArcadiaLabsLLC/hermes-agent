"""Native file snapshots and turn attribution, never the operator's workspace."""
import pytest

from agent_runtime.turn_checkpoints import TurnCheckpointRecorder, read_turn_checkpoint
from tools.checkpoint_manager import CheckpointManager
from tests.agent_runtime.test_operator_turn_undo import setup_turn, call, messages


def test_first_baseline_tracks_new_deleted_and_net_unchanged_files(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    work = tmp_path / "work"
    work.mkdir()
    (work / "package.json").write_text("{}")
    original = work / "original.txt"
    original.write_text("first\n")
    manager = CheckpointManager(enabled=True)
    manager.history_observer = TurnCheckpointRecorder("chat", "turn", manager)
    assert manager.ensure_checkpoint(str(work))
    original.write_text("middle\n")
    manager.record_agent_write(str(original))
    manager.new_turn()
    assert manager.ensure_checkpoint(str(work))
    original.write_text("last\n")
    manager.record_agent_write(str(original))
    added = work / "new.txt"
    added.write_text("new content\n")
    manager.record_agent_write(str(added))
    files = read_turn_checkpoint("chat", "turn")["workspaces"][str(work)]["files"]
    assert "-first" in files["original.txt"]["diff"]
    assert "-middle" not in files["original.txt"]["diff"]
    assert files["new.txt"]["insertions"] == 1
    original.unlink()
    manager.record_agent_write(str(original))
    files = read_turn_checkpoint("chat", "turn")["workspaces"][str(work)]["files"]
    assert files["original.txt"]["deleted"]
    assert files["original.txt"]["deletions"] == 1
    original.write_text("first\n")
    manager.record_agent_write(str(original))
    assert "original.txt" not in read_turn_checkpoint("chat", "turn")["workspaces"][str(work)]["files"]
    assert read_turn_checkpoint("other-chat", "turn") is None


def test_oversize_or_unproven_write_does_not_enter_turn(tmp_path, monkeypatch):
    target, work, manager, _, _ = setup_turn(tmp_path, monkeypatch)
    manager.max_file_size_mb = 1
    huge = work / "huge.txt"
    huge.write_text("a" * (1024 * 1024 + 1))
    manager.record_agent_write(str(huge))
    manager.history_observer.write(str(work), work / "one.txt", {"sha256": "wrong", "deleted": False})
    files = read_turn_checkpoint(target["session_id"], "first")["workspaces"][str(work)]["files"]
    assert set(files) == {"one.txt", "two.txt"}
    assert files["one.txt"]["sha256"] != "wrong"


def test_partial_recovery_refuses_stale_choice_and_preserves_later_edit(tmp_path, monkeypatch):
    import tools.checkpoint_manager as checkpoints
    target, work, _, _, request = setup_turn(tmp_path, monkeypatch)
    original = checkpoints._run_git
    def fail_one(args, *a, **kw):
        if "checkout" in args and args[-1] == "two.txt":
            return False, "", "simulated sharing violation"
        return original(args, *a, **kw)
    with monkeypatch.context() as patch:
        patch.setattr(checkpoints, "_run_git", fail_one)
        partial = call("undo.apply", request)["result"]
    assert partial["state"] == "partial"
    recovery = {**target, "operation_id": request["operation_id"], "direction": "finish"}
    refused = call("undo.recover", {**recovery, "recovery_revision": "stale"})
    assert refused["error"]["data"]["reason"] == "recovery_changed"
    assert (work / "two.txt").read_text() == "after two\n"
    (work / "two.txt").write_text("human wrote this meanwhile")
    result = call("undo.recover", {**recovery, "recovery_revision": partial["recovery_revision"]})["result"]
    assert result["state"] == "partial"
    assert (work / "two.txt").read_text() == "human wrote this meanwhile"
    assert len(messages(tmp_path, target)) == 4


def test_recovery_backup_survives_native_snapshot_retention(tmp_path, monkeypatch):
    from tools.checkpoint_manager import _run_git, _store_path
    from tools.checkpoint_manager import restore_revision
    from tests.tools.test_checkpoint_reviewed_restore_downstream import workspace
    manager, work, checkpoint = workspace(tmp_path, monkeypatch)
    plan = manager.preview_restore(str(work), checkpoint)
    result = manager.restore_preview(str(work), checkpoint, revision=plan["revision"],
                                    selected_paths=["agent.txt"], operation_id="e" * 64)
    assert result["success"]
    manager.max_snapshots = 1
    manager.history_observer = None
    (work / "unrelated.txt").write_text("later snapshot")
    manager.new_turn()
    assert manager.ensure_checkpoint(str(work))
    ok, _, _ = _run_git(["gc", "--prune=now", "--quiet"], _store_path(), str(work))
    assert ok
    restored = manager.resume_restore("e" * 64, revision=restore_revision(result), rollback=True)
    assert restored["success"], restored
    assert (work / "agent.txt").read_text() == "agent change"
    assert (work / "human.txt").read_text() == "human change"
    assert (work / "unrelated.txt").read_text() == "later snapshot"
