"""p10-messaging M5: the bridge is a serve lane — it starts with the Work engine, stops on the drain, and is off
unless the setting AND the token say otherwise.

The transport is a fake (``TRANSPORTS`` row swapped; never the network); the binding/operator/credential stores,
the send queue and the harness config are the real ones on this test's isolated home. The last test runs the
real ``serve_loop`` in service mode (the harness of ``test_serve_service_mode.py``) and drains it over the socket.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import httpx
import pytest

from agent_runtime import paths
from agent_runtime.messaging import credentials, rpc, serve_lane
from agent_runtime.messaging.models import Platform
from agent_runtime.messaging.operators import Operator, OperatorStore
from agent_runtime.messaging.serve_lane import LaneReason, LaneState, MessagingLane, start_messaging_bridge
from agent_runtime.messaging.transport import InboundMessage, MessageRef, SendResult
from agent_runtime.work_store.persona_turn import OriginKind, PersonaTurnExecutor
from tests.waiting import wait_until

TOKEN = "123456789:AAFakeTokenForTestsOnly_abcdefghijk"
TG = Platform.TELEGRAM


class FakeTransport:
    """A transport that records what the lane did to it; ``deliver`` plays the poller."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("a bot token is required")  # as TelegramTransport does
        self.on_update = None
        self.starts = 0
        self.stops = 0
        self.sent: list[tuple[str, str]] = []

    def start(self, on_update) -> None:
        self.starts += 1
        self.on_update = on_update

    def stop(self) -> None:
        self.stops += 1

    @property
    def polling(self) -> bool:
        return self.starts > self.stops

    def deliver(self, text: str, update_id: int = 1000) -> None:
        self.on_update(InboundMessage(update_id, "-1001", None, "42", "Max", "7", text))

    def send(self, chat, text, thread=None, reply_to=None):
        self.sent.append((chat, text))
        return SendResult((MessageRef(chat, str(len(self.sent))),))

    def send_card(self, chat, text, buttons, thread=None):
        return MessageRef(chat, "card")

    def edit(self, ref, text, buttons=None):
        return None

    def typing(self, chat, thread=None):
        return None

    def answer_callback(self, callback_id, text=""):
        return None


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("a messaging test reached the network")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture
def built(monkeypatch):
    made: list[FakeTransport] = []

    def factory(token):
        transport = FakeTransport(token)
        made.append(transport)
        return transport
    monkeypatch.setitem(serve_lane.TRANSPORTS, TG, factory)
    monkeypatch.setattr(serve_lane, "_current", None)
    return made


class _Instances:
    def get(self, instance_id):
        return SimpleNamespace(id=instance_id, persona_id="alice", display_name="Alice",
                               runtime_root=str(paths.store_root()))


def _session():
    turns = PersonaTurnExecutor(instances=_Instances(), root_of=lambda store, **_: "persona_chat_root_tg",
                                wake=lambda: None)
    return SimpleNamespace(drain_state=None, liveness_stop=threading.Event(), work_executor=turns,
                           serve_request_home=None)


def _enable(on: bool = True) -> None:
    rpc.execute("platform.enable" if on else "platform.disable", {"platform": "telegram"}, by="test")


def _lane_word(lane: MessagingLane) -> tuple[str, str | None]:
    row = lane.state()["telegram"]
    return row["state"], row["reason"]


def test_the_lane_stays_off_while_messaging_is_disabled(built):
    """Killing mutation: ``_wanted`` drops its ``messaging_enabled`` check → a transport is built and polls
    with the setting false (``built`` non-empty) → red."""
    credentials.set_token(TG, TOKEN)
    lane = MessagingLane(_session())
    lane.tick()
    assert built == []
    assert _lane_word(lane) == (LaneState.OFF.value, LaneReason.DISABLED.value)


