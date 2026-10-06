"""The ``stream_gap_receipt``: where the first-event -> first-text gap goes (h-stream-gap, 2026-10-06).

**The question this answers.** On Neko turns of 2026-10-06 12:04-12:20 the
Codex stream's first parsed event and its first substantive progress were
2.9-5.0 s apart; at 01:25 the same model on the same input took 0.3-0.7 s.
That window holds three different things and only one is the provider's
silence: the provider sending nothing, the provider sending reasoning frames
that are not reply text, or this process holding bytes it already read (a
reader thread starved of the GIL, a slow parse). One summary line per streamed
request splits them.

**What is measured, and where.**

* *Byte arrival* -- a response event hook wraps the SSE response's
  ``httpx.SyncByteStream``; each chunk is stamped the moment the read returns
  in the consuming thread (the closest Python gets to the socket).
* *Parse* -- ``observe_stream_event`` is called from the Codex consume loop's
  ``on_event`` (one fork seam line in ``agent/codex_runtime.py``) when the SDK
  hands over a parsed event.
* *Read->parse lag* -- for each event, parse time minus the arrival of the
  latest chunk read before it: a LOWER bound on that event's lag (its bytes
  arrived no later than that chunk), so a large value is a real local delay.
  ``first_lag_ms`` is the window-opening event's own (on a cold process it
  carries the SDK's one-off event-model build, measured ~460 ms offline);
  ``max_lag_ms`` is the largest over the rest of the window, text included.
* *Stall probe* -- from the first event to the first output-text delta a daemon
  thread sleeps ``STALL_INTERVAL_S`` at a time and records how late it wakes.
  A starved reader cannot stamp its own late wake-up; the probe can.
* *Reasoning volume* -- the terminal event's ``usage.output_tokens`` and
  ``output_tokens_details.reasoning_tokens``, the reasoning-summary characters
  streamed, and ``gap_ms_per_reasoning_token``: a multi-second gap over a
  handful of reasoning tokens points away from model thinking.

All window times are milliseconds from the first parsed event.

**Cost and failure.** A few attribute writes per chunk and per event, one
short-lived thread per request, one ``INFO`` line per request. Every entry
point is fail-open: an instrument is never the reason a request fails.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

import httpx

__layer__ = "policy"

logger = logging.getLogger(__name__)

STREAM_GAP_RECEIPT = "stream_gap_receipt"
TEXT_DELTA_TYPE = "response.output_text.delta"
REASONING_SUMMARY_DELTA_TYPE = "response.reasoning_summary_text.delta"
TERMINAL_TYPES = frozenset({"response.completed", "response.incomplete", "response.failed"})
STALL_INTERVAL_S = 0.01
STALL_REPORT_FLOOR_MS = 50.0

_AGENT_ATTR = "_hermes_stream_gap_receipt"
_HOOK_MARK = "_hermes_stream_gap_hook"


def _field(obj: Any, name: str) -> Any:
    value = getattr(obj, name, None)
    if value is None and isinstance(obj, dict):
        value = obj.get(name)
    return value


class _StallProbe:
    """A sampler thread recording its own wake-up lateness until stopped."""

    def __init__(self, interval_s: float = STALL_INTERVAL_S) -> None:
        self.interval_s = interval_s
        self.samples = 0
        self.max_late_ms = 0.0
        self.late_over_floor_ms = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="stream-gap-stall-probe", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        clock = time.perf_counter
        while True:
            before = clock()
            if self._stop.wait(self.interval_s):
                return
            late_ms = max(0.0, (clock() - before - self.interval_s) * 1000.0)
            self.samples += 1
            self.max_late_ms = max(self.max_late_ms, late_ms)
            if late_ms >= STALL_REPORT_FLOOR_MS:
                self.late_over_floor_ms += late_ms


@dataclass
class StreamGapReceipt:
    """One streamed request's first-event -> first-text window."""

    clock: Callable[[], float] = time.perf_counter
    probe_factory: Callable[[], _StallProbe] | None = _StallProbe
    first_event_at: float | None = None
    text_at: float | None = None
    last_chunk_at: float | None = None
    text_chunk_at: float | None = None
    window_chunks: list[tuple[float, int]] = field(default_factory=list)
    kinds: Counter = field(default_factory=Counter)
    parse_ms: list[float] = field(default_factory=list)
    first_lag_ms: float | None = None
    max_lag_ms: float | None = None
    text_lag_ms: float | None = None
    reasoning_summary_chars: int = 0
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    end: str | None = None
    logged: bool = False
    probe: _StallProbe | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # -- byte side ---------------------------------------------------------
    def on_chunk(self, size: int) -> None:
        now = self.clock()
        self.last_chunk_at = now
        if self.first_event_at is not None and self.text_at is None:
            self.window_chunks.append((now, size))

    # -- parse side --------------------------------------------------------
    def on_event(self, event: Any) -> None:
        now = self.clock()
        kind = str(_field(event, "type") or "?")
        if kind == REASONING_SUMMARY_DELTA_TYPE:
            self.reasoning_summary_chars += len(str(_field(event, "delta") or ""))
        if kind in TERMINAL_TYPES:
            self._read_usage(_field(event, "response"))
        if self.text_at is not None:
            return
        lag_ms = None if self.last_chunk_at is None else max(0.0, (now - self.last_chunk_at) * 1000.0)
        if self.first_event_at is None:
            # The first event's lag is reported apart: it opens the window and,
            # on a cold process, carries the SDK's one-off event-model build.
            self.first_event_at, self.first_lag_ms = now, lag_ms
            if self.probe_factory is not None:
                self.probe = self.probe_factory()
                self.probe.start()
        elif lag_ms is not None:
            self.max_lag_ms = lag_ms if self.max_lag_ms is None else max(self.max_lag_ms, lag_ms)
        if kind == TEXT_DELTA_TYPE and _field(event, "delta"):
            self.text_at, self.text_lag_ms, self.end = now, lag_ms, "text"
            self.text_chunk_at = self.last_chunk_at
            if self.window_chunks and self.window_chunks[-1][0] == self.text_chunk_at:
                self.window_chunks.pop()  # the chunk that delivered the text closes the window
            self._stop_probe()
            return
        self.kinds[kind] += 1
        self.parse_ms.append((now - self.first_event_at) * 1000.0)

    def _read_usage(self, response: Any) -> None:
        usage = _field(response, "usage")
        if usage is None:
            return
        output = _field(usage, "output_tokens")
        details = _field(usage, "output_tokens_details")
        reasoning = _field(details, "reasoning_tokens") if details is not None else None
        self.output_tokens = int(output) if isinstance(output, (int, float)) else None
        self.reasoning_tokens = int(reasoning) if isinstance(reasoning, (int, float)) else None

    def _stop_probe(self) -> None:
        if self.probe is not None:
            self.probe.stop()

    # -- the line ----------------------------------------------------------
    def gap_ms(self) -> float | None:
        if self.first_event_at is None or self.text_at is None:
            return None
        return (self.text_at - self.first_event_at) * 1000.0

    def fields(self) -> dict[str, Any]:
        origin = self.first_event_at

        def rel(t: float | None) -> float | None:
            return None if t is None or origin is None else (t - origin) * 1000.0

        gap = self.gap_ms()
        per_token = None
        if gap is not None and self.reasoning_tokens:
            per_token = gap / self.reasoning_tokens
        probe = self.probe
        return {
            "end": self.end or "no_text",
            "gap_ms": gap,
            "events": sum(self.kinds.values()),
            "kinds": ",".join(f"{k}:{n}" for k, n in self.kinds.most_common()) or "-",
            "chunks": len(self.window_chunks),
            "bytes": sum(size for _t, size in self.window_chunks),
            "first_chunk_ms": rel(self.window_chunks[0][0]) if self.window_chunks else None,
            "last_chunk_ms": rel(self.window_chunks[-1][0]) if self.window_chunks else None,
            "text_chunk_ms": rel(self.text_chunk_at),
            "parse_first_ms": self.parse_ms[0] if self.parse_ms else None,
            "parse_last_ms": self.parse_ms[-1] if self.parse_ms else None,
            "first_lag_ms": self.first_lag_ms,
            "max_lag_ms": self.max_lag_ms,
            "text_lag_ms": self.text_lag_ms,
            "stall_samples": probe.samples if probe else None,
            "stall_max_ms": probe.max_late_ms if probe else None,
            "stall_over50_ms": probe.late_over_floor_ms if probe else None,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "reasoning_summary_chars": self.reasoning_summary_chars,
            "gap_ms_per_reasoning_token": per_token,
        }

    def line(self, *, request_id: Any = None, model: Any = None) -> str:
        def fmt(value: Any) -> str:
            if value is None:
                return "na"
            if isinstance(value, float):
                return f"{value:.1f}"
            return str(value)

        parts = [STREAM_GAP_RECEIPT, f"request={request_id or 'na'}", f"model={model or 'na'}"]
        parts += [f"{key}={fmt(value)}" for key, value in self.fields().items()]
        return " ".join(parts)

    def finish(self, *, end: str | None = None, request_id: Any = None, model: Any = None) -> str | None:
        with self._lock:
            if self.logged or self.first_event_at is None:
                self._stop_probe()
                return None
            self.logged = True
        self._stop_probe()
        if end is not None and self.end is None:
            self.end = end
        text = self.line(request_id=request_id, model=model)
        logger.info("%s", text)
        return text


