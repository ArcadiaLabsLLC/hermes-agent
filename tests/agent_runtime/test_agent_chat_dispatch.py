"""``agent_chat_send(wait=false)`` — the detached dispatch lane.

The lane's whole promise is "go do this, I'll keep working, bring me the answer
later". These tests pin what makes that promise keepable: the call returns
without running the turn, the row is durable BEFORE the work starts, the turn
runs in its OWN PROCESS (never on a thread that would serialize behind
``profile_runner._WORKDIR_LOCK`` and freeze the whole runtime), and the lane
refuses outright whenever the answer would have nowhere to land.
"""

from __future__ import annotations

import json
import os

import pytest
from hermes_cli.harness_parts.persona import chat_turn_message

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")

from tests._downstream.split_package_source import patch_where_bound
from agent_runtime import dispatch_delivery, subprocess_pumps
from agent_runtime.dispatch_store import (
    DELIVERY_PENDING,
    STATE_ERROR,
    STATE_RUNNING,
    get_dispatch,
    mint_dispatch_id,
    record_dispatch,
    running_dispatches,
)
from agent_runtime.relay_policy import RELAY_CHAIN, RELAY_DEADLINE
from tests.agent_runtime.dispatch_turn_stub import StubTurn, bind_stub_turn
from tools import agent_chat_dispatch
from tools.agent_chat_dispatch import native
from tools.agent_chat_tool import (
    AGENT_CHAT_DISPATCHES_SCHEMA,
    AGENT_CHAT_SEND_SCHEMA,
    agent_chat_dispatches,
    agent_chat_send,
)
from tools.registry import registry

SENDER_ROOT = "persona_chat_personainst_neko_aaaaaaaaaaaa"


@pytest.fixture
def store_home(tmp_path, monkeypatch):
    home = tmp_path / "bg-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    return home


@pytest.fixture
def deliverable_lane(monkeypatch):
    """A lane where a detached dispatch's answer genuinely has somewhere to land.

    Both halves are real preconditions the admission checks enforce: a live
    delivery consumer, and a sender root that resolves to a persona the drain can
    forge a turn back into.
    """

    from agent_runtime.delivery_capability import declare_async_delivery_channel
    from gateway.session_context import _SESSION_ASYNC_DELIVERY

    # The REAL contextvar, not a stub of the getter: the lane now requires a
    # POSITIVE declaration, so a test that stubbed only the value would pass
    # while the mechanism it is about went unexercised.
    token = _SESSION_ASYNC_DELIVERY.set(_SESSION_ASYNC_DELIVERY.get())
    declare_async_delivery_channel()
    patch_where_bound(monkeypatch, dispatch_delivery, "_sender_persona",
        lambda root: ("neko_supervisor", "personainst_neko") if root == SENDER_ROOT else None,
    )
    yield
    _SESSION_ASYNC_DELIVERY.reset(token)


@pytest.fixture
def queued(monkeypatch):
    """Capture the spec that would have been queued, without spawning anything."""

    calls = []

    def fake_queue(*, dispatch_id, spec, max_concurrent):
        calls.append({"dispatch_id": dispatch_id, "spec": spec, "max_concurrent": max_concurrent})

    monkeypatch.setattr(agent_chat_dispatch, "dispatch_detached_turn", fake_queue)
    return calls


def _send(**overrides):
    payload = {
        "persona_id": "dev",
        "message": "Run the full launcher suite and report failures.",
        "wait": False,
        "requested_by_session": SENDER_ROOT,
    }
    payload.update(overrides)
    return json.loads(agent_chat_send(**payload))


# --------------------------------------------------------------------------
# the tool surface
# --------------------------------------------------------------------------


def test_a_send_to_the_senders_own_instance_is_refused_and_never_queued(store_home, deliverable_lane, queued):
    """RT-FU-A-SEND-TO-AN-UNPLACED-AGENT-GOES-BACK-TO-THE-SENDER-AND-A-REFUSED-SEND-SAYS-OK (seen live
    2026-11-21, dispatch-c58c34703868; replayed at 96569d9544^, before native dispatch: accepted and
    queued there too). On a lane that CAN deliver, a ``wait=false`` send onto the sender's own
    instance is refused ``ok: false, relay_cycle`` by the turn's own resolver, writes no row and
    queues nothing. Killing mutation: ``Send.local_target`` returns None instead of
    ``admit_send(...)`` -> ``ok: true, dispatched: true`` and one queued turn, red."""

    token = RELAY_CHAIN.set(("personainst_dev",))
    try:
        result = _send(persona_id="@personainst_dev")
    finally:
        RELAY_CHAIN.reset(token)

    assert (result["ok"], result["error_kind"]) == (False, "relay_cycle")
    assert "dispatched" not in result
    assert queued == []
    assert running_dispatches() == []


def test_wait_false_returns_a_handle_without_the_reply(store_home, deliverable_lane, queued):
    result = _send()

    assert result["ok"] is True
    assert result["dispatched"] is True
    assert result["dispatch_id"]
    assert result["target_persona"] == "dev"
    assert result["started_at"] > 0
    # The reply is deliberately ABSENT: an agent handed an empty `reply` field
    # would read it as "they had nothing to say" and act on the silence.
    assert "reply" not in result
    assert "do not re-send" in result["next_expected"]


def test_the_row_is_durable_before_the_turn_is_queued(store_home, deliverable_lane, queued):
    result = _send()

    row = get_dispatch(result["dispatch_id"])
    assert row is not None
    assert row["state"] == STATE_RUNNING
    assert row["delivery_state"] == DELIVERY_PENDING
    assert row["sender_session_id"] == SENDER_ROOT
    # Recorded, not left blank: the row answers "who asked for this" on its own.
    assert row["sender_persona_id"] == "neko_supervisor"
    assert row["target_persona"] == "dev"
    assert row["ask"].startswith("Run the full launcher suite")
    assert [item["dispatch_id"] for item in running_dispatches()] == [result["dispatch_id"]]
    # And only THEN was it queued.
    assert queued[0]["dispatch_id"] == result["dispatch_id"]


def test_notify_operator_rides_the_row(store_home, deliverable_lane, queued):
    result = _send(notify_operator=True)

    assert result["notify_operator"] is True
    assert get_dispatch(result["dispatch_id"])["notify_operator"] is True


def test_wait_true_is_unchanged_and_never_touches_the_store(store_home, monkeypatch):
    """The default lane must behave exactly as it did before this feature."""

    def fake_handler(args):
        args.payload_sink({"ok": True, "reply": "ack", "session_id": "s1"})
        return 0

    monkeypatch.setattr(chat_turn_message, "_cmd_mission_chat_message", fake_handler)
    result = json.loads(agent_chat_send(persona_id="dev", message="hi"))

    assert result["ok"] is True
    assert result["reply"] == "ack"
    assert "dispatched" not in result
    assert running_dispatches() == []


