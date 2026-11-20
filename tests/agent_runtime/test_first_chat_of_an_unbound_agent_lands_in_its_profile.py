"""An agent whose chats live in its own profile keeps its FIRST chat there too.

RT-FU-AN-AGENTS-FIRST-CHAT-IS-WRITTEN-TO-THE-SHARED-STORE-NOT-ITS-OWN (review w1118a.59). Seen on disk
2026-11-20 (w1118a-hrun, lane namespace): Neko Mission Lead's record said ``per_profile`` in
``profiles/neko`` with its default chat set, yet that chat's session was in ``profiles/base/state.db``;
Eternia could not reopen it and a teammate's answer to it was dropped (``unknown_chat_session``).

Cause (traced here in a unit): the instance row EXISTED before its first chat (``ensure_for_persona`` mints
one for every persona; a placement mints one too) but was never bound. A turn's store is
``chat_heads.resolve_conversation_chat_scope``, which answered such a row with the process head
(``profiles/base``), while the turn's bind (``open_chat``) stamped the first-bind head — the agent's profile.
A never-bound row now asks ``first_bind_chat_head`` as a missing row does, so both agree.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime.chat_heads import resolve_conversation_chat_scope
from agent_runtime.chat_session_scope import (
    ChatHeadSource,
    SessionDbAccess,
    open_chat_session_db,
    resolve_chat_session_scope,
)
from agent_runtime.models import CHAT_HEAD_KIND_PER_PROFILE
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_assignments.identity import persona_chat_session_id_for


@pytest.fixture
def heads(tmp_path, monkeypatch):
    """``HERMES_HEAD_HOME=profiles/base`` (the serve's); persona ``neko`` runs in profile ``neko``."""

    from agent_runtime import profile_context
    from agent_runtime.config import roster
    from agent_runtime.models import AgentPersona

    root = tmp_path / ".hermes"
    store_root = root / "agent-runtime"
    base = root / "profiles" / "base"
    neko = root / "profiles" / "neko"
    for path in (store_root, base, neko):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(store_root))
    monkeypatch.setenv("HERMES_HOME", str(base))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(base))
    monkeypatch.setattr(profile_context, "profile_exists", lambda name: name == "neko")
    monkeypatch.setattr(profile_context, "get_profile_dir", lambda name: {"neko": neko}[name])
    persona = AgentPersona(id="neko", display_name="Neko", role="lead", model=None, provider=None,
                           api_mode=None, hermes_profile="neko")
    monkeypatch.setattr(roster, "ensure_persisted_personas", lambda *a, **k: [persona])
    return SimpleNamespace(base=base, neko=neko, persona=persona)


def _session_ids(home) -> set[str]:
    from hermes_state import SessionDB

    if not (home / "state.db").is_file():
        return set()
    db = SessionDB(db_path=home / "state.db", read_only=True)
    try:
        return {row["id"] for row in db._read_all("SELECT id FROM sessions", [])}
    finally:
        db.close()


def _first_turn(store: PersonaInstanceStore, instance_id: str) -> str:
    """The turn's order: resolve and open its store (``chat_turn_message``), bind, then ensure its root in
    that store (``admit._bind_instance``: ``open_chat``, then the chat-session ensure)."""

    root = persona_chat_session_id_for(instance_id)
    scope = resolve_conversation_chat_scope(persona_instance_id=instance_id, instance_store=store)
    db = open_chat_session_db(scope, access=SessionDbAccess.WRITE)
    try:
        store.open_chat(persona_id="neko", persona_instance_id=instance_id, session_id=root)
        db.ensure_session(root, source="persona_chat")
    finally:
        db.close()
    return root


def test_an_existing_never_bound_agents_first_chat_is_in_its_own_profile(heads):
    """KILLING MUTATION (run 2026-11-20): ``resolve_conversation_chat_scope`` answering every existing
    row through ``resolve_instance_chat_scope`` (the ``_never_bound`` test dropped) -> the root is in
    ``profiles/base`` while the record says ``profiles/neko``, red."""

    store = PersonaInstanceStore()
    instance = store.ensure_for_persona(heads.persona)
    assert not instance.default_chat_session_id and not instance.chat_head_home

    root = _first_turn(store, instance.id)

    bound = store.get(instance.id)
    assert (bound.chat_head_kind, bound.chat_head_home) == (CHAT_HEAD_KIND_PER_PROFILE, str(heads.neko))
    assert root in _session_ids(heads.neko)
    assert root not in _session_ids(heads.base)
    scope = resolve_chat_session_scope(session_id=root)
    assert (scope.head_home, scope.source) == (heads.neko, ChatHeadSource.INSTANCE_RECORDED)


def test_positive_control_a_never_bound_agent_with_a_legacy_chat_in_base_stays_on_base(heads):
    """Same turn, one variable changed: base holds a session naming the instance, so the first bind
    stays ``process`` and the turn writes base too."""

    from hermes_state import SessionDB

    store = PersonaInstanceStore()
    instance = store.ensure_for_persona(heads.persona)
    db = SessionDB(db_path=heads.base / "state.db")
    try:
        db.create_session(session_id="legacy_opaque_chat", source="mission_control", model=None,
                          model_config={"persona_instance_id": instance.id})
    finally:
        db.close()

    root = _first_turn(store, instance.id)

    bound = store.get(instance.id)
    assert bound.chat_head_kind != CHAT_HEAD_KIND_PER_PROFILE
    assert root in _session_ids(heads.base)
    assert root not in _session_ids(heads.neko)


def test_a_bound_agents_scope_is_still_its_record(heads):
    """An instance already bound answers its record, never a fresh first-bind guess."""

    store = PersonaInstanceStore()
    instance = store.ensure_for_persona(heads.persona)
    root = _first_turn(store, instance.id)

    scope = resolve_conversation_chat_scope(session_id=root, instance_store=store)
    assert (scope.head_home, scope.source) == (heads.neko, ChatHeadSource.INSTANCE_RECORDED)
    assert scope.instance_head is not None and scope.instance_head.instance_id == instance.id
