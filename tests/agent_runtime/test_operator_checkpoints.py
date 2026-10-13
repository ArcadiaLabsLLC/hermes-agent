"""The real RPC resolves one chat's workspace/profile and restores only its files."""
from contextlib import closing
from types import SimpleNamespace
import sys

from hermes_state import SessionDB
from tools.checkpoint_manager import CheckpointManager
from tests.agent_runtime.test_operator_conversation_attachment import call, fixture


def test_rpc_checkpoint_round_trip_is_workspace_pinned(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    from agent_runtime.models import AgentPersona
    from agent_runtime.store import AgentStore
    AgentStore().save(AgentPersona(id="builder", display_name="Builder", role="builder",
        model=None, provider=None, api_mode=None, system_prompt_path=""))
    work = tmp_path / "work"
    work.mkdir()
    (work / "package.json").write_text("{}")
    path = work / "change.txt"
    path.write_text("before")
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        db.update_session_cwd(target["session_id"], str(work))
    manager = CheckpointManager(enabled=True)
    assert manager.ensure_checkpoint(str(work))
    path.write_text("after")
    manager.record_agent_write(str(path))
    listed = call("checkpoints", target)
    assert "result" in listed, listed
    assert listed["result"]["workspace_path"] == str(work.resolve())
    checkpoint = listed["result"]["checkpoints"][0]["hash"]
    preview = call("checkpoint.preview", {**target, "checkpoint": checkpoint})
    assert "result" in preview, preview
    params = {**target, "checkpoint": checkpoint, "revision": preview["result"]["revision"],
              "selected_paths": ["change.txt"], "operation_id": "rpc-restore-operation-one",
              "workspace_path": str(work.resolve())}
    refused = call("checkpoint.restore", {**params, "workspace_path": str(tmp_path)})
    assert refused["error"]["data"]["reason"] == "workspace_changed"
    applied = call("checkpoint.restore", params)
    assert "result" in applied, applied
    assert applied["result"]["success"], applied
    assert path.read_text() == "before"
    assert call("checkpoint.status", params)["result"]["result"]["success"]
    assert call("checkpoint.restore", params)["result"]["replayed"]


def test_factory_uses_native_profile_checkpoint_settings(tmp_path, monkeypatch):
    from agent_runtime.profile_runner.runner import _default_agent_factory
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    (home / "config.yaml").write_text("checkpoints:\n  enabled: false\n  max_snapshots: 7\n  max_file_size_mb: 3\n")
    seen = []
    monkeypatch.setitem(sys.modules, "run_agent", SimpleNamespace(AIAgent=lambda **kw: (seen.append(kw) or SimpleNamespace())))
    monkeypatch.setattr("agent_runtime.chat_lane_tool_form.apply_chat_lane_defer", lambda *a, **k: None)
    _default_agent_factory(model="test")
    assert seen[0]["checkpoints_enabled"] is False
    assert seen[0]["checkpoint_max_snapshots"] == 7
    assert seen[0]["checkpoint_max_file_size_mb"] == 3
