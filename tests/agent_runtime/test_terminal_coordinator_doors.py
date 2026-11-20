"""An agent typing a coordinator verb in its terminal is held to its own settings, never to its argv.

Row ``RT-AN-AGENT-THAT-ADDS-INSTANCES-FROM-ITS-TERMINAL-SKIPS-ITS-SPAWN-BUDGET`` (review w1118a.62 D1,
ruling (a)). Seen live 2026-11-20: Neko Mission Lead (shipped, ``propose_only``, zero budget) placed
two seats by running ``hermes harness persona instance create --add-instance`` in its terminal;
nothing refused it and each seat read ``spawned_by: operator``. The CLI coordinator doors (create,
open-chat, retire, steer, update-profile, set-model) now read the asker from the terminal's chat
session (``terminal_request_actor``) and the scope only from the store and the settings
(``agent_create.staff.coordinator_scope``, the add-instance tool's own); the five argv scope flags are
gone. Every witness is the persona-instance store or the payload the door printed.
"""

from __future__ import annotations

import argparse
import json

import pytest

from agent_runtime.models import AutonomyLevel
from tests.agent_runtime.test_serve_rpc_agent_create import (
    WORKSPACE,
    _instances,
    _seed_workspace,
    dev_persona,  # noqa: F401 — the fixture, re-exported for this file
    qa_persona,  # noqa: F401 — the fixture, re-exported for this file
)

#: The flags review w1118a.62 D1 deleted: a caller may not declare its own budget or kill rights.
DELETED_SCOPE_FLAGS = (
    ("--coordinator-max-spawns", "5"),
    ("--coordinator-spawns-used", "0"),
    ("--coordinator-may-kill-own", None),
    ("--coordinator-no-kill-own", None),
    ("--coordinator-may-kill-others", None),
)


def _parser() -> argparse.ArgumentParser:
    from hermes_cli import harness

    root = argparse.ArgumentParser(prog="hermes")
    harness.build_parser(root.add_subparsers(dest="command"))
    return root


def _run(argv: list[str], capsys) -> tuple[int, dict]:
    args = _parser().parse_args([*argv, "--json"])
    code = args.func(args)
    raw = capsys.readouterr().out
    return code, json.loads(raw[raw.index("{"): raw.rindex("}") + 1])


def _lead(dev_persona, autonomy: AutonomyLevel) -> dict:
    """A seated ``dev`` instance with ``autonomy``: the agent whose terminal runs the verbs."""

    from agent_runtime.agent_create import perform_agent_place
    from agent_runtime.store import AgentStore

    dev_persona.autonomy = autonomy
    AgentStore().save(dev_persona)
    _seed_workspace()
    placed = perform_agent_place({"persona_id": "dev", "workspace_id": WORKSPACE, "idempotency_key": "lead"})
    assert placed.refusal is None, placed.refusal
    return placed.result


def _in_terminal_of(lead: dict, monkeypatch) -> None:
    """What the terminal tool exports to its child: the agent turn's chat session."""

    monkeypatch.setenv("HERMES_SESSION_ID", lead["default_chat_session_id"])


def _qa_seats() -> list:
    return [i for i in _instances().values() if i.persona_id == "qa"]


def _add_instance_argv(name: str) -> list[str]:
    # The agent names itself the operator, as an agent scripting the verb may: it changes nothing.
    return ["harness", "persona", "instance", "create", "--persona", "qa", "--title", name,
            "--display-name", name, "--add-instance", "--workspace", WORKSPACE, "--requested-by", "operator"]


