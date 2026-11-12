"""``RT-NEW-TURN-WAITS-ON-ANOTHER-AGENTS-MODEL-CALL``: one agent's slow reply does not freeze another's turn.

Seen live 2026-11-12 (Eternia lane w1112b-turn5, hermes b2d9d99738): a message to one agent sat in
"Thinking" for as long as ANOTHER agent had a model call in flight — the waiting turns' ``phases`` read
``write_ahead`` 317 ms → ``agent_ready`` 125 793 ms, 87 → 80 743 ms and 142 811 ms, each ending when the
other agent's held call returned.

Reproduced whole (``held_model_turn``, two agents on one model server, agent A's call held): agent B's
turn stood in ``profile_runner.workdir._posix_process_home`` waiting for ``_PROCESS_HOME_LOCK``, the POSIX
lock every run held for its whole body so that the process ``HOME`` could be pointed at a profile's
``home/`` — although neither profile has one and nothing was written. The gate that replaced it lets runs
wanting the same ``HOME`` hold it together; the proof here is B's own phase record, not a timing.

Killing mutations (reds recorded in the commit body):
* ``_ProcessHomeGate.hold`` admits a top-level run only when nobody holds (``self._holders == 0`` alone,
  the old whole-run lock) → the whole-turn test red ("agent B's turn is still waiting…") and the
  side-by-side gate test red;
* the same line admits any value (``or True``) → "a run saw another profile's HOME";
* the line drops its place check (``self._line[0] is place``) → "…jumped the line";
* the nested branch skips its wait for the other holders → "…while another run was still inside".
"""

from __future__ import annotations

import os
import threading
from types import SimpleNamespace

import pytest

from agent_runtime import serve_rpc
from agent_runtime.mission_chat_turns.reads import mission_chat_turn_record
from agent_runtime.mission_chat_turns.states import TERMINAL_TURN_STATES
from agent_runtime.profile_runner.errors import ProfileRunnerError
from agent_runtime.profile_runner.workdir import _posix_process_home
from tests.agent_runtime.held_model_turn import OWNER, HeldModel, Running, operator_turn
from tests.agent_runtime.test_serve_rpc_open_chat import (  # placed_agent / qa_persona are fixtures
    PERSONA, WORKSPACE, _call, placed_agent, qa_persona,
)

pytestmark = [pytest.mark.timeout(180), pytest.mark.skipif(os.name == "nt", reason="HOME is not written on Windows")]
HELD = "HOLD-THIS-ONE: write me a long essay."
_WAIT = 20.0


@pytest.fixture
def chat_head(monkeypatch, isolate_agent_runtime_root):
    from hermes_constants import get_hermes_home

    monkeypatch.setenv("HERMES_HEAD_HOME", str(get_hermes_home()))


@pytest.fixture
def model(chat_head):
    from hermes_constants import get_hermes_home

    held = HeldModel()
    held.hold_if = lambda body: any(HELD in str(m.get("content")) for m in body["messages"])
    held.configure(get_hermes_home())
    yield held
    held.close()


def _chat(instance: str, key: str) -> str:
    return _call(dict(persona_id=PERSONA, persona_instance_id=instance, new_session=True,
                      idempotency_key=key, client_scope=OWNER))["result"]["session_id"]


def test_agent_b_is_built_and_answers_while_agent_a_waits_on_its_model_call(placed_agent, model):
    a = placed_agent["persona_instance_id"]
    second = serve_rpc.handle_request(dict(jsonrpc="2.0", id="seed-2", method="runtime.agent.create", params=dict(
        persona_id=PERSONA, workspace_id=WORKSPACE, position=[3.0, 2.0], idempotency_key="second-agent")))
    b = second["result"]["persona_instance_id"]
    assert a != b
    root_a, root_b = _chat(a, "chat-a"), _chat(b, "chat-b")
    held = operator_turn(a, root_a, "msg-a", HELD)
    assert model.entered.wait(60), "agent A's turn never reached the model"

    quick = operator_turn(b, root_b, "msg-b", "A quick question.")
    quick.thread.join(60)

    still_held = held.thread.is_alive() and not model.release.is_set()
    assert still_held, "agent A's call was let go: this no longer proves agent B did not wait for it"
    assert not quick.thread.is_alive(), "agent B's turn is still waiting while agent A's model call is held"
    _code, payload = quick.join(1)
    assert payload["reply"] == "Thanks, noted."
    # The phase records: B's agent was built and its turn settled; A's turn has not ended.
    record_b = mission_chat_turn_record(session_id=root_b, client_message_id="msg-b")
    record_a = mission_chat_turn_record(session_id=root_a, client_message_id="msg-a")
    assert "agent_ready" in record_b["phases"] and record_b["state"] in TERMINAL_TURN_STATES, record_b
    assert record_a["state"] not in TERMINAL_TURN_STATES, record_a
    model.release.set()
    held.join(60)


