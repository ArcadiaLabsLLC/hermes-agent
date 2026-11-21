"""The operator chat's turn runs on the gateway engine (row RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT).

Each test names the mutation that turns it red.
"""

import threading
import traceback

import pytest

from agent_runtime import operator_gateway_turn
from agent_runtime.profile_runner import AgentRunRequest, ProfileAgentRunner
from tests.agent_runtime.test_profile_runner import FakeAgent


class _StackAgent(FakeAgent):
    """Records the stack it converses on, and the message it was handed."""

    stacks: list = []
    messages: list = []

    def run_conversation(self, user_message, system_message=None, task_id=None):
        type(self).stacks.append("".join(traceback.format_stack()))
        type(self).messages.append(user_message)
        return super().run_conversation(user_message, system_message=system_message, task_id=task_id)


def _gateway_session(sid):
    from tui_gateway import server

    return server._sessions.get(sid)


def _run(message="hi", **kwargs):
    _StackAgent.stacks, _StackAgent.messages = [], []
    FakeAgent.response = None
    runner = ProfileAgentRunner(agent_factory=_StackAgent)
    kwargs.setdefault("root_chat_session_id", "root_operator_chat")
    kwargs.setdefault("session_id", kwargs["root_chat_session_id"])
    return runner.run(AgentRunRequest(profile=None, user_message=message, **kwargs))


def test_an_operator_turn_runs_inside_the_gateways_prompt_turn():
    # Red when ProfileAgentRunner._converse runs the turn's policy itself (``return turn.converse(agent)``
    # in place of ``operator_gateway_turn.run_turn``): the agent then converses off the gateway's turn.
    result = _run()

    assert result.final_response == "ok"
    assert len(_StackAgent.stacks) == 1
    assert "tui_gateway/prompt_turn.py" in _StackAgent.stacks[0]
    assert "in _invoke_agent" in _StackAgent.stacks[0]


def test_an_operator_chats_agent_is_built_once_by_the_engines_agent_build(monkeypatch):
    # Red when ``OperatorTurn.open_session`` builds the agent itself (``return self.construct_agent()``
    # in place of ``open_actor(self)``): a second builder beside the gateway's ``_make_agent``, and an
    # actor with no gateway session (the turn is then refused "the chat's gateway session is gone").
    stacks = []
    original = _StackAgent.__init__

    def recording_init(self, **kwargs):
        stacks.append("".join(traceback.format_stack()))
        original(self, **kwargs)

    monkeypatch.setattr(_StackAgent, "__init__", recording_init)

    result = _run(root_chat_session_id="root_built_once")

    assert result.final_response == "ok"
    assert len(stacks) == 1
    assert "tui_gateway/agent_factory.py" in stacks[0] and "in _make_agent" in stacks[0]
    assert "operator_turn_policy.py" in stacks[0] and "in build_agent" in stacks[0]


def test_the_gateway_session_is_an_operator_session_with_the_message_from_the_operator_lane():
    # Red when run_turn submits the request's text (``"text": execution.request.user_message``): the
    # gateway then writes its own user row and hands its text in, and the door no longer takes the turn
    # (``_take`` admits only the empty submit), so the agent runs the bare text on no operator turn.
    _run("the composed message")

    assert _StackAgent.messages and "the composed message" in _StackAgent.messages[0]
    actors = list(operator_gateway_turn._actors.values())
    assert actors
    session = _gateway_session(actors[-1].sid)
    assert session is not None and session.get("source") == operator_gateway_turn.OPERATOR_SOURCE


def test_pin_session_holds_the_resolved_model_and_keeps_first_contact_out():
    # Red when pin_session stops writing ``model_override`` (the gateway's per-turn config sync would
    # switch the agent to the config model) or stops setting ``first_contact_owned``.
    agent = type("A", (), {"model": "m-operator", "provider": "p-operator"})()
    session = {"source": operator_gateway_turn.OPERATOR_SOURCE, "agent": agent}

    operator_gateway_turn.pin_session(session)

    assert session["model_override"] == {"model": "m-operator", "provider": "p-operator"}
    assert session["first_contact_owned"] is True

    other = {"source": "desktop", "agent": agent}
    operator_gateway_turn.pin_session(other)
    assert "model_override" not in other and "first_contact_owned" not in other


def test_an_operator_turn_leaves_the_store_homes_config_alone(tmp_path):
    # Red when the gateway's first-contact note runs for an operator session (the
    # ``first_contact_owned`` skip in ``prompt_turn._stage_first_contact_onboarding_note`` removed): its
    # latch writes ``onboarding.seen.profile_build_offered`` into the store home's config.yaml.
    from hermes_constants import get_hermes_home

    config = get_hermes_home() / "config.yaml"
    before = config.read_text() if config.exists() else None

    _run()

    after = config.read_text() if config.exists() else None
    assert after == before


