"""``runtime.agent.create`` with no ``workspace_id`` makes an UNSEATED agent.

Row ``RT-ONE-CREATE-VERB-MAKES-AN-AGENT-WITH-OR-WITHOUT-A-WORKSPACE`` (review
w1118a.69): the one create verb also makes an agent no workspace seats — the
same maker (``agent_create.mint_new_agent`` -> ``create_independent_agent``), the
same name rule and the same idempotency receipt, with the placement and skills
phases skipped. A place is a seat and still needs a workspace.

The witnesses are the stores, never the reply alone: the instance row read off
disk (its ``workspace_id`` is ``None``), the office (no surface was opened) and
the receipt file (``done``, written once).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent_runtime import serve_rpc
from tests.agent_runtime.test_serve_rpc_agent_create import (  # noqa: F401  (fixture)
    _instances,
    qa_persona,
)

#: The unseated reply, exactly: no placement field and no skills block.
UNSEATED_REPLY_KEYS = {
    "persona_instance_id",
    "persona_id",
    "profile_id",
    "display_name",
    "default_chat_session_id",
    "phases",
    "idempotent_replay",
}


def _call(method: str, params: dict, rid: str = "u1") -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})


def _create(**overrides) -> dict:
    params = {"persona_id": "qa", "idempotency_key": "unseated-1", "display_name": "Unseated Orchid"}
    params.update(overrides)
    return _call("runtime.agent.create", params)


def _receipt(key: str) -> dict:
    import hashlib

    from agent_runtime import paths

    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return json.loads(paths.agent_create_reservation_path(digest).read_text())


def _office_workspaces() -> list:
    """Every file under the office root: a seat would add an actor (and a surface)."""

    from agent_runtime import paths

    root = paths.office_root()
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()) if root.exists() else []


def test_a_create_with_no_workspace_makes_an_unseated_agent(qa_persona):
    """KILLING MUTATION: restore the unconditional ``workspace_id_required`` raise in
    ``normalize_agent_create`` and this reds on the refusal; drop the
    ``finish_unseated`` branch in ``place_and_finish`` and it reds on the reply's keys."""

    office_before = _office_workspaces()
    reply = _create()

    assert "result" in reply, reply
    result = reply["result"]
    assert set(result) == UNSEATED_REPLY_KEYS
    assert set(result["phases"]) == {"instance_ms", "total_ms"}
    assert result["idempotent_replay"] is False
    assert result["display_name"] == "Unseated Orchid"
    # A NEW agent: its own persona and profile, never the source's.
    assert result["persona_id"] != qa_persona.id
    assert result["profile_id"] and result["profile_id"] != qa_persona.hermes_profile

    instance = _instances()[result["persona_instance_id"]]
    assert instance.workspace_id is None
    assert instance.persona_id == result["persona_id"]
    assert instance.default_chat_session_id == result["default_chat_session_id"]
    # Nothing seated: no office surface was opened for it.
    assert _office_workspaces() == office_before

    receipt = _receipt("unseated-1")
    assert receipt["state"] == "done"
    assert receipt["workspace_id"] == ""
    assert receipt["persona_instance_id"] == result["persona_instance_id"]


def test_an_unseated_create_replays_its_answer_and_mints_once(qa_persona):
    """KILLING MUTATION: blank the receipt-read's ``workspace_id`` allowance back to
    ``all((persona_id, workspace_id, created_at))`` and the replay reds
    ``reservation_corrupt``."""

    first = _create()["result"]
    count = len(_instances())
    replay = _create()
    assert "result" in replay, replay
    again = replay["result"]
    assert again["idempotent_replay"] is True
    assert {k: v for k, v in again.items() if k != "idempotent_replay"} == {
        k: v for k, v in first.items() if k != "idempotent_replay"
    }
    assert len(_instances()) == count


def test_an_unseated_create_keeps_the_name_rule(qa_persona):
    _create()
    count = len(_instances())

    taken = _create(idempotency_key="unseated-2", display_name="unseated  ORCHID")
    assert taken["error"]["data"]["reason"] == "agent_name_taken"
    assert taken["error"]["data"]["rolled_back"] is True
    # No seat, so no placement id to name (an empty one reads as a placement that has none).
    assert "placement_id" not in taken["error"]["data"]

    nameless = _create(idempotency_key="unseated-3", display_name="")
    assert nameless["error"]["data"]["reason"] == "agent_name_required"
    assert len(_instances()) == count


@pytest.mark.parametrize(
    "seat_param",
    [{"position": [1.0, 2.0]}, {"placement_id": "qa_agent_9"}, {"skills": []}],
    ids=["position", "placement_id", "skills"],
)
def test_a_seats_param_with_no_workspace_is_refused_and_writes_nothing(qa_persona, seat_param):
    """KILLING MUTATION: empty ``UNSEATED_REFUSED_PARAMS`` and every case reds: the
    create makes an unseated agent the caller meant to seat."""

    before = set(_instances())
    reply = _create(**seat_param)
    assert reply["error"]["code"] == serve_rpc.ERR_INVALID_PARAMS
    assert reply["error"]["data"]["reason"] == "workspace_id_required"
    assert set(_instances()) == before


def test_a_place_with_no_workspace_is_still_refused(qa_persona):
    """KILLING MUTATION: drop ``not seat_optional or`` in ``normalize_agent_create``
    (or set ``AgentPlace.SEAT_OPTIONAL = True``) and the place answers instead."""

    before = set(_instances())
    reply = _call(
        "runtime.agent.place",
        {"persona_id": "qa", "idempotency_key": "unseated-place", "display_name": "A seat"},
    )
    assert reply["error"]["data"]["reason"] == "workspace_id_required"
    assert set(_instances()) == before


def test_the_cli_independent_agent_lowers_to_the_one_maker(monkeypatch):
    """KILLING MUTATION: put the CLI's own ``agent_create_lock`` +
    ``create_independent_agent`` back in ``_create_independent_instance`` and the
    one maker is never asked."""

    import agent_runtime.agent_create as agent_create
    from hermes_cli.harness_parts.persona import lifecycle_commands

    asked: list[dict] = []

    def spy(store, **identity):
        asked.append(identity)
        return "made"

    monkeypatch.setattr(agent_create, "mint_new_agent", spy)
    args = SimpleNamespace(source_instance_id=None, client_message_id="cli-key", workspace_id=None, realm_id=None)
    made = lifecycle_commands._create_independent_instance(
        args, "qa", placement_id=None, display_name="Cli Orchid", owner=None
    )
    assert made == "made"
    assert asked == [{
        "source_persona_id": "qa",
        "source_instance_id": None,
        "placement_id": None,
        "creation_key": "cli-key",
        "display_name": "Cli Orchid",
        "workspace_id": None,
        "realm_id": None,
        "client_scope": None,
    }]
