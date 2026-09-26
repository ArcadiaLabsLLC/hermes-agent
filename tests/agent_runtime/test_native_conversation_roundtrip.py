"""Actual native worker/agent over a loopback-only deterministic provider."""
import json
import threading
import time
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


def test_real_profile_a_b_a_native_turns_and_persistent_sessions(tmp_path):
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
            "mcp_servers: {}\n", encoding="utf-8")
    service = ConversationService(root, "isolated-install", profile_home=lambda p: tmp_path / p)
    sessions = {}
    try:
        for number, profile in enumerate(("a", "b", "a")):
            scope = ConversationScope("operator", "isolated-account", profile)
            opened = service.open(scope, key="chat", cwd=str(tmp_path), expected_home=str(tmp_path / profile))
            sid = opened["session_id"]
            if profile in sessions:
                assert sessions[profile] == sid
            sessions[profile] = sid
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
            assert terminal[-1]["text"] == "Local native answer"
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
    finally:
        service.close()
        provider.shutdown()
        provider.server_close()
        thread.join(timeout=3)
