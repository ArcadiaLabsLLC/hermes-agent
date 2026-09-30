"""Real native agents reach the existing app-function request authority."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent_runtime.conversations.app_functions import AppFunctionPool, NativeAppFunctions, METHOD
from agent_runtime.conversations.model import ConversationScope
from agent_runtime.conversations.service import ConversationService
from tests.agent_runtime.native_recovery_provider import until

pytestmark = pytest.mark.timeout(120)
TOOLS = [{"name": "launcher_generated_create", "method": "launcher.generated.create",
          "description": "Create a generated document.", "parameters": {"type": "object",
          "properties": {"title": {"type": "string"}}, "required": ["title"]}}]


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        self.reply({"object": "list", "data": [{"id": "test-model", "object": "model"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(body)
        messages = body.get("messages", [])
        called = any(m.get("role") == "tool" for m in messages)
        names = [t.get("function", {}).get("name") for t in body.get("tools", [])]
        message = {"role": "assistant", "content": "Tool unavailable"}
        finish = "stop"
        if ("launcher_generated_create" in names or "tool_call" in names) and not called:
            direct = "launcher_generated_create" in names
            name = "launcher_generated_create" if direct else "tool_call"
            arguments = {"title": "Native proof"} if direct else {"calls": [{"name": "launcher_generated_create", "arguments": {"title": "Native proof"}}]}
            message = {"role": "assistant", "tool_calls": [{"index": 0, "id": "create-1", "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)}}]}
            finish = "tool_calls"
        elif called:
            message["content"] = "Created through the Launcher"
        base = {"id": "native-tool-proof", "created": 1, "model": "test-model"}
        if body.get("stream"):
            rows = [{**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": message, "finish_reason": None}]},
                    {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}]
            data = ("".join("data: " + json.dumps(r) + "\n\n" for r in rows) + "data: [DONE]\n\n").encode()
            self._reply(data, "text/event-stream")
        else:
            self.reply({**base, "object": "chat.completion", "choices": [{"index": 0, "message": message, "finish_reason": finish}]})

    def reply(self, data):
        self._reply(json.dumps(data).encode(), "application/json")

    def _reply(self, data, kind):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.mark.parametrize("mode", ["native-worker", "isolated-compute", "in-process"])
def test_real_agent_discovers_and_calls_once_without_replaying_on_reopen(tmp_path, mode):
    compute = mode == "isolated-compute"
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    provider.requests = []
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    from hermes_cli.profiles import get_profile_dir
    from agent_runtime.conversations.in_process_peer import start_in_process_worker
    home = get_profile_dir("native-proof") if mode == "in-process" else tmp_path / "profile"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        "model:\n  default: test-model\n  provider: custom:native-test\n"
        f"providers:\n  native-test:\n    api: http://127.0.0.1:{provider.server_port}/v1\n    api_key: isolated-test\n"
        f"dashboard:\n  turn_isolation: {str(compute).lower()}\nmcp_servers: {{}}\n", encoding="utf-8")
    options = {"worker_factory": start_in_process_worker} if mode == "in-process" else {}
    service = ConversationService(tmp_path, "isolated", profile_home=lambda _: home, **options)
    scope = ConversationScope("operator", "account", "native-proof")
    calls = []
    def request(method, params):
        calls.append((method, params))
        return {"tools": TOOLS} if method == "launcher.app_functions.list" else {"data": {"id": "generated-proof"}}
    try:
        sid = service.open(scope, key="chat", cwd=str(tmp_path), expected_home=str(home))["session_id"]
        service.send(scope, sid, "turn", {"text": "Create the native proof document.", "images": []}, launcher_request=request)
        settled = until(lambda: service.read(scope, sid, 0, "turn"),
                        lambda page: page["turn"]["state"] not in {"dispatching", "running", "unknown"}, timeout=60)
        assert settled["turn"]["state"] == "completed", settled
        assert [method for method, _ in calls] == ["launcher.app_functions.list", "launcher.generated.create"], calls
        assert calls[-1][1]["title"] == "Native proof"
        assert any("generated-proof" in json.dumps(b.get("messages", [])) for b in provider.requests)
        before = list(calls)
        service.open(scope, key="chat", cwd=str(tmp_path), expected_home=str(home), resume=sid)
        service.send(scope, sid, "turn", {"text": "Create the native proof document.", "images": []}, launcher_request=lambda *_: pytest.fail("rebound"))
        assert calls == before
    finally:
        service.close()
        provider.shutdown()
        provider.server_close()
        thread.join(timeout=3)


def test_duplicate_and_retired_requests_never_repeat_an_effect():
    class Peer:
        def __init__(self):
            self.replies = []
        def write(self, frame):
            self.replies.append(frame)
    peer, pool = Peer(), AppFunctionPool()
    current = [True]
    calls = []
    relay = NativeAppFunctions(peer, pool, lambda execution: current[0] and execution == "turn")
    relay.bind("turn", lambda method, args: calls.append(method) or {"ok": True})
    frame = {"id": "one", "method": METHOD, "params": {"request": {"method": "launcher.generated.create", "params": {}}}}
    try:
        assert relay.receive(frame)
        until(lambda: peer.replies, bool)
        assert relay.receive(frame)
        assert calls == ["launcher.generated.create"]
        current[0] = False
        assert relay.receive({**frame, "id": "two"})
        until(lambda: peer.replies, lambda rows: len(rows) == 2)
        assert "error" in peer.replies[-1]["result"]["reply"]
        assert calls == ["launcher.generated.create"]
    finally:
        pool.close()
