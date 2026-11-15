"""AUDIT: the fork's bridge on UPSTREAM's Telegram adapter, end to end over HTTP against a local Bot API.

Nothing is injected and nothing in the adapter is replaced: ``connect()`` is the adapter's own, an update
arrives through python-telegram-bot's long poll, is parsed and gated by the adapter's own handlers, reaches
the fork's ``MessagingBridge`` through ``UpstreamAdapterTransport``, and the reply leaves through the
adapter's own ``send`` as a ``sendMessage`` HTTP call. The only stand-in is the server
(``fake_bot_api_server.FakeTelegram`` on 127.0.0.1). No ``GatewayRunner`` exists in the process.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime import mission_chat_door, paths
from agent_runtime.messaging import rpc
from agent_runtime.messaging.bindings import Binding, BindingStore
from agent_runtime.messaging.bridge import MessagingBridge
from agent_runtime.messaging.models import Platform
from agent_runtime.messaging.operators import Operator, OperatorStore
from agent_runtime.messaging.refused import RefusedSenders
from agent_runtime.messaging.approvals import CALLBACK_PREFIX
from agent_runtime.messaging.upstream_adapter_transport import TelegramUpstreamAdapterTransport
from agent_runtime.work_store.persona_turn import PersonaTurnExecutor
from tests.agent_runtime.messaging.fake_bot_api_server import FakeTelegram

TOKEN = "1234567890:AAFakeTokenForTheAuditOnly_abcdefghijk"
ROOT = "persona_chat_root_e2e"
TG = Platform.TELEGRAM
GATE_ENV = ("TELEGRAM_ALLOWED_USERS", "TELEGRAM_GROUP_ALLOWED_USERS", "TELEGRAM_ALLOW_ALL_USERS",
            "GATEWAY_ALLOW_ALL_USERS", "GATEWAY_ALLOWED_USERS", "TELEGRAM_WEBHOOK_URL", "TELEGRAM_PROXY",
            "TELEGRAM_BOT_TOKEN", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY")


def _wait(condition, timeout=20.0, what="the condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(f"timed out after {timeout}s waiting for {what}")


@pytest.fixture(autouse=True)
def _needs_the_library():
    # A fixture, not a module-level skip: test_serve_lane_transport_choice imports this module's helpers.
    pytest.importorskip(
        "telegram", reason="python-telegram-bot is the `messaging` extra, outside `[all]` and the canonical "
        "test venv; these tests drive the real upstream adapter (RT-MESSAGING-TESTS-NEED-THE-MESSAGING-EXTRA)")


@pytest.fixture(autouse=True)
def _no_direct_turns(monkeypatch):
    def refuse(args):
        raise AssertionError("the bridge ran a chat turn directly instead of queueing it")
    monkeypatch.setattr(mission_chat_door, "run_mission_chat_turn", refuse)


def _instance(instance_id="inst-alice", display="Alice"):
    return SimpleNamespace(id=instance_id, persona_id="alice", display_name=display,
                           runtime_root=str(paths.store_root()))


class _Instances:
    def __init__(self, *instances):
        self.by_id = {i.id: i for i in instances}

    def get(self, instance_id):
        return self.by_id[instance_id]


@pytest.fixture
def rig(monkeypatch):
    import gateway.session as gateway_session
    from gateway.config import PlatformConfig
    from plugins.platforms.telegram.adapter import TelegramAdapter

    for name in GATE_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HERMES_TELEGRAM_DISABLE_FALLBACK_IPS", "1")  # no DNS-over-HTTPS discovery
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    stores = []
    original = gateway_session.SessionStore.__init__
    monkeypatch.setattr(gateway_session.SessionStore, "__init__",
                        lambda self, *a, **k: (stores.append(self), original(self, *a, **k))[1])

    server = FakeTelegram(TOKEN)
    adapter = TelegramAdapter(PlatformConfig(enabled=True, token=TOKEN, typing_indicator=False,
                                             extra={"base_url": server.base_url}))
    transport = TelegramUpstreamAdapterTransport(adapter, press_prefix=CALLBACK_PREFIX, connect=True)
    alice, bob = _instance(), _instance("inst-bob", "Bob")
    turns = PersonaTurnExecutor(instances=_Instances(alice, bob), root_of=lambda store, **_: ROOT, wake=lambda: None)
    bridge = MessagingBridge(transport, turns, roster=lambda: [alice, bob], root_busy=lambda _root: False)
    OperatorStore().allow(Operator(TG, "42", "Max", "rpc:stdio_owner", "2026-11-14T00:00:00+00:00"))
    started = time.monotonic()
    bridge.start()
    connect_seconds = time.monotonic() - started
    try:
        yield SimpleNamespace(server=server, adapter=adapter, transport=transport, turns=turns, bridge=bridge,
                              stores=stores, connect_seconds=connect_seconds)
    finally:
        bridge.stop()
        server.close()


def _bind(chat="42", thread=None, instance="inst-alice"):
    BindingStore().set(Binding(TG, chat, thread, instance, "rpc:stdio_owner", "2026-11-14T00:00:00+00:00"))


def _entry_for(text):
    return next((e for e in send_queue.entries(ROOT) if e.args.get("message") == text), None)


def test_connect_is_the_adapters_own_and_needs_no_runner(rig):
    assert rig.adapter.is_connected and rig.adapter.gateway_runner is None
    assert "getMe" in rig.server.methods()
    _wait(lambda: "getUpdates" in rig.server.methods(), what="the adapter's long poll to start")
    assert rig.stores == []


def test_a_real_update_becomes_a_queued_turn_and_the_reply_is_a_real_send(rig):
    """The whole path. Killing mutation: ``UpstreamAdapterTransport.start`` does not install the handler →
    the adapter drops the update ("no gateway message handler") → nothing queued → red."""
    _bind()
    update = rig.server.push_message("what moved today?")
    entry = _wait(lambda: _entry_for("what moved today?"), what="the queued turn")
    assert entry.state == send_queue.STATE_QUEUED and entry.args["persona_instance_id"] == "inst-alice"
    assert entry.args["session_id"] == ROOT and entry.args["requested_by"] == "messaging:telegram:42"
    assert entry.client_message_id == f"msg-telegram-{update['update_id']}"  # the platform's own update id
    origin = entry.args[send_queue.ORIGIN_ARG]["messaging"]
    assert origin["chat_id"] == "42" and origin["message_id"] == str(update["message"]["message_id"])
    _wait(lambda: "sendChatAction" in rig.server.methods(), what="the typing action")
    assert rig.server.sent == []
    rig.turns.settled(entry, 0, {"ok": True, "reply": "three things moved"})
    [sent] = rig.server.sent
    assert str(sent["chat_id"]) == "42" and "three things moved" in sent["text"]
    assert sent.get("reply_parameters", {}).get("message_id") == update["message"]["message_id"]
    assert not sent.get("disable_notification")  # the reply must buzz the phone, as the fork's own does
    assert rig.stores == []


def test_upstreams_command_menu_is_not_pushed_to_the_bot(rig):
    """Killing mutation: drop the ``_register_command_menu`` override in ``_prepare`` → ``setMyCommands`` → red."""
    _wait(lambda: "getUpdates" in rig.server.methods(), what="the long poll")
    time.sleep(1.5)  # the menu is registered off the connect path
    assert "setMyCommands" not in rig.server.methods()


def test_a_stranger_passes_the_adapters_gate_and_is_refused_by_the_forks_operator_list(rig):
    """With ``is_allowed=None`` (this rig) every sender reaches the bridge, which refuses the stranger and
    lists them — the bridge is a second gate behind the adapter's (``test_upstream_telegram_stranger_gate.py``)."""
    _bind()
    rig.server.push_message("let me in", user_id=99, first_name="Stranger")
    refused = _wait(lambda: RefusedSenders().recent(TG), what="the refused sender to be recorded")
    assert [(r["user_id"], r["display"]) for r in refused] == [("99", "Stranger")]
    assert not send_queue.has_entries(ROOT) and rig.server.sent == []


