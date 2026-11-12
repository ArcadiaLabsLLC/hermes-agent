"""``RT-UNTIL-DONE-CHAT-STOP-DOES-NOT-END-RUN``: the conversation's own Stop ends an until-done run.

Seen live 2026-11-12 (Eternia lane w1112b-work3, hermes 7bb8dbd9f6): Stop pressed in the chat during
pass 3 of an until-done run did nothing. Which, established from that run's own records:

* the Stop was REFUSED, not lost: ``runtime.operator.conversation.stop`` answered 4090
  ``execution_not_admitted`` (Eternia drew "This response has no confirmed runtime admission"). A pass is
  a send the Work engine queued, run by the serve's queued-send runner: it has no admission receipt and
  is not in the serve's in-flight table, the only two things that door knew how to stop;
* so nothing interrupted the pass: it ran its model call to the end and settled a PLAIN reply — no
  ``stopped: true`` — and the judge (timed out, "falling through to continue") queued pass 4.

``ae8b1f8d4d``'s rule "the conversation's own Stop on a pass does the same" was pinned only on a settle
payload a test wrote by hand (``stopped: true``), which that door could never produce for a pass.

Here the real door is driven: a real persona instance and chat root (``runtime.agent.create`` + open
chat), the real ``PersonaTurnExecutor`` with its binding and send queue on this test's home, the RPC
through ``serve_rpc.handle_request``, and the pass registered in ``live_turns`` as a running turn is. The
goal judge is ``contract_fakes.FakeGoals`` (it is what must NOT be asked) and the model is absent.

Killing mutations (each recorded red in the commit body):
* ``stop_operator_execution`` skips ``_stop_run_pass`` (the code as it was) → every Stop test here red
  (``execution_not_admitted``);
* ``goal_turns.stop_from_conversation`` does not bind ``stopping`` → the plain-reply test red (the judge
  is asked and pass 4 is queued);
* ``PersonaTurnExecutor.wake_parked`` drops ``_end_stopped`` → the between-passes test red (the run never ends).
"""

from __future__ import annotations

import pytest

from agent_runtime import chat_goal, paths, serve_rpc
from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.live_turns import live_turn
from agent_runtime.serde import safe_assignment_token
from agent_runtime.work_store.executor import Assignment, Brief, GoalMode, Verdict
from agent_runtime.work_store.grammar import RowRef
from agent_runtime.work_store.persona_turn import PersonaTurnExecutor
from tests.agent_runtime.test_serve_rpc_open_chat import (  # placed_agent / qa_persona are fixtures
    PERSONA, WORKSPACE, _call, placed_agent, qa_persona,
)
from tests.agent_runtime.work_store.contract_fakes import FakeGoals, decision

OWNER = "a" * 64
REF = RowRef("repo", "q.md", "RT-A")
#: A run id of the engine's own shape: colons, which a turn id spells as underscores.
REQUEST = "ws_x:repo:RT-A:2026-11-12:e30b7e"


@pytest.fixture(autouse=True)
def chat_head(monkeypatch, isolate_agent_runtime_root):
    from hermes_constants import get_hermes_home

    monkeypatch.setenv("HERMES_HEAD_HOME", str(get_hermes_home()))


class _Agent:
    def __init__(self) -> None:
        self.interrupts = 0

    def interrupt(self, *_args, **_kwargs) -> None:
        self.interrupts += 1


class _Run:
    """An until-done run on a real chat root, advanced to a chosen pass."""

    def __init__(self, placed) -> None:
        self.instance = placed["persona_instance_id"]
        self.root = _call(dict(persona_id=PERSONA, persona_instance_id=self.instance, new_session=True,
                               idempotency_key="new-chat", client_scope=OWNER))["result"]["session_id"]
        self.goals = FakeGoals()
        self.executor = PersonaTurnExecutor(root_of=lambda store, **_: self.root, wake=lambda: None,
                                            goals=self.goals, workdir_of=lambda instance: None)
        self.ended = []
        self.executor.on_settle(lambda run, outcome: self.ended.append(outcome))
        brief = Brief(title="Keep the meadow tidy", objective="Keep the meadow tidy")
        self.executor.start(Assignment((REF,), self.instance, brief, REQUEST, goal_mode=GoalMode.UNTIL_DONE))
        self.interrupted: list[str] = []

    @property
    def goal(self):
        return self.goals(self.root)

    @property
    def cmid(self) -> str:
        return chat_goal.binding(self.root).cmid

    def settle(self, payload: dict) -> None:
        entry = send_queue.find(self.root, self.cmid)
        self.executor.settled(entry, 0, payload)
        send_queue.remove(self.root, entry.client_message_id)  # the runner's own order: tell, then remove

    def to_pass(self, number: int) -> None:
        for _ in range(number - 1):
            self.goal.decisions = [decision("continue", go_on=True)]
            self.settle({"ok": True, "reply": "more to do"})
        assert chat_goal.run_pass(self.root, self.cmid)["goal"]["pass"] == number

    def stop(self, turn_request_id: str, method: str = "runtime.operator.conversation.stop") -> dict:
        params = dict(install_id=ensure_install_identity(paths.store_root()).install_id, persona_id=PERSONA,
                      persona_instance_id=self.instance, workspace_id=WORKSPACE, session_id=self.root,
                      client_scope=OWNER, turn_request_id=turn_request_id)
        context = serve_rpc.RpcContext(interrupt_operator=lambda turn: self.interrupted.append(turn) or False)
        return serve_rpc.handle_request(dict(jsonrpc="2.0", id="stop", method=method, params=params), context)

    def queued_passes(self) -> list[str]:
        return [e.client_message_id for e in send_queue.entries(self.root)]


