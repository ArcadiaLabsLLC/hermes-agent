"""Reviewed restore shares native writes and keeps only recoverable retention."""
import pytest

from agent_runtime import checkpoint_reviewed_restore as reviewed_restore
from tools import checkpoint_manager as checkpoints
from tests.tools.test_checkpoint_reviewed_restore_downstream import workspace


def _pins(work):
    ok, refs, error = checkpoints._run_git(
        ["for-each-ref", "--format=%(refname)", "refs/operator-restore/"],
        checkpoints._store_path(), str(work))
    assert ok, error
    return refs.splitlines()


def test_apply_verifies_the_same_native_write_used_by_recovery(tmp_path, monkeypatch):
    manager, work, checkpoint = workspace(tmp_path, monkeypatch)
    preview = manager.preview_restore(str(work), checkpoint)
    original = manager._checkout_restore_paths

    def altered_after_checkout(*args, **kwargs):
        result = original(*args, **kwargs)
        (work / "agent.txt").write_text("concurrent edit after checkout")
        return result

    monkeypatch.setattr(manager, "_checkout_restore_paths", altered_after_checkout)
    result = manager.restore_preview(str(work), checkpoint, revision=preview["revision"],
        selected_paths=["agent.txt"], operation_id="a" * 64)
    assert not result["success"], result
    assert result["failed_files"] == [{"path": "agent.txt", "reason": "file_write_failed"}]
    assert result["restored_files"] == []
    assert len(_pins(work)) == 2


@pytest.mark.parametrize("failure", ["second_pin", "initial_receipt"])
def test_failed_preparation_releases_pins_without_touching_workspace(tmp_path, monkeypatch, failure):
    manager, work, checkpoint = workspace(tmp_path, monkeypatch)
    preview = manager.preview_restore(str(work), checkpoint)
    if failure == "second_pin":
        original = checkpoints._run_git

        def fail_backup_pin(args, *a, **kw):
            if args[0] == "update-ref" and args[1].endswith("/backup"):
                return False, "", "pin refused"
            return original(args, *a, **kw)

        monkeypatch.setattr(checkpoints, "_run_git", fail_backup_pin)
    else:
        def refuse_receipt(*a, **kw):
            raise OSError("receipt disk full")

        monkeypatch.setattr(manager, "_write_restore_receipt", refuse_receipt)
    try:
        result = manager.restore_preview(str(work), checkpoint, revision=preview["revision"],
            selected_paths=["agent.txt"], operation_id="b" * 64)
        assert not result["success"]
    except OSError:
        assert failure == "initial_receipt"
    assert (work / "agent.txt").read_text() == "agent change"
    assert _pins(work) == []


def test_status_retires_orphan_pins_only_when_no_write_receipt_exists(tmp_path, monkeypatch):
    from tools.checkpoint_pruning import store_lock
    manager, work, checkpoint = workspace(tmp_path, monkeypatch)
    with store_lock(checkpoints._resolve_checkpoint_base()):
        assert reviewed_restore.pin_restore_checkpoints(str(work), "c" * 64, checkpoint, checkpoint)
    assert len(_pins(work)) == 2
    assert manager.restore_receipt("c" * 64) is None
    assert _pins(work) == []
