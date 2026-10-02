"""Server→client requests on the serve wire, settled by id on the asking sink.

The serve NDJSON wire carries requests in both directions. This is the lane
the runtime uses to ask a client something — today the Launcher's app
functions (:mod:`agent_runtime.launcher_app_functions`): each request is a
JSON-RPC frame with an ``lrq-<12 hex>`` id, answered by a response frame with
the same ``id``, which ``handle_message`` routes here through
:func:`resolve_response`. Ids never collide with the client's own.

Moved out of :mod:`agent_runtime.launcher_app_functions` (one module per
concern: this is the wire lane; that one is the Launcher's tools).
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Mapping

__layer__ = "stores"

__all__ = [
    "CLIENT_REQUESTS",
    "ClientRequestFailed",
    "ClientRequests",
    "is_response_frame",
    "resolve_response",
]

#: JSON-RPC code this side answers with when the Launcher never replied.
_NO_REPLY_CODE = -32000
#: The client has no handler for the method: as final as silence.
_METHOD_NOT_FOUND = -32601


class ClientRequestFailed(Exception):
    """The client answered with an error, or never answered."""

    def __init__(self, code: int, message: str, data: Any = None, *, timed_out: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data
        #: True when nothing answered at all (as opposed to an error reply).
        self.timed_out = timed_out


class _Pending:
    __slots__ = ("event", "frame", "sink")

    def __init__(self, sink: Any) -> None:
        self.sink = sink
        self.event = threading.Event()
        self.frame: dict[str, Any] | None = None


def is_response_frame(frame: Any) -> bool:
    """A JSON-RPC response: an ``id`` and a ``result``/``error``, and no ``method``."""

    return (
        isinstance(frame, dict)
        and "method" not in frame
        and "id" in frame
        and ("result" in frame or "error" in frame)
    )


class ClientRequests:
    """Server→client requests on the serve wire, settled by id on the asking sink."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open: dict[str, _Pending] = {}

    def request(self, sink: Any, method: str, params: Mapping[str, Any], *, timeout: float) -> dict[str, Any]:
        """Send one request on *sink* and wait for its result (a dict)."""

        request_id = f"lrq-{uuid.uuid4().hex[:12]}"
        pending = _Pending(sink)
        with self._lock:
            self._open[request_id] = pending
        try:
            sink.emit({"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)})
            answered = pending.event.wait(timeout)
        finally:
            with self._lock:
                self._open.pop(request_id, None)
        if not answered or pending.frame is None:
            raise ClientRequestFailed(_NO_REPLY_CODE, f"no reply to {method} within {timeout:g}s", timed_out=True)
        return _result_of(pending.frame)

    def resolve(self, frame: Mapping[str, Any], sink: Any) -> bool:
        """Settle the open request *frame* answers. False when nothing on *sink* waits for it."""

        request_id = frame.get("id")
        if not isinstance(request_id, str):
            return False
        with self._lock:
            pending = self._open.get(request_id)
            if pending is None or pending.sink is not sink:
                return False
            self._open.pop(request_id, None)
        pending.frame = dict(frame)
        pending.event.set()
        return True

    def open_count(self) -> int:
        with self._lock:
            return len(self._open)


def _result_of(frame: Mapping[str, Any]) -> dict[str, Any]:
    error = frame.get("error")
    if error is not None:
        body = error if isinstance(error, dict) else {}
        code = body.get("code")
        raise ClientRequestFailed(
            code if isinstance(code, int) else _NO_REPLY_CODE,
            str(body.get("message") or "the client answered with an error"),
            body.get("data"),
        )
    result = frame.get("result")
    return result if isinstance(result, dict) else {}


#: The one request lane of this process.
CLIENT_REQUESTS = ClientRequests()


def resolve_response(frame: Mapping[str, Any], sink: Any) -> bool:
    """Route one inbound response frame (``handle_message``'s entry point)."""

    return CLIENT_REQUESTS.resolve(frame, sink)
