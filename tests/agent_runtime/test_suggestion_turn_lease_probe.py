"""The suggestion context's read-only turn-lease probe (moved out of upstream's
``hermes_state_compression`` into ``agent_runtime/persona_chat_history/suggestion_context.py``)."""

from __future__ import annotations

from contextlib import closing

from agent_runtime.persona_chat_history.suggestion_context import _session_turn_is_active
from hermes_state import SessionDB


def test_the_probe_reads_a_live_lease_and_never_claims_one(tmp_path):
    with closing(SessionDB(db_path=tmp_path / "state.db")) as db:
        db.create_session(session_id="s1", source="cli")
        assert _session_turn_is_active(db, "s1") is False
        assert db.try_acquire_session_turn_lease("s1", "holder-a", ttl_seconds=60)
        assert _session_turn_is_active(db, "s1") is True
        db.release_session_turn_lease("s1", "holder-a")
        assert _session_turn_is_active(db, "s1") is False
        # Probing claimed nothing: another holder still acquires at once.
        assert db.try_acquire_session_turn_lease("s1", "holder-b", ttl_seconds=60)


def test_an_expired_lease_is_not_active(tmp_path):
    with closing(SessionDB(db_path=tmp_path / "state.db")) as db:
        db.create_session(session_id="s2", source="cli")
        assert db.try_acquire_session_turn_lease("s2", "holder-a", ttl_seconds=0.1)
        with db._read_ctx() as conn:
            key = db._session_turn_lease_key_on_conn(conn, "s2")
        db._execute_write(lambda conn: conn.execute(
            "UPDATE session_turn_leases SET expires_at = 0 WHERE conversation_id = ?", (key,)))
        assert _session_turn_is_active(db, "s2") is False
