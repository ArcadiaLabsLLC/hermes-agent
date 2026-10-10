"""Only temporary workspaces: strict preview, preservation and recovery receipts."""
from pathlib import Path
import pytest
from tools.checkpoint_manager import CheckpointManager


def workspace(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    work = tmp_path / "workspace"
    work.mkdir()
    (work / "package.json").write_text("{}")
    (work / "agent.txt").write_text("before")
    (work / "human.txt").write_text("before")
    manager = CheckpointManager(enabled=True)
    assert manager.ensure_checkpoint(str(work), "before edit")
    checkpoint = manager.list_checkpoints(str(work))[0]["hash"]
    (work / "agent.txt").write_text("agent change")
    manager.record_agent_write(str(work / "agent.txt"))
    (work / "human.txt").write_text("human change")
    return manager, work, checkpoint


def test_restore_preserves_human_edits_and_replay_never_repeats_write(tmp_path, monkeypatch):
    manager, work, checkpoint = workspace(tmp_path, monkeypatch)
    preview = manager.preview_restore(str(work), checkpoint)
    assert preview["success"], preview
    files = {row["path"]: row for row in preview["files"]}
    assert files["agent.txt"]["eligible"]
    assert not files["human.txt"]["eligible"]
    kwargs = dict(revision=preview["revision"], selected_paths=["agent.txt"], operation_id="a" * 64)
    result = manager.restore_preview(str(work), checkpoint, **kwargs)
    assert result["success"], result
    assert (work / "agent.txt").read_text() == "before"
    assert (work / "human.txt").read_text() == "human change"
    assert result["recovery_checkpoint"] != checkpoint
    (work / "agent.txt").write_text("after restoration")
    replay = manager.restore_preview(str(work), checkpoint, **kwargs)
    assert replay["replayed"] and (work / "agent.txt").read_text() == "after restoration"
    assert manager.restore_receipt("a" * 64)["restored_files"] == ["agent.txt"]


@pytest.mark.parametrize("selection", [["human.txt"], ["../outside"], ["missing.txt"]])
def test_unproven_or_unselected_paths_never_mutate(tmp_path, monkeypatch, selection):
    manager, work, checkpoint = workspace(tmp_path, monkeypatch)
    preview = manager.preview_restore(str(work), checkpoint)
    result = manager.restore_preview(str(work), checkpoint, revision=preview["revision"],
                                      selected_paths=selection, operation_id="b" * 64)
    assert result["reason"] == "restore_conflict"
    assert (work / "agent.txt").read_text() == "agent change"
    assert (work / "human.txt").read_text() == "human change"


def test_external_edit_after_preview_and_failed_backup_refuse(tmp_path, monkeypatch):
    manager, work, checkpoint = workspace(tmp_path, monkeypatch)
    preview = manager.preview_restore(str(work), checkpoint)
    (work / "agent.txt").write_text("later human edit")
    result = manager.restore_preview(str(work), checkpoint, revision=preview["revision"],
                                      selected_paths=["agent.txt"], operation_id="c" * 64)
    assert result["reason"] == "workspace_changed"
    (work / "agent.txt").write_text("agent change")
    monkeypatch.setattr(manager, "_take", lambda *args, **kwargs: False)
    result = manager.restore_preview(str(work), checkpoint, revision=preview["revision"],
                                      selected_paths=["agent.txt"], operation_id="d" * 64)
    assert result["reason"] == "recovery_checkpoint_failed"
    assert (work / "agent.txt").read_text() == "agent change"


def test_checkpoint_from_another_project_is_refused(tmp_path, monkeypatch):
    manager, work, checkpoint = workspace(tmp_path, monkeypatch)
    other = tmp_path / "other"
    other.mkdir()
    (other / "private.txt").write_text("other project")
    assert manager.ensure_checkpoint(str(other))
    foreign = manager.list_checkpoints(str(other))[0]["hash"]
    assert manager.preview_restore(str(work), foreign)["reason"] == "checkpoint_unavailable"


def test_restore_new_file_deletion_has_a_recovery_path(tmp_path, monkeypatch):
    manager, work, checkpoint = workspace(tmp_path, monkeypatch)
    added = work / "added.bin"
    added.write_bytes(b"\x00\x01original bytes\xff")
    manager.record_agent_write(str(added))
    preview = manager.preview_restore(str(work), checkpoint)
    result = manager.restore_preview(str(work), checkpoint, revision=preview["revision"],
                                      selected_paths=["added.bin"], operation_id="e" * 64)
    assert result["success"] and not added.exists(), result
    recovery = manager.preview_restore(str(work), result["recovery_checkpoint"])
    restored = manager.restore_preview(str(work), result["recovery_checkpoint"], revision=recovery["revision"],
                                      selected_paths=["added.bin"], operation_id="f" * 64)
    assert restored["success"], restored
    assert added.read_bytes() == b"\x00\x01original bytes\xff"


def test_partial_failure_has_a_receipt_and_does_not_repeat_successful_writes(tmp_path, monkeypatch):
    import tools.checkpoint_manager as checkpoint_module
    manager, work, checkpoint = workspace(tmp_path, monkeypatch)
    second = work / "second.txt"
    second.write_text("agent addition")
    manager.record_agent_write(str(second))
    preview = manager.preview_restore(str(work), checkpoint)
    original_unlink = Path.unlink
    def fail_second(path, *args, **kwargs):
        if path == second:
            raise OSError("simulated sharing violation")
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(checkpoint_module.Path, "unlink", fail_second)
    kwargs = dict(revision=preview["revision"], selected_paths=["agent.txt", "second.txt"], operation_id="1" * 64)
    result = manager.restore_preview(str(work), checkpoint, **kwargs)
    assert result["reason"] == "restore_partial"
    assert result["restored_files"] == ["agent.txt"]
    assert result["failed_files"] == [{"path": "second.txt", "reason": "file_write_failed"}]
    assert second.read_text() == "agent addition"
    (work / "agent.txt").write_text("later edit")
    assert manager.restore_preview(str(work), checkpoint, **kwargs)["replayed"]
    assert (work / "agent.txt").read_text() == "later edit"


def test_interrupted_restore_keeps_pending_receipt_and_never_auto_reapplies(tmp_path, monkeypatch):
    manager, work, checkpoint = workspace(tmp_path, monkeypatch)
    added = work / "added.txt"
    added.write_text("agent addition")
    manager.record_agent_write(str(added))
    preview = manager.preview_restore(str(work), checkpoint)
    original_unlink = Path.unlink
    def interrupt(path, *args, **kwargs):
        if path == added:
            raise KeyboardInterrupt()
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", interrupt)
    kwargs = dict(revision=preview["revision"], selected_paths=["added.txt"], operation_id="2" * 64)
    with pytest.raises(KeyboardInterrupt):
        manager.restore_preview(str(work), checkpoint, **kwargs)
    monkeypatch.setattr(Path, "unlink", original_unlink)
    replay = manager.restore_preview(str(work), checkpoint, **kwargs)
    assert replay["reason"] == "restore_outcome_unknown" and replay["replayed"]
    assert added.read_text() == "agent addition"


def test_external_deletion_and_oversize_are_preserved(tmp_path, monkeypatch):
    manager, work, checkpoint = workspace(tmp_path, monkeypatch)
    (work / "agent.txt").unlink()
    deleted = manager.preview_restore(str(work), checkpoint)
    assert not next(row for row in deleted["files"] if row["path"] == "agent.txt")["eligible"]
    (work / "agent.txt").write_bytes(b"x" * (1024 * 1024 + 1))
    manager.record_agent_write(str(work / "agent.txt"))
    manager.max_file_size_mb = 1
    large = manager.preview_restore(str(work), checkpoint)
    assert next(row for row in large["files"] if row["path"] == "agent.txt")["reason"] == "oversize"
