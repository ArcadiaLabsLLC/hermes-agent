"""RT-ANTHROPIC-CONN-PER-TURN: an anthropic actor's request client keeps its
connection between turns, and its prewarm opens one.

Live 2026-10-25: every Neko (anthropic) turn handshook (``conn=new``) because
the SDK's own ``httpx.Client`` reaps an idle connection after httpx's 5 s
default; the OpenAI-wire clients ride upstream's 20 s keep-alive pool.

Named sabotage: drop the ``adopt_keepalive_http_client`` seam call in
``agent/client_lifecycle.py::_create_request_anthropic_client`` → the
two-requests-six-seconds-apart test sees two TCP connections; drop the
anthropic arm of ``provider_preconnect._turn_client`` → the prewarm answers
``no_client``.
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock

import pytest


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def setup(self):
        super().setup()
        self.server.connections += 1

    def _answer(self):
        self.send_response(404)
        self.send_header("content-length", "0")
        self.send_header("connection", "keep-alive")
        self.end_headers()

    do_GET = _answer
    do_HEAD = _answer


@pytest.fixture
def keepalive_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    server.connections = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def _agent(base_url: str):
    from run_agent import AIAgent

    agent = AIAgent(
        api_key="sk-ant-test-key",
        base_url=base_url,
        model="claude-test",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    agent.api_mode = "anthropic_messages"
    agent.provider = "custom"
    agent._anthropic_api_key = "sk-ant-test-key"
    agent._anthropic_base_url = base_url
    return agent


def test_an_idle_gap_past_five_seconds_reuses_the_connection(keepalive_server):
    base = f"http://127.0.0.1:{keepalive_server.server_address[1]}"
    agent = _agent(base)
    client = agent._create_request_anthropic_client(reason="test")
    http = client._client
    assert http.get(f"{base}/v1/ping").status_code == 404
    # The agent's own construction may probe the endpoint too; count from here.
    opened = keepalive_server.connections
    agent._close_request_anthropic_client(client, reason="stream_request_complete")
    time.sleep(6.0)  # past httpx's 5 s default keepalive_expiry, inside the pool's 20 s
    again = agent._create_request_anthropic_client(reason="test")
    assert again is client
    assert again._client.get(f"{base}/v1/ping").status_code == 404
    assert keepalive_server.connections == opened


def test_bedrock_and_non_sdk_clients_are_left_alone():
    from agent_runtime.anthropic_keepalive import adopt_keepalive_http_client

    other = MagicMock()
    assert adopt_keepalive_http_client(other, ("bedrock", "us-east-1")) is False
    assert adopt_keepalive_http_client(other, ("direct", "k", None, 600.0, False)) is False


def test_an_anthropic_prewarm_opens_its_connection(keepalive_server):
    from agent_runtime.provider_preconnect import _http_client

    base = f"http://127.0.0.1:{keepalive_server.server_address[1]}"
    agent = _agent(base)
    http = _http_client(agent)
    assert http is not None
    # The turn's own request client carries the very pool the prewarm warmed.
    client = agent._create_request_anthropic_client(reason="turn")
    assert client._client is http
    agent._close_request_anthropic_client(client, reason="stream_request_complete")


def test_a_second_agent_copies_the_template_instead_of_constructing_the_sdk(keepalive_server, monkeypatch):
    """RT-ANTHROPIC-CLIENT-BUILT-PER-TURN: live 2026-10-26, warm Neko turns paid
    ``client_built_ms`` 79-113 constructing ``anthropic.Anthropic`` per turn.

    Named sabotage: drop ``_record_template`` from ``adopt_keepalive_http_client``
    -> the second agent constructs the SDK again (``built == 2``)."""

    import agent.anthropic_adapter as adapter

    base = f"http://127.0.0.1:{keepalive_server.server_address[1]}"
    built = []
    real = adapter.build_anthropic_client

    def counting(*args, **kwargs):
        built.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(adapter, "build_anthropic_client", counting)
    first_agent, second_agent = _agent(base), _agent(base)
    first = first_agent._create_request_anthropic_client(reason="turn")
    assert len(built) == 1
    second = second_agent._create_request_anthropic_client(reason="turn")
    assert len(built) == 1, "the second agent constructed the SDK client again"
    assert second is not first and second._client is not first._client
    assert second.default_headers == first.default_headers and second.api_key == first.api_key

    assert first._client.get(f"{base}/v1/ping").status_code == 404
    opened = keepalive_server.connections
    # One agent's teardown close cannot close the other's client.
    first_agent._close_cached_request_anthropic_client(reason="teardown")
    assert second._client.get(f"{base}/v1/ping").status_code == 404
    assert keepalive_server.connections == opened


def test_an_entra_bearer_provider_key_is_never_pooled():
    """A callable credential's ``httpx.Client`` carries the per-request auth hook;
    moving it onto the pool would send the placeholder token."""

    import anthropic

    from agent_runtime.anthropic_keepalive import adopt_keepalive_http_client, pooled_anthropic_client

    key = ("direct", lambda: "jwt", "https://example.services.ai.azure.com/anthropic", 600.0, False)
    client = anthropic.Anthropic(auth_token="entra-id-bearer-via-http-hook", base_url=key[2])
    own = client._client
    assert adopt_keepalive_http_client(client, key) is False
    assert client._client is own
    assert pooled_anthropic_client(key) is None
