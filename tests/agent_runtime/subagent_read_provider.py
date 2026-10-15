"""Deterministic loopback model: delegate once, hold the real child's stream."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class SubagentProvider(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.entered = threading.Event()
        self.release = threading.Event()
        self.requests = []
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.release.set()
        self.shutdown()
        self.server_close()
        self.thread.join(timeout=3)

    def configure(self, home, compute):
        (home / "config.yaml").write_text(
            "model:\n  default: test-model\n  provider: custom:subagent-proof\n"
            f"providers:\n  subagent-proof:\n    api: http://127.0.0.1:{self.server_port}/v1\n    api_key: isolated-proof\n"
            f"dashboard:\n  turn_isolation: {str(compute).lower()}\n"
            "delegation:\n  max_iterations: 2\nmcp_servers: {}\n", encoding="utf-8")


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        self.reply({"object": "list", "data": [{"id": "test-model", "object": "model"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(body)
        messages = body.get("messages", [])
        last = messages[-1] if messages else {}
        child = last.get("role") == "user" and "CHILD_READ_PROOF" in str(last.get("content"))
        delegated = any(m.get("role") == "tool" for m in messages)
        delta, finish = {"role": "assistant", "content": "Parent settled"}, "stop"
        if child:
            delta["content"] = "Child public progress. " * 200
        elif not delegated and body.get("tools"):
            arguments = {"goal": "CHILD_READ_PROOF", "context": "PRIVATE_KICKOFF_CONTEXT"}
            names = [t.get("function", {}).get("name") for t in body["tools"]]
            name = "delegate_task" if "delegate_task" in names else "tool_call"
            if name == "tool_call":
                arguments = {"calls": [{"name": "delegate_task", "arguments": arguments}]}
            delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": "delegate-proof",
                "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}
            finish = "tool_calls"
        if not body.get("stream"):
            self.reply({"id": "proof", "object": "chat.completion", "created": 1, "model": "test-model",
                        "choices": [{"index": 0, "message": delta, "finish_reason": finish}]})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            self.chunk(delta)
            if child:
                self.server.entered.set()
                self.server.release.wait(40)
            self.chunk({}, finish)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except OSError:
            pass  # The test may deliberately retire its isolated execution owner.

    def chunk(self, delta, finish=None):
        frame = {"id": "proof", "object": "chat.completion.chunk", "created": 1, "model": "test-model",
                 "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
        self.wfile.write(("data: " + json.dumps(frame) + "\n\n").encode())
        self.wfile.flush()

    def reply(self, value):
        data = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
