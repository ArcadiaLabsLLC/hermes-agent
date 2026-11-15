"""RT-MESSAGING-TELEGRAM-ON-UPSTREAM-ADAPTER-OPT-IN: the serve lane picks ONE Telegram transport from a setting.

``messaging_telegram_transport`` is ``fork`` (the default: the fork's own ``TelegramTransport``) or
``upstream`` (upstream's adapter behind ``upstream_adapter_transport``). The first tests swap both factory
rows for fakes; the last ones run the real ``_telegram_upstream`` factory through the lane against the local
Bot API stand-in (``fake_bot_api_server.FakeTelegram``), never the network, pointed there by the harness setting
``messaging_telegram_api_base`` (RT-MESSAGING-SERVE-CANNOT-USE-A-LOCAL-APP-API), which takes a loopback
origin only.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime import paths
from agent_runtime.harness_settings import PLUGIN_ID, harness_setting
from agent_runtime.messaging import credentials, rpc, serve_lane
from agent_runtime.messaging.bindings import Binding, BindingStore
from agent_runtime.messaging.models import Platform
from agent_runtime.messaging.operators import Operator, OperatorStore
from agent_runtime.messaging.refused import RefusedSenders
from agent_runtime.messaging.serve_lane import LaneState, MessagingLane, TransportKind, transport_kind
from agent_runtime.messaging.transport import MessageRef, SendResult
from agent_runtime.work_store.persona_turn import PersonaTurnExecutor
from tests.agent_runtime.messaging.fake_bot_api_server import FakeTelegram
from tests.agent_runtime.messaging.test_upstream_telegram_end_to_end import GATE_ENV, _wait
from tests.agent_runtime.messaging._telegram_extra import require_telegram_extra

TOKEN = "1234567890:AAFakeTokenForTheLaneOnly_abcdefghijklm"
TG = Platform.TELEGRAM
ROOT = "persona_chat_root_lane"
SETTING = "messaging_telegram_transport"


def _set(name: str, value) -> None:
    """Write one harness setting the way ``rpc._write_enabled`` does."""
    from hermes_cli.config import load_config, save_config

    config = load_config()
    node = config
    for segment in ("plugins", "entries", PLUGIN_ID, "settings"):
        node = node.setdefault(segment, {})
    node[name] = value
    save_config(config)


class _Fake:
    """Records its own start and stop on a shared timeline, so the order across two transports is visible."""

    def __init__(self, kind: str, timeline: list, token: str) -> None:
        self.kind, self.timeline, self.token = kind, timeline, token

    def start(self, on_update) -> None:
        self.timeline.append((self.kind, "start"))

    def stop(self) -> None:
        self.timeline.append((self.kind, "stop"))

    def send(self, chat, text, thread=None, reply_to=None):
        return SendResult((MessageRef(chat, "1"),))

    def send_card(self, chat, text, buttons, thread=None):
        return MessageRef(chat, "card")

    def edit(self, ref, text, buttons=None):
        return None

    def typing(self, chat, thread=None):
        return None

    def answer_callback(self, callback_id, text=""):
        return None


class _Instances:
    def get(self, instance_id):
        return SimpleNamespace(id=instance_id, persona_id="alice", display_name="Alice",
                               runtime_root=str(paths.store_root()))


def _session():
    turns = PersonaTurnExecutor(instances=_Instances(), root_of=lambda store, **_: ROOT, wake=lambda: None)
    return SimpleNamespace(drain_state=None, liveness_stop=threading.Event(), work_executor=turns,
                           serve_request_home=None)


@pytest.fixture
def fakes(monkeypatch):
    timeline: list = []
    monkeypatch.setitem(serve_lane.TRANSPORTS, TG, lambda token: _Fake("fork", timeline, token))
    monkeypatch.setitem(serve_lane.UPSTREAM_TRANSPORTS, TG,
                        lambda token, scope: _Fake("upstream", timeline, token))
    monkeypatch.setattr(serve_lane, "_current", None)
    credentials.set_token(TG, TOKEN)
    rpc.execute("platform.enable", {"platform": "telegram"}, by="test")
    return timeline


def test_the_default_is_the_forks_own_transport(fakes):
    """Killing mutation: ``transport_kind`` returns UPSTREAM when the setting is absent → red."""
    assert harness_setting(SETTING, None) is None and transport_kind(TG) is TransportKind.FORK
    lane = MessagingLane(_session())
    lane.tick()
    assert fakes == [("fork", "start")]
    lane.close()


def test_the_plugin_manifest_declares_the_setting_with_the_fork_default():
    from hermes_cli.plugins_manifest import parse_manifest_file

    plugin_dir = Path(serve_lane.__file__).resolve().parents[2] / "plugins" / "eternia-harness"
    schema = parse_manifest_file(plugin_dir / "plugin.yaml", plugin_dir, "bundled", "").config_schema
    assert schema[SETTING]["default"] == "fork"


def test_upstream_is_built_only_when_the_setting_says_upstream(fakes):
    _set(SETTING, "upstream")
    lane = MessagingLane(_session())
    lane.tick()
    assert fakes == [("upstream", "start")]
    lane.close()


@pytest.mark.parametrize("value", ["both", "", "Upstream-ish", "true", 1, None])
def test_anything_but_the_word_upstream_is_the_forks_transport(fakes, value):
    """A typo must fall back to the transport that is known to work, never to the opt-in one."""
    _set(SETTING, value)
    assert transport_kind(TG) is TransportKind.FORK


def test_a_changed_setting_stops_the_old_transport_before_the_new_one_starts(fakes):
    """One poller per bot. Killing mutation: ``_reconcile`` starts the new transport without stopping the
    running one → ``upstream start`` precedes ``fork stop`` (or no stop at all) → red."""
    lane = MessagingLane(_session())
    lane.tick()
    _set(SETTING, "upstream")
    lane.tick()
    lane.tick()  # a tick with nothing changed restarts nothing
    assert fakes == [("fork", "start"), ("fork", "stop"), ("upstream", "start")]
    _set(SETTING, "fork")
    lane.tick()
    assert fakes[3:] == [("upstream", "stop"), ("fork", "start")]
    assert lane.state()["telegram"]["state"] == LaneState.RUNNING.value
    lane.close()


def test_an_upstream_adapter_without_its_own_intake_gate_is_not_wired_in(fakes, monkeypatch, caplog):
    """RT-MESSAGING-SHIM-STRANGER-GATE-HOLDS-ONLY-ON-TELEGRAM. Killing mutation: ``_start`` drops the
    ``has_own_intake_gate(INTAKE_GATED…)`` check → the upstream fake starts → red."""
    from agent_runtime.messaging import upstream_adapter_transport as shim

    monkeypatch.delitem(shim.INTAKE_GATED, TG.value)
    _set(SETTING, "upstream")
    lane = MessagingLane(_session())
    lane.tick()
    assert fakes == []
    assert lane.state()["telegram"] == {"state": "off", "reason": "start_failed"}
    lane.close()


# ── the local stand-in Bot API setting: loopback only ──

API_BASE = serve_lane.API_BASE_SETTING


def test_the_plugin_manifest_declares_the_api_base_setting_with_no_default():
    from hermes_cli.plugins_manifest import parse_manifest_file

    plugin_dir = Path(serve_lane.__file__).resolve().parents[2] / "plugins" / "eternia-harness"
    schema = parse_manifest_file(plugin_dir / "plugin.yaml", plugin_dir, "bundled", "").config_schema
    assert schema[API_BASE]["type"] == "str" and "default" not in schema[API_BASE]


@pytest.mark.parametrize("value", ["http://127.0.0.1:8081", "http://localhost:8081/", "https://[::1]:9",
                                   "http://127.0.0.2:8081"])
def test_a_loopback_origin_is_the_api_base(fakes, value):
    _set(API_BASE, value)
    assert serve_lane.telegram_api_base() == value.rstrip("/")


@pytest.mark.parametrize("value", ["http://example.com:8081", "https://api.telegram.org", "http://10.0.0.5:8081",
                                   "http://127.0.0.1.example.com:8081", "http://localhost.example.com",
                                   "http://user:pw@127.0.0.1:8081", "http://127.0.0.1:8081/bot",
                                   "http://127.0.0.1:8081/?x=1", "ftp://127.0.0.1:21", "127.0.0.1:8081",
                                   "http://127.0.0.1:notaport", "http://[::ffff:8.8.8.8]:1"])
def test_a_host_that_is_not_loopback_is_refused_naming_the_setting_not_its_value(fakes, value):
    """Killing mutation: ``_loopback_api_host`` returns True for any host → no refusal → red."""
    from agent_runtime.messaging.models import MessagingRefused

    _set(API_BASE, value)
    with pytest.raises(MessagingRefused) as refused:
        serve_lane.telegram_api_base()
    assert refused.value.detail == API_BASE and value not in str(refused.value)


def test_a_serve_pointed_at_a_remote_host_starts_neither_transport_and_hands_it_no_token(monkeypatch):
    """The real factories, not fakes: a refused setting is ``start_failed``, never a fall-back to the real API,
    and no adapter or client is built. Killing mutation: ``_telegram`` ignores the setting → the fork
    transport starts against the real Bot API → ``running`` → red."""
    from agent_runtime.messaging import telegram_api

    built: list = []
    monkeypatch.setattr(telegram_api.TelegramTransport, "start", lambda self, on_update: built.append(self))
    monkeypatch.setattr(serve_lane, "_current", None)
    credentials.set_token(TG, TOKEN)
    rpc.execute("platform.enable", {"platform": "telegram"}, by="test")
    _set(API_BASE, "http://203.0.113.7:8081")
    lane = MessagingLane(_session())
    lane.tick()
    assert built == [] and lane.state()["telegram"] == {"state": "off", "reason": "start_failed"}
    _set(SETTING, "upstream")
    lane.tick()
    assert lane.state()["telegram"] == {"state": "off", "reason": "start_failed"}
    lane.close()


def test_the_forks_own_transport_uses_the_api_base(monkeypatch):
    from agent_runtime.messaging import telegram_api

    seen: list = []
    real_init = telegram_api.TelegramTransport.__init__

    def spy(self, token, **kwargs):
        seen.append(kwargs.get("api_base"))
        real_init(self, token, **kwargs)

    monkeypatch.setattr(telegram_api.TelegramTransport, "__init__", spy)
    _set(API_BASE, "http://127.0.0.1:8081")
    serve_lane._telegram(TOKEN)
    _set(API_BASE, "")
    serve_lane._telegram(TOKEN)
    assert seen == ["http://127.0.0.1:8081", telegram_api.API_BASE]


# ── the real upstream factory, through the lane, against the local Bot API ──


@pytest.fixture
def live(monkeypatch):
    require_telegram_extra()
    for name in GATE_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HERMES_TELEGRAM_DISABLE_FALLBACK_IPS", "1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setattr(serve_lane, "_current", None)
    server = FakeTelegram(TOKEN)
    _set(serve_lane.API_BASE_SETTING, server.base_url.removesuffix("/bot"))
    monkeypatch.setitem(serve_lane.TRANSPORTS, TG,
                        lambda token: (_ for _ in ()).throw(AssertionError("the fork transport was built")))
    credentials.set_token(TG, TOKEN)
    OperatorStore().allow(Operator(TG, "42", "Max", "rpc:stdio_owner", "2026-11-14T00:00:00+00:00"))
    BindingStore().set(Binding(TG, "42", None, "inst-alice", "rpc:stdio_owner", "2026-11-14T00:00:00+00:00"))
    rpc.execute("platform.enable", {"platform": "telegram"}, by="test")
    _set(SETTING, "upstream")
    lane = MessagingLane(_session())
    lane.tick()
    try:
        yield SimpleNamespace(server=server, lane=lane)
    finally:
        lane.close()
        server.close()


def _receipts(caplog, kind):
    return [json.loads(r.getMessage()) for r in caplog.records
            if r.name == "agent_runtime.work_store.receipts" and f'"kind": "{kind}"' in r.getMessage()]


def test_the_lane_runs_upstreams_adapter_and_an_operators_message_is_a_queued_turn(live):
    assert live.lane.state()["telegram"] == {"state": "running", "reason": None}
    assert "setMyCommands" not in live.server.methods()
    live.server.push_message("what moved today?")
    entry = _wait(lambda: next((e for e in send_queue.entries(ROOT) if e.args.get("message") == "what moved today?"),
                               None), what="the queued turn")
    assert entry.args["persona_instance_id"] == "inst-alice" and entry.args["requested_by"] == "messaging:telegram:42"
    live.lane._running[TG].bridge.turns.settled(entry, 0, {"ok": True, "reply": "three things moved"})
    [sent] = live.server.sent
    assert str(sent["chat_id"]) == "42" and not sent.get("disable_notification")


def test_a_stranger_is_refused_at_the_adapter_and_listed_for_the_console_with_a_name(live, caplog):
    """Killing mutation: ``_telegram_upstream`` builds the transport without ``is_allowed`` → the photo is
    fetched (``getFile``) → red. Or without ``on_refused`` → nothing is listed → red."""
    caplog.set_level("INFO")
    live.server.push_photo("look", user_id=99, first_name="Stranger")
    rows = _wait(lambda: RefusedSenders().recent(TG), what="the refused sender")
    assert [(r["user_id"], r["display"], r["chat_id"]) for r in rows] == [("99", "Stranger", "99")]
    time.sleep(1.0)
    assert "getFile" not in live.server.methods() and live.server.sent == []
    assert not send_queue.has_entries(ROOT)
    [receipt] = _receipts(caplog, "messaging.refused")
    assert receipt["reason"] == "unknown_operator" and receipt["user_id"] == "99"
    listed = rpc.execute("refused.recent", {"platform": "telegram"}, by="rpc:stdio_owner")["refused"]["telegram"]
    assert [r["user_id"] for r in listed] == ["99"]
