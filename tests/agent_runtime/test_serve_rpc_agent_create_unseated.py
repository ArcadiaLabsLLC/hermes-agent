"""``runtime.agent.create`` with no ``workspace_id`` makes an UNSEATED agent.

Row ``RT-ONE-CREATE-VERB-MAKES-AN-AGENT-WITH-OR-WITHOUT-A-WORKSPACE`` (review
w1118a.69): the one create verb also makes an agent no workspace seats — the
same maker (``agent_create.mint_new_agent`` -> ``create_independent_agent``), the
same name rule and the same idempotency receipt, with the placement and skills
phases skipped. A place is a seat and still needs a workspace.

Rows ``RT-FU-A-NEW-AGENT-MADE-WITH-NO-WORKSPACE-HAS-NO-INSTANCE-UNTIL-IT-IS-PLACED`` and
``RT-FU-CREATE-INDEPENDENT-COPY-LEAVES-AN-INSTANCE-PLACED-NOWHERE`` (w1122b-hmcreate,
owner 2026-11-21: every live agent is a placed instance): the unseated create makes
the agent's TEMPLATE only, its persona and profile, and no instance; its first New
chat places one in the Default workspace.

The witnesses are the stores, never the reply alone: the instance rows read off
disk (none was added), the persona store (the new agent is there), the office (no
surface was opened) and the receipt file (``done``, written once, naming no instance).
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

#: The unseated reply, exactly: the agent, and no instance, chat, placement or skills block.
UNSEATED_REPLY_KEYS = {
    "persona_id",
    "profile_id",
    "display_name",
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


def _agent(persona_id: str):
    from agent_runtime.store import AgentStore

    return AgentStore().get(persona_id)


def test_a_create_with_no_workspace_makes_an_unseated_agent(qa_persona):
    """KILLING MUTATION: restore the unconditional ``workspace_id_required`` raise in
    ``normalize_agent_create`` and this reds on the refusal; drop the
    ``finish_unseated`` branch in ``place_and_finish`` and it reds on the reply's keys."""

    office_before = _office_workspaces()
    reply = _create()

    assert "result" in reply, reply
    result = reply["result"]
    assert set(result) == UNSEATED_REPLY_KEYS
    assert set(result["phases"]) == {"agent_ms", "total_ms"}
    assert result["idempotent_replay"] is False
    assert result["display_name"] == "Unseated Orchid"
    # A NEW agent: its own persona and profile, never the source's.
    assert result["persona_id"] != qa_persona.id
    assert result["profile_id"] and result["profile_id"] != qa_persona.hermes_profile
    made = _agent(result["persona_id"])
    assert (made.hermes_profile, made.display_name) == (result["profile_id"], "Unseated Orchid")
    # Nothing seated: no office surface was opened for it.
    assert _office_workspaces() == office_before

    receipt = _receipt("unseated-1")
    assert receipt["state"] == "done"
    assert receipt["workspace_id"] == ""
    assert receipt["persona_instance_id"] is None


def test_an_unseated_create_makes_a_template_with_no_instance(qa_persona):
    """Rows RT-FU-A-NEW-AGENT-MADE-WITH-NO-WORKSPACE-HAS-NO-INSTANCE-UNTIL-IT-IS-PLACED and
    RT-FU-CREATE-INDEPENDENT-COPY-LEAVES-AN-INSTANCE-PLACED-NOWHERE: no instance row is written,
    so none stands in no workspace.

    KILLING MUTATION (run 2026-11-22): send ``mint_new_agent``'s no-workspace arm to
    ``create_independent_agent`` -> red (the create is refused by its fence, or, with the
    fence dropped too, an instance with ``workspace_id`` None is written)."""

    before = set(_instances())
    result = _create()["result"]

    assert set(_instances()) == before
    assert not any(i.persona_id == result["persona_id"] for i in _instances().values())


def test_the_first_new_chat_with_an_unseated_agent_places_it_in_the_default_workspace(qa_persona):
    """The template's first chat places its first instance, through the one reuse-or-place rule."""

    from agent_runtime.agent_create.staff import reuse_or_place
    from agent_runtime.default_scope import DEFAULT_WORKSPACE_ID, ensure_default_scope

    ensure_default_scope(seed_active_pointers=False)
    result = _create()["result"]

    instance_id, refusal = reuse_or_place(result["persona_id"])

    assert refusal is None, refusal
    placed = _instances()[instance_id]
    assert (placed.persona_id, placed.workspace_id) == (result["persona_id"], DEFAULT_WORKSPACE_ID)
    assert placed.profile_id == result["profile_id"]


