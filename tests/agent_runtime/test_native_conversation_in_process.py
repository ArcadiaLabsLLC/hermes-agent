"""The engine with no subprocess: upstream's gateway served in this process behind the peer seam.

Embedded-hermes plan Stage 2 step 8, and since RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT the
engine every chat with an agent runs on, desktop and phone alike. Driven directly (``engine_session``), as the
gateway's clients drive it: real agents, a loopback provider — and no child process at all.

Proven: A/B/A turns complete with each profile's own credentials, skills and history (profile isolation),
retirement leaves no execution possible, and a reopen recovers the transcript without running a turn
(recovery); the process never gained a child.

Killing mutations (applied, red recorded, reverted — see the commit message):

* ``InProcessPeer._send`` stops injecting ``profile``            -> red (both profiles share one home).
* ``InProcessPeer.close`` skips ``session.close``                 -> red (execution stays possible).
* ``execution_possible`` answers True for a registered in-process worker -> red (retired peers).
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psutil
import pytest

from agent_runtime.conversations.in_process_peer import InProcessPeer
from agent_runtime.conversations.model import ConversationError, Refusal
from agent_runtime.conversations.process_evidence import execution_possible
from tests.agent_runtime.engine_session import EngineSession, until

pytestmark = pytest.mark.timeout(180)


class Provider(BaseHTTPRequestHandler):
    requests: list = []

    def log_message(self, *_):
        pass

    def do_GET(self):
        self._send("application/json", json.dumps({"object": "list", "data": [{"id": "test-model"}]}).encode())

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append((self.headers.get("Authorization"), body))
        base = {"id": "r", "object": "chat.completion.chunk", "created": 1, "model": "test-model"}
        rows = [{**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Local native answer"},
                                      "finish_reason": None}]},
                {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}}]
        self._send("text/event-stream", ("".join("data: " + json.dumps(r) + "\n\n" for r in rows)
                                         + "data: [DONE]\n\n").encode())

    def _send(self, kind, data):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _profiles(port: int, shared: bool) -> dict[str, Path]:
    from hermes_cli.profiles import get_profile_dir

    homes = {}
    for profile in ("a", "b"):
        home = get_profile_dir(profile)
        (home / "skills" / f"review-{profile}").mkdir(parents=True)
        (home / "skills" / f"review-{profile}" / "SKILL.md").write_text(
            f"---\nname: review-{profile}\ndescription: Profile review\n---\nRead only {profile}.\n", encoding="utf-8")
        definitions = ("" if shared else
            f"providers:\n  local-test:\n    api: http://127.0.0.1:{port}/v1\n    api_key: isolated-{profile}\n")
        (home / "config.yaml").write_text(
            "model:\n  default: test-model\n  provider: custom:local-test\n"
            + definitions +
            "dashboard:\n  turn_isolation: false\nmcp_servers: {}\n", encoding="utf-8")
        homes[profile] = home
    return homes


@pytest.mark.parametrize("shared", [False, True], ids=["private-provider", "shared-provider"])
def test_a_b_a_turns_sessions_and_recovery_with_no_child_process(tmp_path, shared):
    Provider.requests = []
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    homes = _profiles(provider.server_port, shared)
    owner = tmp_path / "owner"
    owner.mkdir()
    (owner / "config.yaml").write_text(
        f"providers:\n  local-test:\n    api: http://127.0.0.1:{provider.server_port}/v1\n"
        "    key_env: PRIVATE_LLM_KEY\n    models: [test-model]\n    discover_models: false\n", encoding="utf-8")
    (owner / ".env").write_text("PRIVATE_LLM_KEY=shared-provider\n", encoding="utf-8")
    children_before = {c.pid for c in psutil.Process().children(recursive=True)}
    engines = {}
    try:
        for number, profile in enumerate(("a", "b", "a")):
            if profile not in engines:
                engines[profile] = EngineSession(homes[profile], cwd=str(tmp_path), auth_home=owner if shared else None)
            engine = engines[profile]
            execution = f"turn-{number}"
            engine.submit(f"Reply to marker-{profile}-{number}", execution)
            done = until(lambda: engine.completion(execution), lambda payload: payload is not None)
            assert done["text"] == "Local native answer"
            catalog = engine.peer.call("eternia.skills.list", {"session_id": engine.sid, "skill_id": None})["data"]
            assert {row["id"] for row in catalog["skills"]} >= {f"review-{profile}"}
            assert not any(row["id"] == f"review-{'b' if profile == 'a' else 'a'}" for row in catalog["skills"])
        chat = [(auth, body) for auth, body in Provider.requests
                if any("marker-" in str(m.get("content", "")) for m in body.get("messages", []))]
        assert len(chat) >= 3
        for auth, body in chat:
            mine = next(p for p in ("a", "b") if f"marker-{p}-" in json.dumps(body))
            assert auth == ("Bearer shared-provider" if shared else f"Bearer isolated-{mine}")
            assert f"marker-{'b' if mine == 'a' else 'a'}-" not in json.dumps(body)
        assert (homes["a"] / "state.db").is_file() and (homes["b"] / "state.db").is_file()
        peers = [engine.peer for engine in engines.values()]
        assert all(isinstance(peer, InProcessPeer) for peer in peers)
        assert all(execution_possible(*peer.process_identity) for peer in peers)  # live: evidence says so
        from tui_gateway import server
        assert all(engine.sid in server._sessions for engine in engines.values())
        assert {c.pid for c in psutil.Process().children(recursive=True)} <= children_before

        stored = engines["a"].stored
        for engine in engines.values():
            engine.close()
        assert all(engine.sid not in server._sessions for engine in engines.values())
        assert all(not peer.execution_possible for peer in peers)
        assert not any(execution_possible(*peer.process_identity) for peer in peers)
        before = len(Provider.requests)
        engines = {"a": EngineSession(homes["a"], resume=stored, auth_home=owner if shared else None)}
        recovered = "".join(engines["a"].history(engines["a"].recover()["history"]))
        assert "marker-a-0" in recovered and "marker-a-2" in recovered and "marker-b-" not in recovered
        assert len(Provider.requests) == before, "reopening must never execute a turn"
    finally:
        for engine in engines.values():
            engine.close()
        provider.shutdown()
        provider.server_close()


def test_a_home_that_is_not_its_profiles_home_is_refused(tmp_path):
    from hermes_cli.profiles import get_profile_dir

    home = get_profile_dir("a")
    home.mkdir(parents=True)
    InProcessPeer(home, receive=lambda _f: None, lost=lambda: None,
                  dispatch=lambda *_a: None).close()  # positive control: the canonical home is served
    with pytest.raises(ConversationError) as refused:
        InProcessPeer(tmp_path, receive=lambda _f: None, lost=lambda: None, dispatch=lambda *_a: None)
    assert refused.value.reason is Refusal.WRONG_OWNER

def test_new_attachment_between_detach_and_reap_survives(monkeypatch):
    from tui_gateway import server

    first, second = object(), object()
    sid = "reconnect-during-release"
    record = dict(transport=first, close_on_disconnect=True)
    monkeypatch.setitem(server._sessions, sid, record)
    detach = server._detach_transport_from_sessions

    def reconnect_after_detach(transport, *, session_id=None):
        clientless = detach(transport, session_id=session_id)
        assert clientless == [(sid, record)]
        with server._session_resume_lock:
            server._rebind_live_transport(sid, record, second)
        return clientless

    monkeypatch.setattr(server, "_detach_transport_from_sessions", reconnect_after_detach)
    assert server._close_sessions_for_transport(first, session_id=sid) == (0, 0)
    assert server._sessions[sid] is record and server._session_transport_contains(record, second)
