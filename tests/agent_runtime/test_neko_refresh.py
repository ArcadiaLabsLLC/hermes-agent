"""Regression coverage for a persona refresh with a concurrent turn.

The normal controls use the production chat and history RPCs. The contention cases also open
the saved chat from a second native gateway client, an explicit setup for the ownership race.
"""
from collections import Counter
from contextlib import ExitStack
from threading import Event

import pytest

from agent_runtime import chat_session_scope, operator_gateway_turn, serve_rpc
from agent_runtime.conversations.in_process_peer import start_in_process_worker
from agent_runtime.models import AgentPersona
from agent_runtime.operator_turn_policy import OperatorTurn
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_continuity.runtime_registry import (
    initialize_persona_chat_runtime_registry,
    reset_persona_chat_runtime_registry,
)
from agent_runtime.store import AgentStore
from hermes_constants import get_hermes_home
from tests.agent_runtime.held_model_turn import HeldModel, OWNER, operator_turn
from tests.agent_runtime.test_serve_rpc_open_chat import WORKSPACE, _call, placed_agent, qa_persona

pytestmark = pytest.mark.timeout(180)

NEKO = "neko_mission_lead_beta"
OTHER_MESSAGE = "second-persona-hold-791"
NATIVE_MESSAGE = "native-client-hold-694"
OPERATOR_MESSAGE = "neko-refresh-message-693"


def open_chat(persona, instance, **options):
    response = _call(dict(persona_id=persona, persona_instance_id=instance, client_scope=OWNER, **options))
    assert "result" in response, response
    return response["result"]["session_id"]


def refresh_neko(instance, root):
    assert open_chat(NEKO, instance, session_id=root) == root
    response = serve_rpc.handle_request(dict(
        jsonrpc="2.0", id="refresh", method="runtime.persona.chat.history", params={"session_id": root}
    ))
    assert "result" in response, response
    assert any("neko-seed-691" in str(row.get("text")) for row in response["result"]["messages"])


