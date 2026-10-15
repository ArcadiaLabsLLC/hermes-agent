"""Tool checkpoint contention consumes the current turn's existing wall budget."""
from contextlib import contextmanager
from types import SimpleNamespace

from agent_runtime.profile_runner.execute import AgentRunExecution
from agent_runtime.turn_budget import TurnWallBudget
from tools.checkpoint_manager import CheckpointManager


def test_checkpoint_and_write_waits_share_remaining_turn_budget(tmp_path, monkeypatch):
    from agent_runtime import turn_budget
    from tools import checkpoint_pruning

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    work = tmp_path / "work"
    work.mkdir()
    (work / "package.json").write_text("{}")
    file = work / "one.txt"
    file.write_text("authored")
    clock = [100.0]
    monkeypatch.setattr(turn_budget, "time", SimpleNamespace(time=lambda: clock[0]))
    waits = []

    @contextmanager
    def lock(base, *, wait_seconds=0):
        waits.append(wait_seconds)
        yield

    monkeypatch.setattr(checkpoint_pruning, "store_lock", lock)
    manager = CheckpointManager(enabled=True)
    monkeypatch.setattr(manager, "_take", lambda *_: True)
    # The same agent/manager is retained by the resident runtime across turns.
    execution = SimpleNamespace(
        agent=SimpleNamespace(_checkpoint_mgr=manager),
        request=SimpleNamespace(root_chat_session_id=None),
        wall_checkpoint=SimpleNamespace(budget=TurnWallBudget(60, 160)),
    )
    AgentRunExecution.bind_chat_root(execution)
    assert manager.ensure_checkpoint(str(work))
    clock[0] = 159.75
    manager.record_agent_write(str(file))
    clock[0] = 161
    manager.record_agent_write(str(file))
    execution.wall_checkpoint = SimpleNamespace(budget=TurnWallBudget(2, 163))
    AgentRunExecution.bind_chat_root(execution)
    manager.record_agent_write(str(file))
    assert waits == [30, .25, 0, 2]


def test_native_unbudgeted_checkpoint_remains_fail_fast(tmp_path, monkeypatch):
    from tools import checkpoint_pruning

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    work = tmp_path / "work"
    work.mkdir()
    (work / "package.json").write_text("{}")
    manager = CheckpointManager(enabled=True)
    waits = []

    @contextmanager
    def lock(base, *, wait_seconds=0):
        waits.append(wait_seconds)
        yield

    monkeypatch.setattr(checkpoint_pruning, "store_lock", lock)
    monkeypatch.setattr(manager, "_take", lambda *_: True)
    assert manager.ensure_checkpoint(str(work))
    manager.record_agent_write(str(work / "package.json"))
    assert waits == [0, 0]
