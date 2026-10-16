"""A real native compaction carrier must not offer an incomplete branch."""
from contextlib import closing

import pytest

from hermes_state import SessionDB
from tests.agent_runtime.test_operator_conversation_attachment import call, fixture
from tests.hermes_state.test_composite_carrier_rewind import _carrier


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("carrier", [False, True])
def test_branch_preview_refuses_incomplete_lineage_and_compaction_carriers(tmp_path, monkeypatch, compressed, carrier):
    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    root = target["session_id"]
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        db.clear_messages(root)
        tip = root
        if compressed:
            db.append_message(root, "user", "earlier work")
            db.end_session(root, "compression")
            tip = "compressed-child"
            db.create_session(tip, source="agent_runtime_persona_chat", parent_session_id=root)
        prompt = _carrier("Continue the review") if carrier else "Continue the review"
        row_id = db.append_message(tip, "user", prompt)
        db.append_message(tip, "assistant", "Review complete")
        before = db.get_messages(tip)
        assert db.resolve_resume_session_id(root) == tip
    reply = call("history.preview", {**target, "action": "branch", "row_id": row_id})
    if carrier:
        assert reply["error"]["data"]["reason"] == "target_requires_compaction_review"
    elif compressed:
        assert reply["error"]["data"]["reason"] == "branch_compressed_history_unavailable"
    else:
        assert reply["result"]["draft"] == "Continue the review"
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        assert db.get_messages(tip) == before
