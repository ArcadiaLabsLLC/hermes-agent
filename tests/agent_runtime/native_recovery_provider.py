"""Loopback provider that asks once, then holds a real streaming response."""
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class RecoveryProvider(ThreadingHTTPServer):
    def __init__(self, *, text="Recovered prefix 🌍", hold_seconds=30):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.partial = threading.Event()
        self.release = threading.Event()
        self.requests = []
        self.text = text
        self.hold_seconds = hold_seconds
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.release.set()
        self.shutdown()
        self.server_close()
        self.thread.join(timeout=3)

    def configure(self, home, *, compute):
        (home / "config.yaml").write_text(
            "model:\n  default: test-model\n  provider: custom:recovery\n"
            f"providers:\n  recovery:\n    api: http://127.0.0.1:{self.server_port}/v1\n    api_key: isolated-recovery\n"
            f"dashboard:\n  turn_isolation: {str(compute).lower()}\n"
            "mcp_servers: {}\n", encoding="utf-8")


def until(read, predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while True:
        value = read()
        if predicate(value):
            return value
        assert time.monotonic() < deadline, value
        time.sleep(.05)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"object":"list","data":[{"id":"test-model","object":"model"}]}')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if not body.get("stream") or not body.get("tools"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"id": "auxiliary", "object": "chat.completion",
                "created": 1, "model": "test-model", "choices": [{"index": 0,
                    "message": {"role": "assistant", "content": "Recovery test"},
                    "finish_reason": "stop"}]}).encode())
            return
        self.server.requests.append(body)
        answered = any(message.get("role") == "tool" for message in body.get("messages", []))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            if not answered:
                self.chunk({"role": "assistant", "tool_calls": [{"index": 0, "id": "question-" + uuid.uuid4().hex,
                    "type": "function", "function": {"name": "clarify", "arguments": json.dumps({
                        "questions": [{"question": "Continue the isolated recovery test?",
                                       "choices": ["Yes", "No"]}]})}}]})
                self.chunk({}, "tool_calls")
            else:
                self.chunk({"role": "assistant", "content": self.server.text})
                self.server.partial.set()
                if not self.server.release.wait(self.server.hold_seconds):
                    return
                self.chunk({"content": " after release"})
                self.chunk({}, "stop")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def chunk(self, delta, finish=None):
        frame = {"id": "recovery-response", "object": "chat.completion.chunk", "created": 1,
            "model": "test-model", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
        self.wfile.write(("data: " + json.dumps(frame) + "\n\n").encode())
        self.wfile.flush()
