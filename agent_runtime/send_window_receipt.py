"""The ``send_window_receipt``: where a request's send -> first-event time goes (h-send-window, 2026-10-06).

**The question this answers.** On the 2026-10-06 Neko turns the span from the
request leaving hermes (``request_sent``) to the provider's first response
headers read 0.6-2.4 s, and nothing on the record could say whether that was
this process (a reader starved of the GIL, a pool wait), the network (a cold
connect + TLS, the upload) or the provider. One summary line per streamed
request splits it.

**What is measured, and where.** Every time is milliseconds from the httpx
``request`` hook (``request start``: the client has the request in hand).

* *httpcore's own lifecycle* -- the trace callable
  (:func:`agent_runtime.transport_phase_trace.phase_trace_for`) forwards every
  event: ``connect_tcp`` and ``start_tls`` happen only on a NEW connection, so
  their absence is the pooled-connection receipt (``conn=reused``);
  ``send_request_headers.started`` -> ``send_request_body.complete`` is the
  upload; ``receive_response_headers.complete`` closes the provider's wait.
* *First byte* -- the response's byte stream is stamped at each read
  (:class:`agent_runtime.stream_gap_receipt._TimedByteStream`).
* *First event* -- the Codex consume loop's parsed-event seam.
* *Stall probe* -- the same sampler thread as the stream-gap receipt, running
  from request start to the first event: its wake-up lateness says whether
  this process (the GIL, the serve) stalled inside the window.

``wait_on`` is a heuristic comparing the largest observed local, network or
response interval. Local callbacks can overlap these durations: their measured
cost and deferred persistence are attribution receipts, never a subtraction from
network time. ``pool_ms`` is retained for compatibility and means time before
the first trace; ``pre_first_trace_ms`` names that observation precisely.

**Cost and failure.** A dict write per httpcore event, one short-lived thread
per request, one ``INFO`` line per request. Fail-open everywhere.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

__layer__ = "policy"

logger = logging.getLogger(__name__)

SEND_WINDOW_RECEIPT = "send_window_receipt"

#: httpcore trace event -> the stamp it sets (first occurrence wins). The
#: ``http11``/``http2`` prefix is folded away and kept as ``http=``.
_STAMPS: dict[str, str] = {
    "connection.connect_tcp.started": "connect_start",
    "connection.connect_tcp.complete": "connect_done",
    "connection.start_tls.started": "tls_start",
    "connection.start_tls.complete": "tls_done",
    "send_request_headers.started": "upload_start",
    "send_request_body.complete": "sent",
    "receive_response_headers.started": "receive_start",
    "receive_response_headers.complete": "headers",
}


@dataclass
class SendWindow:
    """One request's request-start -> first-parsed-event window."""

    clock: Callable[[], float] = time.perf_counter
    probe_factory: Callable[[], Any] | None = None
    started_at: float | None = None
    body_bytes: int | None = None
    http: str | None = None
    content_type: str | None = None
    first_trace_at: float | None = None
    stamps: dict[str, float] = field(default_factory=dict)
    first_byte_at: float | None = None
    first_event_at: float | None = None
    first_event_lag_ms: float | None = None
    probe: Any = None
    end: str | None = None
    callback_ms: float = 0.0
    callback_count: int = 0
    persist_ms: float | None = None
    logged: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def begin(self, request: Any) -> None:
        self.started_at = self.clock()
        try:
            length = request.headers.get("content-length")
            self.body_bytes = int(length) if length is not None else len(request.content)
        except Exception:
            self.body_bytes = None
        if self.probe_factory is not None:
            self.probe = self.probe_factory()
            self.probe.start()

    def on_trace(self, event_name: str) -> None:
        now = self.clock()
        if self.first_trace_at is None:
            self.first_trace_at = now
        name = event_name
        for prefix in ("http11.", "http2."):
            if event_name.startswith(prefix):
                self.http = self.http or ("1.1" if prefix == "http11." else "2")
                name = event_name[len(prefix):]
                break
        stamp = _STAMPS.get(name)
        if stamp is not None and stamp not in self.stamps:
            self.stamps[stamp] = now

    def on_first_event(self, lag_ms: float | None) -> None:
        if self.first_event_at is None:
            self.first_event_at, self.first_event_lag_ms = self.clock(), lag_ms
            self._stop_probe()

    def _stop_probe(self) -> None:
        if self.probe is not None:
            self.probe.stop()

    # -- the line ----------------------------------------------------------
    def fields(self) -> dict[str, Any]:
        origin = self.started_at
        stamps = self.stamps

        def rel(t: float | None) -> float | None:
            return None if t is None or origin is None else (t - origin) * 1000.0

        def span(a: float | None, b: float | None) -> float | None:
            return None if a is None or b is None else max(0.0, (b - a) * 1000.0)

        connect = span(stamps.get("connect_start"), stamps.get("connect_done"))
        tls = span(stamps.get("tls_start"), stamps.get("tls_done"))
        upload = span(stamps.get("upload_start"), stamps.get("sent"))
        server_wait = span(stamps.get("sent"), stamps.get("headers"))
        body_wait = span(stamps.get("headers"), self.first_byte_at)
        probe = self.probe
        stall_over = getattr(probe, "late_over_floor_ms", None) if probe else None
        shares = {
            "local": max(stall_over or 0.0, self.first_event_lag_ms or 0.0, self.callback_ms),
            "network": max(connect or 0.0, tls or 0.0, upload or 0.0),
            "server": max(server_wait or 0.0, body_wait or 0.0),
        }
        wait_on = max(shares, key=shares.get) if any(shares.values()) else None
        return {
            "end": self.end or "event",
            "conn": "new" if "connect_start" in stamps else ("reused" if stamps else None),
            "http": self.http,
            "body_bytes": self.body_bytes,
            "content_type": (self.content_type or "").split(";")[0].strip() or None,
            "pool_ms": rel(self.first_trace_at),  # compatibility: not pool acquisition
            "pre_first_trace_ms": rel(self.first_trace_at),
            "receive_start_ms": rel(stamps.get("receive_start")),
            "callback_ms": self.callback_ms if self.callback_count else None,
            "callback_count": self.callback_count or None,
            "deferred_persist_ms": self.persist_ms,
            "connect_ms": connect,
            "tls_ms": tls,
            "upload_ms": upload,
            "request_sent_ms": rel(stamps.get("sent")),
            "server_wait_ms": server_wait,
            "response_headers_ms": rel(stamps.get("headers")),
            "first_byte_ms": rel(self.first_byte_at),
            "first_event_ms": rel(self.first_event_at),
            "first_event_lag_ms": self.first_event_lag_ms,
            "stall_samples": probe.samples if probe else None,
            "stall_max_ms": probe.max_late_ms if probe else None,
            "stall_over50_ms": stall_over,
            "wait_on": wait_on,
            "wait_on_is_heuristic": True,
        }

    def line(self, *, request_id: Any = None, model: Any = None) -> str:
        from agent_runtime.stream_gap_receipt import receipt_value as fmt


        parts = [SEND_WINDOW_RECEIPT, f"request={request_id or 'na'}", f"model={model or 'na'}"]
        parts += [f"{key}={fmt(value)}" for key, value in self.fields().items()]
        return " ".join(parts)

    def finish(self, *, end: str | None = None, request_id: Any = None, model: Any = None) -> str | None:
        with self._lock:
            if self.logged or self.started_at is None:
                self._stop_probe()
                return None
            self.logged = True
        self._stop_probe()
        if end is not None and self.end is None:
            self.end = end
        text = self.line(request_id=request_id, model=model)
        logger.info("%s", text)
        return text


__all__ = ["SEND_WINDOW_RECEIPT", "SendWindow"]
