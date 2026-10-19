"""The idle keeper arms on a serve without resident chats (owner ruling 2026-10-16).

Live 2026-10-15 (QA home, ``persona_chat.hot_sessions_enabled`` off) 6/6 turns read ``conn=new``:
the keeper armed only where the resident registry existed, and the per-turn actor it would have
read was gone at the next tick. The serve now arms it either way, and with no resident chats the
tick keeps the process-shared pool warm through a client of its own
(``provider_preconnect.refresh_process_connection``) instead of reading a discarded actor back.
The connected case (the after-idle turn rides ``conn=reused``) is the idle-box guard
``test_idle_turn_guard_downstream.py[no_resident_chats]``.
"""

from __future__ import annotations

import gc
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent_runtime import idle_turn_keeper, provider_preconnect
from agent_runtime.persona_chat_continuity.runtime_registry import (
    initialize_persona_chat_runtime_registry,
    reset_persona_chat_runtime_registry,
)


class _Head(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    seen: list[str] = []

    def do_HEAD(self):
        type(self).seen.append(self.headers.get("user-agent") or "")
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_args):
        pass


@pytest.fixture
def server():
    _Head.seen = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Head)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/v1"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(provider_preconnect, "_is_loopback", lambda host: False)
    yield
    idle_turn_keeper.reset_for_tests()
    provider_preconnect.reset_process_target_for_tests()
    reset_persona_chat_runtime_registry()


class _Actor:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self._client_kwargs = {"default_headers": {"User-Agent": "hermes-test/1", "Authorization": "secret"}}
        self.request_clients = 0

    def _create_request_openai_client(self, **_kw):
        self.request_clients += 1
        raise AssertionError("the keeper never builds a client on a non-resident actor")


def test_a_serve_without_resident_chats_arms_the_keeper():
    initialize_persona_chat_runtime_registry(enabled=False)
    reset_persona_chat_runtime_registry()
    idle_turn_keeper.stop()
    assert idle_turn_keeper.arm() is None, "no serve: nothing arms"
    initialize_persona_chat_runtime_registry(enabled=False)
    thread = idle_turn_keeper.arm()
    assert thread is not None and thread.is_alive()
    reset_persona_chat_runtime_registry()
    idle_turn_keeper.stop()
    assert idle_turn_keeper.arm() is None, "a reset registry disarms it"


def test_the_tick_keeps_the_last_chats_pool_warm_after_its_actor_is_gone(server):
    initialize_persona_chat_runtime_registry(enabled=False)
    actor = _Actor(server)
    idle_turn_keeper.note_active_agent(actor)
    del actor
    gc.collect()

    _refreshed, socket = idle_turn_keeper.tick_once(1)
    assert socket == "404"
    assert _Head.seen == ["hermes-test/1"], "one HEAD, identity headers only"


def test_without_resident_chats_a_live_actor_is_never_read_back(server):
    initialize_persona_chat_runtime_registry(enabled=False)
    actor = _Actor(server)
    idle_turn_keeper.note_active_agent(actor)

    _refreshed, socket = idle_turn_keeper.tick_once(1)
    assert socket == "404"
    assert actor.request_clients == 0


def test_no_chat_yet_is_a_receipt_not_an_error():
    initialize_persona_chat_runtime_registry(enabled=False)
    assert idle_turn_keeper.tick_once(1)[1] == provider_preconnect.STATUS_NO_TARGET