def test_a_missing_token_is_reported_never_raised(built):
    """Killing mutation: ``_wanted`` drops its ``bot_token`` check → the lane builds a transport over an empty
    token, which raises (``start_failed``) instead of reporting ``credential_absent`` → red."""
    _enable()
    lane = MessagingLane(_session())
    monkey_current = serve_lane._current
    serve_lane._current = lane
    try:
        lane.tick()
        assert built == []
        assert _lane_word(lane) == (LaneState.OFF.value, LaneReason.CREDENTIAL_ABSENT.value)
        telegram = rpc.status({}, "test")["platforms"]["telegram"]
        assert telegram["credential"] == "absent"
        assert telegram["lane"] == {"state": "off", "reason": "credential_absent"}
    finally:
        serve_lane._current = monkey_current


def test_drain_stops_polling(built, caplog):
    """Killing mutation: ``_wanted`` ignores ``drain_state`` → the transport is never stopped and an update
    the poller still holds is queued as a turn after the drain began → red.

    The settle listener outlives the polling: a turn already queued still sends its reply until
    ``liveness_stop``, when the bridge stops."""
    credentials.set_token(TG, TOKEN)
    OperatorStore().allow(Operator(TG, "42", "Max", "test", "2026-10-19T00:00:00+00:00"))
    _enable()
    session = _session()
    lane = MessagingLane(session)
    lane.tick()
    [transport] = built
    assert transport.polling and _lane_word(lane) == (LaneState.RUNNING.value, None)
    assert OriginKind.MESSAGING in session.work_executor._origin_listeners

    session.drain_state = object()
    lane.tick()
    assert not transport.polling
    assert _lane_word(lane) == (LaneState.DRAINING.value, LaneReason.DRAINING.value)
    caplog.clear()
    transport.deliver("hello after the drain")  # an update the long poll was already holding
    assert '"kind": "messaging.inbound"' not in caplog.text and transport.sent == []
    assert OriginKind.MESSAGING in session.work_executor._origin_listeners

    session.liveness_stop.set()
    lane.close()
    assert OriginKind.MESSAGING not in session.work_executor._origin_listeners


def test_enable_and_disable_reach_the_running_lane(built):
    """Killing mutation: ``_platform_switch`` writes the setting without ``poke()`` → the lane (60 s tick) does
    not start within the wait → red."""
    credentials.set_token(TG, TOKEN)
    session = _session()
    lane = start_messaging_bridge(session, tick_seconds=60.0)
    try:
        lane.poke()  # the first tick otherwise waits one interval
        wait_until(lambda: lane.state().get("telegram"), what="the first tick")
        assert _lane_word(lane) == (LaneState.OFF.value, LaneReason.DISABLED.value)
        _enable()
        wait_until(lambda: built and built[0].polling, timeout=5, what="the lane started on enable")
        _enable(False)
        wait_until(lambda: not built[0].polling, timeout=5, what="the lane stopped on disable")
        assert _lane_word(lane) == (LaneState.OFF.value, LaneReason.DISABLED.value)
    finally:
        session.liveness_stop.set()
        lane.poke()
        lane.thread.join(5)


def test_a_service_serve_runs_the_lane_and_a_socket_drain_stops_it(built):
    """The real ``serve_loop`` under ``--service``: the lane starts with the Work engine, the starter detaches,
    ``serve connect --drain`` stops the polling and ends the runtime.

    Killing mutation: drop the ``start_messaging_bridge`` call from ``start_serve_work_engine`` → no transport
    is ever built → red."""
    from tests.agent_runtime.test_serve_service_mode import _drain_over_socket, _serve

    credentials.set_token(TG, TOKEN)
    _enable()
    with _serve(service=True) as handle:
        wait_until(lambda: built and built[0].polling, timeout=20, what="the serve's messaging lane polling")
        handle.pipe.close()  # the OS scheduler's starter walks away; the service parks
        lane = serve_lane.current()
        assert lane is not None and _lane_word(lane) == (LaneState.RUNNING.value, None)
        verdict = _drain_over_socket(handle)
        assert verdict["event"] == "drain_complete"
        handle.thread.join(20)
        assert not handle.thread.is_alive()
    wait_until(lambda: not built[0].polling, timeout=5, what="polling stopped by the drain")
