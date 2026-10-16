"""A compaction carrier is refused; a compressed lineage branches whole (branch-across-compressed-ancestry)."""
from contextlib import closing

import pytest

from hermes_state import SessionDB
from tests.agent_runtime.test_operator_conversation_attachment import call, fixture
from tests.hermes_state.test_composite_carrier_rewind import _carrier


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("carrier", [False, True])
def test_branch_preview_offers_compressed_lineage_and_refuses_compaction_carriers(tmp_path, monkeypatch, compressed, carrier):
    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    root = target["session_id"]
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        db.clear_messages(root)
        tip = root
        if compressed:
            db.append_message(root, "user", "earlier work")
            db.append_message(root, "assistant", "earlier answer")
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
    else:
        assert "result" in reply, reply
        assert reply["result"]["draft"] == "Continue the review"
        assert reply["result"]["earlier_turns"] == (1 if compressed else 0)
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        assert db.get_messages(tip) == before


def test_branch_apply_on_a_compressed_chat_copies_the_ancestor_turns(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Amelia")
    root = target["session_id"]
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        db.clear_messages(root)
        db.append_message(root, "user", "earlier work")
        db.append_message(root, "assistant", "earlier answer")
        db.end_session(root, "compression")
        db.create_session("compressed-child", source="agent_runtime_persona_chat", parent_session_id=root)
        row_id = db.append_message("compressed-child", "user", "Continue the review")
        db.append_message("compressed-child", "assistant", "Review complete")
        before = {sid: db.get_messages(sid) for sid in (root, "compressed-child")}
    plan = call("history.preview", {**target, "action": "branch", "row_id": row_id})["result"]
    applied = call("history.apply", {**target, "action": "branch", "row_id": plan["row_id"],
                                     "preview_token": plan["preview_token"], "operation_id": "compressed-branch-one"})
    assert "result" in applied, applied
    child = applied["result"]["result_session_id"]
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        assert [(m["role"], m["content"]) for m in db.get_messages(child)] == [
            ("user", "earlier work"), ("assistant", "earlier answer")]
        assert {sid: db.get_messages(sid) for sid in before} == before
        assert db.resolve_resume_session_id(root) == "compressed-child"
