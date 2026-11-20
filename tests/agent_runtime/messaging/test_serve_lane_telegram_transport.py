"""RT-MESSAGING-RETIRE-FORK-TELEGRAM: the serve lane's one Telegram transport is upstream's adapter behind the shim.

The fork's own httpx ``TelegramTransport`` and its ``messaging_telegram_transport`` choice are gone (the opt-in
trial of RT-MESSAGING-TELEGRAM-ON-UPSTREAM-ADAPTER-OPT-IN passed). The first tests swap the factory row for a
fake; the last ones run the real ``_telegram_upstream`` factory through the lane against the local
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
from agent_runtime.harness_settings import PLUGIN_ID
from agent_runtime.messaging import credentials, rpc, serve_lane
from agent_runtime.messaging.bindings import Binding, BindingStore
from agent_runtime.messaging.models import Platform
from agent_runtime.messaging.operators import Operator, OperatorStore
from agent_runtime.messaging.refused import RefusedSenders
from agent_runtime.messaging.serve_lane import MessagingLane
from agent_runtime.messaging.transport import MessageRef, SendResult
from agent_runtime.work_store.persona_turn import PersonaTurnExecutor
from tests.agent_runtime.messaging.fake_bot_api_server import FakeTelegram
from tests.agent_runtime.messaging.test_upstream_telegram_end_to_end import GATE_ENV, _wait
from tests.agent_runtime.messaging._telegram_extra import require_telegram_extra

TOKEN = "1234567890:AAFakeTokenForTheLaneOnly_abcdefghijklm"
TG = Platform.TELEGRAM
ROOT = "persona_chat_root_lane"
RETIRED_SETTING = "messaging_telegram_transport"


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
    monkeypatch.setitem(serve_lane.TRANSPORTS, TG, lambda token, scope: _Fake("upstream", timeline, token))
    monkeypatch.setattr(serve_lane, "_current", None)
    credentials.set_token(TG, TOKEN)
    rpc.execute("platform.enable", {"platform": "telegram"}, by="test")
    return timeline


def test_a_retired_fork_setting_left_in_a_config_still_runs_upstreams_adapter(fakes):
    """An owner who tried the opt-in (or set ``fork``) keeps the key in config.yaml; nothing reads it now."""
    _set(RETIRED_SETTING, "fork")
    lane = MessagingLane(_session())
    lane.tick()
    lane.tick()  # a tick with nothing changed restarts nothing
    assert fakes == [("upstream", "start")]
    assert lane.state()["telegram"] == {"state": "running", "reason": None}
    lane.close()


def test_the_plugin_manifest_no_longer_offers_the_transport_choice():
    """Killing mutation: put the ``messaging_telegram_transport`` entry back in plugin.yaml → red."""
    from hermes_cli.plugins_manifest import parse_manifest_file

    plugin_dir = Path(serve_lane.__file__).resolve().parents[2] / "plugins" / "eternia-harness"
    schema = parse_manifest_file(plugin_dir / "plugin.yaml", plugin_dir, "bundled", "").config_schema
    assert RETIRED_SETTING not in schema and "messaging_enabled" in schema


def test_the_fork_transport_modules_are_gone():
    """RT-MESSAGING-RETIRE-FORK-TELEGRAM: one Telegram connection, upstream's. Killing mutation: restore
    ``agent_runtime/messaging/telegram_api.py`` → red."""
    import importlib.util

    assert importlib.util.find_spec("agent_runtime.messaging.telegram_api") is None
    assert importlib.util.find_spec("agent_runtime.messaging.chunks") is None


def test_an_upstream_adapter_without_its_own_intake_gate_is_not_wired_in(fakes, monkeypatch, caplog):
    """RT-MESSAGING-SHIM-STRANGER-GATE-HOLDS-ONLY-ON-TELEGRAM. Killing mutation: ``_start`` drops the
    ``has_own_intake_gate(INTAKE_GATED…)`` check → the upstream fake starts → red."""
    from agent_runtime.messaging import upstream_adapter_transport as shim

    monkeypatch.delitem(shim.INTAKE_GATED, TG.value)
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


def test_a_serve_pointed_at_a_remote_host_starts_no_adapter_and_hands_it_no_token(monkeypatch):
    """The real factory, not a fake: a refused setting is ``start_failed``, never a fall-back to the real API,
    and no adapter is built. Killing mutation: ``_telegram_upstream`` ignores the setting → the adapter is
    built (and would start against the real Bot API) → red."""
    from plugins.platforms.telegram import adapter as telegram_adapter

    built: list = []
    monkeypatch.setattr(telegram_adapter, "check_telegram_requirements", lambda: True)
    monkeypatch.setattr(telegram_adapter, "TelegramAdapter", lambda config: built.append(config))
    monkeypatch.setattr(serve_lane, "_current", None)
    credentials.set_token(TG, TOKEN)
    rpc.execute("platform.enable", {"platform": "telegram"}, by="test")
    _set(API_BASE, "http://203.0.113.7:8081")
    lane = MessagingLane(_session())
    lane.tick()
    assert built == [] and lane.state()["telegram"] == {"state": "off", "reason": "start_failed"}
    lane.close()


def test_the_adapter_is_pointed_at_the_api_base(monkeypatch):
    from contextlib import nullcontext

    require_telegram_extra()
    _set(API_BASE, "http://127.0.0.1:8081")
    assert serve_lane._telegram_upstream(TOKEN, nullcontext).adapter.config.extra["base_url"] == \
        "http://127.0.0.1:8081/bot"
    _set(API_BASE, "")
    assert "base_url" not in serve_lane._telegram_upstream(TOKEN, nullcontext).adapter.config.extra


# ── python-telegram-bot is an opt-in extra: the factory asks upstream's lazy installer first ──


def test_the_factory_asks_upstreams_lazy_installer_before_it_builds_the_adapter(monkeypatch):
    """A Harness without the ``messaging`` extra gets python-telegram-bot installed on first use, as upstream's
    ``create_adapter`` does; where it cannot be installed the lane reads ``start_failed`` and builds nothing.
    Killing mutation: drop the ``check_telegram_requirements()`` guard in ``_telegram_upstream`` → the installer
    is never asked and the adapter is built without its library → red."""
    from plugins.platforms.telegram import adapter as telegram_adapter

    asked: list = []
    built: list = []
    monkeypatch.setattr(telegram_adapter, "check_telegram_requirements", lambda: asked.append(1) or False)
    monkeypatch.setattr(telegram_adapter, "TelegramAdapter", lambda config: built.append(config))
    monkeypatch.setattr(serve_lane, "_current", None)
    credentials.set_token(TG, TOKEN)
    rpc.execute("platform.enable", {"platform": "telegram"}, by="test")
    lane = MessagingLane(_session())
    lane.tick()
    assert asked == [1] and built == []
    assert lane.state()["telegram"] == {"state": "off", "reason": "start_failed"}
    lane.close()


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
    credentials.set_token(TG, TOKEN)
    OperatorStore().allow(Operator(TG, "42", "Max", "rpc:stdio_owner", "2026-11-14T00:00:00+00:00"))
    BindingStore().set(Binding(TG, "42", None, "inst-alice", "rpc:stdio_owner", "2026-11-14T00:00:00+00:00"))
    rpc.execute("platform.enable", {"platform": "telegram"}, by="test")
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
