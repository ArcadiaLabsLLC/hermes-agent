"""Real harness dispatcher, stores and native child registry; no model calls."""
from contextlib import closing
from types import SimpleNamespace
import json

import pytest

from agent_runtime import serve_rpc
from agent_runtime.call_authorization import UNKNOWN_CALLER
from agent_runtime.persona_chat_durability import default_persona_session_db
from tools.delegate_tool_child_run import _register_child
from tools.delegate_tool_registry import _unregister_subagent
from tools.delegation_live_log import LiveTranscriptWriter
from tests.agent_runtime.test_operator_session_inspection import target, inspect
from tests.agent_runtime.test_serve_rpc_open_chat import qa_persona, placed_agent, _device
from tests.agent_runtime.test_instance_conversation_owner import chat_head, OTHER
from tests.agent_runtime.test_subagent_worker_ownership import Child


def test_operator_children_remain_private_to_exact_conversation(placed_agent, tmp_path):
    params = target(placed_agent["persona_instance_id"])
    child = Child("owned-child")
    with closing(default_persona_session_db()) as db:
        from pathlib import Path
        child._session_db = db
        child.logs_dir = Path(db.db_path).parent / "sessions"
        parent = SimpleNamespace(session_id=params["session_id"])
        _register_child(child, parent, "owned work", owner_session_id=None,
                        owner_transport=None, owner_session_record=None)
        writer = LiveTranscriptWriter("owned", 0, "task", root=tmp_path)
        writer.assistant_text("owned output")
        child._live_transcript_path = str(writer.path)
        try:
            result = inspect("subagents.list", params)
            assert "result" in result, result
            roster = result["result"]
            assert [row["subagent_id"] for row in roster["children"]] == ["owned-child"]
            selected = {**params, "child_ref": roster["children"][0]["child_ref"],
                        "expected_generation": roster["generation"]}
            tail = inspect("subagents.tail", selected)["result"]
            assert "owned output" in tail["text"]
            capture = {"capabilities": inspect("subagents.capabilities", params)["result"],
                       "list": roster, "tail": tail}
            (tmp_path / "subagent-read-capture.json").write_text(json.dumps(capture, indent=2), encoding="utf-8")
            for key, value in (("install_id", "other"), ("workspace_id", "other"),
                               ("persona_id", "other"), ("persona_instance_id", "other"),
                               ("session_id", "other"), ("client_scope", OTHER)):
                assert "error" in inspect("subagents.list", {**params, key: value})
                assert "error" in inspect("subagents.tail", {**selected, key: value})
            for caller in (_device("read"), UNKNOWN_CALLER):
                assert "error" in inspect("subagents.list", params, caller)
            child.logs_dir = tmp_path / "other-profile" / "sessions"
            assert inspect("subagents.list", params)["result"]["children"] == []
            assert "error" in inspect("subagents.tail", selected)
        finally:
            _unregister_subagent("owned-child", agent=child)


def test_manifest_discovers_only_implemented_console_private_operations():
    manifest = serve_rpc.manifest()
    for family in ("runtime.conversation", "runtime.operator.conversation"):
        for operation in ("capabilities", "list", "tail"):
            name = f"{family}.subagents.{operation}"
            assert name in manifest["methods"]
            assert manifest["tiers"][name] == "console"
            assert "expected_generation" in manifest["params"][name]
        assert f"{family}.subagents.stop" not in manifest["methods"]
