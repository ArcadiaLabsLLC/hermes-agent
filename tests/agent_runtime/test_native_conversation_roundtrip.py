"""Actual native worker/agent over a loopback-only deterministic provider."""
import json
import threading
import time
import psutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent_runtime.conversations.model import ConversationScope
from agent_runtime.conversations.service import ConversationService

pytestmark = pytest.mark.timeout(120)


class Provider(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *_):
        pass

    def do_GET(self):
        data = json.dumps({"object": "list", "data": [{"id": "test-model", "object": "model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append((self.headers.get("Authorization"), body))
        base = {"id": "test-response", "object": "chat.completion", "created": 1, "model": "test-model"}
        self.send_response(200)
        if body.get("stream"):
            pieces = [
                {**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": "Local native answer"}, "finish_reason": None}]},
                {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}},
            ]
            data = ("".join("data: " + json.dumps(row) + "\n\n" for row in pieces) + "data: [DONE]\n\n").encode()
            kind = "text/event-stream"
        else:
            data = json.dumps({**base, "choices": [{"index": 0, "message": {
                "role": "assistant", "content": "Local native answer"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}}).encode()
            kind = "application/json"
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.mark.parametrize("compute", [False, True], ids=["inline", "compute-child"])
def test_real_profile_a_b_a_native_turns_and_persistent_sessions(tmp_path, compute):
    Provider.requests = []
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    root = tmp_path / "runtime"
    root.mkdir()
    for profile in ("a", "b"):
        home = tmp_path / profile
        home.mkdir()
        (home / "config.yaml").write_text(
            "model:\n  default: test-model\n  provider: custom:local-test\n"
            f"providers:\n  local-test:\n    api: http://127.0.0.1:{provider.server_port}/v1\n    api_key: isolated-{profile}\n"
            f"dashboard:\n  turn_isolation: {str(compute).lower()}\n"
            "mcp_servers: {}\n", encoding="utf-8")
        skill = home / "skills" / f"review-{profile}" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(f"---\nname: review-{profile}\ndescription: Profile review\n---\nRead only {profile}.\n", encoding="utf-8")
    now = [0.0]
    service = ConversationService(root, "isolated-install", profile_home=lambda p: tmp_path / p,
                                  retention_options={"clock": lambda: now[0]})
    sessions = {}
    try:
        for number, profile in enumerate(("a", "b", "a")):
            scope = ConversationScope("operator", "isolated-account", profile)
            opened = service.open(scope, key="chat", cwd=str(tmp_path), expected_home=str(tmp_path / profile))
            sid = opened["session_id"]
            if profile in sessions:
                assert sessions[profile] == sid
            sessions[profile] = sid
            # Give native prewarming time to run, as when a user waits before typing.
            time.sleep(1)
            turn = f"turn-{number}"
            service.send(scope, sid, turn, {"text": f"Reply to marker-{profile}-{number}", "images": []})
            deadline = time.monotonic() + 45
            while True:
                result = service.read(scope, sid, 0, turn)
                if result["turn"]["state"] not in {"dispatching", "running"}:
                    break
                assert time.monotonic() < deadline, "native turn did not settle"
                time.sleep(.05)
            assert result["turn"]["state"] == "completed", result
            terminal = [e["frame"]["params"]["payload"] for e in result["events"]
                        if e["turn_id"] == turn and e["frame"].get("params", {}).get("type") == "message.complete"]
            assert terminal, json.dumps(result)
            assert terminal[-1]["text"] == "Local native answer"
            catalog = service.skills(scope, sid, "list")
            assert any(row["id"] == f"review-{profile}" for row in catalog["skills"])
            detail = service.skills(scope, sid, "detail", f"review-{profile}")
            assert f"Read only {profile}." in detail["skill"]["content"]
            deadline = time.monotonic() + 10
            while service.skills(scope, sid, "history") != {"loaded": [], "historyComplete": True}:
                assert time.monotonic() < deadline, "skill history did not settle"
                time.sleep(.05)
        assert len(set(sessions.values())) == 2
        # The real agents reached the stub using only their own profile credentials/history.
        chat = [(auth, body) for auth, body in Provider.requests if any(
            "marker-" in str(m.get("content", "")) for m in body.get("messages", []))]
        assert len(chat) >= 3
        for auth, body in chat:
            expected = auth.removeprefix("Bearer isolated-")
            assert expected in {"a", "b"}
            other = "b" if expected == "a" else "a"
            assert f"marker-{other}-" not in json.dumps(body)
        assert (tmp_path / "a" / "state.db").is_file()
        assert (tmp_path / "b" / "state.db").is_file()
        peers = [entry.live.peer for entry in service._bindings._entries.values()]
        children = [child for peer in peers for child in psutil.Process(peer.process.pid).children(recursive=True)]
        compute_children = [child for child in children if "tui_gateway.compute_host" in child.cmdline()]
        assert bool(compute_children) == compute, [child.cmdline() for child in children]
        # Native turn.done can follow message.complete; retirement must wait for it.
        now[0] = 1000
        deadline = time.monotonic() + 15
        while service._bindings._entries:
            service._bindings.sweep()
            assert time.monotonic() < deadline, "settled sessions did not retire"
            time.sleep(.05)
        assert all(not peer.execution_possible for peer in peers)
        assert not any(child.is_running() for child in compute_children)
        assert not service._workers._workers
        requests_before = len(Provider.requests)
        scope = ConversationScope("operator", "isolated-account", "a")
        reopened = service.open(scope, key="chat", cwd=str(tmp_path),
            expected_home=str(tmp_path / "a"), resume=sessions["a"])
        assert reopened["session_id"] == sessions["a"]
        assert reopened["turn"]["state"] == "completed"
        assert reopened["recovery"]["execution"]["status"] == "complete"
        page = service.history(scope, sessions["a"], reopened["recovery"]["history"], 0, 0)
        recovered = "".join(chunk["data"] for chunk in page["chunks"])
        assert "marker-a-0" in recovered and "marker-a-2" in recovered
        assert "Local native answer" in recovered and "marker-b-" not in recovered
        assert len(Provider.requests) == requests_before, "reopening must never execute a turn"
    finally:
        service.close()
        provider.shutdown()
        provider.server_close()
        thread.join(timeout=3)
