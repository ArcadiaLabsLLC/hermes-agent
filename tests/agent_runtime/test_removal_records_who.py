"""A removed agent's record and the activity log say who removed it, never ``null``.

Row ``RT-RETIRED-AGENT-RECORD-SAYS-WHO-REMOVED-IT`` (review w1118a.53 D9). Seen 2026-11-19: the owner
removed Base Agent from the testv4 level; the retire receipt read ``requested_by: null``, the
``persona_instance.retired`` event named no actor and ``office.actor.removed`` said only
``instance_reaped``. Every retire and removal verb now records an actor through ONE helper
(``agent_runtime.request_actor``): the person behind Eternia's authenticated call, the agent instance
that asked, or ``unknown``. Each witness is what the store and the event log persisted.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_runtime import serve_rpc
from agent_runtime.agent_retire import perform_agent_retire
from agent_runtime.call_authorization import LOCAL_CONSOLE, RpcCaller
from agent_runtime.serve_rpc.protocol import RpcContext
from tests.agent_runtime.test_agent_copy_delete import _copy, _delete
from tests.agent_runtime.test_agent_retire_service import (
    WORKSPACE,
    _payloads,
    _place,
    qa_persona,  # noqa: F401 — the fixture, re-exported for this file
    seeded_workspace,  # noqa: F401 — the fixture, re-exported for this file
)


def _receipt(ack: dict) -> dict:
    return json.loads(Path(ack["retire_receipt_path"]).read_text(encoding="utf-8"))


def _retire_over_rpc(instance_id: str, caller: RpcCaller) -> dict:
    reply = serve_rpc.handle_request(
        {"jsonrpc": "2.0", "id": "r1", "method": "runtime.agent.retire",
         "params": {"persona_instance_id": instance_id, "reason": "placement removed from Mission Office"}},
        RpcContext(caller=caller, transport="socket"),
    )
    assert "result" in reply, reply
    return reply["result"]


def test_eternias_retire_records_the_operator_on_the_receipt_and_both_events(qa_persona, seeded_workspace):
    # Mutation: pass the bare ``requested_by`` param in ``perform_agent_retire`` again -> the
    # receipt reads null (Eternia sends none) and the first assert reds.
    placed = _place()

    ack = _retire_over_rpc(placed["persona_instance_id"], LOCAL_CONSOLE)

    assert _receipt(ack)["requested_by"] == "operator"
    (retired,) = _payloads("persona_instance.retired")
    assert retired["requested_by"] == "operator"
    assert retired["activity"] == f"You removed QA Agent from seed {WORKSPACE}"
    assert [p["requested_by"] for p in _payloads("office.actor.removed")] == ["operator"]


def test_a_paired_device_is_named_as_the_device(qa_persona, seeded_workspace):
    placed = _place()
    phone = RpcCaller(kind="device", transport="gateway", device_id="phone-7", device_tier="console")

    ack = _retire_over_rpc(placed["persona_instance_id"], phone)

    assert ack["requested_by"] == "device:phone-7"
    assert _payloads("persona_instance.retired")[0]["activity"].startswith("A paired device (phone-7) removed")


def test_an_agents_own_removal_names_that_agent_instance(qa_persona, seeded_workspace):
    lead = _place("qa_lead_agent_9")
    placed = _place()

    ack = perform_agent_retire(
        {"persona_instance_id": placed["persona_instance_id"], "requested_by": lead["persona_instance_id"]}
    )

    assert ack.result["requested_by"] == lead["persona_instance_id"]
    activity = _payloads("persona_instance.retired")[0]["activity"]
    assert activity == f"{lead['display_name']} removed {placed['display_name']} from seed {WORKSPACE}"


def test_a_removal_nobody_named_records_unknown(qa_persona, seeded_workspace):
    # Mutation: return ``requested_by`` unchanged from ``request_actor`` -> the receipt reads null.
    placed = _place()

    ack = perform_agent_retire({"persona_instance_id": placed["persona_instance_id"]})

    assert _receipt(ack.result)["requested_by"] == "unknown"
    assert _payloads("persona_instance.retired")[0]["activity"].startswith("Someone removed QA Agent")
    assert [p["requested_by"] for p in _payloads("office.actor.removed")] == ["unknown"]


def test_an_office_reap_names_who_removed_the_agent(qa_persona, seeded_workspace):
    # Mutation: drop ``requested_by=`` from the ``office.actor.removed`` emit in
    # ``_archive_actor_locked`` -> the office event carries no actor.
    placed = _place()

    perform_agent_retire({"persona_instance_id": placed["persona_instance_id"], "requested_by": "operator"})

    (removed,) = _payloads("office.actor.removed")
    assert (removed["reason"], removed["requested_by"]) == ("instance_reaped", "operator")


def test_a_delete_records_who_deleted_it(qa_persona):
    # Mutation: pass ``requested_by="runtime.agent.delete"`` in ``_retire_all`` again -> the retired
    # instance's event names the verb, not who asked.
    copy = _copy()

    reply = _delete(copy["persona"].id)["result"]

    assert reply["requested_by"] == "operator"
    assert {p["requested_by"] for p in _payloads("persona_instance.retired")} == {"operator"}


# ── an agent's own terminal (row RT-AN-AGENT-THAT-REMOVES-ANOTHER-FROM-ITS-TERMINAL-IS-RECORDED-AS-YOU) ──


def _cli(argv: list[str], capsys) -> dict:
    import argparse

    from hermes_cli import harness

    root = argparse.ArgumentParser(prog="hermes")
    harness.build_parser(root.add_subparsers(dest="command"))
    args = root.parse_args([*argv, "--json"])
    assert args.func(args) == 0
    return json.loads(capsys.readouterr().out)


def test_an_agents_terminal_carries_its_chat_session(monkeypatch):
    # Review w1118a.61 D7's premise, checked: the env the terminal tool hands its child
    # (``_make_run_env``, the foreground path) exports the turn's ``HERMES_SESSION_ID``. Mutation:
    # skip ``_inject_session_context_env`` in ``_finalize_child_env`` -> the child gets the
    # process's own id ("operator-shell") and this reds.
    from gateway.session_context import scoped_current_session_id
    from tools.environments.local import _make_run_env

    session = "persona_chat_personainst_lead_0123456789ab"
    monkeypatch.setenv("HERMES_SESSION_ID", "operator-shell")
    with scoped_current_session_id(session):
        child = _make_run_env({})

    assert child["HERMES_SESSION_ID"] == session


def test_an_agents_terminal_retire_records_that_agent_not_you(qa_persona, seeded_workspace, capsys, monkeypatch):
    # Mutation: drop the session check in ``request_actor`` -> the agent's own ``--requested-by
    # operator`` wins, the receipt reads "operator" and the first assert reds.
    from agent_runtime.agent_create import perform_agent_place
    from agent_runtime.models import AutonomyLevel
    from agent_runtime.store import AgentStore

    # Since review w1118a.62 D1 the terminal's agent is also held to its coordinator scope: an
    # autonomous agent may retire a seat it spawned itself (an operator-placed one asks you).
    qa_persona.autonomy = AutonomyLevel.AUTONOMOUS
    AgentStore().save(qa_persona)
    lead = _place("qa_lead_agent_9")
    placed = perform_agent_place(
        {"persona_id": "qa", "workspace_id": WORKSPACE, "idempotency_key": "lead-spawned"},
        requested_by=lead["persona_instance_id"],
    ).result
    monkeypatch.setenv("HERMES_SESSION_ID", lead["default_chat_session_id"])

    ack = _cli(["harness", "persona", "instance", "retire", placed["persona_instance_id"],
                "--requested-by", "operator"], capsys)["persona_instance_retired"]

    assert _receipt(ack)["requested_by"] == lead["persona_instance_id"]
    (retired,) = _payloads("persona_instance.retired")
    assert retired["activity"] == f"{lead['display_name']} removed {placed['display_name']} from seed {WORKSPACE}"


def test_the_operators_own_shell_still_records_you(qa_persona, seeded_workspace, capsys, monkeypatch):
    placed = _place()
    monkeypatch.delenv("HERMES_SESSION_ID", raising=False)

    _cli(["harness", "persona", "instance", "retire", placed["persona_instance_id"]], capsys)

    # The verb's own default actor (``--requested-by cli``) is one of the operator's names.
    assert _payloads("persona_instance.retired")[0]["activity"].startswith("You removed QA Agent")


def test_an_agents_terminal_office_remove_records_that_agent(qa_persona, seeded_workspace, capsys, monkeypatch):
    # Mutation: drop ``requested_by=terminal_request_actor()`` in ``_cmd_office_actor_remove`` -> the
    # event reads "operator" (the verb's own ``updated_by``) and this reds.
    lead = _place("qa_lead_agent_9")
    placed = _place()
    monkeypatch.setenv("HERMES_SESSION_ID", lead["default_chat_session_id"])

    _cli(["harness", "office", "actor-remove", "--workspace", WORKSPACE, "--actor", placed["actor_key"]], capsys)

    assert [p["requested_by"] for p in _payloads("office.actor.removed")] == [lead["persona_instance_id"]]
