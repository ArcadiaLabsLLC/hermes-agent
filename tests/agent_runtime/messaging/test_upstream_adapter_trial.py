"""TRIAL (RT-MESSAGING-UPSTREAM-ADAPTER-TRIAL): the fork's ``MessagingBridge`` on top of an UPSTREAM adapter.

The bridge, the operator / binding / refused stores, the send queue and the ``PersonaTurnExecutor`` are the
real ones on this test's isolated home (the rig of ``test_bridge_inbound.py``). The transport is
``UpstreamAdapterTransport`` over a real upstream adapter class built with NO ``GatewayRunner``; only the
adapter's network calls (``send``, ``send_typing``, ``stop_typing``) are recorders, and a message arrives
through the adapter's real ``handle_message``. Every test runs once per adapter.

The bridge is labelled ``telegram`` in every run: ``Platform`` has one member, and adding one is per-app
work the trial does not do.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime import mission_chat_door, paths
from agent_runtime.messaging import rpc
from agent_runtime.messaging.bindings import Binding, BindingStore
from agent_runtime.messaging.bridge import QUEUED_NOTICE, MessagingBridge
from agent_runtime.messaging.models import Platform
from agent_runtime.messaging.operators import Operator, OperatorStore
from agent_runtime.messaging.refused import RefusedSenders
from agent_runtime.messaging.transport import Transport
from agent_runtime.messaging.upstream_adapter_transport import UpstreamAdapterTransport, update_id_of
from agent_runtime.work_store.persona_turn import ORIGIN_KIND_KEY, PersonaTurnExecutor

ROOT = "persona_chat_root_trial"
TG = Platform.TELEGRAM
CHAT = "4242"

ADAPTERS = {
    "telegram": ("plugins.platforms.telegram.adapter", "TelegramAdapter",
                 dict(token="1234567890:" + "A" * 35)),
    "discord": ("plugins.platforms.discord.adapter", "DiscordAdapter", dict(token="x" * 59)),
    "slack": ("plugins.platforms.slack.adapter", "SlackAdapter",
              dict(token="xoxb-" + "1" * 40, extra={"app_token": "xapp-" + "1" * 40})),
    "signal": ("plugins.platforms.signal.adapter", "SignalAdapter",
               dict(extra={"http_url": "http://127.0.0.1:9", "account": "+10000000000"})),
}


@pytest.fixture(autouse=True)
def _no_direct_turns(monkeypatch):
    def refuse(args):
        raise AssertionError("the bridge ran a chat turn directly instead of queueing it")
    monkeypatch.setattr(mission_chat_door, "run_mission_chat_turn", refuse)


@pytest.fixture
def session_stores(monkeypatch):
    """Every upstream ``SessionStore`` built while the test runs — the trial's claim is that there are none."""
    import gateway.session as gateway_session

    built = []
    original = gateway_session.SessionStore.__init__

    def counting(self, *args, **kwargs):
        built.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(gateway_session.SessionStore, "__init__", counting)
    return built


def _instance(instance_id="inst-alice", display="Alice"):
    return SimpleNamespace(id=instance_id, persona_id="alice", display_name=display,
                           runtime_root=str(paths.store_root()))


class _Instances:
    def __init__(self, *instances):
        self.by_id = {i.id: i for i in instances}

    def get(self, instance_id):
        return self.by_id[instance_id]


@pytest.fixture(params=sorted(ADAPTERS))
def rig(request, session_stores):
    from gateway.config import PlatformConfig
    from gateway.platforms.base import SendResult as UpstreamSendResult

    module, cls_name, config = ADAPTERS[request.param]
    adapter = getattr(importlib.import_module(module), cls_name)(PlatformConfig(enabled=True, typing_indicator=False, **config))
    assert adapter.gateway_runner is None
    sent, typed = [], []

    async def record_send(chat_id, content, reply_to=None, metadata=None, **_kwargs):
        sent.append({"chat_id": str(chat_id), "text": content, "reply_to": reply_to,
                     "thread_id": (metadata or {}).get("thread_id")})
        return UpstreamSendResult(success=True, message_id=f"out-{len(sent)}")

    async def record_typing(chat_id, metadata=None, **_kwargs):
        typed.append(str(chat_id))

    async def quiet(*_args, **_kwargs):
        return None

    adapter.send, adapter.send_typing, adapter.stop_typing = record_send, record_typing, quiet
    transport = UpstreamAdapterTransport(adapter, connect=False)
    assert isinstance(transport, Transport)
    alice, bob = _instance(), _instance("inst-bob", "Bob")
    turns = PersonaTurnExecutor(instances=_Instances(alice, bob), root_of=lambda store, **_: ROOT, wake=lambda: None)
    busy = {"value": False}
    bridge = MessagingBridge(transport, turns, roster=lambda: [alice, bob], root_busy=lambda _root: busy["value"])
    OperatorStore().allow(Operator(TG, "42", "Max", "rpc:stdio_owner", "2026-11-14T00:00:00+00:00"))
    bridge.start()
    counter = {"n": 0}

    def push(text, *, user_id="42", user_name="Max", chat_id=CHAT, thread_id=None, message_id=None):
        from gateway.platforms.event import MessageEvent

        counter["n"] += 1
        source = adapter.build_source(chat_id=chat_id, chat_type="dm", user_id=user_id, user_name=user_name,
                                      thread_id=thread_id)
        event = MessageEvent(text=text, source=source, message_id=message_id or f"in-{counter['n']}")
        transport.deliver(event)
        return event

    yield SimpleNamespace(name=request.param, adapter=adapter, transport=transport, turns=turns, bridge=bridge,
                          busy=busy, sent=sent, typed=typed, push=push, session_stores=session_stores)
    bridge.stop()