def test_the_gateways_own_goal_continuation_runs_nothing_on_an_operator_chat(monkeypatch):
    # Red when ``_is_goal_continuation`` is dropped from ``_gateway_turn``: the gateway's follow-up would
    # then be delivered as a second turn, and the goal would continue twice (the operator settle
    # continues it once, from the engine's decision).
    ran = []

    class Agent:
        session_id = "s1"

        def run_conversation(self, *args, **kwargs):
            ran.append(args)
            return {"final_response": "ran"}

    agent = Agent()
    operator_gateway_turn._install_door(agent, "sid-1")
    agent._operator_gateway_actor = operator_gateway_turn._SessionActor("sid-1", "s1", None, "root-1")
    monkeypatch.setattr(operator_gateway_turn, "_is_goal_continuation", lambda actor, a, text: True)
    delivered = []
    monkeypatch.setattr(operator_gateway_turn, "_deliver", lambda *a, **k: delivered.append(a) or {"x": 1})

    result = agent.run_conversation("[Continuing toward your standing goal]", conversation_history=[{"r": 1}])

    assert ran == [] and delivered == []
    assert result["interrupted"] is True and result["final_response"] == ""
    assert result["messages"] == [{"r": 1}]


def test_a_completion_the_gateway_claims_is_delivered_as_an_operator_turn(monkeypatch):
    # Red when ``_gateway_turn`` answers every gateway-started turn with an empty turn (the completion
    # the gateway's poller claimed for the chat is then lost: one drain, and it dropped it).
    class Agent:
        session_id = "s2"

        def run_conversation(self, *args, **kwargs):
            raise AssertionError("the gateway's own text never reaches the agent directly")

    agent = Agent()
    operator_gateway_turn._install_door(agent, "sid-2")
    agent._operator_gateway_actor = operator_gateway_turn._SessionActor("sid-2", "s2", None, "root-2")
    monkeypatch.setattr(operator_gateway_turn, "_is_goal_continuation", lambda actor, a, text: False)
    delivered = []

    def deliver(a, actor, text, kwargs):
        delivered.append((actor.root, text))
        return {"final_response": "delivered"}

    monkeypatch.setattr(operator_gateway_turn, "_deliver", deliver)

    result = agent.run_conversation("[background process finished]")

    assert delivered == [("root-2", "[background process finished]")]
    assert result == {"final_response": "delivered"}


def _judged_turn(before, after, monkeypatch):
    turn = operator_gateway_turn._Turn(execution=None, text="")
    turn.agent = type("A", (), {"session_id": "tip"})()
    turn.goal_before = before
    turn.settled.set()
    monkeypatch.setitem(operator_gateway_turn._last_turn, "root-j", turn)
    monkeypatch.setattr(operator_gateway_turn, "_goal_mark", lambda home, key: after)

    class _Goal:
        state = None

    from agent_runtime import chat_goal

    monkeypatch.setattr(chat_goal, "manager", lambda root: _Goal())
    return operator_gateway_turn.EngineJudgedGoal("root-j").evaluate_after_turn("reply")


def test_the_settle_reads_the_engines_judgement_and_never_judges_again(monkeypatch):
    # Red when ``evaluate_after_turn`` stops comparing the goal before and after the turn
    # (``after[:2] == turn.goal_before[:2]`` dropped): an unjudged turn would then read the previous
    # turn's ``continue`` and continue the goal a second time.
    unjudged = _judged_turn((1, 10.0, "active", "continue", "r"), (1, 10.0, "active", "continue", "r"), monkeypatch)
    assert unjudged["should_continue"] is False and unjudged["verdict"] == "waiting"

    judged = _judged_turn((1, 10.0, "active", "continue", "r"), (2, 20.0, "active", "continue", "more"), monkeypatch)
    assert judged["should_continue"] is True and judged["reason"] == "more"

    done = _judged_turn((2, 20.0, "active", "continue", "r"), (3, 30.0, "done", "done", "finished"), monkeypatch)
    assert done["should_continue"] is False and done["status"] == "done"


def test_the_gateway_turn_waits_for_the_operator_settle_before_it_judges():
    # Red when the door stops waiting on ``turn.released`` (the gateway's judge then reads a turn the
    # operator lane has not settled, and a Work run's checking mark races it).
    class Agent:
        session_id = "s3"

        def run_conversation(self, *args, **kwargs):
            return {"final_response": "ok"}

    agent = Agent()
    operator_gateway_turn._install_door(agent, "sid-3")

    class _Execution:
        request = type("R", (), {"root_chat_session_id": None})()

        def converse(self, agent):
            return ({"final_response": "ok"}, agent, {})

    turn = operator_gateway_turn._Turn(_Execution(), "")
    operator_gateway_turn._pending["sid-3"] = __import__("collections").deque([turn])
    finished = threading.Event()
    threading.Thread(target=lambda: (agent.run_conversation(""), finished.set()), daemon=True).start()

    assert turn.done.wait(5)
    assert not finished.wait(0.3)
    turn.released.set()
    assert finished.wait(5)
    operator_gateway_turn._settling.pop("sid-3", None)


