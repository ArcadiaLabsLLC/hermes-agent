"""Catalog identities survive branch apply, lost replies and legacy history."""
from contextlib import closing

import pytest

from hermes_state import SessionDB
from agent_runtime.persona_chat_history.vocabulary import canonical_chat_persona_id
from tests.agent_runtime.test_operator_conversation_attachment import call, fixture


@pytest.mark.parametrize("spelling", ["profile_audit", "profile:audit"])
def test_history_profile_identity_uses_catalog_spelling(spelling):
    assert canonical_chat_persona_id(spelling) == "profile_audit"


def test_profile_branch_apply_status_replay_and_origin_match_catalog(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Audit", persona_id="profile_audit")
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        row_id = db.get_messages(target["session_id"])[4]["id"]
    preview = call("history.preview", {**target, "action": "branch", "row_id": row_id})
    assert "result" in preview, preview
    request = {**target, "action": "branch", "row_id": row_id,
               "operation_id": "profile-branch-operation", "preview_token": preview["result"]["preview_token"]}
    applied = call("history.apply", request)
    assert "result" in applied, applied
    child = applied["result"]["result_session_id"]
    status = call("history.status", request)
    assert status["result"]["state"] == "applied", status
    for response in (applied, {"result": status["result"]["result"]}, call("history.apply", request)):
        assert "result" in response, response
        result = response["result"]
        assert result["branch"]["persona_id"] == target["persona_id"]
        assert result["branch"]["persona_instance_id"] == target["persona_instance_id"]
        assert result["result_session_id"] == child
    origin = call("history.origin", {**target, "session_id": child})
    assert "result" in origin, origin
    assert origin["result"]["origin"]["persona_id"] == target["persona_id"]
