"""``branch_before_message`` copies the whole visible prefix across native compressed ancestry.

Plan: docs/agent-runtime-harness/archive/branch-across-compressed-ancestry-2026-10-15.md (S1-S4).
"""
from __future__ import annotations

import pytest

from hermes_state import SessionDB
from hermes_state_history_controls import HistoryControlError


def _branch(db, root, target_id, child="child", *, revision=None, after_reply=False):
    revision = db.branch_history_revision(root) if revision is None else revision
    return db.branch_before_message(
        root, target_id, child_session_id=child, expected_history_digest=revision,
        operation_receipt=(f"receipt-{child}", "{}"), model_config={"_branched_from": root},
        title="Branch", after_reply=after_reply)


def _rotate(db, parent, child):
    db.end_session(parent, "compression")
    db.create_session(child, source="tui", parent_session_id=parent)


def _pairs(db, session_id):
    return [(m["role"], m["content"], m.get("tool_call_id")) for m in db.get_messages(session_id)]


def _display_prefix(db, root, before_id):
    tip = db.resolve_resume_session_id(root)
    display = db.get_messages_as_conversation(tip, include_ancestors=True, include_compacted=True,
                                              include_row_ids=True)
    cut = next(i for i, m in enumerate(display) if m["_row_id"] == before_id)
    return [(m["role"], m["content"], m.get("tool_call_id")) for m in display[:cut]]


@pytest.fixture
def db(tmp_path):
    store = SessionDB(tmp_path / "state.db")
    yield store
    store.close()


def _two_session_chat(db):
    db.create_session("root", source="tui")
    db.append_message("root", "user", "first ask")
    db.append_message("root", "assistant", "first answer")
    in_root = db.append_message("root", "user", "second ask")
    db.append_message("root", "assistant", "second answer")
    _rotate(db, "root", "tip")
    in_tip = db.append_message("tip", "user", "third ask")
    db.append_message("tip", "assistant", "third answer")
    return in_root, in_tip


def test_s1_target_in_the_tip_copies_the_ancestor_rows_too(db):
    """Killing mutation: read only the tip's rows (today's code) -> the root's turns are missing."""
    _, in_tip = _two_session_chat(db)
    expected = _display_prefix(db, "root", in_tip)
    _branch(db, "root", in_tip)
    assert _pairs(db, "child") == expected
    assert [c for _, c, _ in expected] == ["first ask", "first answer", "second ask", "second answer"]


def test_s1_target_in_an_ancestor_cuts_inside_the_ancestor(db):
    in_root, _ = _two_session_chat(db)
    _branch(db, "root", in_root)
    assert [c for _, c, _ in _pairs(db, "child")] == ["first ask", "first answer"]


def test_s1_after_reply_includes_the_reply(db):
    _two_session_chat(db)
    reply = next(m["id"] for m in db.get_messages("root") if m["content"] == "second answer")
    _branch(db, "root", reply, after_reply=True)
    assert [c for _, c, _ in _pairs(db, "child")][-1] == "second answer"


def test_s1_a_row_outside_the_lineage_is_refused(db):
    _two_session_chat(db)
    db.create_session("other", source="tui")
    foreign = db.append_message("other", "user", "not this chat")
    with pytest.raises(HistoryControlError, match="target_unavailable"):
        _branch(db, "root", foreign)
    assert db.get_session("child") is None


def test_s2_an_ancestor_edit_after_the_preview_refuses(db):
    """Killing mutation: pin only the tip's rows -> the edited ancestor branches anyway."""
    in_root, in_tip = _two_session_chat(db)
    revision = db.branch_history_revision("root")
    assert db.set_user_message_content("root", in_root, "second ask, edited") == 1
    with pytest.raises(HistoryControlError, match="history_changed"):
        _branch(db, "root", in_tip, revision=revision)
    assert db.get_session("child") is None


def test_s2_a_rotation_after_the_preview_refuses(db):
    _, in_tip = _two_session_chat(db)
    revision = db.branch_history_revision("root")
    _rotate(db, "tip", "tip2")
    db.append_message("tip2", "user", "fourth ask")
    with pytest.raises(HistoryControlError, match="history_changed"):
        _branch(db, "root", in_tip, revision=revision)
    assert db.get_session("child") is None


def test_s3_a_tool_result_cloned_into_the_tip_stays_with_its_call(db):
    """The result's live copy sits in the tip with an id ABOVE the target's.

    Killing mutation: cut by row id instead of display position -> the result is dropped.
    """
    db.create_session("root", source="tui")
    db.append_message("root", "user", "inspect it")
    calls = [{"id": "c1", "type": "function", "function": {"name": "inspect", "arguments": "{}"}}]
    db.append_message("root", "assistant", None, tool_calls=calls)
    result = db.append_message("root", "tool", "inspected", tool_call_id="c1", tool_name="inspect")
    target = db.append_message("root", "user", "now summarise")
    db.append_message("root", "assistant", "summary")
    _rotate(db, "root", "tip")
    db._execute_write(lambda conn: db._clone_message_rows(conn, [result], session_id="tip"))
    db.append_message("tip", "user", "later")
    clone = max(m["id"] for m in db.get_messages("tip") if m["role"] == "tool")
    assert clone > target  # the fixture really puts the representative after the target by id
    _branch(db, "root", target)
    copied = _pairs(db, "child")
    assert copied == [("user", "inspect it", None), ("assistant", None, None), ("tool", "inspected", "c1")]
    assert db.get_messages("child")[1]["tool_calls"][0]["id"] == "c1"


def test_s3_a_cut_that_would_orphan_a_result_is_refused(db):
    db.create_session("root", source="tui")
    db.append_message("root", "user", "inspect it")
    calls = [{"id": "c1", "type": "function", "function": {"name": "inspect", "arguments": "{}"}}]
    db.append_message("root", "assistant", None, tool_calls=calls)
    stray = db.append_message("root", "user", "interjection")
    db.append_message("root", "tool", "inspected", tool_call_id="c1", tool_name="inspect")
    with pytest.raises(HistoryControlError, match="target_unavailable"):
        _branch(db, "root", stray)


def test_s4_sources_are_untouched_and_the_child_never_joins_the_lineage(db):
    """Killing mutation: child parented on the tip -> its ``_branched_from`` marker no longer names its
    parent, so SessionDB stops recognising it as an explicit fork (the exemption every lineage walk relies on)."""
    _, in_tip = _two_session_chat(db)
    before = {sid: db.get_messages(sid, include_inactive=True) for sid in ("root", "tip")}
    revision = db.branch_history_revision("root")
    _branch(db, "root", in_tip)
    assert db.branch_history_revision("root") == revision
    assert {sid: db.get_messages(sid, include_inactive=True) for sid in before} == before
    assert db.resolve_resume_session_id("root") == "tip"
    assert db._resume_lineage_ids("tip") == ["root", "tip"]
    assert db._resume_lineage_ids("child") == ["child"]
    assert db.is_explicit_fork_child("child")
    assert db.get_session("child")["parent_session_id"] == "root"
    with db._read_ctx() as conn:
        flags = conn.execute("SELECT active, compacted FROM messages WHERE session_id = 'child'").fetchall()
    assert flags and all(tuple(f) == (1, 0) for f in flags)
