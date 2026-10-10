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
