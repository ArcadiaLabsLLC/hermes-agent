"""A real serve and agent loop with an isolated, loopback-only provider."""
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
import threading

from tests.agent_runtime.test_native_conversation_roundtrip import Provider
from tests.hermes_cli.test_harness_serve_drain_order import _Pipe, _Sink
from tests.waiting import wait_until


class IndependentConversationPeer:
    def __init__(self):
        self.reader, self.writer = _Pipe(), _Sink()
        self.serial = 0

    def call(self, method, **params):
        self.serial += 1
        rid = f"independent-{self.serial}"
        self.reader.send(dict(jsonrpc="2.0", id=rid, method=method, params=params))
        reply = wait_until(lambda: next((r for r in self.writer.frames()
                           if r.get("id") == rid and "jsonrpc" in r), None),
                           timeout=30, what=method)
        assert "result" in reply, reply
        return reply["result"]


@contextmanager
def independent_conversation_peer(monkeypatch):
    from hermes_constants import get_hermes_home
    from hermes_cli.profiles import get_profile_dir
    from hermes_cli.harness_parts.serve import serve_loop

    monkeypatch.setenv("HERMES_HEAD_HOME", str(get_hermes_home()))
    Provider.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    provider_thread = threading.Thread(target=server.serve_forever, daemon=True)
    provider_thread.start()
    home = get_profile_dir("independent-native")
    home.mkdir(parents=True)
    config = (
        "model:\n  default: test-model\n  provider: custom:local-test\n"
        f"providers:\n  local-test:\n    api: http://127.0.0.1:{server.server_port}/v1\n"
        "    api_key: isolated-test\n    discover_models: false\n"
        "agent_runtime:\n  persona_chat:\n    hot_sessions_enabled: false\n"
        "mcp_servers: {}\n"
    )
    for destination in (home, get_hermes_home()):
        (destination / "config.yaml").write_text(config, encoding="utf-8")
    peer = IndependentConversationPeer()
    result = {}
    def run():
        result["code"] = serve_loop(peer.reader, peer.writer, socket_lane=True)
    runtime_thread = threading.Thread(target=run, daemon=True)
    runtime_thread.start()
    try:
        peer.writer.wait_for("ready")
        yield peer
    finally:
        peer.reader.close()
        runtime_thread.join(timeout=30)
        server.shutdown()
        server.server_close()
        provider_thread.join(timeout=3)
        assert not runtime_thread.is_alive() and not provider_thread.is_alive()
        assert result.get("code") == 0, result