@pytest.mark.parametrize("mode", ["cold", "warm", "owner_released", "attached_idle", "native_busy", "observer_exit", "owner_exit"])
def test_refresh_with_a_second_persona_at_the_model(mode, monkeypatch, placed_agent):
    from tui_gateway import server

    home = get_hermes_home()
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    builds = Counter()
    construct = OperatorTurn.construct_agent

    def count_build(turn):
        builds[turn.request.root_chat_session_id] += 1
        return construct(turn)

    monkeypatch.setattr(OperatorTurn, "construct_agent", count_build)
    AgentStore().save(AgentPersona(NEKO, "Neko Mission Lead Beta", "alice_supervisor", None, None, None,
                                   system_prompt_path=""))
    neko = PersonaInstanceStore().add_instance(persona_id=NEKO, workspace_id=WORKSPACE,
                                              placement_id="neko_agent_07c76f93")
    other = placed_agent["persona_instance_id"]
    with ExitStack() as cleanup:
        prior_homes = set(operator_gateway_turn._peers)

        @cleanup.callback
        def release_test_sessions():
            for actor in list(operator_gateway_turn._actors.values()):
                if actor.home not in prior_homes:
                    actor.close()
            for store, peer in list(operator_gateway_turn._peers.items()):
                if store not in prior_homes:
                    peer.close()

        model = HeldModel()
        cleanup.callback(model.close)
        model.configure(home)
        if mode == "warm":
            initialize_persona_chat_runtime_registry(enabled=True)
            cleanup.callback(reset_persona_chat_runtime_registry)
        at_model = {OTHER_MESSAGE: Event(), NATIVE_MESSAGE: Event()}

        def hold(body):
            for text, event in at_model.items():
                if text in str(body["messages"][-1]["content"]):
                    event.set()
                    return True
            return False

        def dispatches(text):
            return sum(text in str(body["messages"][-1]["content"]) for body in model.requests)

        model.hold_if = hold
        root = open_chat(NEKO, neko.id, new_session=True, idempotency_key="mint-neko")
        second = open_chat("qa", other, new_session=True, idempotency_key="mint-second")
        assert root != second
        assert operator_turn(neko.id, root, "seed", "neko-seed-691").join(55)[0] == 0
        run = operator_turn(other, second, "held", OTHER_MESSAGE)
        cleanup.callback(run.join, 65)
        cleanup.callback(model.release.set)
        assert at_model[OTHER_MESSAGE].wait(40)
        refresh_neko(neko.id, root)
        sid = None
        if mode not in {"cold", "warm"}:
            # End only the test's idle Neko actor so a separate gateway client can open the same
            # durable chat. Never engineer the mismatch by editing either registry's map.
            actor = operator_gateway_turn._actors.get(root)
            if actor is not None:
                actor.close()
            store = chat_session_scope.resolve_process_chat_scope().db_path.parent

            terminal = Event()

            def receive(frame):
                event = frame.get("params", {})
                if event.get("type") == "message.complete" and event.get("session_id") == sid:
                    terminal.set()

            def native_client(on_frame=lambda _: None):
                peer = start_in_process_worker(store, receive=on_frame, lost=lambda: None)
                cleanup.callback(peer.close)
                return peer

            native = native_client(receive if mode != "owner_exit" else lambda _: None)
            sid = native.call("session.resume", {"session_id": root, "lazy": True})["session_id"]
            if mode == "owner_released":
                native.close()
                assert sid not in server._sessions
            if mode in {"native_busy", "observer_exit", "owner_exit"}:
                native.call("prompt.submit", {"session_id": sid, "text": NATIVE_MESSAGE})
                assert at_model[NATIVE_MESSAGE].wait(25)
            if mode in {"observer_exit", "owner_exit"}:
                observer = native_client(receive if mode == "owner_exit" else lambda _: None)
                seen = observer.call("session.resume", {"session_id": root, "observe_only": True})
                assert seen["session_id"] == sid and seen["running"] is True
                departing = native if mode == "owner_exit" else observer
                departing.close()
                assert departing.execution_possible, "a surviving busy session can still write"
            refresh_neko(neko.id, root)

        before = builds[root]
        if mode in {"observer_exit", "owner_exit"}:
            code, result = None, {}
        else:
            code, result = operator_turn(neko.id, root, "new-send", OPERATOR_MESSAGE).join(55)
        session_live = sid in server._sessions
        assert run.thread.is_alive() and not model.release.is_set()
        model.release.set()
        assert run.join(60)[0] == 0 and dispatches(OTHER_MESSAGE) == 1
        assert not any(OTHER_MESSAGE in str(body["messages"]) and "neko-seed-691" in str(body["messages"])
                       for body in model.requests)
        error = result.get("error_kind")
        refusal = result.get("provider_refusal") or {}
        print(f"{mode}: exit={code} builds={builds[root]-before} sends={dispatches(OPERATOR_MESSAGE)} "
              f"native_session_live={session_live} other_turn=completed_once error={error} "
              f"detail={refusal.get('message')}")
        if mode in {"cold", "warm", "owner_released"}:
            assert code == 0 and dispatches(OPERATOR_MESSAGE) == 1
            assert builds[root] - before == (0 if mode == "warm" else 1)
        else:
            assert session_live, "a second client's attachment closed the native owner's session"
            if mode in {"native_busy", "observer_exit", "owner_exit"}:
                assert terminal.wait(30), "the remaining client never received its terminal frame"
                assert dispatches(NATIVE_MESSAGE) == 1
                if mode in {"observer_exit", "owner_exit"}:
                    (observer if mode == "owner_exit" else native).close()
                    assert not departing.execution_possible
            if mode in {"attached_idle", "native_busy"}:
                assert code != 0 and error == "chat_busy"
                assert not refusal and dispatches(OPERATOR_MESSAGE) == 0
                native.close()
                assert sid not in server._sessions
                assert operator_turn(neko.id, root, "after-release", OPERATOR_MESSAGE).join(55)[0] == 0
                assert dispatches(OPERATOR_MESSAGE) == 1
        for chat, expected, foreign in ((root, "neko-seed-691", OTHER_MESSAGE),
                                        (second, OTHER_MESSAGE, "neko-seed-691")):
            history = serve_rpc.handle_request(dict(jsonrpc="2.0", id="history", method="runtime.persona.chat.history",
                                                    params={"session_id": chat}))["result"]["messages"]
            assert any(expected in str(row.get("text")) for row in history)
            assert all(foreign not in str(row.get("text")) for row in history)