def test_an_agents_terminal_add_instance_past_its_budget_is_refused(qa_persona, dev_persona, capsys, monkeypatch):
    # The live incident: a propose-only lead (zero budget) adds a seat from its terminal.
    # Mutation: drop the session read in ``chat_coordinator._coordinator_actor_id`` -> no coordinator
    # is seen, the seat is placed with exit 0 and every assert reds.
    lead = _lead(dev_persona, AutonomyLevel.PROPOSE_ONLY)
    _in_terminal_of(lead, monkeypatch)

    code, payload = _run(_add_instance_argv("QA Extra"), capsys)

    assert code == 2
    assert payload["status"] == "needs_operator_confirm"
    assert payload["coordinator_id"] == lead["persona_instance_id"]
    assert payload["settings"] == {"autonomy": "propose_only", "max_spawns": 0, "spawns_used": 0}
    assert "autonomy is propose_only" in payload["message"]
    assert "agent_runtime.coordinator_permissions.max_spawns" in payload["message"]
    assert _qa_seats() == []


def test_open_chat_add_instance_from_an_agents_terminal_is_refused_too(qa_persona, dev_persona, capsys, monkeypatch):
    # The second --add-instance door reads the same asker and scope.
    # Mutation: hand ``_cmd_persona_instance_open_chat`` a scope not read from the store
    # (``CoordinatorPermissionScope(max_spawns=99)``) -> the seat is placed and the asserts red.
    lead = _lead(dev_persona, AutonomyLevel.PROPOSE_ONLY)
    _in_terminal_of(lead, monkeypatch)

    code, payload = _run(["harness", "persona", "instance", "open-chat", "--persona", "qa", "--add-instance",
                          "--workspace", WORKSPACE, "--display-name", "QA Extra"], capsys)

    assert code == 2
    assert payload["status"] == "needs_operator_confirm"
    assert "autonomy is propose_only" in payload["message"]
    assert _qa_seats() == []


def test_a_seat_placed_within_budget_names_that_agent_and_counts_against_it(qa_persona, dev_persona, capsys,
                                                                             monkeypatch):
    # An autonomous agent's budget is max(1, the install's max_spawns=0) = one seat.
    # Mutation: stamp ``coordinator_id=None`` in the create door's ``_maybe_stamp_spawned_by`` ->
    # the seat reads ``operator``, is not counted, and the second create is not refused.
    lead = _lead(dev_persona, AutonomyLevel.AUTONOMOUS)
    _in_terminal_of(lead, monkeypatch)

    first_code, _ = _run(_add_instance_argv("QA One"), capsys)
    second_code, refused = _run(_add_instance_argv("QA Two"), capsys)

    assert first_code == 0
    (seat,) = _qa_seats()
    assert seat.spawned_by == lead["persona_instance_id"]
    assert second_code == 2
    assert refused["settings"] == {"autonomy": "autonomous", "max_spawns": 1, "spawns_used": 1}
    assert "Your spawn budget is 1 and you have used 1" in refused["message"]


def test_an_agents_terminal_retire_grants_itself_no_kill_rights(qa_persona, dev_persona, capsys, monkeypatch):
    # A seat another coordinator spawned; the asking agent's settings never let it kill another's.
    # The argv form is gone (argparse refuses it, pinned below), so the old attribute is handed in
    # directly, as a door that read it would see it.
    # Mutation: read may-kill rights off args again in ``_cmd_persona_instance_retire``
    # (``scope.may_kill_others = getattr(args, "coordinator_may_kill_others")``) -> the seat is
    # retired and the asserts red.
    from agent_runtime.agent_create import perform_agent_place
    from hermes_cli.harness_parts.persona import instance_commands

    lead = _lead(dev_persona, AutonomyLevel.AUTONOMOUS)
    other = perform_agent_place({"persona_id": "qa", "workspace_id": WORKSPACE, "idempotency_key": "other"},
                                requested_by="personainst_some_other_lead")
    assert other.refusal is None, other.refusal
    target = other.result["persona_instance_id"]
    _in_terminal_of(lead, monkeypatch)

    code = instance_commands._cmd_persona_instance_retire(argparse.Namespace(
        persona_instance_id=target, reason="cleanup", requested_by="operator", coordinator_id=None,
        coordinator_may_kill_own=True, coordinator_may_kill_others=True, correlation_id=None, json=True))
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["reason"] == "kill_other_not_granted"
    assert payload["permission_scope"]["may_kill_others"] is False
    assert target in _instances()


