"""RT-CHAT-HEAD-CH2C-FIRST-BIND-STAMP — a never-bound instance's first bind stamps ``per_profile``.

Plan: ``docs/agent-runtime-harness/planned/chat-head-per-profile-2026-10-26.md``
§7.2 decision 8 (a); test plan §7.4 (CH2C).
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from agent_runtime.chat_session_scope import ChatHeadSource, resolve_chat_session_scope
from agent_runtime.models import CHAT_HEAD_KIND_PER_PROFILE
from agent_runtime.persona_assignments import PersonaInstanceStore

INSTANCE_ID = "personainst_qa_agent_c0ffee00"
SESSION_ID = "persona_chat_personainst_qa_agent_c0ffee00"


@pytest.fixture
def heads(tmp_path, monkeypatch):
    """``HERMES_HEAD_HOME=profiles/base``; persona ``qa`` runs in profile ``alice``."""

    import agent_runtime.config.roster as roster
    import agent_runtime.profile_context as profile_context

    root = tmp_path / ".hermes"
    store_root = root / "agent-runtime"
    base = root / "profiles" / "base"
    alice = root / "profiles" / "alice"
    for path in (store_root, base, alice):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(store_root))
    monkeypatch.setenv("HERMES_HOME", str(base))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(base))
    monkeypatch.setattr(profile_context, "profile_exists", lambda name: name == "alice")
    monkeypatch.setattr(profile_context, "get_profile_dir", lambda name: {"alice": alice}[name])
    persona = SimpleNamespace(id="qa", hermes_profile="alice")
    monkeypatch.setattr(roster, "ensure_persisted_personas", lambda *a, **k: [persona])
    return SimpleNamespace(base=base, alice=alice, persona=persona)


def _base_session(heads, session_id: str, model_config: dict) -> None:
    from hermes_state import SessionDB

    db = SessionDB(db_path=heads.base / "state.db")
    try:
        db.create_session(session_id=session_id, source="mission_control", model=None,
                          model_config=model_config)
    finally:
        db.close()


def _session_ids(home) -> set[str]:
    from hermes_state import SessionDB

    if not (home / "state.db").is_file():
        return set()
    db = SessionDB(db_path=home / "state.db", read_only=True)
    try:
        return {row["id"] for row in db._read_all("SELECT id FROM sessions", [])}
    finally:
        db.close()


def test_the_first_bind_of_a_fresh_instance_stamps_its_profile_home(heads):
    _base_session(heads, "someone_elses_chat", {"persona_instance_id": "personainst_other_1"})

    instance = PersonaInstanceStore().open_chat(
        persona_id="qa", session_id=SESSION_ID, persona_instance_id=INSTANCE_ID
    )

    assert instance.chat_head_kind == CHAT_HEAD_KIND_PER_PROFILE
    assert instance.chat_head_home == str(heads.alice)
    scope = resolve_chat_session_scope(session_id=SESSION_ID)
    assert (scope.head_home, scope.source) == (heads.alice, ChatHeadSource.INSTANCE_RECORDED)


def test_a_never_bound_legacy_instance_with_a_session_in_base_stays_process(heads):
    """Same bind, one variable changed: base holds a session whose meta names the instance."""

    _base_session(heads, "legacy_opaque_chat", {"persona_instance_id": INSTANCE_ID})

    instance = PersonaInstanceStore().open_chat(
        persona_id="qa", session_id=SESSION_ID, persona_instance_id=INSTANCE_ID
    )

    assert instance.chat_head_kind != CHAT_HEAD_KIND_PER_PROFILE
    assert instance.chat_head_home == str(heads.base)


def test_binding_a_session_that_lives_in_base_stays_process(heads):
    _base_session(heads, "opaque_root_in_base", {"persona_id": "qa"})

    instance = PersonaInstanceStore().open_chat(
        persona_id="qa", session_id="opaque_root_in_base", persona_instance_id=INSTANCE_ID
    )

    assert instance.chat_head_home == str(heads.base)


def test_a_rebind_of_an_already_bound_process_instance_never_stamps_per_profile(heads):
    store = PersonaInstanceStore()
    _base_session(heads, "legacy_opaque_chat", {"persona_instance_id": INSTANCE_ID})
    store.open_chat(persona_id="qa", session_id=SESSION_ID, persona_instance_id=INSTANCE_ID)
    with sqlite3.connect(heads.base / "state.db") as conn:
        conn.execute("DELETE FROM sessions")

    again = store.open_chat(persona_id="qa", session_id=SESSION_ID, persona_instance_id=INSTANCE_ID)

    assert again.chat_head_home == str(heads.base)


def test_a_created_agent_mints_its_root_in_its_profile_and_none_in_base(heads):
    instance = PersonaInstanceStore().create_operator_chat(persona_id="qa", display_name="QA")

    root = instance.default_chat_session_id
    assert instance.chat_head_kind == CHAT_HEAD_KIND_PER_PROFILE
    assert root in _session_ids(heads.alice)
    assert root not in _session_ids(heads.base)


def test_positive_control_a_persona_that_inherits_the_process_profile_mints_in_base(heads):
    heads.persona.hermes_profile = None

    instance = PersonaInstanceStore().create_operator_chat(persona_id="qa", display_name="QA")

    root = instance.default_chat_session_id
    assert instance.chat_head_kind != CHAT_HEAD_KIND_PER_PROFILE
    assert instance.chat_head_home == str(heads.base)
    assert root in _session_ids(heads.base)
    assert root not in _session_ids(heads.alice)
