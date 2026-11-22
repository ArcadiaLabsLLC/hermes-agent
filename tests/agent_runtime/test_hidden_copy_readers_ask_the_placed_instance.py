"""The last readers that guessed an agent's hidden-copy name ask for its placed instance.

Row RT-FU-THE-LAST-READERS-THAT-GUESS-AN-AGENTS-HIDDEN-COPY-NAME-ASK-FOR-ITS-PLACED-INSTANCE (from
RT-HERMES-STOPS-MAKING-A-HIDDEN-COPY-OF-EVERY-AGENT): nothing mints ``personainst_<persona>`` any more, so a
reader that derived that id from an agent's bare id answered "not found", or filed a chat under an id no row
holds. Each now asks the one read-only answer, ``placed_instance_for``; a profile's own channel
``personainst_profile_<name>`` keeps its id.

Killing mutations (each applied alone, red recorded, reverted — see the commit):
  M1 ``placed_instance_for`` drops the Default-first sort      -> default-workspace test red
  M2 ``placed_instance_for`` ignores the workspace test        -> unplaced-row test red
  M3 ``harness_query.core.resolve_instance`` reads ``persona_instance_id_for(value)`` again
                                                               -> harness-query test red
  M4 ``lens.trigger._operator_client_scope`` reads ``persona_instance_id_for`` again
                                                               -> lens test red
  M5 ``own_session_import`` binds every agent's ``persona_instance_id_for`` (profile test dropped)
                                                               -> import test red
  M6 ``history_rows._history_row`` falls back to ``persona_instance_id_for`` -> history-row test red
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from hermes_time import now

from agent_runtime import paths
from agent_runtime.harness_query import core
from agent_runtime.lens import trigger
from agent_runtime.models import PersonaInstance
from agent_runtime.own_session_import import BoundBy, Targets
from agent_runtime.persona_assignments import PersonaInstanceStore, placed_instance_for
from agent_runtime.persona_chat_history import messages
from agent_runtime.persona_chat_history.history_rows import _history_row
from agent_runtime.states import WorkerSessionState
from tests.agent_runtime.persona_instance_mint import mint_placed_instance


def _row(instance_id: str, persona_id: str, *, workspace_id: str | None = None) -> PersonaInstance:
    instance = PersonaInstance(
        id=instance_id,
        persona_id=persona_id,
        role=persona_id,
        display_name=persona_id,
        profile_id=None,
        runtime_root=str(paths.store_root()),
        state=WorkerSessionState.IDLE,
        mode="configured",
        workspace_id=workspace_id,
        updated_at=now(),
    )
    PersonaInstanceStore()._write(instance)
    return PersonaInstanceStore().get(instance_id)


def test_the_default_workspaces_instance_answers_first():
    mint_placed_instance("base", placement="agent_a", workspace_id="ws_other")
    mint_placed_instance("base", placement="agent_z", workspace_id="ws_default")

    assert placed_instance_for("base").id == "personainst_base_agent_z"


def test_an_agent_placed_nowhere_has_no_instance_to_answer():
    # An older runtime's held hidden copy stands in no workspace: it answers for nobody.
    _row("personainst_base", "base")

    assert placed_instance_for("base") is None
    mint_placed_instance("base", placement="agent_1", workspace_id="ws_other")
    assert placed_instance_for("base").id == "personainst_base_agent_1"


def test_a_profiles_own_channel_keeps_its_id():
    _row("personainst_profile_alice", "profile_alice")

    assert placed_instance_for("profile_alice").id == "personainst_profile_alice"


def test_a_harness_query_on_an_agents_id_answers_its_placed_instance():
    mint_placed_instance("base", placement="agent_1", workspace_id="ws_default")

    assert core.resolve_instance("base").id == "personainst_base_agent_1"
    assert core.resolve_instance("personainst_base_agent_1").id == "personainst_base_agent_1"
    assert core.resolve_instance("neko_supervisor") is None


def test_a_lens_episode_takes_the_owner_of_the_placed_instances_chat(monkeypatch):
    placed = mint_placed_instance("base", placement="agent_1", workspace_id="ws_default")
    store = PersonaInstanceStore()
    placed.default_chat_session_id = "persona_chat_personainst_base_agent_1_root"
    store._write(placed)
    read: list[str] = []

    @contextmanager
    def existing(*, session_id, client_scope=None):
        read.append(session_id)
        yield SimpleNamespace(owner="account:42")

    monkeypatch.setattr(messages, "existing_chat_session", existing)

    assert trigger._operator_client_scope("base") == "account:42"
    assert read == ["persona_chat_personainst_base_agent_1_root"]


def test_an_imported_chat_never_binds_to_an_agents_hidden_copy_name():
    # The target still holds an old hidden copy AND a placed instance: the chat binds as the agent's
    # instances say (two here: ambiguous), never through the hidden-copy name.
    hidden = _row("personainst_base", "base")
    placed = mint_placed_instance("base", placement="agent_1", workspace_id="ws_default")
    targets = Targets([hidden, placed])
    session = {"id": "s1", "source": "persona_chat", "model_config": {"persona_id": "base"}}

    bound = targets.resolve(session, {})

    assert bound[1] is not BoundBy.PERSONA_CHANNEL
    assert bound[0] != "personainst_base"


def test_a_profile_chat_still_binds_to_its_profiles_channel():
    channel = _row("personainst_profile_alice", "profile_alice")
    targets = Targets([channel])
    session = {"id": "s2", "source": "persona_chat", "model_config": {"persona_id": "profile_alice"}}

    assert targets.resolve(session, {})[:2] == ("personainst_profile_alice", BoundBy.PERSONA_CHANNEL)


def test_a_history_row_with_no_instance_names_no_hidden_copy():
    row = _history_row({"title": "t"}, persona_id="base", instance_id="", session_id="s3")

    assert row["persona_instance_id"] == ""
    held = _history_row({"title": "t"}, persona_id="base", instance_id="personainst_base_agent_1", session_id="s4")
    assert held["persona_instance_id"] == "personainst_base_agent_1"
