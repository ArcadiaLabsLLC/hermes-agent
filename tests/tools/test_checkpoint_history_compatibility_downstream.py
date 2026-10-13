"""History attribution preserves the native snapshot and safe-restore contract."""
import pytest

from tests.tools.test_checkpoint_reviewed_restore_downstream import workspace


@pytest.mark.parametrize("recreated", [False, True])
def test_agent_deletion_retains_native_ownership_but_preserves_user_recreation(tmp_path, monkeypatch, recreated):
    manager, work, checkpoint = workspace(tmp_path, monkeypatch)
    path = work / "agent.txt"
    path.unlink()
    manager.record_agent_write(str(path))
    if recreated:
        path.write_text("human replacement")
    result = manager.restore(str(work), checkpoint, safe=True)
    assert result["success"], result
    assert path.exists(), result
    assert path.read_text() == ("human replacement" if recreated else "before")
    assert ("agent.txt" in result["skipped_user_edits"]) is recreated


def test_unchanged_first_checkpoint_attempt_still_reserves_the_turn_baseline(tmp_path, monkeypatch):
    manager, work, _ = workspace(tmp_path, monkeypatch)
    manager.new_turn()
    assert manager.ensure_checkpoint(str(work))
    manager.new_turn()
    baseline = manager.list_checkpoints(str(work))[0]["hash"]
    assert not manager.ensure_checkpoint(str(work))
    (work / "agent.txt").write_text("first write of this turn")
    assert not manager.ensure_checkpoint(str(work))
    assert manager.list_checkpoints(str(work))[0]["hash"] == baseline


def test_absence_without_prior_authored_content_is_not_restore_ownership(tmp_path, monkeypatch):
    manager, work, checkpoint = workspace(tmp_path, monkeypatch)
    path = work / "human.txt"
    path.unlink()
    manager.record_agent_write(str(path))
    preview = manager.preview_restore(str(work), checkpoint)
    row = next(row for row in preview["files"] if row["path"] == "human.txt")
    assert not row["eligible"] and row["reason"] == "no_write_evidence"