class _TimedByteStream(httpx.SyncByteStream):
    """The response's own byte stream, with each read stamped on the receipt."""

    def __init__(self, inner: httpx.SyncByteStream, receipt: StreamGapReceipt) -> None:
        self._inner = inner
        self._receipt = receipt

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self._inner:
            try:
                self._receipt.on_chunk(len(chunk))
            except Exception:
                logger.debug("stream gap chunk stamp failed", exc_info=True)
            yield chunk

    def close(self) -> None:
        self._inner.close()


def _finish_agent_receipt(agent: Any, end: str) -> None:
    receipt = getattr(agent, _AGENT_ATTR, None)
    if isinstance(receipt, StreamGapReceipt):
        receipt.finish(end=end, request_id=getattr(agent, "_current_api_request_id", None),
                       model=getattr(agent, "model", None))


def begin_stream_gap_receipt(agent: Any, client: Any) -> None:
    """Open a fresh receipt for the request about to be sent and hook *client*. Never raises.

    A previous receipt that never saw its terminal event is logged first with
    ``end=abandoned`` (a retried or interrupted attempt keeps its record).
    """

    try:
        _finish_agent_receipt(agent, "abandoned")
        setattr(agent, _AGENT_ATTR, StreamGapReceipt())
        http_client = getattr(client, "_client", None)
        hooks = getattr(http_client, "event_hooks", None)
        if not isinstance(hooks, dict):
            return
        if any(getattr(hook, _HOOK_MARK, False) for hook in hooks.get("response", ())):
            return

        def _on_response(response: Any) -> None:
            try:
                receipt = getattr(agent, _AGENT_ATTR, None)
                content_type = str(response.headers.get("content-type", ""))
                stream = response.stream
                if (isinstance(receipt, StreamGapReceipt) and "text/event-stream" in content_type
                        and isinstance(stream, httpx.SyncByteStream)
                        and not isinstance(stream, _TimedByteStream)):
                    response.stream = _TimedByteStream(stream, receipt)
            except Exception:
                logger.debug("stream gap byte stamps not attached", exc_info=True)

        setattr(_on_response, _HOOK_MARK, True)
        http_client.event_hooks = {**hooks, "response": [*hooks.get("response", ()), _on_response]}
    except Exception:
        logger.debug("stream gap receipt install skipped", exc_info=True)


def observe_stream_event(agent: Any, event: Any) -> None:
    """Record one parsed SSE event; log the receipt on the terminal event. Never raises."""

    try:
        receipt = getattr(agent, _AGENT_ATTR, None)
        if not isinstance(receipt, StreamGapReceipt):
            return
        receipt.on_event(event)
        kind = _field(event, "type")
        if kind in TERMINAL_TYPES:
            _finish_agent_receipt(agent, "no_text")
    except Exception:
        logger.debug("stream gap event observe failed", exc_info=True)


__all__ = [
    "STREAM_GAP_RECEIPT",
    "StreamGapReceipt",
    "begin_stream_gap_receipt",
    "observe_stream_event",
]