@pytest.fixture
def run(placed_agent) -> _Run:
    return _Run(placed_agent)


@pytest.mark.parametrize("spelled", [lambda cmid: cmid, safe_assignment_token], ids=["client_message_id", "turn_id"])
def test_stop_on_a_running_pass_is_accepted_and_the_run_ends_though_the_pass_settles_as_a_plain_reply(run, spelled):
    """The live case: pass 3 is running, Stop is pressed, the model call is not interruptible and the pass
    settles an ordinary reply. The run still ends STOPPED and no pass 4 is queued."""

    run.to_pass(3)
    third = run.cmid
    send_queue.mark(run.root, third, state=send_queue.STATE_RUNNING)
    agent = _Agent()
    with live_turn(turn_id=safe_assignment_token(third), session_id=run.root,
                   persona_instance_id=run.instance, agent=agent):
        reply = run.stop(spelled(third))
        assert "result" in reply, reply
        result = reply["result"]
        assert result["turn_request_id"] == spelled(third), "Eternia checks the echo before it believes a Stop"
        assert result["outcome"] == "stop_requested" and result["stop_requested"] is True
        assert result["stopped"] == "work_run" and result["work_request"] == REQUEST and result["ends"] == "now"
        assert agent.interrupts == 1 and result["owner_observed"] is True, "the pass's own agent was interrupted"
        assert chat_goal.binding(run.root).stopping is True
        status = run.stop(spelled(third), "runtime.operator.conversation.status")["result"]
        assert status["outcome"] == "stop_requested", "a status read while the pass winds down says so"

        run.goal.decisions = [decision("continue", go_on=True)]  # what the judge would say, were it asked
        run.settle({"ok": True, "reply": "The meadow is a little tidier."})

    [outcome] = run.ended
    assert outcome.verdict is Verdict.STOPPED and outcome.per_row[REF].reason == "operator stop"
    assert len(run.goal.evaluated) == 2, "the judge heard passes 1 and 2 and was not asked about the stopped one"
    assert chat_goal.binding(run.root) is None and run.queued_passes() == [], "no pass 4"


def test_stop_naming_an_earlier_pass_of_the_run_still_ends_it(run):
    """Stop raced the settle: the pass it names has ended and the next is already queued. A pass not begun
    never begins, and the run ends at the engine's next tick."""

    run.to_pass(2)
    first = f"work-{REQUEST}"
    assert run.cmid != first and run.queued_passes() == [run.cmid]

    result = run.stop(first)["result"]
    assert result["outcome"] == "stop_requested" and result["ends"] == "now" and result["owner_observed"] is False
    assert run.queued_passes() == [], "the queued pass was taken off the root"
    assert run.ended == []

    run.executor.wake_parked()  # the engine's tick
    [outcome] = run.ended
    assert outcome.verdict is Verdict.STOPPED and chat_goal.binding(run.root) is None
    run.executor.wake_parked()
    assert len(run.ended) == 1, "ended once"


def test_stop_on_a_turn_that_is_no_pass_of_the_run_is_answered_as_before(run):
    """Positive control: the door still refuses a turn nobody admitted, and the run is untouched."""

    reply = run.stop("somebody-elses-turn")
    assert reply["error"]["data"]["reason"] == "execution_not_admitted", reply
    assert chat_goal.binding(run.root).stopping is False and run.queued_passes() == [run.cmid]
    run.executor.wake_parked()
    assert run.ended == []
