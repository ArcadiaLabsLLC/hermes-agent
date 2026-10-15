"""Every chat ``SessionDB`` acquisition declares READ or WRITE, and a READ never creates the store.

Runtime-queue row (lane W3-D follow-up): the read door created an ABSENT store
with a writer open, because ``None`` there would have dropped bound sessions
unaccounted. Now a READ answers ``None`` for an absent store, and the history
projection accounts each bound session in it as ``session_db_absent``.
"""

from __future__ import annotations

import pytest

from agent_runtime import chat_session_scope
from agent_runtime.chat_session_scope import (
    SESSION_DB_ABSENT,
    ChatHeadSource,
    ChatSessionScope,
    SessionDbAccess,
    open_chat_session_db,
)
from agent_runtime.persona_chat_history import persona_chat_history_summary
from agent_runtime.projection_accountant import ProjectionAccountant


@pytest.fixture
def scope(tmp_path, monkeypatch):
    home = tmp_path / "head"
    home.mkdir()
    resolved = ChatSessionScope(head_home=home, source=ChatHeadSource.ENV_HEAD_HOME)
    monkeypatch.setattr(chat_session_scope, "resolve_process_chat_scope", lambda: resolved)
    return resolved


def test_the_access_is_declared_or_the_call_is_refused(scope):
    with pytest.raises(TypeError):
        open_chat_session_db(scope)  # type: ignore[call-arg]


def test_a_read_of_an_absent_store_creates_nothing_and_a_write_creates_it(scope):
    """*Killing mutation:* drop the ``read and not _store_exists`` early return."""

    assert open_chat_session_db(scope, access=SessionDbAccess.READ) is None
    assert not scope.db_path.exists(), "a READ created the store"
    # Positive control: the same door, WRITE, does create it — and a READ now attaches.
    writer = open_chat_session_db(scope, access=SessionDbAccess.WRITE)
    assert writer is not None and scope.db_path.is_file()
    writer.close()
    reader = open_chat_session_db(scope, access=SessionDbAccess.READ)
    assert reader is not None
    reader.close()


def test_a_bound_session_in_an_absent_store_is_a_typed_drop(scope, isolate_agent_runtime_root):
    """*Killing mutation:* drop ``summary.account_absent_store()`` — the bound
    session vanishes from the projection with no reason recorded."""

    from agent_runtime.persona_assignments import PersonaInstanceStore

    bound = PersonaInstanceStore().open_chat(persona_id="dev", session_id="chat_bound")
    accountant = ProjectionAccountant("persona_chat_history")

    rows = persona_chat_history_summary(persona_instances=[bound], accountant=accountant)

    assert rows == []
    assert not scope.db_path.exists(), "the projection's read created the store"
    summary = accountant.summary()
    assert summary["reasons"] == {SESSION_DB_ABSENT: 1}, summary
    assert SESSION_DB_ABSENT not in summary["by_design"]


def test_a_present_store_missing_the_row_is_still_session_not_in_db(scope, isolate_agent_runtime_root):
    """Positive control: the absent-store drop is not the only drop the capture sees."""

    from agent_runtime.persona_assignments import PersonaInstanceStore

    open_chat_session_db(scope, access=SessionDbAccess.WRITE).close()
    bound = PersonaInstanceStore().open_chat(persona_id="dev", session_id="chat_bound")
    accountant = ProjectionAccountant("persona_chat_history")

    persona_chat_history_summary(persona_instances=[bound], accountant=accountant)

    assert accountant.summary()["reasons"] == {"session_not_in_db": 1}
