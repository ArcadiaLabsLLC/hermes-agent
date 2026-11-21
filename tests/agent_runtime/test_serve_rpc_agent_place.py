"""``runtime.agent.place`` — putting an EXISTING agent on a desk adds an instance of it.

Owner 2026-11-19 (row ``RT-PLACING-A-SHIPPED-AGENT-MAKES-A-SECOND-ONE``): "it
should create an agent instance, not a duplicate copy of the profile and
persona", and "the action should be split". ``runtime.agent.create`` keeps making
a NEW agent (its own persona and profile, ``TASK-INDEPENDENT-AGENT-CREATION``);
``runtime.agent.place`` and the argv ``--add-instance`` doors seat the agent that
already exists. Each witness below is the persona and profile inventory, which
the minting path grows and the placing path must not.
"""

from __future__ import annotations

from agent_runtime import serve_rpc
from tests.agent_runtime.test_serve_rpc_agent_create import (
    WORKSPACE,
    _actors,
    _instances,
    _params,
    _seed_workspace,
    qa_persona,  # noqa: F401 — the fixture, re-exported for this file
)


def _place(params: dict, rid: str = "p1") -> dict:
    return serve_rpc.handle_request(
        {"jsonrpc": "2.0", "id": rid, "method": "runtime.agent.place", "params": params}
    )


def _identities() -> tuple[set[str], set[str]]:
    from hermes_cli.profiles import list_profiles

    from agent_runtime.store import AgentStore

    return {p.id for p in AgentStore().list_all()}, {p.name for p in list_profiles()}


def test_placing_an_existing_agent_adds_an_instance_and_mints_no_persona_or_profile(qa_persona):
    # Mutation: make ``AgentPlace.new_instance`` call ``create_independent_agent``
    # (the create arm) → a new ``agent_<hex>`` persona and ``agent-<hex>`` profile
    # appear and the inventory and ``persona_id`` asserts red.
    _seed_workspace()
    before = _identities()

    first = _place(_params(display_name=None, idempotency_key="drop-1", placement_id="qa_agent_2"))["result"]
    second = _place(_params(display_name=None, idempotency_key="drop-2", position=[5.0, 1.0]))["result"]

    assert _identities() == before
    assert first["persona_id"] == second["persona_id"] == "qa"
    assert first["persona_instance_id"] == "personainst_qa_agent_2"
    assert first["persona_instance_id"] != second["persona_instance_id"]
    instances = _instances()
    for result in (first, second):
        instance = instances[result["persona_instance_id"]]
        assert (instance.persona_id, instance.workspace_id) == ("qa", WORKSPACE)
        assert instance.default_chat_session_id == result["default_chat_session_id"]
        assert _actors()[result["actor_key"]].persona_id == "qa"
    # The seat still gets the persona's honest name, numbered against the agent's
    # other placed instances — the unplaced canonical ``personainst_qa`` is not one.
    assert first["display_name"] == "QA Agent"
    assert second["display_name"] == "QA Agent · 2"


def test_a_place_replays_its_key_without_a_second_instance(qa_persona):
    # Mutation: drop ``STATE_DONE: AgentCreate.replay`` from ``RESUME_ACTIONS``
    # → the replay re-runs the mint and answers ``idempotent_replay: false``.
    _seed_workspace()
    first = _place(_params(display_name=None, idempotency_key="drop-1", placement_id="qa_agent_2"))["result"]
    replay = _place(_params(display_name=None, idempotency_key="drop-1", placement_id="qa_agent_2"))["result"]

    assert replay["idempotent_replay"] is True
    assert replay["persona_instance_id"] == first["persona_instance_id"]
    assert replay["revision"] == first["revision"] == 1
    assert [i for i in _instances() if i != "personainst_qa"] == ["personainst_qa_agent_2"]


def test_create_still_makes_a_new_agent_where_place_does_not(qa_persona):
    # Mutation: point ``AgentCreate.new_instance`` at ``store.add_instance`` →
    # create stops minting and the persona inventory assert reds.
    _seed_workspace()
    personas, profiles = _identities()

    created = serve_rpc.handle_request({
        "jsonrpc": "2.0", "id": "c1", "method": "runtime.agent.create",
        "params": _params(idempotency_key="new-agent"),
    })["result"]

    after_personas, after_profiles = _identities()
    assert after_personas - personas == {created["persona_id"]}
    assert after_profiles - profiles == {created["profile_id"]}
    assert created["persona_id"].startswith("agent_")


def test_the_place_verb_is_advertised_without_a_source_instance(qa_persona):
    # Mutation: list ``runtime.agent.place`` under ``AGENT_CREATE_METHOD_PARAMS``
    # in ``serve_rpc.registry`` → ``source_instance_id`` is advertised and reds.
    manifest = serve_rpc.manifest()
    assert manifest["tiers"]["runtime.agent.place"] == "console"
    params = manifest["params"]["runtime.agent.place"]
    assert "source_instance_id" not in params
    assert set(manifest["params"]["runtime.agent.create"]) - set(params) == {"source_instance_id"}


def test_the_add_instance_twin_places_and_only_independent_agent_mints(qa_persona, capsys):
    # The argv twins (RT-THE-OLD-CREATE-NO-LONGER-PLACES-OR-COPIES-AN-AGENT): ``persona instance create
    # --add-instance`` is ``runtime.agent.place``'s sequence, ``--independent-agent`` the create's.
    # Mutation: restore ``or add_instance`` on ``independent`` in
    # ``lifecycle_commands._cmd_persona_instance_create`` → the add-instance
    # call mints an ``agent_<hex>`` persona and the first assert reds.
    import json
    from argparse import Namespace

    from hermes_cli.harness_parts.persona.lifecycle_commands import _cmd_persona_instance_create

    _seed_workspace()
    before = _identities()

    def create(key, **overrides):
        args = Namespace(**{
            "json": True, "persona_id": "qa", "title": "QA Agent", "display_name": "QA Agent", "requested_by": "cli",
            "coordinator_id": None, "client_message_id": key, "client_scope": None, "session_id": None,
            "workspace_id": None, "realm_id": None, "placement_id": None, "source_instance_id": None,
            "add_instance": False, "independent_agent": False, **overrides})
        code = _cmd_persona_instance_create(args)
        row = json.loads(capsys.readouterr().out)
        assert code == 0 and row["ok"] is True, row
        return row

    placed = create("seat", add_instance=True, placement_id="qa_agent_7", workspace_id=WORKSPACE)
    assert (placed["persona_id"], placed["persona_instance_id"]) == ("qa", "personainst_qa_agent_7")
    # Seated by the place's own write, not a second seat helper.
    assert placed["actor_key"] and placed["workspace_id"] == WORKSPACE
    assert _identities() == before

    # A new agent takes a name of its own, never its source's
    # (RT-INDEPENDENT-AGENT-COPY-HAS-ONE-ACTION).
    minted = create("new", independent_agent=True, display_name="QA Agent copy")
    assert minted["persona_id"] != "qa"
    assert _identities()[0] - before[0] == {minted["persona_id"]}
