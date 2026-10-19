"""p10-messaging M3: a platform message is a QUEUED turn of the bound instance; the settle carries the reply.

The transport is the real ``TelegramTransport`` over the recorded fake Bot API (never the network); the send
queue, the settle records and the binding/operator stores are the real ones on this test's isolated home;
the instance store and the root lookup are fakes. Updates are driven by ``poll_once(bridge.inbound)``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime import mission_chat_door, paths
from agent_runtime.chat_turn_settles import outcome_from_payload, record_settle
from agent_runtime.messaging import bridge as bridge_module
from agent_runtime.messaging import rpc
from agent_runtime.messaging.bindings import Binding, BindingStore
from agent_runtime.messaging.bridge import QUEUED_NOTICE, MessagingBridge
from agent_runtime.messaging.models import Platform
from agent_runtime.messaging.operators import Operator, OperatorStore
from agent_runtime.messaging.telegram_api import TelegramTransport
from agent_runtime.work_store.persona_turn import ORIGIN_KIND_KEY, PersonaTurnExecutor
from tests.agent_runtime.messaging.fake_bot_api import API_BASE, FakeBotApi

TOKEN = "123456789:AAFakeTokenForTestsOnly_abcdefghijk"
ROOT = "persona_chat_root_tg"
TG = Platform.TELEGRAM


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("a messaging test reached the network")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture(autouse=True)
def _no_direct_turns(monkeypatch):
    def refuse(args):
        raise AssertionError("the bridge ran a chat turn directly instead of queueing it")
    monkeypatch.setattr(mission_chat_door, "run_mission_chat_turn", refuse)


class _Instances:
    def __init__(self, *instances):
        self.by_id = {i.id: i for i in instances}

    def get(self, instance_id):
        return self.by_id[instance_id]


def _instance(instance_id="inst-alice", display="Alice"):
    return SimpleNamespace(id=instance_id, persona_id="alice", display_name=display,
                           runtime_root=str(paths.store_root()))


@pytest.fixture
def rig():
    api = FakeBotApi(TOKEN)
    transport = TelegramTransport(TOKEN, client=api.client(), api_base=API_BASE, wait=lambda _s: False)
    alice, bob = _instance(), _instance("inst-bob", "Bob")
    turns = PersonaTurnExecutor(instances=_Instances(alice, bob), root_of=lambda store, **_: ROOT, wake=lambda: None)
    busy = {"value": False}
    bridge = MessagingBridge(transport, turns, roster=lambda: [alice, bob], root_busy=lambda _root: busy["value"])
    turns.register_origin_listener("messaging", bridge.settled)
    OperatorStore().allow(Operator(TG, "42", "Max", "rpc:stdio_owner", "2026-10-19T00:00:00+00:00"))
    return SimpleNamespace(api=api, transport=transport, turns=turns, bridge=bridge, busy=busy)


def _bind(chat="-1001", thread=None, instance="inst-alice"):
    BindingStore().set(Binding(TG, chat, thread, instance, "rpc:stdio_owner", "2026-10-19T00:00:00+00:00"))


def _poll(rig) -> list:
    seen = []
    rig.transport.poll_once(lambda update: (seen.append(update), rig.bridge.inbound(update)))
    return seen


def _receipts(caplog, kind):
    return [json.loads(r.getMessage()) for r in caplog.records
            if r.name == "agent_runtime.work_store.receipts" and f'"kind": "{kind}"' in r.getMessage()]


def test_unknown_operator_is_dropped_with_receipt(rig, caplog):
    """Killing mutation: drop the ``operators.is_allowed`` check in ``_message`` → the stranger is answered
    with the roster (or queued) → red."""
    caplog.set_level("INFO")
    _bind()
    rig.api.push_message("let me in", user_id=99)
    _poll(rig)
    assert rig.api.sent == [] and "sendChatAction" not in rig.api.methods()
    assert not send_queue.has_entries(ROOT)
    [refused] = _receipts(caplog, "messaging.refused")
    assert refused["reason"] == "unknown_operator" and refused["user_id"] == "99"
    assert "let me in" not in caplog.text  # receipts carry ids, never text


def test_inbound_is_a_queued_send_never_a_direct_turn(rig, caplog):
    """Killing mutation: ``_message`` calls ``mission_chat_door.run_mission_chat_turn`` instead of
    ``queue_inbound`` → no entry on the root (the fixture's refusal is logged by ``inbound``) → red."""
    caplog.set_level("INFO")
    _bind(thread="9")
    update_id = rig.api.push_message("what moved today?", thread_id=9)
    _poll(rig)
    entry = send_queue.find(ROOT, f"msg-telegram-{update_id}")
    assert entry is not None and entry.state == send_queue.STATE_QUEUED
    assert entry.args["message"] == "what moved today?" and entry.args["persona_instance_id"] == "inst-alice"
    assert entry.args["requested_by"] == "messaging:telegram:42" and entry.args["session_id"] == ROOT
    origin = entry.args[send_queue.ORIGIN_ARG]
    assert origin[ORIGIN_KIND_KEY] == "messaging" and "session_id" not in origin["messaging"]
    assert origin["messaging"] == {"platform": "telegram", "chat_id": "-1001", "thread_id": "9", "user_id": "42",
                                   "message_id": origin["messaging"]["message_id"], "update_id": update_id}
    assert rig.api.methods().count("sendChatAction") == 1 and rig.api.sent == []  # idle root: no notice
    [queued] = _receipts(caplog, "messaging.queued")
    assert queued["replay"] is False and queued["run_id"] == f"{ROOT}/msg-telegram-{update_id}"


def test_redelivery_converges(rig, caplog):
    """Killing mutation: the cmid stops being a function of the update id (e.g. ``msg-<message text hash>
    -<time>``) → the re-delivered update queues a second entry → red."""
    caplog.set_level("INFO")
    _bind()
    rig.api.push_message("once only")
    [update] = _poll(rig)
    rig.bridge.inbound(update)  # Telegram re-delivers an update whose offset was never confirmed
    assert [e.client_message_id for e in send_queue.entries(ROOT)] == [f"msg-telegram-{update.update_id}"]
    assert [r["replay"] for r in _receipts(caplog, "messaging.queued")] == [False, True]
    assert rig.api.methods().count("sendChatAction") == 1
    # After the runner ran it (settle recorded, entry removed) a re-delivery converges on the settle.
    cmid = f"msg-telegram-{update.update_id}"
    payload = {"ok": True, "session_id": ROOT, "reply": "done"}
    record_settle(client_message_id=cmid, session_id=ROOT, request_id=f"queued:{cmid}", exit_code=0,
                  outcome=outcome_from_payload(payload))
    send_queue.remove(ROOT, cmid)
    rig.bridge.inbound(update)
    assert not send_queue.has_entries(ROOT)
    assert [r["replay"] for r in _receipts(caplog, "messaging.queued")] == [False, True, True]


def test_a_busy_root_holds_the_message_and_says_so_once(rig):
    _bind()
    rig.busy["value"] = True
    rig.api.push_message("are you there?")
    [update] = _poll(rig)
    rig.bridge.inbound(update)
    assert len(send_queue.entries(ROOT)) == 1
    assert [m["text"] for m in rig.api.sent] == [QUEUED_NOTICE]


def test_the_settle_carries_the_reply_chunked_to_the_origin_chat(rig):
    _bind(thread="9")
    update_id = rig.api.push_message("write a lot", thread_id=9)
    _poll(rig)
    entry = send_queue.find(ROOT, f"msg-telegram-{update_id}")
    rig.turns.settled(entry, 0, {"ok": True, "reply": "x" * 5000})
    assert [len(m["text"]) for m in rig.api.sent] == [4096, 904]
    assert {m["chat_id"] for m in rig.api.sent} == {"-1001"} and {m["message_thread_id"] for m in rig.api.sent} == {9}
    assert "reply_parameters" in rig.api.sent[0] and "reply_parameters" not in rig.api.sent[1]
    rig.turns.settled(entry, 1, {"ok": False, "error": {"kind": "provider_timeout"}, "reply": ""})
    assert rig.api.sent[-1]["text"].startswith("(no reply: the turn ended")


def test_a_settle_of_another_platform_or_no_platform_sends_nothing(rig):
    entry, _, _ = send_queue.enqueue(ROOT, "operator-1", {send_queue.ORIGIN_ARG: {"owner": "stdio"}, "message": "hi"})
    rig.bridge.settled(entry, 0, {"reply": "for the desk"})
    other, _, _ = send_queue.enqueue(ROOT, "msg-x", {send_queue.ORIGIN_ARG: {
        ORIGIN_KIND_KEY: "messaging", "messaging": {"platform": "discord", "chat_id": "1"}}})
    rig.bridge.settled(other, 0, {"reply": "for discord"})
    assert rig.api.sent == []


def test_an_unbound_chat_gets_the_roster_and_persona_binds_it(rig, monkeypatch, caplog):
    caplog.set_level("INFO")
    monkeypatch.setattr(rpc, "_instance_known", lambda instance_id: instance_id in {"inst-alice", "inst-bob"})
    rig.api.push_message("hello?")
    _poll(rig)
    [roster] = rig.api.sent
    assert "not bound" in roster["text"] and "Bob (inst-bob)" in roster["text"]
    assert not send_queue.has_entries(ROOT)
    rig.api.push_message("/persona@hermes_test_bot bob")
    _poll(rig)
    binding = BindingStore().get(TG, "-1001")
    assert binding.persona_instance_id == "inst-bob" and binding.bound_by == "messaging:telegram:42"
    assert rig.api.sent[-1]["text"] == "This chat now talks to Bob."
    rig.api.push_message("/persona nobody")
    _poll(rig)
    assert "No single persona" in rig.api.sent[-1]["text"]
    assert BindingStore().get(TG, "-1001").persona_instance_id == "inst-bob"
    assert [r["reason"] for r in _receipts(caplog, "messaging.refused")] == ["unknown_persona"]
    update_id = rig.api.push_message("now talk")
    _poll(rig)
    assert send_queue.find(ROOT, f"msg-telegram-{update_id}").args["persona_instance_id"] == "inst-bob"


def test_start_registers_the_listener_and_stop_removes_it(rig, monkeypatch):
    calls = []
    monkeypatch.setattr(rig.transport, "start", lambda on_update: calls.append(("start", on_update)))
    monkeypatch.setattr(rig.transport, "stop", lambda: calls.append(("stop", None)))
    rig.turns.unregister_origin_listener("messaging")
    rig.bridge.start()
    assert calls == [("start", rig.bridge.inbound)]
    assert rig.turns._origin_listeners["messaging"] == rig.bridge.settled
    rig.bridge.stop()
    assert "messaging" not in rig.turns._origin_listeners and calls[-1] == ("stop", None)
    assert bridge_module.messaging_origin(send_queue.QueuedSend(ROOT, "x", 0, "", {})) is None
