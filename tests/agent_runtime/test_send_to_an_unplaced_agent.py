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
    the agent and places it. Kill-mutation: drop ``_unplaced_hidden_copy_persona`` in
    ``_cmd_persona_instance_open_new_chat`` → refused ``persona_instance_not_found``, red."""
    from hermes_cli.harness_parts.persona.chat_open import _cmd_persona_instance_open_chat

    ensure_default_scope(seed_active_pointers=False)
    opened = set()
    # Eternia sends the agent as ``persona:dev`` beside the id (read live); the id names the agent too.
    for n, persona in enumerate((DEV, f"persona:{DEV}")):
        payloads = []
        args = SimpleNamespace(
            persona_id=persona, persona_instance_id=HIDDEN, session_id=None, new_session=True, add_instance=False,
            idempotency_key=f"open-hidden-{n}", title=None, select_session=True, client_scope=None, json=True,
            payload_sink=payloads.append,
        )
        assert _cmd_persona_instance_open_chat(args) == 0, payloads
        opened.add(payloads[-1]["persona_instance_id"])
    (placed,) = opened  # the second open reuses the idle instance the first placed
    assert placed.startswith(f"{HIDDEN}_agent_")
    assert PersonaInstanceStore().get(placed).workspace_id == DEFAULT_WORKSPACE_ID
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


def _discovered_profile_agent(name: str) -> str:
    """Profile discovery's record for hermes profile ``name`` (``reconcile_profile_personas``)."""
    from agent_runtime.models import AgentPersona
    from agent_runtime.personas import PROFILE_ROLE_SENTINEL, AutonomyLevel
    from agent_runtime.store import AgentStore

    persona_id = f"profile_{name}"
    AgentStore().save(AgentPersona(
        id=persona_id, display_name=name.title(), role=PROFILE_ROLE_SENTINEL, model=None, provider=None,
        api_mode=None, autonomy=AutonomyLevel.PROPOSE_ONLY.value, hermes_profile=name,
        include_profile_memory=True, readiness={"auto_discovered_profile": True},
    ))
    return persona_id


def _open_new_chat(persona_id: str, instance_id: str, key: str) -> tuple[int, dict]:
    from hermes_cli.harness_parts.persona.chat_open import _cmd_persona_instance_open_chat

    payloads = []
    args = SimpleNamespace(
        persona_id=persona_id, persona_instance_id=instance_id, session_id=None, new_session=True,
        add_instance=False, idempotency_key=key, title=None, select_session=True, client_scope=None, json=True,
        payload_sink=payloads.append,
    )
    return _cmd_persona_instance_open_chat(args), payloads[-1]


def test_a_new_chat_on_a_profile_agent_with_no_channel_places_it():
    """Eternia row MC-FU-A-CHAT-CAN-BE-STARTED-ON-YOUR-PHONES-AGENT-FROM-THE-PHONE-AND-FROM-YOUR-COMPUTER, seen
    live 2026-11-26: on a fresh account namespace Base is profile discovery's ``profile_base``, a template
    only, and Eternia's first send names ``personainst_profile_base``; the open answered "persona instance
    not found: personainst_profile_base". With no row under the channel id the open means the agent and
    places it. Kill-mutations: answer None for every ``profile_`` candidate in
    ``_unplaced_hidden_copy_persona``, or drop ``and hidden_copy_of is None`` in ``_new_chat_target`` → red."""
    ensure_default_scope(seed_active_pointers=False)
    persona_id = _discovered_profile_agent("base")
    channel = persona_instance_id_for(persona_id)
    opened = set()
    for n, persona in enumerate((persona_id, f"persona:{persona_id}")):
        code, payload = _open_new_chat(persona, channel, f"open-profile-{n}")
        assert code == 0, payload
        opened.add(payload["persona_instance_id"])
    (placed,) = opened  # the second open reuses the idle instance the first placed
    assert placed.startswith(f"{channel}_agent_")
    assert PersonaInstanceStore().get(placed).workspace_id == DEFAULT_WORKSPACE_ID
    assert channel not in _stored_ids()


def test_a_profile_agents_standing_channel_still_opens_as_itself():
    """A row under ``personainst_profile_<name>`` (a profile's own held channel) is opened as itself; a profile
    the roster does not hold is not placed and stays not found."""
    from tests.agent_runtime.test_global_row_adoption import _seed

    ensure_default_scope(seed_active_pointers=False)
    persona_id = _discovered_profile_agent("alice")
    channel = persona_instance_id_for(persona_id)
    _seed(channel, persona_id=persona_id)
    code, payload = _open_new_chat(persona_id, channel, "open-channel")
    assert code == 0, payload
    assert payload["persona_instance_id"] == channel

    before = _stored_ids()
    code, payload = _open_new_chat("profile_nobody", persona_instance_id_for("profile_nobody"), "open-nobody")
    assert code == 2 and payload["error_kind"] == "persona_instance_not_found", payload
    assert _stored_ids() == before