def test_a_run_that_is_no_chat_is_refused_and_leaves_no_session_row():
    # Red when ``ProfileAgentRunner._converse`` runs a request with no chat root outside the engine again
    # (the second turn path the fold deleted: the agent then converses, here or on the engine), or mints
    # a session for it (a phantom row in the store).
    from hermes_constants import get_hermes_home
    from hermes_state import SessionDB

    from agent_runtime.profile_runner import ProfileRunnerError

    _StackAgent.stacks.clear()
    with pytest.raises(ProfileRunnerError, match="names no chat root"):
        _run(root_chat_session_id=None, session_id=None)

    assert _StackAgent.stacks == []
    db_path = get_hermes_home() / "state.db"
    if db_path.exists():
        db = SessionDB(db_path=db_path)
        try:
            assert db.session_count_ge(1) is False
        finally:
            db.close()


def test_the_gateways_factory_builds_only_operator_sessions_through_the_operator_lane(monkeypatch):
    # Red when ``worker_app_functions.operator_agent`` stops checking the session's source (every
    # gateway session, an Intelligence conversation's included, would then be built by the operator
    # lane, which refuses a build no operator turn asked for).
    from agent_runtime.conversations import worker_app_functions

    built = []
    monkeypatch.setattr(operator_gateway_turn, "construct", lambda sid: built.append(sid) or "agent")

    assert worker_app_functions.operator_agent("sid-a", "desktop") is None
    assert worker_app_functions.operator_agent("sid-b", operator_gateway_turn.OPERATOR_SOURCE) == "agent"
    assert built == ["sid-b"]


# ── the completion drain: the engine's poller for an open chat, this lane's wake for a closed one ──

from tests.agent_runtime.test_dispatch_delivery import SENDER_ROOT, resolvable_sender, store_home  # noqa: E402,F401


def _completion():
    return {"type": "completion", "session_id": SENDER_ROOT, "session_key": SENDER_ROOT,
            "command": "sleep 1", "exit_code": 0, "output": "done"}


class _Forge:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return True, {"ok": True}


def _empty_queue():
    from tools.process_registry import process_registry

    while not process_registry.completion_queue.empty():
        process_registry.completion_queue.get_nowait()
    return process_registry


def test_a_completion_for_a_chat_with_an_open_engine_session_is_left_to_the_engine(store_home, resolvable_sender, monkeypatch):
    # Red when ``_chat_root_of_completion`` stops asking ``_engine_session_open`` (the lane would then
    # forge a second delivery of a completion the open session's own poller delivers).
    from agent_runtime import dispatch_delivery
    from agent_runtime.dispatch_delivery import DrainPolicy

    registry = _empty_queue()
    actor = operator_gateway_turn._SessionActor("sid-open", SENDER_ROOT, None, SENDER_ROOT)
    monkeypatch.setitem(operator_gateway_turn._actors, SENDER_ROOT, actor)
    registry.completion_queue.put(_completion())
    forge = _Forge()

    tally = dispatch_delivery.drain_background_completions(
        policy=DrainPolicy(sender_persona=resolvable_sender, sender_is_idle=lambda root: True), forge=forge)

    assert forge.calls == [] and tally["delivered"] == 0
    assert not registry.completion_queue.empty()
    _empty_queue()


def test_a_completion_parked_for_a_closed_chat_wakes_it_through_this_lane(store_home, resolvable_sender):
    # Red when ``BackgroundDrain.run`` stops claiming parked completions (``self._parked()``): the
    # engine's poller parks a completion whose chat has no open session, and nothing else opens it.
    from agent_runtime import dispatch_delivery
    from agent_runtime.dispatch_delivery import DrainPolicy
    from tui_gateway import notification_park

    _empty_queue()
    notification_park.clear()
    assert notification_park.park(_completion())
    forge = _Forge()

    tally = dispatch_delivery.drain_background_completions(
        policy=DrainPolicy(sender_persona=resolvable_sender, sender_is_idle=lambda root: True), forge=forge)

    assert tally["delivered"] == 1
    assert [call["root_session_id"] for call in forge.calls] == [SENDER_ROOT]
    assert notification_park.parked() == []


def test_importing_the_engine_in_process_leaves_the_serves_stdout_alone(monkeypatch):
    # Red when ``_import_gateway_keeping_stdout`` stops putting stdout back: the gateway's import swaps
    # ``sys.stdout`` for stderr (its stdio guard), and every reply line the serve prints afterwards
    # becomes a stderr frame the client never reads as the reply.
    import sys

    from agent_runtime.conversations import in_process_peer

    serve_stdout = object()
    monkeypatch.setattr(sys, "stdout", serve_stdout)
    monkeypatch.delitem(sys.modules, "tui_gateway.server", raising=False)
    imported = []

    def import_module(name):
        imported.append(name)
        sys.stdout = sys.stderr  # what tui_gateway/server.py does at import

    monkeypatch.setattr(in_process_peer, "_import_module", import_module)

    in_process_peer._import_gateway_keeping_stdout()

    assert imported == ["tui_gateway.server"]
    assert sys.stdout is serve_stdout
