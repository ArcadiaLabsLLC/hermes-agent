"""Hermes makes no hidden copy of an agent; an agent's template is its persona.

Row ``RT-HERMES-STOPS-MAKING-A-HIDDEN-COPY-OF-EVERY-AGENT`` (plan
``agent-template-vs-canonical-instance-2026-11-21`` §2, §3(c), §3(e), §4; owner RULED 2026-11-21: Base is a
template like any persona, and every new instance gets a workspace). Read in code before it:
``PersonaInstanceStore.ensure_for_persona(s)`` minted ``personainst_<persona>`` on discovery, prewarm, every
snapshot build, status, the peer roster, every send and the CLI, and the canonical predicate special-cased
that row at about 37 sites. The fixture is a fresh namespace the way the serve boot leaves it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime import paths
from agent_runtime.default_scope import DEFAULT_WORKSPACE_ID, ensure_default_scope
from agent_runtime.persona_assignments import PersonaInstanceStore, canonical_chat_instance_id, persona_instance_id_for
from tests.agent_runtime.persona_instance_mint import mint_placed_instance

pytestmark = pytest.mark.usefixtures("isolate_agent_runtime_root", "persisted_persona_samples")


def _hidden_copies() -> list[str]:
    return sorted(i.id for i in PersonaInstanceStore().list_all() if i.id == persona_instance_id_for(i.persona_id))


def test_a_fresh_namespace_boot_and_snapshot_builds_write_no_hidden_copy():
    """Kill-mutation: list a persona's hidden copy back into ``snapshot/sections.py`` (``ensure_for_personas``
    restored) → rows appear, red."""
    from agent_runtime.snapshot import build_snapshot
    from agent_runtime.status import build_status

    ensure_default_scope(seed_active_pointers=False)
    build_snapshot()
    build_snapshot()
    build_status()
    assert _hidden_copies() == []
    rows = paths.persona_instances_dir()
    assert not rows.exists() or not any(rows.glob("*.json"))


def test_the_first_new_chat_places_an_instance_in_the_default_workspace():
    """The operator's open of a bare agent places ``personainst_<persona>_agent_<hex>`` in ``ws_default``."""
    from agent_runtime.agent_create.staff import reuse_or_place

    ensure_default_scope(seed_active_pointers=False)
    instance_id, refusal = reuse_or_place("dev")
    assert refusal is None and instance_id.startswith(f"{persona_instance_id_for('dev')}_agent_")
    assert PersonaInstanceStore().get(instance_id).workspace_id == DEFAULT_WORKSPACE_ID
    assert _hidden_copies() == []


def test_a_bare_agent_names_no_hidden_copy():
    """Kill-mutation: answer ``persona_instance_id_for`` for every persona in ``canonical_chat_instance_id`` → red."""
    assert canonical_chat_instance_id("dev") is None
    assert canonical_chat_instance_id("dev", "personainst_dev_agent_2") == "personainst_dev_agent_2"
    assert canonical_chat_instance_id("profile_alice") == persona_instance_id_for("profile_alice")


def test_an_open_naming_no_instance_makes_a_held_row():
    """The one door left: a bind naming no instance makes a row HELD machine-local, never an ordinary
    unscoped one. Kill-mutation: drop the stamp in ``chat_binding._load_or_mint_chat_instance`` → red."""
    from agent_runtime.persona_instance_adoption import unstamped_hidden_copies

    copy = persona_instance_id_for("dev")
    opened = PersonaInstanceStore().open_chat(persona_id="dev", session_id=f"persona_chat_{copy}_0123456789ab")
    assert opened.id == copy and opened.adopted_from_global and opened.workspace_id is None
    assert unstamped_hidden_copies() == []
    channel = persona_instance_id_for("profile_alice")
    opened = PersonaInstanceStore().open_chat(persona_id="profile_alice", session_id=f"persona_chat_{channel}_0123456789ab")
    assert opened.id == channel and opened.adopted_from_global


