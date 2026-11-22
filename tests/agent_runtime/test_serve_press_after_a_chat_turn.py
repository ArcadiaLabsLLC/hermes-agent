"""A press you make in Eternia acts as you, even after an agent's chat turn ran in the same serve.

Row ``RT-FU-AN-ETERNIA-PRESS-AFTER-A-CHAT-TURN-IS-JUDGED-AS-THAT-CHATS-AGENT`` (review w1118a.67 D2,
ruling (a)). Seen live 2026-11-20: Mission Control's Create independent copy of Base worked on its
first press and, after two chat turns in the same serve, was refused ``spawn_scope_exhausted``. The
CLI coordinator doors read the asker from ``HERMES_SESSION_ID`` (``terminal_request_actor``), and a
turn's agent build publishes its session process-wide (``agent_init._publish_session_id`` writes
``os.environ``), so a later press the serve ran for Eternia read that chat's session and was judged as
its agent. The serve now binds the session empty for every request that is not a chat turn.

Real serve, real CLI handlers for create and retire; the turn is the real ``_publish_session_id`` an
agent build calls. Killing mutation (recorded in the landing commit): bind ``None`` for every request
in ``ArgvLanes._dispatch_guarded`` (no empty session for a press) -> the create asks you to confirm
(``needs_operator_confirm``), the retire is refused ``operator_placed_target``, the steer reads the
lead's instance and every assert of the first test reds.
"""

from __future__ import annotations

import json

from agent_runtime.models import AutonomyLevel
from tests.agent_runtime.test_serve_socket_lane import _read_until, client, running_serve
from tests.agent_runtime.test_serve_rpc_agent_create import (
    WORKSPACE,
    _instances,
    dev_persona,  # noqa: F401 — the fixture, re-exported for this file
    qa_persona,  # noqa: F401 — the fixture, re-exported for this file
)
from tests.agent_runtime.test_terminal_coordinator_doors import _lead, _parser, _qa_seats

_TURN = ["harness", "mission-chat", "message", "--client-message-id"]


def _serve_dispatch(session_id: str, seen: dict):
    """The serve's dispatch: a turn as an agent build leaves it, the persona doors as the CLI runs them."""

    def dispatch(argv: list[str]) -> int:
        from agent.agent_init import _publish_session_id
        from hermes_cli.harness_parts.persona.lifecycle_commands import terminal_request_actor
        import os

        from tools.environments.local import _inject_session_context_env

        tail = argv[1:]
        if tail[:2] == ["mission-chat", "message"]:
            if tail[-1] == "build":
                _publish_session_id(session_id)  # what the turn's agent build does
            # What this turn's agent terminal carries: the process's own value, then the bridge's word.
            terminal_env = {"HERMES_SESSION_ID": os.environ.get("HERMES_SESSION_ID", "")}
            _inject_session_context_env(terminal_env)
            seen[f"terminal {tail[-1]}"] = terminal_env.get("HERMES_SESSION_ID")
            return 0
        if tail[:3] == ["persona", "instance", "steer"]:
            seen["steer"] = terminal_request_actor()  # the asker the steer door reviews
            return 0
        args = _parser().parse_args([*argv, "--json"])
        return args.func(args)

    return dispatch


def _send(connection, rid: str, argv: list[str]) -> tuple[int, dict | None]:
    connection.send({"id": rid, "argv": argv})
    lines: list[str] = []
    while True:
        frame = connection.read_frame()
        assert frame is not None, f"connection closed before {rid}'s exit"
        if frame.get("event") == "line":
            lines.append(frame["line"])
        elif frame.get("event") == "exit":
            raw = "\n".join(lines)
            return frame["code"], (json.loads(raw[raw.index("{"): raw.rindex("}") + 1]) if "{" in raw else None)


def test_a_press_after_a_chat_turn_acts_as_you(qa_persona, dev_persona, monkeypatch):
    # The live incident: a propose-only lead (zero budget) ran a turn; your presses come after it.
    monkeypatch.delenv("HERMES_SESSION_ID", raising=False)  # restored after the turn's process-wide write
    from agent_runtime.agent_create import perform_agent_place

    lead = _lead(dev_persona, AutonomyLevel.PROPOSE_ONLY)
    placed = perform_agent_place({"persona_id": "qa", "workspace_id": WORKSPACE, "idempotency_key": "yours"})
    assert placed.refusal is None, placed.refusal
    yours = placed.result["persona_instance_id"]
    seen: dict = {}
    create = ["harness", "persona", "instance", "create", "--persona", "qa", "--title", "QA Two",
              "--display-name", "QA Two", "--add-instance", "--workspace", WORKSPACE]

    with running_serve(dispatch=_serve_dispatch(lead["default_chat_session_id"], seen), pool_size=1) as handle:
        with client(handle, name="launcher") as (connection, _hello):
            assert _send(connection, "turn", [*_TURN, "c1", "build"])[0] == 0
            created = _send(connection, "create", create)
            steer = _send(connection, "steer", ["harness", "persona", "instance", "steer", yours])
            retired = _send(connection, "retire", ["harness", "persona", "instance", "retire", yours])

    assert seen["terminal build"] == lead["default_chat_session_id"]
    assert created[0] == 0, created[1]
    (seat,) = [i for i in _qa_seats() if i.id != yours]
    assert seat.spawned_by in (None, "operator"), seat.spawned_by
    assert steer[0] == 0 and seen["steer"] == "operator"
    assert retired[0] == 0, retired[1]
    assert yours not in _instances()


def test_a_later_turn_still_carries_its_chats_session_to_its_terminal(monkeypatch):
    # The other half of the ruling: only an agent's terminal is judged as that agent, so a turn on a
    # resident agent (no build this turn) still hands its terminal the session the build published,
    # and a press between the turns does not wipe it.
    # Mutation: bind "" for every request in ``_dispatch_guarded`` -> the second turn's terminal
    # carries "" and its agent would be judged as you.
    monkeypatch.delenv("HERMES_SESSION_ID", raising=False)
    seen: dict = {}
    with running_serve(dispatch=_serve_dispatch("persona_chat_dev_lead", seen), pool_size=1) as handle:
        with client(handle, name="launcher") as (connection, _hello):
            for rid, argv in (
                ("turn1", [*_TURN, "c1", "build"]),
                ("press", ["harness", "persona", "instance", "steer", "personainst_any"]),
                ("turn2", [*_TURN, "c2", "reuse"]),
            ):
                connection.send({"id": rid, "argv": argv})
                assert _read_until(connection, "exit")["code"] == 0

    assert seen["steer"] == "operator"
    assert seen["terminal build"] == "persona_chat_dev_lead"
    assert seen["terminal reuse"] == "persona_chat_dev_lead"