def _bind(chat=CHAT, thread=None, instance="inst-alice"):
    BindingStore().set(Binding(TG, chat, thread, instance, "rpc:stdio_owner", "2026-11-14T00:00:00+00:00"))


def test_a_message_through_the_upstream_adapter_is_a_queued_turn_on_the_personas_one_root(rig):
    """The trial's question. Killing mutation: ``UpstreamAdapterTransport._handle`` returns without calling
    ``on_update`` → no entry on the root → red."""
    _bind(thread="9")
    event = rig.push("what moved today?", thread_id="9")
    entry = send_queue.find(ROOT, f"msg-telegram-{update_id_of(event)}")
    assert entry is not None and entry.state == send_queue.STATE_QUEUED
    assert entry.args["message"] == "what moved today?" and entry.args["persona_instance_id"] == "inst-alice"
    assert entry.args["session_id"] == ROOT and entry.args["requested_by"] == "messaging:telegram:42"
    origin = entry.args[send_queue.ORIGIN_ARG]
    assert origin[ORIGIN_KIND_KEY] == "messaging" and "session_id" not in origin["messaging"]
    assert origin["messaging"]["chat_id"] == CHAT and origin["messaging"]["thread_id"] == "9"
    assert rig.sent == [] and rig.typed == [CHAT]  # idle root: typing, no notice, no reply yet
    assert rig.session_stores == []  # no upstream session store was built
    assert rig.adapter._active_sessions == {}  # the adapter holds no "busy" state once the bridge has it


def test_the_settle_sends_the_reply_through_the_adapter_to_the_origin_chat(rig):
    """Killing mutation: ``UpstreamAdapterTransport.send`` returns before ``adapter.send`` → nothing sent → red."""
    _bind(thread="9")
    event = rig.push("write a lot", thread_id="9")
    entry = send_queue.find(ROOT, f"msg-telegram-{update_id_of(event)}")
    rig.turns.settled(entry, 0, {"ok": True, "reply": "the answer"})
    assert rig.sent == [{"chat_id": CHAT, "text": "the answer", "reply_to": event.message_id, "thread_id": "9"}]
    rig.turns.settled(entry, 1, {"ok": False, "error": {"kind": "provider_timeout"}, "reply": ""})
    assert rig.sent[-1]["text"].startswith("(no reply: the turn ended")
    assert rig.session_stores == []


def test_a_stranger_reaches_the_bridge_and_is_refused_there(rig):
    """The adapter's own sender gate is told yes; the fork's operator list decides. Killing mutation: drop
    ``set_authorization_check`` AND the bridge's ``is_allowed`` → the stranger is queued → red."""
    _bind()
    rig.push("let me in", user_id="99", user_name="Stranger")
    assert not send_queue.has_entries(ROOT) and rig.sent == [] and rig.typed == []
    assert [(r["user_id"], r["display"], r["chat_id"]) for r in RefusedSenders().recent(TG)] == [
        ("99", "Stranger", CHAT)]


def test_a_redelivered_message_converges_on_one_queued_entry(rig):
    """Killing mutation: ``update_id_of`` mixes in a clock or a counter → two entries → red."""
    _bind()
    first = rig.push("once only", message_id="m-77")
    rig.push("once only", message_id="m-77")
    assert [e.client_message_id for e in send_queue.entries(ROOT)] == [f"msg-telegram-{update_id_of(first)}"]
    assert rig.typed == [CHAT]


def test_a_busy_root_holds_the_message_and_says_so_once(rig):
    _bind()
    rig.busy["value"] = True
    rig.push("are you there?", message_id="m-1")
    rig.push("are you there?", message_id="m-1")
    assert len(send_queue.entries(ROOT)) == 1
    assert [m["text"] for m in rig.sent] == [QUEUED_NOTICE]


def test_an_unbound_chat_gets_the_roster_and_persona_binds_it(rig, monkeypatch):
    """``/persona`` must reach the bridge: upstream's slash commands live in the runner, which is absent."""
    monkeypatch.setattr(rpc, "_instance_known", lambda instance_id: instance_id in {"inst-alice", "inst-bob"})
    rig.push("hello?")
    [roster] = rig.sent
    assert "not bound" in roster["text"] and "Bob (inst-bob)" in roster["text"]
    assert not send_queue.has_entries(ROOT)
    rig.push("/persona bob")
    assert BindingStore().get(TG, CHAT).persona_instance_id == "inst-bob"
    assert rig.sent[-1]["text"] == "This chat now talks to Bob."
    event = rig.push("now talk")
    assert send_queue.find(ROOT, f"msg-telegram-{update_id_of(event)}").args["persona_instance_id"] == "inst-bob"
    assert rig.session_stores == []