def test_an_independent_agent_instance_is_never_made_in_no_workspace(qa_persona):
    """The maker's own fence: ``create_independent_agent`` seats, so it refuses a create with no
    workspace before it writes anything.

    KILLING MUTATION (run 2026-11-22): drop the ``not workspace_id`` refusal in
    ``create_independent_agent`` -> red (an instance with no workspace is written)."""

    from agent_runtime.persona_assignments import PersonaInstanceStore
    from agent_runtime.persona_assignments.independent import create_independent_agent

    before = set(_instances())
    with pytest.raises(ValueError, match="needs a workspace"):
        create_independent_agent(
            PersonaInstanceStore(), source_persona_id="qa", display_name="Nowhere", creation_key="k-nowhere",
        )
    assert set(_instances()) == before


def test_an_unseated_create_replays_its_answer_and_mints_once(qa_persona):
    """KILLING MUTATION: blank the receipt-read's ``workspace_id`` allowance back to
    ``all((persona_id, workspace_id, created_at))`` and the replay reds
    ``reservation_corrupt``."""

    first = _create()["result"]
    count = len(_instances())
    personas = len(_personas())
    replay = _create()
    assert "result" in replay, replay
    again = replay["result"]
    assert again["idempotent_replay"] is True
    assert {k: v for k, v in again.items() if k != "idempotent_replay"} == {
        k: v for k, v in first.items() if k != "idempotent_replay"
    }
    assert len(_instances()) == count
    assert len(_personas()) == personas


def test_a_retry_after_a_crash_before_the_receipt_answers_its_own_agent(qa_persona):
    """A crash after the template was written and before the ``done`` receipt: the same key's
    retry finds its own agent and never meets its own name.

    KILLING MUTATION (run 2026-11-22): ask ``name_is_taken`` before the ``made`` lookup in
    ``create_agent_template`` -> red (``agent_name_taken`` on the retry)."""

    import hashlib

    from agent_runtime import paths

    first = _create()["result"]
    paths.agent_create_reservation_path(hashlib.sha256(b"unseated-1").hexdigest()).unlink()
    personas = len(_personas())

    again = _create()
    assert "result" in again, again
    assert again["result"]["persona_id"] == first["persona_id"]
    assert len(_personas()) == personas


def _personas() -> set[str]:
    from agent_runtime.store import AgentStore

    return {p.id for p in AgentStore().list_all()}


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


@pytest.mark.parametrize(("flag", "service"), [("independent_agent", "perform_agent_create"),
                                               ("add_instance", "perform_agent_place")])
def test_the_cli_create_flags_lower_to_the_one_sequence(monkeypatch, capsys, flag, service):
    """``--independent-agent`` and ``--add-instance`` are argv twins of ``runtime.agent.create`` /
    ``runtime.agent.place`` (RT-THE-OLD-CREATE-NO-LONGER-PLACES-OR-COPIES-AN-AGENT): the door maps
    argv onto the method's params and the one sequence does the rest.

    KILLING MUTATION (run 2026-11-21): send ``--add-instance`` back to
    ``PersonaInstanceStore().add_instance`` in ``_cmd_persona_instance_create`` -> the
    ``add_instance`` case reds (the sequence is never asked)."""

    import agent_runtime.agent_create as agent_create
    from agent_runtime.agent_create.outcome import AgentCreateOutcome
    from hermes_cli.harness_parts.persona import lifecycle_commands

    asked: list[tuple[str, dict, dict]] = []

    def spy(name):
        def run(params, **kwargs):
            asked.append((name, params, kwargs))
            return AgentCreateOutcome(result={"persona_instance_id": "personainst_made", "persona_id": "made",
                                              "default_chat_session_id": "persona_chat_made"})
        return run

    for name in ("perform_agent_create", "perform_agent_place"):
        monkeypatch.setattr(agent_create, name, spy(name))
    monkeypatch.setattr(lifecycle_commands, "_persona_by_id", lambda cfg, persona_id: SimpleNamespace(id="qa"))
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: None)
    args = SimpleNamespace(
        json=True, persona_id="qa", title="t", display_name="Cli Orchid", requested_by="cli", coordinator_id=None,
        client_message_id="cli-key", client_scope=None, session_id=None, workspace_id="ws_1", realm_id=None,
        placement_id=None, source_instance_id=None, add_instance=flag == "add_instance",
        independent_agent=flag == "independent_agent",
    )

    assert lifecycle_commands._cmd_persona_instance_create(args) == 0
    assert [name for name, _params, _kw in asked] == [service]
    _name, params, kwargs = asked[0]
    assert params == {"persona_id": "qa", "display_name": "Cli Orchid", "workspace_id": "ws_1",
                      "idempotency_key": "cli-key"}
    if service == "perform_agent_place":
        assert kwargs["requested_by"] == "operator"
    row = json.loads(capsys.readouterr().out)
    assert (row["ok"], row["session_id"], row["persona_instance_id"]) == (True, "persona_chat_made",
                                                                          "personainst_made")
