"""A whole persona chat turn against a loopback model whose reply can be held, cut off or scripted.

The turn-cleanup rows of 2026-11-12 (``TASK-TURN-CLEANUP``) each shipped once on a result a test typed by
hand and missed the live path. This rig is the live path without the client: a real persona instance and
chat root, the real mission-chat door (``_cmd_mission_chat_message`` → ``profile_runner.execute`` →
``AIAgent``), and a real HTTP model — the Eternia QA fixture's ``[[qa:hold]]`` is :attr:`HeldModel.hold`.
Not a test module; the files that import it are its pins.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from agent_runtime import paths, serve_rpc
from agent_runtime.gateway_identity import ensure_install_identity

OWNER = "a" * 64


class HeldModel(ThreadingHTTPServer):
    """An OpenAI-compatible model. ``hold`` set: a chat call waits for ``release`` (or the client hanging up)."""

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.daemon_threads = True
        self.entered, self.release = threading.Event(), threading.Event()
        self.hold = True
        #: Every chat request body, in arrival order (the QA fixture's ``/qa/state``).
        self.requests: list[dict] = []
        #: ``reply(body) -> (text, finish_reason)`` for a call that is not held.
        self.reply: Callable[[dict], tuple[str, str]] = lambda body: ("Thanks, noted.", "stop")
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def configure(self, home) -> None:
        (home / "config.yaml").write_text(
            "model:\n  default: test-model\n  provider: custom:held\n"
            f"providers:\n  held:\n    api: http://127.0.0.1:{self.server_port}/v1\n    api_key: isolated\n"
            "dashboard:\n  turn_isolation: false\nmcp_servers: {}\n", encoding="utf-8")

    def close(self) -> None:
        self.release.set()
        self.shutdown()
        self.server_close()

    def user_texts(self, index: int = -1) -> list[str]:
        """The user messages of one chat request, as the model read them."""

        return [str(m.get("content")) for m in self.requests[index]["messages"] if m.get("role") == "user"]


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        self._send("application/json", json.dumps({"object": "list", "data": [{"id": "test-model"}]}).encode())

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if not self.path.endswith("/chat/completions"):  # the client's context-length probe (/api/show)
            self.send_error(404)
            return
        self.server.requests.append(body)
        self.server.entered.set()
        if self.server.hold:
            self.server.release.wait(60)
        text, finish = self.server.reply(body)
        base = {"id": "r", "object": "chat.completion.chunk", "created": 1, "model": "test-model"}
        rows = [{**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": text},
                                      "finish_reason": None}]},
                {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                 "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}}]
        try:
            self._send("text/event-stream", ("".join("data: " + json.dumps(r) + "\n\n" for r in rows)
                                             + "data: [DONE]\n\n").encode())
        except OSError:
            pass  # the stopped turn hung up

    def _send(self, kind, data):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Running:
    """One call running on its own thread; ``result`` once :meth:`join` returns."""

    def __init__(self, call: Callable[[], Any]) -> None:
        self.result: Any = None
        self.error: BaseException | None = None

        def _run() -> None:
            try:
                self.result = call()
            except BaseException as exc:  # the test reads it
                self.error = exc

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()

    def join(self, timeout: float = 60) -> Any:
        self.thread.join(timeout)
        assert not self.thread.is_alive(), "the turn is still running"
        if self.error is not None:
            raise self.error
        return self.result


def operator_params(instance: str, root: str, turn_request_id: str, *, persona: str, workspace: str) -> dict:
    return dict(install_id=ensure_install_identity(paths.store_root()).install_id, persona_id=persona,
                persona_instance_id=instance, workspace_id=workspace, session_id=root,
                client_scope=OWNER, turn_request_id=turn_request_id)


def operator_call(method: str, params: dict, *, interrupt_operator: Callable[[str], bool] = lambda turn: False) -> dict:
    """One ``runtime.operator.conversation.*`` request through the dispatcher, as the console sends it.

    ``interrupt_operator`` is the serve's in-flight table; a turn the runtime started is never in it.
    """

    context = serve_rpc.RpcContext(interrupt_operator=interrupt_operator)
    return serve_rpc.handle_request(dict(jsonrpc="2.0", id="rig", method=f"runtime.operator.conversation.{method}",
                                         params=params), context)
