"""A PROFILE subject's permission: ``permission.set(persona_id="profile:<name>")`` (design D2.07 decisions
2, 7, 8; w1015b-con-x). A retired profile conversation's grant is what its adoption copies
(``conversations.migration._preserve_permission``)."""

from __future__ import annotations

import pytest

from agent_runtime.serve_rpc import console_operations as rpc
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT
from agent_runtime.tool_permissions import (
    READ_ONLY_BLOCKS, ChatToolPermissionStore,
)

pytestmark = pytest.mark.timeout(45)


def _set(subject: str, session: str, mode: str = "read_only") -> dict:
    return rpc.permission_set("set", {"persona_id": subject, "session_id": session, "mode": mode,
                                      "reason": "operator"})


def test_permission_set_writes_a_profile_subject_record():
    reply = _set("profile:default", "conversation-1")
    assert "result" in reply, reply
    assert reply["result"]["permission_state"]["mode"] == "read_only"
    assert reply["result"]["permission_state"]["subject"] == "profile:default"
    record = ChatToolPermissionStore().get(persona_id="profile:default", session_id="conversation-1")
    assert record is not None and record.mode == "read_only"


def test_an_unknown_profile_is_refused_and_writes_nothing():
    reply = _set("profile:no-such-profile", "conversation-1")
    assert reply["error"]["code"] == ERR_CONFLICT
    assert "profile not found" in reply["error"]["data"]["error"]
    assert ChatToolPermissionStore().get(persona_id="profile:no-such-profile", session_id="conversation-1") is None


def test_preview_names_the_requested_modes_blocked_tools_without_writing():
    reply = rpc.permission_preview("preview", {"persona_id": "profile:default", "session_id": "conversation-2",
                                               "mode": "read_only"})
    state = reply["result"]["permission_state"]
    assert state["mode"] == "read_only"
    assert set(READ_ONLY_BLOCKS) <= set(state["blocked_tools"])
    assert ChatToolPermissionStore().get(persona_id="profile:default", session_id="conversation-2") is None