def test_a_long_reply_is_split_by_the_adapter_at_telegrams_limit(rig):
    _bind()
    rig.server.push_message("write a lot")
    entry = _wait(lambda: _entry_for("write a lot"), what="the queued turn")
    counted = []
    real_send = rig.transport.send
    rig.transport.send = lambda *a, **k: (counted.append(real_send(*a, **k)), counted[-1])[1]
    rig.turns.settled(entry, 0, {"ok": True, "reply": "word " * 2000})  # 10,000 characters
    assert len(counted[0].refs) == len(rig.server.sent)  # the shim reports every part, not only the last
    sizes = [len(m["text"]) for m in rig.server.sent]
    assert len(sizes) >= 3 and max(sizes) <= 4096, sizes
    assert sum(m["text"].count("word") for m in rig.server.sent) == 2000  # nothing lost in the split


def test_persona_command_reaches_the_bridge_and_binds_the_chat(rig, monkeypatch):
    monkeypatch.setattr(rpc, "_instance_known", lambda instance_id: instance_id in {"inst-alice", "inst-bob"})
    rig.server.push_message("hello?")
    roster = _wait(lambda: rig.server.sent[:], what="the roster reply")[0]
    assert "not bound" in roster["text"] and "Bob" in roster["text"]
    rig.server.push_message("/persona bob")
    _wait(lambda: BindingStore().get(TG, "42"), what="the binding")
    assert BindingStore().get(TG, "42").persona_instance_id == "inst-bob"
    _wait(lambda: any("now talks to Bob" in m["text"] for m in rig.server.sent), what="the confirmation")


def test_a_forum_topic_message_keeps_its_thread_both_ways(rig):
    _bind(chat="-1001", thread="9")
    OperatorStore().allow(Operator(TG, "42", "Max", "rpc:stdio_owner", "2026-11-14T00:00:00+00:00"))
    rig.server.push_message("in the topic", chat_id=-1001, chat_type="supergroup", thread_id=9)
    entry = _wait(lambda: _entry_for("in the topic"), what="the queued turn")
    assert entry.args[send_queue.ORIGIN_ARG]["messaging"]["thread_id"] == "9"
    rig.turns.settled(entry, 0, {"ok": True, "reply": "answer in the topic"})
    [sent] = rig.server.sent
    assert str(sent["chat_id"]) == "-1001" and str(sent.get("message_thread_id")) == "9"
