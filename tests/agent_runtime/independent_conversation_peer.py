"""A real serve and agent loop with an isolated, loopback-only provider."""
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
import json
import threading
import time

from tests.agent_runtime.test_native_conversation_roundtrip import Provider
from tests.hermes_cli.test_harness_serve_drain_order import _Pipe, _Sink


class _FrameSink(_Sink):
    """The serve's stdout, parsed once per line as it lands, waking whoever waits on it.

    The base sink re-joins and re-decodes every byte written so far on each ``frames()``
    call. Polled every 10 ms for a reply and again for each turn's read, that cost a
    three-turn run 6.6 s of 25.8 s (w1115c-h2, 1386 calls over a 545 KB stdout), all of it
    under the GIL the serve's own threads need; on a loaded box it starved the serve past
    the test's 30 s ceiling. A waiter here blocks on the write itself and costs nothing
    until a new line arrives. With the settle wait beside it, the native-turn test's whole
    process went from 31.8 s of CPU to 13.8 s (13.5 s of it had been the test's own thread).
    """

    def __init__(self) -> None:
        super().__init__()
        self._arrived = threading.Condition(self._lock)
        self._rows: list[dict] = []
        self._tail = ""

    def write(self, text: str) -> int:
        with self._arrived:
            self._parts.append(text)
            *lines, self._tail = (self._tail + text).split("\n")
            for line in filter(None, (line.strip() for line in lines)):
                try:
                    self._rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            self._arrived.notify_all()
        return len(text)

    def frames(self) -> list[dict]:
        with self._lock:
            return list(self._rows)

    def wait_frame(self, predicate, *, timeout: float, what: str, on_wake=None) -> dict:
        """The first frame, already here or still to come, that ``predicate`` accepts.

        ``on_wake`` runs (outside the lock) each time new output lands while it waits: a check
        that must hold THROUGHOUT what is being waited for, read at every step the serve takes.
        """
        deadline = time.monotonic() + timeout
        seen = 0
        while True:
            with self._arrived:
                for row in self._rows[seen:]:
                    if predicate(row):
                        return row
                seen = len(self._rows)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AssertionError(f"timed out after {timeout}s waiting for {what}")
                self._arrived.wait(remaining)
            if on_wake is not None:
                on_wake()

    def wait_for(self, event: str, timeout: float = 25.0) -> dict:
        return self.wait_frame(lambda row: row.get("event") == event, timeout=timeout,
                               what=f"a {event!r} frame")


class IndependentConversationPeer:
    def __init__(self):
        self.reader, self.writer = _Pipe(), _FrameSink()
        self.serial = 0

    def call(self, method, **params):
        self.serial += 1
        rid = f"independent-{self.serial}"
        self.reader.send(dict(jsonrpc="2.0", id=rid, method=method, params=params))
        reply = self.writer.wait_frame(lambda r: r.get("id") == rid and "jsonrpc" in r,
                                       timeout=30, what=method)
        assert "result" in reply, reply
        return reply["result"]

    def wait_settled(self, turn_request_id: str, *, timeout: float = 60, throughout=None) -> dict:
        """The settle lane's ``turn_settled`` for this turn: the serve's own end-of-turn signal.

        ``throughout`` is checked each time the serve writes while the turn runs.
        """
        return self.writer.wait_frame(
            lambda r: r.get("event") == "turn_settled" and r.get("client_message_id") == turn_request_id,
            timeout=timeout, what=f"turn {turn_request_id!r} to settle", on_wake=throughout)


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
