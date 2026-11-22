"""A chat or send that names an agent with no instance in reach is placed or refused, never sent to a hidden copy.

Row ``RT-A-SEND-TO-AN-AGENT-WITH-NO-INSTANCE-IN-REACH-IS-PLACED-OR-REFUSED`` (plan
``docs/agent-runtime-harness/planned/agent-template-vs-canonical-instance-2026-11-21.md`` §3(d), §4, §7 row 1;
review w1118a.78). Before it, a bare persona with no placement landed on ``personainst_<persona>``: the CLI's
``harness persona chat send dev``, an operator's new chat naming only the agent, and an agent's send all ran
on the hidden copy, in no workspace. The fixture is the serve boot's Default workspace and the sample personas.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent_runtime import paths
from agent_runtime.default_scope import DEFAULT_WORKSPACE_ID, ensure_default_scope
from agent_runtime.persona_assignments import PersonaInstanceStore, persona_instance_id_for

pytestmark = pytest.mark.usefixtures("isolate_agent_runtime_root", "persisted_persona_samples")

DEV = "dev"
HIDDEN = persona_instance_id_for(DEV)


def _resolve(**overrides):
    from hermes_cli.harness_parts.persona.chat_turn_target import resolve_turn_instance

    fields = dict(
        instance_store=PersonaInstanceStore(), normalized_persona=DEV, raw_persona_id=DEV,
        persona_instance_id=None, session_id=None, relay_chain=(DEV,), requested_by_session=None,
        relay_chain_in=(), place=True,
    )
    fields.update(overrides)
    return resolve_turn_instance(**fields)


def _stored_ids() -> set[str]:
    directory = paths.persona_instances_dir()
    return {path.stem for path in directory.glob("*.json")} if directory.exists() else set()


def test_an_operator_bare_send_places_in_the_default_workspace():
    """Kill-mutation: answer the hidden copy instead of ``reuse_or_place`` → red."""
    ensure_default_scope(seed_active_pointers=False)
    instance_id, refusal = _resolve()
    assert refusal is None and instance_id and instance_id != HIDDEN
    placed = PersonaInstanceStore().get(instance_id)
    assert (placed.persona_id, placed.workspace_id) == (DEV, DEFAULT_WORKSPACE_ID)
    # The next bare send reuses that idle instance rather than placing another beside it.
    again, _ = _resolve()
    assert again == instance_id


def test_an_operator_bare_send_continues_the_adopted_copy():
    """With the adoption landed, the reuse-idle pick finds the adopted copy (review w1118a.78)."""
    from agent_runtime.persona_instance_adoption import adopt_global_rows
    from tests.agent_runtime.test_global_row_adoption import _seed

    ensure_default_scope(seed_active_pointers=False)
    _seed(HIDDEN, persona_id=DEV, default_chat_session_id=f"persona_chat_{HIDDEN}_0123456789ab")
    assert adopt_global_rows(apply=True)[0]["fate"] == "adopted"
    assert _resolve() == (HIDDEN, None)


def test_the_read_only_admission_places_nothing():
    """``place=False`` (``admit_turn_target``) answers "the turn places one" and writes no row."""
    ensure_default_scope(seed_active_pointers=False)
    before = _stored_ids()
    assert _resolve(place=False) == (None, None)
    assert _stored_ids() == before


def test_an_agents_send_to_an_unplaced_persona_is_refused():
    """Kill-mutation: answer the hidden copy on the agent arm → red."""
    ensure_default_scope(seed_active_pointers=False)
    before = _stored_ids()
    for overrides in ({"relay_chain_in": ("personainst_qa",)}, {"requested_by_session": "persona_chat_x_0123456789ab"}):
        instance_id, refusal = _resolve(**overrides)
        assert instance_id is None
        assert refusal["error_kind"] == "no_instance_in_scope"
        assert "agent_add_instance" in refusal["error"] and "agent_add_instance" in refusal["next_expected"]
    assert _stored_ids() == before  # an agent's send never places


def test_an_agents_send_is_refused_in_the_sending_turn(monkeypatch):
    """Through ``agent_chat_send``: admission asks the turn's resolver, so the refusal comes back now."""
    from agent_runtime import relay_policy
    from hermes_cli.harness_parts.persona import chat_turn_message
    from tools.agent_chat_tool import agent_chat_send

    ensure_default_scope(seed_active_pointers=False)
    seen = []
    monkeypatch.setattr(chat_turn_message, "_cmd_mission_chat_message", lambda args: seen.append(args) or 0)
    token = relay_policy.RELAY_CHAIN.set(("personainst_qa",))
    try:
        data = json.loads(agent_chat_send(persona_id=DEV, message="hi", wait=False))
    finally:
        relay_policy.RELAY_CHAIN.reset(token)
    assert (data["ok"], data["error_kind"]) == (False, "no_instance_in_scope")
    assert seen == []