def test_an_agents_terminal_retire_of_a_seat_you_placed_asks_you(qa_persona, dev_persona, capsys, monkeypatch):
    # Before D1 an agent's terminal retire ran no coordinator review at all unless the agent declared
    # itself ``--requested-by coordinator``. Mutation: drop the session read in
    # ``_coordinator_actor_id`` -> the operator-placed seat is retired (exit 0) and this reds.
    from agent_runtime.agent_create import perform_agent_place

    lead = _lead(dev_persona, AutonomyLevel.AUTONOMOUS)
    yours = perform_agent_place({"persona_id": "qa", "workspace_id": WORKSPACE, "idempotency_key": "yours"})
    assert yours.refusal is None, yours.refusal
    target = yours.result["persona_instance_id"]
    _in_terminal_of(lead, monkeypatch)

    code, payload = _run(["harness", "persona", "instance", "retire", target, "--requested-by", "operator"],
                         capsys)

    assert code == 2
    assert payload["reason"] == "operator_placed_target"
    assert target in _instances()


@pytest.mark.parametrize("verb", ["steer", "update-profile"])
def test_steer_and_update_profile_review_the_terminals_agent_against_the_stores_scope(
        verb, qa_persona, dev_persona, monkeypatch):
    # Mutation: drop the session read in ``_coordinator_actor_id`` -> the review is never asked (the
    # agent named itself the operator) and ``seen`` stays empty.
    from agent_runtime.agent_create import perform_agent_place
    from hermes_cli.harness_parts.persona import instance_commands

    lead = _lead(dev_persona, AutonomyLevel.PROPOSE_ONLY)
    seat = perform_agent_place({"persona_id": "qa", "workspace_id": WORKSPACE, "idempotency_key": "seat"})
    target = seat.result["persona_instance_id"]
    _in_terminal_of(lead, monkeypatch)
    seen: list[tuple] = []

    def review(action, scope, target_instance=None, *, actor, coordinator_id):
        seen.append((actor, scope))
        from agent_runtime.coordinator_permissions import CoordinatorBudgetReview

        return CoordinatorBudgetReview(ok=False, needs_operator_confirm=True, reason="spy", scope=scope)

    monkeypatch.setattr(instance_commands, "review_coordinator_budget", review)
    args = argparse.Namespace(
        persona_instance_id=target, requested_by="operator", coordinator_id=None, coordinator_max_spawns=99,
        coordinator_may_kill_others=True, parent_instance_id=lead["persona_instance_id"], add_parent=None,
        remove_parent=None, set_parents=None, goal_id=None, detach=False, json=True)
    handler = {"steer": instance_commands._cmd_persona_instance_steer,
               "update-profile": instance_commands._cmd_persona_instance_update_profile}[verb]

    assert handler(args) == 2
    ((actor, scope),) = seen
    assert actor == lead["persona_instance_id"]
    assert (scope.max_spawns, scope.may_kill_own, scope.may_kill_others) == (0, False, False)


@pytest.mark.parametrize("verb", [
    ["create", "--persona", "qa", "--title", "t"],
    ["open-chat", "--persona", "qa"],
    ["retire", "personainst_x"],
    ["steer", "personainst_x"],
    ["update-profile", "personainst_x"],
    ["set-model", "personainst_x"],
])
@pytest.mark.parametrize(("flag", "value"), DELETED_SCOPE_FLAGS)
def test_no_coordinator_door_takes_a_scope_flag(verb, flag, value):
    # Mutation: put any of the five lines back in ``common_args._add_coordinator_permission_args``
    # -> that flag parses and its rows red.
    argv = ["harness", "persona", "instance", *verb, flag, *([value] if value else [])]

    with pytest.raises(SystemExit):
        _parser().parse_args(argv)