# --------------------------------------------------------------------------
# admission: never accept a promise this lane cannot keep
# --------------------------------------------------------------------------


def test_a_lane_with_no_chat_session_refuses_the_promise(store_home, deliverable_lane, queued):
    """No session ⇒ nowhere to deliver ⇒ refuse, never run-and-drop."""

    result = _send(requested_by_session=None)

    assert result["ok"] is False
    assert result["error_kind"] == "async_delivery_unavailable"
    assert queued == []
    assert running_dispatches() == []


def test_a_cold_cli_lane_refuses_instead_of_orphaning_the_work(store_home, monkeypatch, queued):
    """The capability contract, enforced by the tool that makes the promise.

    ``async_delivery_supported()`` is False when this turn's process ends with
    the turn. Accepting a dispatch there would leave orphaned work writing into
    a chat thread with no recorder left to settle its row — so the tool refuses,
    exactly as ``delegate_task`` falls back to its inline path on the same signal.
    """

    from gateway.session_context import _SESSION_ASYNC_DELIVERY, declare_stateless_channel

    token = _SESSION_ASYNC_DELIVERY.set(_SESSION_ASYNC_DELIVERY.get())
    declare_stateless_channel()
    patch_where_bound(monkeypatch, dispatch_delivery, "_sender_persona", lambda root: ("neko_supervisor", "personainst_neko")
    )
    try:
        result = _send()
    finally:
        _SESSION_ASYNC_DELIVERY.reset(token)

    assert result["ok"] is False
    assert result["error_kind"] == "async_delivery_unavailable"
    assert "wait=true" in result["error"]
    assert queued == []
    assert running_dispatches() == []


def test_a_sender_root_the_drain_cannot_resolve_is_refused_before_running(
    store_home, monkeypatch, queued
):
    """Run-and-drop is the one outcome this lane must never have.

    The drain addresses its forged turn by resolving the sender root to a
    persona; a root it cannot resolve is dropped AFTER the target has already
    done the work. The admission check uses the SAME resolver, so what the drain
    could not deliver never runs.
    """

    from agent_runtime.delivery_capability import declare_async_delivery_channel

    declare_async_delivery_channel()
    patch_where_bound(monkeypatch, dispatch_delivery, "_sender_persona", lambda root: None)

    result = _send()

    assert result["ok"] is False
    assert result["error_kind"] == "async_delivery_unavailable"
    assert queued == []
    assert running_dispatches() == []


def test_a_store_failure_refuses_rather_than_running_blind(
    store_home, deliverable_lane, queued, monkeypatch
):
    monkeypatch.setattr(
        "agent_runtime.dispatch_store.record_dispatch",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("disk full")),
    )

    result = _send()

    assert result["ok"] is False
    assert result["error_kind"] == "dispatch_store_unavailable"
    # Nothing was queued: work whose result has nowhere to go must not run.
    assert queued == []


def test_a_queue_failure_settles_the_row_instead_of_stranding_it(
    store_home, deliverable_lane, monkeypatch
):
    """A row that can never complete must not sit `running` in the HUD forever."""

    def boom(**kw):
        raise RuntimeError("executor gone")

    monkeypatch.setattr(agent_chat_dispatch, "dispatch_detached_turn", boom)
    result = _send()

    assert result["ok"] is False
    assert result["error_kind"] == "dispatch_queue_failed"
    assert running_dispatches() == []


# --------------------------------------------------------------------------
# the relay ruling
# --------------------------------------------------------------------------


def test_a_detached_dispatch_gets_the_background_budget_not_the_chain_remainder(
    store_home, deliverable_lane, queued
):
    """Operator ruling: a detached dispatch is a NEW CHAIN ROOT with its own clock.

    The shared chain deadline exists so a SYNCHRONOUS hop cannot outlive the
    caller blocked on it. Nobody is blocked here, so inheriting a conversational
    window would kill exactly the long work this lane exists to host.
    """

    import time

    chain_token = RELAY_CHAIN.set(("neko_supervisor",))
    deadline_token = RELAY_DEADLINE.set(time.time() + 12.0)
    try:
        result = _send()
    finally:
        RELAY_CHAIN.reset(chain_token)
        RELAY_DEADLINE.reset(deadline_token)

    assert result["ok"] is True
    # Sized by the dispatch budget rather than the 12s that was left.
    assert queued[0]["spec"]["max_seconds"] >= 1800


def test_the_deadline_is_minted_when_the_turn_starts_not_when_it_is_queued(
    store_home, deliverable_lane, queued
):
    """Budget erosion: a queued dispatch must not burn its window waiting.

    The spec carries a BUDGET, never a deadline; the absolute epoch is computed
    by the supervisor when the turn starts (``native.run_turn`` -> ``turn_args``).
    Minting it at enqueue made the budget the sender was told about and the budget
    the turn actually got drift apart, silently, by however long the concurrency
    cap held it.
    """

    import time

    _send()
    spec = queued[0]["spec"]

    assert "relay_deadline_epoch" not in spec
    args = native.turn_args(spec, deadline_epoch=time.time() + spec["max_seconds"])
    assert args.relay_deadline_epoch >= time.time() + spec["max_seconds"] - 5


def test_a_detached_dispatch_still_forwards_the_chain(store_home, deliverable_lane, queued):
    """Fresh CLOCK, same CHAIN — the budget is what resets, never the reach.

    Depth and cycle detection read the chain, not the deadline, and they are
    decided downstream by ``evaluate_relay`` at the handler chokepoint the native
    turn enters. Dropping the chain here would turn "buy more time" into "escape
    the cycle guard".
    """

    chain_token = RELAY_CHAIN.set(("neko_supervisor", "qa"))
    try:
        result = _send()
    finally:
        RELAY_CHAIN.reset(chain_token)

    assert result["relay_chain"] == ["neko_supervisor", "qa"]
    assert native.turn_args(queued[0]["spec"], deadline_epoch=1.0).relay_chain == ["neko_supervisor", "qa"]


def test_an_exhausted_chain_budget_still_fast_fails_a_WAITING_send(store_home):
    """The clamp is skipped for detached sends ONLY — the inline lane is unchanged."""

    import time

    deadline_token = RELAY_DEADLINE.set(time.time() + 1.0)
    try:
        result = json.loads(agent_chat_send(persona_id="dev", message="hi"))
    finally:
        RELAY_DEADLINE.reset(deadline_token)

    assert result["ok"] is False
    assert result["error_kind"] == "relay_budget_exhausted"