def test_an_operator_open_of_an_unplaced_agent_places_it():
    """``persona instance open-chat --new-session`` naming only the agent.
    Kill-mutation: answer ``persona_instance_id_for`` in ``_cmd_persona_instance_open_new_chat`` → red."""
    from hermes_cli.harness_parts.persona.chat_open import _cmd_persona_instance_open_chat

    ensure_default_scope(seed_active_pointers=False)
    payloads = []
    args = SimpleNamespace(
        persona_id=DEV, persona_instance_id=None, session_id=None, new_session=True, add_instance=False,
        idempotency_key="open-1", title=None, select_session=True, client_scope=None, json=True,
        payload_sink=payloads.append,
    )
    assert _cmd_persona_instance_open_chat(args) == 0, payloads
    opened = payloads[-1]["persona_instance_id"]
    assert opened != HIDDEN
    assert PersonaInstanceStore().get(opened).workspace_id == DEFAULT_WORKSPACE_ID


def test_an_open_naming_a_missing_hidden_copy_places_the_agent():
    """Eternia's template console names ``personainst_<persona>`` on its New chat (read live 2026-11-21,
    w1118a-mint: "persona instance not found: personainst_base"). With no row under that id the open means
    the agent and places it. Kill-mutation: drop ``_names_an_unplaced_hidden_copy`` in
    ``_cmd_persona_instance_open_new_chat`` → refused ``persona_instance_not_found``, red."""
    from hermes_cli.harness_parts.persona.chat_open import _cmd_persona_instance_open_chat

    ensure_default_scope(seed_active_pointers=False)
    payloads = []
    args = SimpleNamespace(
        persona_id=DEV, persona_instance_id=HIDDEN, session_id=None, new_session=True, add_instance=False,
        idempotency_key="open-hidden-1", title=None, select_session=True, client_scope=None, json=True,
        payload_sink=payloads.append,
    )
    assert _cmd_persona_instance_open_chat(args) == 0, payloads
    opened = payloads[-1]["persona_instance_id"]
    assert opened != HIDDEN and opened.startswith(f"{HIDDEN}_agent_")
    assert PersonaInstanceStore().get(opened).workspace_id == DEFAULT_WORKSPACE_ID
    assert HIDDEN not in _stored_ids()


def test_reading_the_addressable_roster_writes_no_row():
    """Kill-mutation: mint the scope's rows in ``addressing._addressable`` again → red."""
    from tools.agent_chat.addressing import _addressable

    before = _stored_ids()
    _addressable(None)
    assert _stored_ids() == before


def test_an_operator_send_from_another_workspace_reuses_the_idle_default_instance():
    """The operator works in another workspace where dev stands nowhere: the send reuses dev's idle
    instance in the Default workspace instead of placing a second one beside it.
    Kill-mutation: drop the idle reuse in ``reuse_or_place`` → a second instance is placed, red."""
    from agent_runtime.store import WorkspaceStore
    from tests.agent_runtime.office_seed import seed_workspace_record
    from tests.agent_runtime.persona_instance_mint import mint_placed_instance

    ensure_default_scope(seed_active_pointers=False)
    other = seed_workspace_record("ws_other").id
    WorkspaceStore().set_active(other)
    idle = mint_placed_instance(DEV, workspace_id=DEFAULT_WORKSPACE_ID)
    before = _stored_ids()
    assert _resolve() == (idle.id, None)
    assert _stored_ids() == before


def test_a_refused_open_places_nothing():
    """Seen in the lane's CLI read: ``open-chat --persona dev --new-session`` with no idempotency key
    placed an instance, then refused ``idempotency_key_required``. The key is checked first now.
    Kill-mutation: drop the key check before ``reuse_or_place`` in the open → red."""
    from hermes_cli.harness_parts.persona.chat_open import _cmd_persona_instance_open_chat

    ensure_default_scope(seed_active_pointers=False)
    before = _stored_ids()
    payloads = []
    args = SimpleNamespace(
        persona_id=DEV, persona_instance_id=None, session_id=None, new_session=True, add_instance=False,
        idempotency_key=None, title=None, select_session=True, client_scope=None, json=True,
        payload_sink=payloads.append,
    )
    assert _cmd_persona_instance_open_chat(args) == 2
    assert payloads[-1]["error_kind"] == "idempotency_key_required"
    assert _stored_ids() == before
