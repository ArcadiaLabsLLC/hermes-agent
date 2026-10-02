"""Owned sessions retain their native directory; console policy stays unchanged."""
from contextlib import closing
from pathlib import Path

import pytest

from agent_runtime import paths
from agent_runtime.conversation_workspace import pinned_conversation_workdir
from agent_runtime.persona_chat_durability import default_persona_session_db
from agent_runtime.persona_chat_history.messages import existing_persona_chat_messages
from tests.agent_runtime.test_instance_conversation_owner import OWNER, chat_head, open_params
from tests.agent_runtime.test_serve_rpc_open_chat import _call, qa_persona, placed_agent


def test_owned_mint_pins_native_workspace_and_retry_preserves_it(placed_agent, qa_persona):
    from agent_runtime.chat_lane_scope import apply_chat_lane_tool_scope
    from agent_runtime.tool_permissions import permission_options_for_chat

    params = open_params(placed_agent)
    opened = _call(params)["result"]
    session = opened["session_id"]
    with closing(default_persona_session_db()) as db:
        cwd = pinned_conversation_workdir(db, session)
        assert Path(cwd).is_dir()
        assert Path(cwd).parent == paths.store_root() / "conversation-workspaces"
    read = existing_persona_chat_messages(session_id=session, client_scope=OWNER)
    assert read["workspace"] == {"id": session, "path": cwd, "name": "Conversation files"}
    options = permission_options_for_chat(qa_persona, session_id=session)
    preview = apply_chat_lane_tool_scope(qa_persona, options, session_id=session)
    assert preview.mission_chat_workdir.path == cwd
    assert _call(params)["result"]["session_id"] == session
    with closing(default_persona_session_db()) as db:
        assert pinned_conversation_workdir(db, session) == cwd
    Path(cwd).rmdir()  # Empty directory created by this test only.
    with closing(default_persona_session_db()) as db:
        with pytest.raises(ValueError, match="workspace is unavailable"):
            pinned_conversation_workdir(db, session)


def test_native_console_mint_retains_its_existing_workdir_policy(placed_agent):
    params = open_params(placed_agent)
    params.pop("client_scope")
    session = _call(params)["result"]["session_id"]
    with closing(default_persona_session_db()) as db:
        assert pinned_conversation_workdir(db, session) is None
    assert not (paths.store_root() / "conversation-workspaces").exists()