# ── the gate itself: what still waits, and that HOME never crosses ──────────────────────────────


def _profile(tmp_path, name: str, *, with_home: bool) -> SimpleNamespace:
    root = tmp_path / "profiles" / name
    (root / "home").mkdir(parents=True) if with_home else root.mkdir(parents=True)
    return SimpleNamespace(profile_home=root)


class _Inside:
    """A run parked inside the gate on its own thread until ``leave``; ``home`` is the HOME it saw."""

    def __init__(self, binding, order: list | None = None, name: str = "") -> None:
        self.entered, self.leave, self.home = threading.Event(), threading.Event(), None

        def _run():
            with _posix_process_home(binding):
                self.home = os.environ.get("HOME")
                if order is not None:
                    order.append(name)
                self.entered.set()
                self.leave.wait(_WAIT * 4)  # longer than any wait below: a run let in late is a red, not a pass

        self.run = Running(_run)

    def out(self) -> None:
        self.leave.set()
        self.run.join(_WAIT)


def test_runs_that_write_no_home_stand_inside_together_and_home_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/the/process/home")
    first = _Inside(_profile(tmp_path, "a", with_home=False))
    assert first.entered.wait(_WAIT)
    second = _Inside(_profile(tmp_path, "b", with_home=False))
    assert second.entered.wait(_WAIT), "a second run that writes no HOME waited for the first"
    first.out(), second.out()
    assert (first.home, second.home, os.environ["HOME"]) == ("/the/process/home",) * 3


def test_a_run_never_sees_another_profiles_home_and_nobody_jumps_the_line(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/the/process/home")
    alpha, beta = _profile(tmp_path, "alpha", with_home=True), _profile(tmp_path, "beta", with_home=True)
    order: list[str] = []
    first = _Inside(alpha, order, "alpha-1")
    assert first.entered.wait(_WAIT)
    other = _Inside(beta, order, "beta")        # another HOME: waits for alpha to leave
    plain = _Inside(_profile(tmp_path, "plain", with_home=False), order, "plain")  # must not see alpha's HOME
    assert not other.entered.wait(0.5) and not plain.entered.is_set(), "a run saw another profile's HOME"
    late = _Inside(alpha, order, "alpha-2")     # the value in force, but beta is ahead of it in line
    assert not late.entered.wait(0.5), "a later run of the profile in force jumped the line"
    first.out()
    assert other.entered.wait(_WAIT)
    other.out()
    assert plain.entered.wait(_WAIT)
    plain.out()
    assert late.entered.wait(_WAIT)
    late.out()
    assert order == ["alpha-1", "beta", "plain", "alpha-2"]
    assert (first.home, other.home, plain.home, late.home) == (
        str(alpha.profile_home / "home"), str(beta.profile_home / "home"), "/the/process/home",
        str(alpha.profile_home / "home"))
    assert os.environ["HOME"] == "/the/process/home"


def test_a_nested_run_with_its_own_home_gets_home_to_itself_and_puts_the_outer_one_back(tmp_path, monkeypatch):
    """The old lock was reentrant; a nested run of another profile still writes its HOME — alone."""

    monkeypatch.setenv("HOME", "/the/process/home")
    beside = _Inside(_profile(tmp_path, "beside", with_home=False))
    assert beside.entered.wait(_WAIT)
    inner_home = _profile(tmp_path, "inner", with_home=True)
    seen: dict[str, object] = {}
    second_in, refused = threading.Event(), threading.Event()

    def _nested():
        with _posix_process_home(_profile(tmp_path, "outer", with_home=False)):
            assert second_in.wait(_WAIT)
            with _posix_process_home(inner_home):
                seen["beside_was_out"] = not beside.run.thread.is_alive()
                seen["inner"] = os.environ.get("HOME")
            seen["outer_again"] = os.environ.get("HOME")

    def _second_nested():
        with _posix_process_home(_profile(tmp_path, "outer-2", with_home=False)):
            second_in.set()
            while not _gate_is_being_taken():
                threading.Event().wait(0.01)
            try:
                with _posix_process_home(inner_home):
                    seen["second_entered"] = True
            except ProfileRunnerError:
                refused.set()

    nested = Running(_nested)
    second = Running(_second_nested)
    assert refused.wait(_WAIT), "two nested runs asking for HOME at once must not wait on each other for ever"
    second.join(_WAIT)
    assert "inner" not in seen, "the nested run wrote its HOME while another run was still inside"
    beside.out()
    nested.join(_WAIT)
    assert seen == {"beside_was_out": True, "inner": str(inner_home.profile_home / "home"),
                    "outer_again": "/the/process/home"}
    assert os.environ["HOME"] == "/the/process/home"


def _gate_is_being_taken() -> bool:
    from agent_runtime.profile_runner import workdir

    return workdir._PROCESS_HOME._sole_owner is not None
