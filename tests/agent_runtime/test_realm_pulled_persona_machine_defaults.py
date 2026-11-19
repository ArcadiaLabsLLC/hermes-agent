"""A member who pulls a teammate's agent is not told its settings changed when the teammate never chose
an API mode (or a model, or a provider).

RT-REALM-PULLED-PERSONA-WITHOUT-API-MODE-READS-CHANGED. Real for Eternia users: Eternia never sends an
``api_mode`` when it places an agent (``mission_agent_create_client.dart`` sends a ``persona_id``), and
the personas a fresh Eternia places from are saved with ``api_mode=None`` by hermes itself (the
fresh-install seed, ``fresh_install_seed.py``; every auto-discovered profile persona such as
``profile_base``, ``profile_persona_discovery.py``).

Reproduced here before the fix on two simulated computers (``_Team``): straight after the join the
member's status read ``persona_definition qa changed`` and still did after an idle pull. The pull writes
the teammate's body into the member's ``config.yaml`` (no store row there), and resolving a
config-declared persona fills each setting the body omits with THIS machine's default
(``persona_records._persona_from_overrides``); the projection then shipped that default as if the persona
carried it, so the body the drift hashed was not the body the pull recorded. The fix: a config-declared
persona's projection carries only what its config states for those default-filled settings
(``persona_config_sync.project_persona_definitions``). Killing mutations are named per test.
"""
from __future__ import annotations

import pytest

from agent_runtime import serve_rpc
from agent_runtime.agent_create import perform_agent_create
from agent_runtime.models import AgentPersona
from agent_runtime.office_store import OfficeStore
from agent_runtime.realm_sync import publish_realm_sync, pull_realm_sync
from agent_runtime.store import AgentStore, WorkspaceStore
from agent_runtime.persona_config_sync import load_raw_config, raw_persona_overrides
from hermes_cli.config import get_config_path
from tests.agent_runtime.test_workspace_move_out_of_server_realm import _Team
from utils import atomic_roundtrip_yaml_update


@pytest.fixture
def team(tmp_path, monkeypatch):
    return _Team(tmp_path, monkeypatch)


def _unpublished(realm_id: str) -> tuple[bool, list[tuple]]:
    reply = serve_rpc.handle_request(
        {"jsonrpc": "2.0", "id": "st", "method": "runtime.realm.sync.status", "params": {"realm_id": realm_id}})
    status = reply["result"]
    return status["unpublished_changes"], [
        (str(item["family"]), item["item_key"], item["kind"]) for item in status["store_drift"]["items"]]


def _pulled_persona_id() -> str:
    """The one persona the pull wrote into this member's ``config.yaml`` (the placed agent's own)."""
    (persona_id,) = raw_persona_overrides(load_raw_config())
    return persona_id


def _shared_agent_without_settings(team: _Team, *, bob_default_model: str | None = None):
    """Alice places an agent from a persona that chose no model, provider or API mode, and publishes."""
    shared = team.found("alice", "Team Realm", "srv_team")
    workspace = WorkspaceStore().create(name="Roadmap", realm_id=shared.id)
    AgentStore().save(AgentPersona(id="qa", display_name="QA Agent", role="qa", model=None, provider=None,
                                   api_mode=None, system_prompt_path=""))
    OfficeStore().ensure_surface(workspace.id, created_by="seed")
    made = perform_agent_create({"persona_id": "qa", "workspace_id": workspace.id, "realm_id": shared.id,
                                 "position": [1.0, 1.0], "idempotency_key": "seat"})
    assert made.refusal is None, made.refusal
    publish_realm_sync(shared.id)
    assert _unpublished(shared.id) == (False, [])
    if bob_default_model is not None:
        team.be("bob")
        atomic_roundtrip_yaml_update(get_config_path(), "agent_runtime.default_model", bob_default_model)
    team.join("bob", shared)
    return shared


def test_a_pulled_agent_whose_teammate_chose_no_api_mode_reads_unchanged(team):
    """Join, then an idle pull: nothing reads changed on the member.

    Mutation: in ``project_persona_definitions`` drop the config-declared skip (project the resolved
    record's every field again) -> ``(True, [('persona_definition', <agent>, 'changed')])`` straight after
    the join, red."""
    shared = _shared_agent_without_settings(team)
    assert _unpublished(shared.id) == (False, [])
    pulled = pull_realm_sync(shared.id)
    assert _pulled_persona_id() in pulled["profile_sync"]["personas"]["converged"]
    assert _unpublished(shared.id) == (False, [])


def test_a_members_own_default_model_is_not_read_as_a_change_to_the_pulled_agent(team):
    """The same flaw for the model: Bob's machine has its own default model, Alice's persona chose none.

    Mutation: as above -> red straight after the join."""
    shared = _shared_agent_without_settings(team, bob_default_model="bob-own-model")
    assert _unpublished(shared.id) == (False, [])
    pull_realm_sync(shared.id)
    assert _unpublished(shared.id) == (False, [])


def test_a_member_who_sets_the_api_mode_himself_reads_changed(team):
    """The honest half: a mode Bob writes on the pulled persona himself is his change.

    Mutation: in ``project_persona_definitions`` let the config override contribute no key the record
    left out (``continue`` before ``body[name] = override_body[name]``) -> Bob's own edit is invisible,
    red."""
    shared = _shared_agent_without_settings(team)
    persona_id = _pulled_persona_id()
    atomic_roundtrip_yaml_update(get_config_path(), f"agent_runtime.personas.{persona_id}.api_mode", "chat_completions")
    assert _unpublished(shared.id) == (True, [("persona_definition", persona_id, "changed")])
