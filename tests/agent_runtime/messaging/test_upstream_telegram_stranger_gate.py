"""AUDIT: what a STRANGER can make the upstream Telegram adapter do before the fork's operator list refuses them.

Read in ``plugins/platforms/telegram/adapter.py::TelegramAdapter._is_user_authorized_from_message``: with no
allowlist configured the adapter's intake gate passes every sender and leaves the decision to a runner —
which the fork does not start. ``_handle_media_message`` then fetches the photo BEFORE the handler runs.
These tests show both halves over HTTP: the open gate (a stranger's photo is downloaded), and the shim's
hardened mode (``is_allowed`` from the fork's ``OperatorStore``), where nothing of a stranger's is fetched.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime import mission_chat_door, paths
from agent_runtime.messaging.bindings import Binding, BindingStore
from agent_runtime.messaging.bridge import MessagingBridge
from agent_runtime.messaging.models import Platform
from agent_runtime.messaging.operators import Operator, OperatorStore
from agent_runtime.messaging.approvals import CALLBACK_PREFIX
from agent_runtime.messaging.upstream_adapter_transport import TelegramUpstreamAdapterTransport
from agent_runtime.work_store.persona_turn import PersonaTurnExecutor
from tests.agent_runtime.messaging.fake_bot_api_server import FakeTelegram
from tests.agent_runtime.messaging.test_upstream_telegram_end_to_end import GATE_ENV, ROOT, TOKEN, _wait

TG = Platform.TELEGRAM


@pytest.fixture(autouse=True)
def _no_direct_turns(monkeypatch):
    monkeypatch.setattr(mission_chat_door, "run_mission_chat_turn",
                        lambda args: (_ for _ in ()).throw(AssertionError("a direct turn")))


@pytest.fixture
def build(monkeypatch):
    from gateway.config import PlatformConfig
    from plugins.platforms.telegram.adapter import TelegramAdapter

    for name in GATE_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HERMES_TELEGRAM_DISABLE_FALLBACK_IPS", "1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    made = []

    def make(*, hardened: bool):
        server = FakeTelegram(TOKEN)
        adapter = TelegramAdapter(PlatformConfig(enabled=True, token=TOKEN, typing_indicator=False,
                                                 extra={"base_url": server.base_url}))
        refused = []
        operators = OperatorStore()
        operators.allow(Operator(TG, "42", "Max", "rpc:stdio_owner", "2026-11-14T00:00:00+00:00"))
        transport = TelegramUpstreamAdapterTransport(
            adapter, press_prefix=CALLBACK_PREFIX, connect=True,
            is_allowed=(lambda user_id: operators.is_allowed(TG, user_id)) if hardened else None,
            on_refused=(lambda user_id, chat_id, display: refused.append((user_id, chat_id, display)))
            if hardened else None)
        alice = SimpleNamespace(id="inst-alice", persona_id="alice", display_name="Alice",
                                runtime_root=str(paths.store_root()))
        turns = PersonaTurnExecutor(instances=SimpleNamespace(get=lambda _id: alice),
                                    root_of=lambda store, **_: ROOT, wake=lambda: None)
        bridge = MessagingBridge(transport, turns, roster=lambda: [alice], root_busy=lambda _root: False)
        BindingStore().set(Binding(TG, "42", None, "inst-alice", "rpc:stdio_owner", "2026-11-14T00:00:00+00:00"))
        bridge.start()
        rig = SimpleNamespace(server=server, adapter=adapter, bridge=bridge, refused=refused)
        made.append(rig)
        return rig

    yield make
    for rig in made:
        rig.bridge.stop()
        rig.server.close()


def _settle(rig, seconds=1.5):
    """Give the adapter time to act on an update it may be about to drop (there is nothing to wait FOR)."""
    _wait(lambda: not rig.server._updates, what="the update to be polled")
    time.sleep(seconds)


def test_with_the_open_gate_a_strangers_photo_is_downloaded_before_the_bridge_refuses(build):
    """Records the hazard: what the adapter does when nobody tells it who is allowed (``is_allowed=None``)."""
    rig = build(hardened=False)
    rig.server.push_photo("look at this", user_id=99, first_name="Stranger")
    _wait(lambda: "getFile" in rig.server.methods(), what="the adapter to fetch the stranger's photo")
    _wait(lambda: "<download>" in rig.server.methods(), what="the download")
    assert not send_queue.has_entries(ROOT)  # the bridge still refused the turn


def test_hardened_the_adapter_fetches_nothing_of_a_strangers_and_the_refusal_is_recorded(build):
    """Killing mutation: ``_prepare`` stops installing ``_named_gate`` AND ``start`` stops configuring
    ``allow_from`` (the adapter then never asks the fork) → the photo is downloaded → red. The refusal
    carries the sender's NAME, which only the named gate sees."""
    rig = build(hardened=True)
    rig.server.push_photo("look at this", user_id=99, first_name="Stranger")
    rig.server.push_message("and some text", user_id=99, first_name="Stranger")
    _settle(rig)
    assert "getFile" not in rig.server.methods() and "<download>" not in rig.server.methods()
    assert not send_queue.has_entries(ROOT) and rig.server.sent == []
    assert ("99", "99", "Stranger") in rig.refused


def test_hardened_the_allowed_operator_still_gets_through(build):
    rig = build(hardened=True)
    rig.server.push_message("what moved today?")
    _wait(lambda: any(e.args.get("message") == "what moved today?" for e in send_queue.entries(ROOT)),
          what="the operator's queued turn")
    assert rig.refused == []