def test_a_refusal_is_rewritten_for_the_lane_it_will_be_read_on():
    """"Answer your caller with what you have" is nonsense in a delivered turn.

    The sync copy addresses a caller blocked on the reply. A detached refusal is
    read minutes later, as its own turn, by an agent with no caller waiting — so
    the guidance has to change even though the refusal did not.
    """

    text = agent_chat_dispatch._detached_error_text(
        {"error_kind": "relay_budget_exhausted", "error": "Answer your caller with what you have."}
    )
    assert "Answer your caller" not in text
    assert "Re-dispatch" in text

    cycle = agent_chat_dispatch._detached_error_text(
        {"error_kind": "relay_cycle", "error": "relay cycle detected"}
    )
    assert "Nothing was executed" in cycle

    # Anything without lane-specific guidance passes through verbatim.
    assert (
        agent_chat_dispatch._detached_error_text({"error": "provider exploded"})
        == "provider exploded"
    )


# --------------------------------------------------------------------------
# the native turn's arguments
# --------------------------------------------------------------------------


def test_the_turn_args_are_a_plain_mission_chat_turn():
    spec = {
        "persona_id": "dev",
        "message": "run the suite",
        "max_seconds": 1800.0,
        "new_session": None,
        "client_message_id": "agent-dispatch-x",
        "requested_by_session": SENDER_ROOT,
        "relay_chain": ["neko_supervisor"],
    }
    args = native.turn_args(spec, deadline_epoch=1000.0)

    assert args.persona_id == "dev"
    assert args.json is True and args.stream is False
    assert args.max_seconds == 1800.0
    assert args.relay_deadline_epoch == 1000.0
    assert args.requested_by_session == SENDER_ROOT
    assert args.client_message_id == "agent-dispatch-x"
    assert args.intent_hint == "chat"


def test_the_thread_tri_state_reaches_the_handler_uncoerced():
    """UNSET is the default and must stay UNSET, never read as "continue".

    Without it every dispatch would silently stop opening its own task thread
    and pile back into one sticky per-pair thread.

    *Killing mutation:* ``new_session=bool(spec.get("new_session"))`` in ``turn_args``.
    """

    def new_session(value):
        return native.turn_args(
            {"persona_id": "dev", "message": "x", "max_seconds": 1.0, "new_session": value},
            deadline_epoch=1.0,
        ).new_session

    assert new_session(True) is True
    assert new_session(None) is None
    assert new_session(False) is False


def test_the_turn_resolves_on_the_head_home_not_the_senders_profile_home(tmp_path, monkeypatch):
    """The roster lives in the head home's config (the launcher pins it to ``profiles/base``);
    a turn resolved on the sender persona's profile home answers ``unknown persona`` for
    every configured target (2026-10-08, four dispatches). The dispatched turn follows the inline
    lane's head-home admission instead.

    *Killing mutation:* read ``get_hermes_home()`` for the ambient home again.
    """
    from agent_runtime.profile_home import get_hermes_head_home
    from hermes_constants import get_hermes_home
    from tools.agent_chat.detached import _dispatch_homes

    head = tmp_path / "head"
    sender_profile = tmp_path / "profiles" / "amelia"
    head.mkdir(parents=True)
    sender_profile.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HEAD_HOME", str(head))
    monkeypatch.setenv("HERMES_HOME", str(sender_profile))
    # Positive control for the fixture: the two authorities really do differ here.
    assert str(get_hermes_home()) == str(sender_profile)
    assert str(get_hermes_head_home()) == str(head)

    ambient, _background = _dispatch_homes()

    assert ambient == str(head), "the turn must resolve personas where the serve does"
    assert ambient != str(sender_profile)


def test_the_turn_binds_the_dispatch_homes_on_its_own_thread_only(store_home, tmp_path, monkeypatch):
    """The homes captured in the sender's turn are bound context-locally on the turn's thread.

    *Killing mutation:* ``_dispatch_homes_scope`` returning ``nullcontext()`` -> the turn reads the
    ambient ``HERMES_HOME`` instead of the captured head home.
    """

    from hermes_constants import get_hermes_home

    ambient, head = tmp_path / "ambient", tmp_path / "head"
    ambient.mkdir()
    head.mkdir()
    stub = bind_stub_turn(monkeypatch, StubTurn({"ok": True, "reply": "ok"}))

    run = native.run_turn(
        _spec(hermes_home=str(ambient), head_home=str(head), client_message_id="agent-dispatch-h"),
        budget=5.0, stop_requested=lambda: False,
    )

    assert run.payload == {"ok": True, "reply": "ok"}
    assert stub.observed[0]["home"] == str(ambient)
    # Nothing leaked into this thread.
    assert str(get_hermes_home()) == str(store_home)


def test_the_payload_survives_noise_on_both_sides_of_it():
    """``emit_json`` is indented multi-line, and children print other things.

    A line scan cannot find it, and a naive decode of everything after the first
    brace chokes on the trailing advisory. Both kinds of noise are real: the
    SQLite WAL warning arrives before, provider teardown chatter after.
    """

    text = (
        "state.db: linked SQLite is vulnerable {not json}\n"
        '{\n  "ok": true,\n  "reply": "done"\n}\n'
        "some trailing chatter\n"
    )
    assert agent_chat_dispatch.parse_reply_payload(text) == {"ok": True, "reply": "done"}
    assert agent_chat_dispatch.parse_reply_payload("") is None
    assert agent_chat_dispatch.parse_reply_payload("no json at all") is None


# --------------------------------------------------------------------------
# the supervisor: stamp → run natively → record
# --------------------------------------------------------------------------


def _armed_dispatch(**overrides):
    dispatch_id = mint_dispatch_id()
    record_dispatch(
        dispatch_id=dispatch_id,
        sender_session_id=SENDER_ROOT,
        target_persona="dev",
        ask="run the suite",
        **overrides,
    )
    return dispatch_id


def _spec(**overrides):
    import uuid

    # The request id the tool stamps on every spec (``dispatch_turn_request_id``): the key a
    # Stop finds the native turn by.
    spec = {"persona_id": "dev", "message": "run the suite", "max_seconds": 1.0,
            "client_message_id": f"agent-dispatch-test-{uuid.uuid4().hex[:12]}"}
    spec.update(overrides)
    return spec


def test_a_turn_that_replies_is_recorded_as_completed(store_home, monkeypatch):
    dispatch_id = _armed_dispatch()
    stub = bind_stub_turn(monkeypatch, StubTurn({"ok": True, "reply": "3 failures", "session_id": "s-dev"}))

    agent_chat_dispatch._run_dispatch(dispatch_id, _spec())

    row = get_dispatch(dispatch_id)
    assert row["state"] == "completed"
    assert row["result"]["reply"] == "3 failures"
    assert row["target_session_id"] == "s-dev"
    assert row["delivery_state"] == DELIVERY_PENDING
    # The turn ran HERE, natively: this process owns the row, and no second Hermes existed.
    assert row["owner_pid"] == os.getpid()
    assert stub.observed[0]["thread"].startswith("agent-chat-dispatch-turn-")