def test_retire_and_duplicate_act_on_an_adopted_hidden_copy_with_no_guard():
    """Plan §3(c): with no mint the retire and duplicate guards are deleted; an adopted copy is ordinary.
    Kill-mutation: restore the ``canonical_instance_stays`` guard in ``agent_duplicate._check_instance``
    keyed on the hidden-copy id → red."""
    import json

    from agent_runtime.agent_duplicate import _check_instance
    from agent_runtime.models import PersonaInstance
    from agent_runtime.serde import to_jsonable
    from agent_runtime.states import WorkerSessionState
    from agent_runtime.store import AgentStore

    legacy_id = persona_instance_id_for("dev")
    row = PersonaInstance(
        id=legacy_id, persona_id="dev", role="dev", display_name="Dev", profile_id=None,
        runtime_root=str(paths.store_root()), state=WorkerSessionState.IDLE, mode="configured",
        workspace_id=DEFAULT_WORKSPACE_ID, adopted_from_global="2026-11-21",
    )
    path = paths.persona_instance_path(legacy_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(row)), encoding="utf-8")
    _check_instance(legacy_id, AgentStore().get("dev"))  # no refusal
    receipt = PersonaInstanceStore().retire(legacy_id, reason="test")
    assert receipt["persona_instance_id"] == legacy_id and not path.exists()


def test_a_held_copy_is_never_addressable():
    """Kill-mutation: return the input unfiltered in ``workspace_scope.exclude_held_copies`` → red."""
    from agent_runtime import workspace_scope

    held = SimpleNamespace(id="personainst_dev", persona_id="dev", workspace_id=None, adopted_from_global="2026-11-21")
    adopted = SimpleNamespace(id="personainst_qa", persona_id="qa", workspace_id="ws_a", adopted_from_global="2026-11-21")
    unseated = SimpleNamespace(id="personainst_dev_k1", persona_id="dev", workspace_id=None, adopted_from_global=None)
    for scope in (None, "ws_a"):
        roster = workspace_scope.addressable_roster([held, adopted, unseated], scope_workspace_id=scope)
        assert [i.id for i in roster] == ["personainst_qa", "personainst_dev_k1"]


def test_a_channel_naming_no_instance_is_not_filed_under_a_hidden_copy():
    """Kill-mutation: restore the ``persona_instance_id_for`` fallback in ``channel_identity`` → red."""
    from agent_runtime.operator_channels.instances import channel_identity

    builder = SimpleNamespace(
        _bound_history=lambda: {"persona_id": "dev", "session_id": "persona_chat_legacy"},
        history_rows=[], trace_rows=[], instances=[],
    )
    identity = channel_identity(builder)
    assert identity.persona_id == "dev" and identity.canonical_id != persona_instance_id_for("dev")


def test_the_cli_operator_chat_opens_on_a_placed_instance(capsys):
    """``harness persona-instance create --display-name`` opens its chat on a placed instance.

    Kill-mutation: skip ``reuse_or_place`` in ``lifecycle_commands._cmd_persona_instance_create`` → the
    chat opens on a held ``personainst_dev`` row, red."""
    import json

    from hermes_cli.harness_parts.persona import lifecycle_commands

    ensure_default_scope(seed_active_pointers=False)
    args = SimpleNamespace(
        json=True, persona_id="dev", title="t", display_name="Cli chat", requested_by="cli", coordinator_id=None,
        client_message_id=None, client_scope=None, session_id=None, workspace_id=None, realm_id=None,
        placement_id=None, source_instance_id=None, add_instance=False, independent_agent=False,
    )
    assert lifecycle_commands._cmd_persona_instance_create(args) == 0
    row = json.loads(capsys.readouterr().out)
    assert row["persona_instance_id"].startswith(f"{persona_instance_id_for('dev')}_agent_")
    assert PersonaInstanceStore().get(row["persona_instance_id"]).workspace_id == DEFAULT_WORKSPACE_ID
    assert _hidden_copies() == []


def test_a_batch_roster_borrows_no_unplaced_instance():
    """A workspace's batch roster is its own instances only. Kill-mutation: admit ``workspace_id is None``
    again in ``batch/dispatcher.py::_workspace_roster`` → the unplaced row joins the roster, red."""
    from agent_runtime.batch.dispatcher import _workspace_roster

    mine = mint_placed_instance("dev", placement="agent_1", workspace_id="ws_a")
    mint_placed_instance("dev", placement="agent_2", workspace_id="ws_b")
    mint_placed_instance("qa", placement="agent_3")  # standing in no workspace
    assert [member.instance_id for member in _workspace_roster("ws_a")] == [mine.id]
