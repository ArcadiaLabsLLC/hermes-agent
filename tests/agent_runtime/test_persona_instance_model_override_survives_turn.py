"""An instance model override survives a turn that loaded the row before it.

Live 2026-10-01 (``personainst_dev_agent_8b319ebf``): set-model gpt-6-luna at
19:43:01Z, inside a turn admitted at 19:40:41Z. The turn's settle wrote its
admission-time copy of the row back at 19:54:36Z, the override was gone, and
nothing in the event log said so.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime.events import EventLog
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.states import WorkerSessionState
from hermes_cli.harness_parts.persona.chat_turn_commit.settle import _SettlePhases

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")


def _chat_instance(store: PersonaInstanceStore):
    return store.create_operator_chat(
        persona_id="profile:alice", display_name="Alice Agent", session_id="chat_alice"
    )


def _patched_fields(event_log: EventLog, instance_id: str) -> list[dict]:
    return [
        event.payload.get("changed") or {}
        for event in event_log.tail(10_000)
        if event.type == "state.patched" and event.payload.get("id") == instance_id
    ]


def test_turn_settle_does_not_revert_a_model_pick_made_mid_turn(isolate_agent_runtime_root):
    store = PersonaInstanceStore()
    instance = _chat_instance(store)
    admitted_copy = store.get(instance.id)  # the turn's admission-time row

    store.update_profile(instance.id, provider="openai-codex", model="gpt-6-luna", requested_by="launcher")
    store.update_profile(instance.id, display_name="Renamed Mid-Turn")

    turn = SimpleNamespace(
        instance=admitted_copy,
        session_id="chat_alice",
        instance_store=store,
        warnings=[],
    )
    turn._warn = lambda kind, detail, step=None: turn.warnings.append((kind, detail, step))
    _SettlePhases._return_instance_to_idle(turn)

    after = store.get(instance.id)
    assert turn.warnings == []
    assert after.state == WorkerSessionState.IDLE
    assert after.default_chat_session_id == "chat_alice"
    assert (after.provider, after.model) == ("openai-codex", "gpt-6-luna")
    # Not a model-tier field, so only the settle's field-scoped write protects it.
    assert after.display_name == "Renamed Mid-Turn"


def test_whole_row_update_from_a_stale_copy_keeps_the_stored_override(isolate_agent_runtime_root):
    store = PersonaInstanceStore()
    instance = _chat_instance(store)
    stale = store.get(instance.id)
    store.update_profile(instance.id, provider="openai-codex", model="gpt-6-luna")
    stored_clock = store.get(instance.id).model_override_issued_at

    stale.display_name = "Renamed By A Stale Writer"
    written = store.update(stale)

    assert written.display_name == "Renamed By A Stale Writer"
    assert (written.provider, written.model) == ("openai-codex", "gpt-6-luna")
    assert written.model_override_issued_at == stored_clock


def test_whole_row_update_that_moves_the_model_tier_ships_a_patch(isolate_agent_runtime_root):
    event_log = EventLog()
    store = PersonaInstanceStore(event_log=event_log)
    instance = _chat_instance(store)
    current = store.get(instance.id)
    before = len(_patched_fields(event_log, instance.id))

    current.model = "gpt-6-luna"
    store.update(current)

    patches = _patched_fields(event_log, instance.id)[before:]
    assert any(patch.get("model") == "gpt-6-luna" for patch in patches)


def test_patch_fields_writes_only_the_named_fields_onto_a_fresh_read(isolate_agent_runtime_root):
    store = PersonaInstanceStore()
    instance = _chat_instance(store)
    store.update_profile(instance.id, display_name="Alice Lead", skills=["technical-writing"])

    written = store.patch_fields(instance.id, skill_manifest_hash="abc123")

    assert written.skill_manifest_hash == "abc123"
    assert written.display_name == "Alice Lead"
    assert written.skill_overrides == ["technical-writing"]
    with pytest.raises(AttributeError):
        store.patch_fields(instance.id, not_a_field=1)
