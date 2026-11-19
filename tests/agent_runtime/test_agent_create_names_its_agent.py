"""A new agent is named by its maker; the runtime never names it with a number.

Row ``RT-A-NEW-AGENT-MADE-FROM-ANOTHER-IS-NAMED-WITH-A-NUMBER`` (review w1118a.41
D8, ruled by Eternia ``bundled-agents-stay-one-agent-design.md`` § 4): seen
2026-11-19, ``runtime.agent.create`` from ``neko_supervisor`` with no
``display_name`` minted an agent named "Neko Mission Lead (2)" — the seat-label
numbering became an agent's name. A nameless create is now refused
``agent_name_required`` and a name any agent has ``agent_name_taken``, both with
nothing written. Driven through ``runtime.agent.create``, the door Eternia uses.
"""

from __future__ import annotations

from agent_runtime import paths, serve_rpc
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.fresh_install_seed import seed_fresh_install_persona
from agent_runtime.store import AgentStore
from tests.agent_runtime.office_seed import seed_workspace_record

NEKO = "neko_supervisor"
WORKSPACE = "ws_agent_create_names"


def _setup() -> None:
    from agent_runtime.office_store import OfficeStore

    seed_fresh_install_persona(load_agent_runtime_config())
    seed_workspace_record(WORKSPACE)
    OfficeStore().ensure_surface(WORKSPACE, created_by="seed")


def _create(key: str, **params) -> dict:
    return serve_rpc.handle_request({
        "jsonrpc": "2.0", "id": key, "method": "runtime.agent.create",
        "params": {"persona_id": NEKO, "workspace_id": WORKSPACE, "idempotency_key": key, **params},
    })


def _written() -> tuple:
    """The personas and roster rows on disk: what a refused create must not grow."""

    instances = paths.persona_instances_dir()
    return (
        sorted(p.id for p in AgentStore().list_all()),
        sorted(p.name for p in instances.glob("*")) if instances.exists() else [],
    )


def test_a_create_with_no_name_is_refused_and_writes_nothing():
    # Mutation: drop the ``agent_name_required`` gate in ``AgentCreate.normalize``
    # and name the agent ``display_name or default_display_name`` again -> red:
    # the create answers a result whose agent is "Neko Mission Lead (2)".
    _setup()
    before = _written()

    for blank in ({}, {"display_name": "   "}):
        reply = _create("nameless", **blank)

        assert reply["error"]["code"] == -32602
        assert reply["error"]["data"] == {"reason": "agent_name_required", "rolled_back": True}
        assert reply["error"]["message"] == "Give the new agent a name."
    assert _written() == before


def test_a_create_named_like_an_existing_agent_is_refused_never_numbered():
    # Mutation: drop the ``name_is_taken`` check in ``AgentCreate.new_instance``
    # -> red: a second agent called "Neko Mission Lead" is minted.
    _setup()
    before = _written()

    reply = _create("taken", display_name="neko   MISSION lead")

    assert reply["error"]["code"] == 4090
    data = reply["error"]["data"]
    assert data["reason"] == "agent_name_taken"
    assert data["name"] == "neko MISSION lead"
    assert (data["phase"], data["rolled_back"]) == ("instance", True)
    assert _written() == before


def test_a_named_create_mints_its_name_takes_it_and_replays_under_its_own_key():
    # Mutation: move the taken check before the reservation (into ``normalize``)
    # -> red: the same-key replay meets its own agent's name and is refused.
    _setup()

    made = _create("first", display_name="Scout")["result"]
    assert AgentStore().get(made["persona_id"]).display_name == "Scout"

    replay = _create("first", display_name="Scout")["result"]
    assert (replay["persona_id"], replay["idempotent_replay"]) == (made["persona_id"], True)

    again = _create("second", display_name="scout")
    assert again["error"]["data"]["reason"] == "agent_name_taken"


def test_placing_without_a_name_keeps_the_seat_label():
    # Mutation: set ``AgentPlace.NAMES_A_NEW_AGENT = True`` -> red: a nameless
    # place is refused ``agent_name_required`` instead of taking its seat label.
    _setup()

    reply = serve_rpc.handle_request({
        "jsonrpc": "2.0", "id": "seat", "method": "runtime.agent.place",
        "params": {"persona_id": NEKO, "workspace_id": WORKSPACE, "idempotency_key": "seat"},
    })

    assert reply["result"]["persona_id"] == NEKO
    assert reply["result"]["display_name"].startswith("Neko Mission Lead")
