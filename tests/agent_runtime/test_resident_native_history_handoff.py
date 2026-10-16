"""A resident actor hands its stamped history to the next turn only while the stamp holds (lineage-stamp S3)."""
from __future__ import annotations

from hermes_state import SessionDB

from agent_runtime.persona_chat_continuity.runtime_registry import PersonaChatRuntimeRegistry
from agent_runtime.persona_chat_session import _persona_chat_native_history, _persona_chat_native_read
from agent_runtime.session_lineage_stamp import lineage_stamp


class _Actor:
    def close(self):
        pass


def _chain(db):
    db.create_session("root", source="tui")
    db.append_message("root", "user", "the start")
    db.append_message("root", "assistant", "first answer")
    db.end_session("root", "compression")
    db.create_session("tip", source="tui", parent_session_id="root")
    db.append_message("tip", "user", "continued")
    db.append_message("tip", "assistant", "second answer")


def _resident(db):
    registry = PersonaChatRuntimeRegistry()
    registry.acquire(root_session_id="root", active_session_id="tip", signature="s", revision="r",
                     factory=_Actor)
    stamp, tip, history = _persona_chat_native_read(db, "root")
    registry.finish("root", active_session_id=tip, revision="r", native_snapshot=(stamp, tip, history))
    return registry


def test_an_unchanged_lineage_hands_over_exactly_what_a_fresh_read_returns(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    _chain(db)
    registry = _resident(db)
    reused = registry.resident_native_history("root", stamp=lineage_stamp(db, "root"))
    assert reused is not None
    assert reused == ("tip", _persona_chat_native_history(db, "tip"))
    reused[1].append({"role": "user", "content": "turn-local"})
    again = registry.resident_native_history("root", stamp=lineage_stamp(db, "root"))
    assert again[1] == _persona_chat_native_history(db, "tip")
    db.close()


def test_a_repaired_ancestor_between_turns_forces_a_fresh_read(tmp_path):
    """Killing mutation: compare only ``stamp.tip`` -> the stale ancestor text is handed over."""
    db = SessionDB(tmp_path / "state.db")
    _chain(db)
    registry = _resident(db)
    root_user = next(m["id"] for m in db.get_messages("root") if m["role"] == "user")
    assert db.set_user_message_content("root", root_user, "repaired start") == 1
    assert registry.resident_native_history("root", stamp=lineage_stamp(db, "root")) is None
    db.close()


def test_a_write_racing_the_read_can_never_be_vouched_for(tmp_path):
    """The stamp is taken BEFORE the read: a write landing after the read leaves the stored stamp older."""
    db = SessionDB(tmp_path / "state.db")
    _chain(db)
    lineage_stamp(db, "root")  # install first, so the race below is the only write
    original = db.get_messages_as_conversation

    def read_then_race(*args, **kwargs):
        result = original(*args, **kwargs)
        db.append_message("tip", "user", "landed after the read")
        return result

    db.get_messages_as_conversation = read_then_race
    stamp, _, history = _persona_chat_native_read(db, "root")
    db.get_messages_as_conversation = original
    assert all(m.get("content") != "landed after the read" for m in history)
    assert stamp != lineage_stamp(db, "root")
    db.close()


def test_no_stamp_never_reuses():
    registry = PersonaChatRuntimeRegistry()
    registry.acquire(root_session_id="root", active_session_id="tip", signature="s", revision="r",
                     factory=_Actor)
    registry.finish("root", active_session_id="tip", revision="r", native_snapshot=(None, "tip", []))
    assert registry.resident_native_history("root", stamp=None) is None