def test_a_turn_that_hands_back_nothing_is_unknown_not_a_silent_success(store_home, monkeypatch):
    dispatch_id = _armed_dispatch()
    bind_stub_turn(monkeypatch, StubTurn(None, exit_code=1))

    agent_chat_dispatch._run_dispatch(dispatch_id, _spec())

    row = get_dispatch(dispatch_id)
    assert row["state"] == "unknown"
    assert "exit code 1" in row["result"]["error"]


def test_a_turn_that_overruns_its_budget_is_interrupted_and_recorded(store_home, monkeypatch):
    """Past its budget plus grace the supervisor reaches the turn's own interrupt seam.

    *Killing mutation:* drop the ``budget_exceeded`` arm in ``native.run_turn`` -> the
    supervisor waits for ever on a turn that does not end itself (the test times out).
    """

    dispatch_id = _armed_dispatch()
    stub = bind_stub_turn(monkeypatch, StubTurn(block=True))
    monkeypatch.setattr(native, "KILL_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(native, "SUPERVISE_POLL_SECONDS", 0.02)

    agent_chat_dispatch._run_dispatch(dispatch_id, _spec(max_seconds=0.01))

    assert stub.interrupted.is_set()
    row = get_dispatch(dispatch_id)
    assert row["state"] == STATE_ERROR
    assert "budget" in row["result"]["error"]
    assert row["delivery_state"] == DELIVERY_PENDING


def test_a_turn_whose_door_raises_settles_the_row(store_home, monkeypatch):
    dispatch_id = _armed_dispatch()
    bind_stub_turn(monkeypatch, StubTurn(raises=OSError("no door for you")))

    agent_chat_dispatch._run_dispatch(dispatch_id, _spec())

    row = get_dispatch(dispatch_id)
    assert row["state"] == STATE_ERROR
    assert "failed before it replied" in row["result"]["error"]
    assert "no door for you" in row["result"]["error"]


def test_a_turn_that_ignores_its_interrupt_is_left_and_the_request_settles(store_home, monkeypatch):
    """Crash/hang isolation, decided 2026-11-21: a wedged turn keeps its thread, never the request.

    *Killing mutation:* drop the abandon arm in ``native.run_turn`` -> ``_run_dispatch`` never
    returns while the turn ignores its interrupt.
    """

    dispatch_id = _armed_dispatch()
    stub = bind_stub_turn(monkeypatch, StubTurn(block=True, ignore_interrupt=True))
    monkeypatch.setattr(native, "KILL_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(native, "ABANDON_GRACE_SECONDS", 0.1)
    monkeypatch.setattr(native, "SUPERVISE_POLL_SECONDS", 0.02)
    try:
        agent_chat_dispatch._run_dispatch(dispatch_id, _spec(max_seconds=0.01))

        assert stub.interrupted.is_set() and not stub.finished.is_set()
        row = get_dispatch(dispatch_id)
        assert row["state"] == STATE_ERROR
        assert "budget" in row["result"]["error"]
        assert dispatch_id not in agent_chat_dispatch.supervised_dispatch_ids()
    finally:
        stub.release.set()
        assert stub.finished.wait(5)
    # The turn's late end writes nothing over the settled row.
    assert get_dispatch(dispatch_id)["state"] == STATE_ERROR


def test_a_typed_chokepoint_refusal_still_reaches_the_sender(store_home, monkeypatch):
    """A cycle refusal on a detached hop must not vanish.

    The guard runs where it always ran (the handler the native turn enters);
    detaching only changes WHEN the sender hears about it. The refusal becomes
    the dispatch's recorded outcome, which the drain then delivers.
    """

    dispatch_id = _armed_dispatch()
    bind_stub_turn(monkeypatch, StubTurn(
        {"ok": False, "error_kind": "relay_cycle", "error": "relay cycle detected"}, exit_code=2,
    ))

    agent_chat_dispatch._run_dispatch(dispatch_id, _spec())

    row = get_dispatch(dispatch_id)
    assert row["state"] == STATE_ERROR
    assert "Nothing was executed" in row["result"]["error"]
    assert row["delivery_state"] == DELIVERY_PENDING


def test_a_real_turn_runs_through_the_bound_door_in_this_process(store_home, monkeypatch):
    """One pass through the REAL handler, in this process, with no second Hermes.

    Everything above stubs the door. This binds the CLI's real turn handler (as serve
    boot does) and dispatches to a persona that does not exist, so the real handler
    refuses in well under a second without a provider call. It proves what the stubs
    cannot: the arguments are the handler's real namespace, its payload comes back
    through the sink, and the completion is recorded — and no process was spawned.

    *Killing mutation:* ``native._turn_body`` dropping ``run.payload`` -> state ``unknown``.
    """

    import subprocess

    from hermes_cli.harness_parts.mission_chat_door_binding import bind_mission_chat_door
    from agent_runtime import mission_chat_door

    monkeypatch.setattr(mission_chat_door, "_turn", None)
    bind_mission_chat_door()

    def no_spawn(*a, **k):
        raise AssertionError("a dispatched turn must not start a process")

    monkeypatch.setattr(subprocess, "Popen", no_spawn)
    dispatch_id = _armed_dispatch()

    agent_chat_dispatch._run_dispatch(dispatch_id, _spec(persona_id="no_such_persona_wp_h2", max_seconds=120.0))

    row = get_dispatch(dispatch_id)
    # A refused turn is a RESULT, not a hang: terminal, deliverable, and typed.
    assert row["state"] == STATE_ERROR
    assert row["delivery_state"] == DELIVERY_PENDING
    assert "persona" in row["result"]["error"].lower()
    assert row["owner_pid"] == os.getpid()


# --------------------------------------------------------------------------
# agent_chat_dispatches
# --------------------------------------------------------------------------


def test_dispatches_lists_only_the_callers_own_work(
    store_home, deliverable_lane, queued, monkeypatch
):
    mine = _send()["dispatch_id"]
    patch_where_bound(monkeypatch, dispatch_delivery, "_sender_persona", lambda root: ("qa", "personainst_qa"))
    _send(requested_by_session="persona_chat_personainst_qa_bbbbbbbbbbbb")

    listed = json.loads(agent_chat_dispatches(requested_by_session=SENDER_ROOT))

    assert listed["ok"] is True
    assert [row["dispatch_id"] for row in listed["dispatches"]] == [mine]
    assert listed["running"] == 1


def test_dispatches_without_a_session_lists_nothing_not_everything(
    store_home, deliverable_lane, queued
):
    _send()

    listed = json.loads(agent_chat_dispatches(requested_by_session=None))

    assert listed["count"] == 0
    assert listed["dispatches"] == []


def test_dispatches_never_carries_the_whole_reply(store_home, deliverable_lane, queued):
    """A status check must not cost the same context as the delivery itself."""

    from agent_runtime.dispatch_store import STATE_COMPLETED, record_completion

    dispatch_id = _send()["dispatch_id"]
    record_completion(dispatch_id, state=STATE_COMPLETED, reply="y" * 5000)

    row = json.loads(agent_chat_dispatches(requested_by_session=SENDER_ROOT))["dispatches"][0]

    assert row["reply_chars"] == 5000
    assert len(row["reply_excerpt"]) == 400


def test_state_filter_splits_running_from_done(store_home, deliverable_lane, queued):
    from agent_runtime.dispatch_store import STATE_COMPLETED, record_completion

    done = _send()["dispatch_id"]
    running = _send()["dispatch_id"]
    record_completion(done, state=STATE_COMPLETED, reply="ok")

    only_running = json.loads(
        agent_chat_dispatches(requested_by_session=SENDER_ROOT, state="running")
    )
    only_done = json.loads(agent_chat_dispatches(requested_by_session=SENDER_ROOT, state="done"))

    assert [row["dispatch_id"] for row in only_running["dispatches"]] == [running]
    assert [row["dispatch_id"] for row in only_done["dispatches"]] == [done]


# --------------------------------------------------------------------------
# schema / registration
# --------------------------------------------------------------------------


def test_both_tools_are_registered_on_the_agent_chat_toolset():
    for name in ("agent_chat_send", "agent_chat_dispatches"):
        entry = registry.get_entry(name)
        assert entry is not None, name
        assert entry.toolset == "agent_chat"
    assert AGENT_CHAT_DISPATCHES_SCHEMA["parameters"]["required"] == []


def test_max_seconds_has_no_schema_default_so_the_dispatch_budget_survives():
    """A materialised 240 default would silently cap every background dispatch."""

    assert "default" not in AGENT_CHAT_SEND_SCHEMA["parameters"]["properties"]["max_seconds"]


def test_the_send_schema_teaches_when_to_detach():
    text = AGENT_CHAT_SEND_SCHEMA["parameters"]["properties"]["wait"]["description"]
    assert "false" in text
    assert "background" in text
    assert "agent_chat_dispatches" in text


def test_a_dispatch_runs_while_another_thread_holds_the_workdir_lock(store_home):
    """THE regression the old child process existed to prevent, now pinned for the native turn.

    The first in-process implementation ran under ``profile_runner._WORKDIR_LOCK``, a
    PROCESS-WIDE lock held for a whole turn, so one 30-minute dispatch froze every
    other turn. Run-serialization S5 retired that whole-run hold; a native turn now
    holds only its own chat root's lock. Here another thread holds the legacy lock for
    the whole test, and the dispatch still runs to a terminal outcome.
    """

    import threading

    from agent_runtime import profile_runner
    from hermes_cli.harness_parts.mission_chat_door_binding import bind_mission_chat_door

    bind_mission_chat_door()
    dispatch_id = _armed_dispatch()
    holding = threading.Event()
    release = threading.Event()

    def _hold_the_lock():
        with profile_runner._WORKDIR_LOCK:
            holding.set()
            release.wait(30)

    holder = threading.Thread(target=_hold_the_lock, daemon=True)
    holder.start()
    try:
        assert holding.wait(10), "could not take the workdir lock"
        agent_chat_dispatch._run_dispatch(
            dispatch_id,
            _spec(persona_id="no_such_persona_wp_h2", max_seconds=120.0),
        )
    finally:
        release.set()
        holder.join(timeout=10)

    row = get_dispatch(dispatch_id)
    assert row["state"] == STATE_ERROR
    assert row["delivery_state"] == DELIVERY_PENDING


# --------------------------------------------------------------------------
# payload integrity: a silent wrong answer is the failure class here
# (the peer frame reader, ``parse_reply_payload``, and the one payload mapping)
# --------------------------------------------------------------------------


def test_trailing_json_after_the_payload_does_not_become_the_result():
    """"Last object wins" was wrong in BOTH directions, and both were live.

    A shutdown notice printed after a successful turn turned it into an error; a
    trailing `{}` turned it into a success with an EMPTY reply, which reads to an
    agent as "they had nothing to report". The handler's own `capability_id` is
    the discriminator, so ordering stops deciding (a peer's printed frames).
    """

    payload = {"ok": True, "capability_id": "mission.chat.message", "reply": "3 failures"}
    text = json.dumps(payload) + '\n{"event":"mcp_shutdown","ok":false}\n'
    assert agent_chat_dispatch.parse_reply_payload(text) == payload


def test_a_trailing_empty_object_does_not_become_an_empty_success():
    payload = {"ok": True, "capability_id": "mission.chat.message", "reply": "done"}
    assert agent_chat_dispatch.parse_reply_payload(json.dumps(payload) + "\n{}\n") == payload
    assert (
        agent_chat_dispatch.parse_reply_payload(json.dumps(payload) + '\n{"ok": true}\n')
        == payload
    )
    # A payload with no marker at all is still better than reporting nothing.
    assert agent_chat_dispatch.parse_reply_payload('{"ok": true, "reply": "hi"}') == {
        "ok": True,
        "reply": "hi",
    }


def test_a_failure_before_the_turn_still_settles_the_row(store_home, monkeypatch):
    """"Never raises" is structural, not a docstring promise.

    A raise before the turn used to escape entirely — `executor.submit` never
    retrieves the Future, so nothing observed it — leaving the row `running` and
    owned by the sender's still-live serve PID, which the orphan sweep can
    therefore never settle. Running forever, silently.
    """

    dispatch_id = _armed_dispatch()
    monkeypatch.setattr(
        agent_chat_dispatch.local,
        "run_turn",
        lambda spec, **kw: (_ for _ in ()).throw(KeyError("persona_id")),
    )

    agent_chat_dispatch._run_dispatch(dispatch_id, _spec())  # must not raise

    row = get_dispatch(dispatch_id)
    assert row["state"] == STATE_ERROR
    assert "supervisor failed" in row["result"]["error"]
    assert row["delivery_state"] == DELIVERY_PENDING


def test_a_supervised_dispatch_is_not_an_orphan(store_home, monkeypatch):
    """THE race the periodic sweep introduced.

    Between the owner stamp and the supervisor's `record_completion` the sweep may
    read a running row whose owner probe says "gone" (a recycled number, a probe
    hiccup). If it answers there, the sender is told "the outcome is unknown" for a
    dispatch that COMPLETED, and the real answer arriving moments later is
    swallowed by the delivery-turn replay dedup: told nothing, never corrected.
    """

    from agent_runtime.dispatch_store import restore_undelivered_dispatches

    dispatch_id = _armed_dispatch()
    monkeypatch.setattr("gateway.status._pid_exists", lambda pid: False)

    agent_chat_dispatch._mark_supervised(dispatch_id)
    try:
        assert restore_undelivered_dispatches()["restored"] == 0
        assert get_dispatch(dispatch_id)["state"] == STATE_RUNNING
    finally:
        agent_chat_dispatch._forget_supervised(dispatch_id)

    # Once nobody is supervising it, it IS an orphan and settles normally.
    assert restore_undelivered_dispatches()["restored"] == 1
    assert get_dispatch(dispatch_id)["state"] == "unknown"


def test_the_supervisors_observed_outcome_beats_the_sweeps_guess(store_home, monkeypatch):
    """End-to-end of the race: the sender must receive the REAL answer.

    Even with the sweep having already settled the row `unknown`, the
    supervisor's observed completion has to win — and re-arm delivery so the
    answer actually goes out.
    """

    from agent_runtime.dispatch_store import restore_undelivered_dispatches

    dispatch_id = _armed_dispatch()
    monkeypatch.setattr("gateway.status._pid_exists", lambda pid: False)

    # The sweep gets there first (nothing supervising, e.g. after a restart).
    assert restore_undelivered_dispatches()["restored"] == 1
    assert get_dispatch(dispatch_id)["state"] == "unknown"

    # The supervisor then reports what it actually observed.
    bind_stub_turn(monkeypatch, StubTurn({"ok": True, "capability_id": "mission.chat.message", "reply": "3 failures"}))
    agent_chat_dispatch._run_dispatch(dispatch_id, _spec())

    row = get_dispatch(dispatch_id)
    assert row["state"] == "completed"
    assert row["result"]["reply"] == "3 failures"
    assert row["delivery_state"] == DELIVERY_PENDING


def test_a_turn_that_answered_with_nothing_records_the_silence(store_home, monkeypatch):
    """`ok` + an empty reply is a SILENT turn, and the row is the only witness.

    If the verdict is not recorded here it is gone, and the sender reads the same
    blank for "they answered with nothing" as for "their answer never made it
    back" — one of which is worth re-dispatching and the other is not.
    """

    dispatch_id = _armed_dispatch()
    bind_stub_turn(monkeypatch, StubTurn({
        "ok": True,
        "reply": "",
        "session_id": "s-dev",
        "turn_visibility": {
            "state": "silent",
            "reason": "truncated",
            "finish_reason": "incomplete",
            "reply_chars": 0,
        },
    }))

    agent_chat_dispatch._run_dispatch(dispatch_id, _spec())

    row = get_dispatch(dispatch_id)
    # Still COMPLETED: the turn ran. Silence is not an error.
    assert row["state"] == "completed"
    assert row["result"]["visibility"]["state"] == "silent"
    assert row["result"]["visibility"]["finish_reason"] == "incomplete"


def test_a_payload_without_the_typed_block_still_gets_a_verdict(store_home, monkeypatch):
    """No block on the payload -> classified from the reply it did send."""

    dispatch_id = _armed_dispatch()
    bind_stub_turn(monkeypatch, StubTurn({"ok": True, "reply": "3 failures", "session_id": "s"}))

    agent_chat_dispatch._run_dispatch(dispatch_id, _spec())

    assert get_dispatch(dispatch_id)["result"]["visibility"]["state"] == "visible"


def test_a_turn_that_handed_back_no_payload_records_no_verdict(store_home, monkeypatch):
    """Absent stays absent: with no payload there is nothing to have a verdict about."""

    dispatch_id = _armed_dispatch()
    bind_stub_turn(monkeypatch, StubTurn(None, exit_code=1))

    agent_chat_dispatch._run_dispatch(dispatch_id, _spec())

    assert "visibility" not in get_dispatch(dispatch_id)["result"]


class _Sink:
    """A pump sink: one ``append`` per line."""

    def __init__(self):
        self.lines: list[str] = []

    def append(self, text):
        self.lines.append(text)

    def text(self):
        return "".join(self.lines)


class _QuickJoin:
    """A pump thread whose joins are capped at 0.2 s, so the release's own
    10 s/2 s joins cost a test a fraction of a second."""

    def __init__(self, thread):
        self.thread = thread
        self.stop = thread.stop

    def join(self, timeout=None):
        self.thread.join(min(timeout or 0.2, 0.2))

    def is_alive(self):
        return self.thread.is_alive()


def _piped_pumps():
    out_r, out_w = os.pipe()
    err_r, err_w = os.pipe()
    proc = type("Proc", (), {})()
    proc.stdout = os.fdopen(out_r, "r", encoding="utf-8")
    proc.stderr = os.fdopen(err_r, "r", encoding="utf-8")
    tail = _Sink()
    threads = [
        subprocess_pumps.drain(proc.stdout, tail),
        subprocess_pumps.drain(proc.stderr, _Sink()),
    ]
    return proc, tail, threads, out_w, err_w


def test_a_pump_hands_the_sink_whole_lines_across_split_writes():
    """The sink contract: one append per line even when a line arrives in two
    writes, CRLF folded to LF as the text-mode stream did, and an unterminated
    tail flushed at EOF."""

    import time

    out_r, out_w = os.pipe()
    stream = os.fdopen(out_r, "r", encoding="utf-8")
    sink: list[str] = []
    pump = subprocess_pumps.drain(stream, sink)
    os.write(out_w, b'{"capability_')
    time.sleep(0.2)
    os.write(out_w, b'id": "x"}\r\nlast')
    os.close(out_w)
    subprocess_pumps.release_pumps(None, [_QuickJoin(pump)])
    assert not pump.is_alive()
    assert sink == ['{"capability_id": "x"}\n', "last"]


def test_the_pumps_release_when_the_writers_close():
    """Positive control for the pump pair (sheet agent_chat_dispatch.md §6.3),
    the cooperative arm: every writer closes, both pumps end inside the join
    bound, and nothing the writer wrote is lost."""

    import time

    proc, tail, threads, out_w, err_w = _piped_pumps()
    os.write(out_w, b'{"capability_id": "x"}\n')
    os.close(out_w)
    os.close(err_w)
    started = time.monotonic()
    subprocess_pumps.release_pumps(proc, [_QuickJoin(t) for t in threads])
    assert time.monotonic() - started < 12
    assert not any(t.is_alive() for t in threads)
    assert tail.text() == '{"capability_id": "x"}\n'


def test_the_pumps_are_forced_loose_when_a_survivor_holds_the_pipe():
    """The forced arm: a grandchild still holds both write ends, so readline
    never sees EOF; closing the parent's read handles must free both pumps."""

    import time

    import threading

    proc, _tail, threads, out_w, err_w = _piped_pumps()
    try:
        # The release runs on its own daemon thread under a deadline, so a
        # release that parks (the Windows close-under-a-blocked-reader hang)
        # reds this case instead of wedging the run that holds it.
        releaser = threading.Thread(
            target=subprocess_pumps.release_pumps,
            args=(proc, [_QuickJoin(t) for t in threads]),
            daemon=True,
        )
        started = time.monotonic()
        releaser.start()
        releaser.join(15)
        assert not releaser.is_alive(), "release_pumps parked on a pipe a survivor holds"
        assert time.monotonic() - started < 12
        assert not any(t.is_alive() for t in threads)
    finally:
        os.close(out_w)
        os.close(err_w)


# --------------------------------------------------------------------------
# relay inside a run: detach, own, cancel (runtime-queue rows of 2026-10-08)
# --------------------------------------------------------------------------
#
# An inline relay from inside a run waits on locks the sender holds (measured
# 203 s on Amelia turn ``agent-chat-send-db7a2d34``, 2026-10-08), so it is
# detached. These tests pin that repair and the Stop contract beside it: normal
# completion keeps a dispatch, Stop on the parent cancels that turn's own
# dispatches, a turn that already replied keeps its reply.

import threading
import time

from agent_runtime.relay_policy import RELAY_PARENT_TURN


def _never_called(*a, **k):
    raise AssertionError("the inline relay handler must not run inside a running turn")


def test_an_inline_send_inside_a_run_is_detached_not_waited_on(store_home, deliverable_lane, queued, monkeypatch):
    from tools.agent_chat import send as send_module

    monkeypatch.setattr(chat_turn_message, "_cmd_mission_chat_message", _never_called)
    monkeypatch.setattr(send_module, "_inside_agent_run", lambda: True)
    token = RELAY_PARENT_TURN.set("turn-parent-1")
    try:
        result = json.loads(agent_chat_send(persona_id="dev", message="hi", requested_by_session=SENDER_ROOT))
    finally:
        RELAY_PARENT_TURN.reset(token)

    assert result["ok"] is True
    assert result["dispatched"] is True
    assert result["auto_detached"] is True
    assert "do not poll" in result["next_expected"]
    assert "reply" not in result
    assert queued[0]["dispatch_id"] == result["dispatch_id"]
    # Owned by the turn that sent it: the one fact Stop needs.
    assert get_dispatch(result["dispatch_id"])["parent_turn_id"] == "turn-parent-1"

    # Positive control: outside a run the inline lane is untouched.
    seen = []

    def inline(args):
        seen.append(args.persona_id)
        args.payload_sink({"ok": True, "reply": "ack"})
        return 0

    monkeypatch.setattr(chat_turn_message, "_cmd_mission_chat_message", inline)
    monkeypatch.setattr(send_module, "_inside_agent_run", lambda: False)
    result = json.loads(agent_chat_send(persona_id="dev", message="hi", requested_by_session=SENDER_ROOT))
    assert result["reply"] == "ack" and "dispatched" not in result
    assert seen == ["dev"]


def test_the_run_lock_itself_is_what_detaches_the_send(store_home, deliverable_lane, queued, monkeypatch):
    """Reproduce the deadlock with the real gauge and the real lock, no stub of either.

    *Killing mutation:* drop the ``_inside_agent_run`` check in ``Send.envelope``.
    The fake child then blocks on ``_WORKDIR_LOCK`` exactly as the real one did,
    and the send never returns within the join below.
    """

    from agent_runtime.profile_runner.workdir import _WORKDIR_LOCK, _counted_agent_run

    def child_turn(args):  # the target's turn needs the run lock, like every run
        with _WORKDIR_LOCK:
            args.payload_sink({"ok": True, "reply": "late"})
        return 0

    monkeypatch.setattr(chat_turn_message, "_cmd_mission_chat_message", child_turn)

    run_entered, run_release = threading.Event(), threading.Event()

    def sender_run():  # the sender's run: holds the lock and is counted in flight
        with _counted_agent_run(), _WORKDIR_LOCK:
            run_entered.set()
            run_release.wait(10)

    outcome = {}

    def tool_thread():  # the tool runs on a worker thread, never the run's own
        outcome["result"] = json.loads(
            agent_chat_send(persona_id="dev", message="hi", requested_by_session=SENDER_ROOT)
        )

    sender = threading.Thread(target=sender_run, daemon=True)
    sender.start()
    assert run_entered.wait(5)
    try:
        # The real executor runs a tool under the turn's copied context
        # (``propagate_context_to_thread``); the delivery declaration the lane
        # checks lives in that context, so the worker is started the same way.
        import contextvars

        worker = threading.Thread(target=contextvars.copy_context().run, args=(tool_thread,), daemon=True)
        worker.start()
        worker.join(5)
        assert not worker.is_alive(), "the send waited on a lock its own turn holds"
    finally:
        run_release.set()
        sender.join(5)
    assert outcome["result"]["auto_detached"] is True
    assert queued and queued[0]["dispatch_id"] == outcome["result"]["dispatch_id"]


def test_an_auto_detached_send_that_cannot_deliver_names_the_turn_not_wait_true(store_home, monkeypatch, queued):
    from tools.agent_chat import send as send_module

    monkeypatch.setattr(chat_turn_message, "_cmd_mission_chat_message", _never_called)
    monkeypatch.setattr(send_module, "_inside_agent_run", lambda: True)

    result = json.loads(agent_chat_send(persona_id="dev", message="hi"))  # no session to deliver into

    assert result["ok"] is False
    assert result["error_kind"] == "inline_relay_unavailable"
    assert "wait=true" not in result["error"]
    assert "running turn" in result["error"]
    assert queued == [] and running_dispatches() == []


def test_cancel_before_start_settles_cancelled_and_the_worker_runs_nothing(store_home, monkeypatch):
    dispatch_id = _armed_dispatch()
    agent_chat_dispatch._mark_supervised(dispatch_id)
    stub = bind_stub_turn(monkeypatch, StubTurn({"ok": True, "reply": "ran anyway"}))

    answer = agent_chat_dispatch.request_cancel(dispatch_id, reason="operator_stop")

    assert answer["outcome"] == "cancelled"
    row = get_dispatch(dispatch_id)
    assert row["state"] == "cancelled"
    assert "before it started" in row["result"]["error"]
    assert row["delivery_state"] == DELIVERY_PENDING  # the sender is still told

    agent_chat_dispatch._run_dispatch(dispatch_id, _spec())  # the queued worker arrives late
    assert stub.calls == []
    assert get_dispatch(dispatch_id)["state"] == "cancelled"
    assert dispatch_id not in agent_chat_dispatch.supervised_dispatch_ids()


def _run_in_background(dispatch_id, stub, monkeypatch):
    bind_stub_turn(monkeypatch, stub)
    monkeypatch.setattr(native, "SUPERVISE_POLL_SECONDS", 0.02)
    agent_chat_dispatch._mark_supervised(dispatch_id)
    worker = threading.Thread(
        target=agent_chat_dispatch._run_dispatch, args=(dispatch_id, _spec(max_seconds=30)), daemon=True
    )
    worker.start()
    assert stub.started.wait(5), "the native turn did not start"
    assert get_dispatch(dispatch_id)["started_at"], "the owner stamp must record when the turn started"
    return worker


def test_cancel_of_a_running_turn_interrupts_it_and_settles_cancelled(store_home, monkeypatch):
    """Stop reaches the native turn through its agent's own interrupt seam (``live_turns``).

    *Killing mutation:* ``native.run_turn`` never calling ``interrupt`` on a Stop -> the turn
    runs on and the worker is still alive after the join.
    """

    dispatch_id = _armed_dispatch()
    stub = StubTurn(block=True)
    worker = _run_in_background(dispatch_id, stub, monkeypatch)

    answer = agent_chat_dispatch.request_cancel(dispatch_id, reason="operator_stop")
    assert answer["outcome"] == "stopping"  # reported until the supervisor settles it
    worker.join(5)
    assert not worker.is_alive()

    assert stub.interrupted.is_set()
    row = get_dispatch(dispatch_id)
    assert row["state"] == "cancelled"
    assert "operator_stop" in row["result"]["error"]


def test_a_cancel_that_lands_before_the_turn_registered_still_stops_it(store_home, monkeypatch):
    """The Stop is re-sent each poll until the turn has registered to take it.

    *Killing mutation:* send the interrupt once only -> a Stop that lands between the owner
    stamp and the turn's ``live_turns`` registration is lost and the worker runs on.
    """

    from agent_runtime import dispatch_store

    dispatch_id = _armed_dispatch()
    # The turn registers a while after it starts: the first interrupt finds nothing to stop.
    stub = StubTurn(block=True, register_after=0.3)
    stamped, cancelled = threading.Event(), threading.Event()
    real_stamp = dispatch_store.set_dispatch_owner

    def stamp_then_wait_for_the_cancel(*args, **kwargs):
        result = real_stamp(*args, **kwargs)
        stamped.set()
        assert cancelled.wait(5)
        return result

    monkeypatch.setattr(dispatch_store, "set_dispatch_owner", stamp_then_wait_for_the_cancel)
    bind_stub_turn(monkeypatch, stub)
    monkeypatch.setattr(native, "SUPERVISE_POLL_SECONDS", 0.02)
    agent_chat_dispatch._mark_supervised(dispatch_id)
    worker = threading.Thread(
        target=agent_chat_dispatch._run_dispatch, args=(dispatch_id, _spec(max_seconds=30)), daemon=True
    )
    worker.start()
    assert stamped.wait(5)
    assert agent_chat_dispatch.request_cancel(dispatch_id, reason="operator_stop")["outcome"] == "stopping"
    cancelled.set()
    worker.join(5)

    assert not worker.is_alive()
    assert stub.interrupted.is_set()
    assert get_dispatch(dispatch_id)["state"] == "cancelled"


def test_cancel_that_lands_after_the_turn_replied_keeps_the_reply(store_home, monkeypatch):
    dispatch_id = _armed_dispatch()
    stub = StubTurn(block=True, ignore_interrupt=True,
                    payload_on_release={"ok": True, "reply": "done already", "session_id": "s-dev"})
    worker = _run_in_background(dispatch_id, stub, monkeypatch)

    assert agent_chat_dispatch.request_cancel(dispatch_id)["outcome"] == "stopping"
    assert stub.interrupted.wait(5)
    stub.release.set()  # the reply was already on its way out
    worker.join(5)

    row = get_dispatch(dispatch_id)
    assert row["state"] == "completed"
    assert row["result"]["reply"] == "done already"


def test_cancel_of_a_finished_dispatch_reports_already_finished_and_keeps_its_result(store_home):
    from agent_runtime.dispatch_store import STATE_COMPLETED, record_completion

    dispatch_id = _armed_dispatch()
    record_completion(dispatch_id, state=STATE_COMPLETED, reply="kept")

    answer = agent_chat_dispatch.request_cancel(dispatch_id)

    assert answer == {"dispatch_id": dispatch_id, "outcome": "already_finished", "state": "completed"}
    assert get_dispatch(dispatch_id)["result"]["reply"] == "kept"


def test_cancel_of_a_queued_dispatch_another_process_supervises_is_settled_through_the_row(store_home):
    """D1.07 (owner ruling a) replaced ``not_owned_here`` here: the canceller
    leaves the durable mark and, the turn not having started, settles the row
    as its owner would. The running half is ``test_dispatch_cancel_elsewhere``."""

    dispatch_id = _armed_dispatch()  # recorded, never marked supervised here

    assert agent_chat_dispatch.request_cancel(dispatch_id)["outcome"] == "cancelled"
    row = get_dispatch(dispatch_id)
    assert row["state"] == "cancelled"
    assert row["cancel_requested"] == "operator_cancel"


def test_stop_cancels_only_the_stopped_turns_own_dispatches(store_home, monkeypatch):
    from agent_runtime import operator_execution

    own = _armed_dispatch(parent_turn_id="turn-A")
    other_turn = _armed_dispatch(parent_turn_id="turn-B")
    other_session = mint_dispatch_id()
    record_dispatch(
        dispatch_id=other_session,
        sender_session_id="persona_chat_personainst_dev_bbbbbbbbbbbb",
        target_persona="dev",
        ask="run the suite",
        parent_turn_id="turn-A",
    )
    for dispatch_id in (own, other_turn, other_session):
        agent_chat_dispatch._mark_supervised(dispatch_id)
    monkeypatch.setattr(operator_execution, "execution_status", lambda *a, **k: {"outcome": "stop_requested"})
    monkeypatch.setattr(operator_execution, "read_chat_turn_receipt", lambda turn: object())  # an admitted send

    result = operator_execution.stop_operator_execution(SENDER_ROOT, "turn-A")

    assert result["dependent_dispatches"] == [
        {"dispatch_id": own, "target_persona": "dev", "outcome": "cancelled"}
    ]
    assert get_dispatch(own)["state"] == "cancelled"
    assert get_dispatch(other_turn)["state"] == STATE_RUNNING
    assert get_dispatch(other_session)["state"] == STATE_RUNNING

    # A turn that finished on its own keeps its children: Stop reaches nothing.
    monkeypatch.setattr(operator_execution, "execution_status", lambda *a, **k: {"outcome": "finished"})
    result = operator_execution.stop_operator_execution(SENDER_ROOT, "turn-B")
    assert "dependent_dispatches" not in result
    assert get_dispatch(other_turn)["state"] == STATE_RUNNING


def test_started_at_and_the_queue_wait_are_recorded_when_the_turn_starts(store_home, monkeypatch):
    dispatch_id = _armed_dispatch()
    bind_stub_turn(monkeypatch, StubTurn({"ok": True, "reply": "ok"}))

    agent_chat_dispatch._run_dispatch(dispatch_id, _spec())

    row = get_dispatch(dispatch_id)
    assert row["started_at"] >= row["dispatched_at"]
    summary = agent_chat_dispatch.summarize_for_caller(row)
    assert summary["queued_seconds"] == int(row["started_at"] - row["dispatched_at"])
    assert summary["parent_turn_id"] is None


