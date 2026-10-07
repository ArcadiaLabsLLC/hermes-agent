"""The chat stream's ``tool.progress`` heartbeat: a live tool is running, not hung.

Between ``tool.started`` and ``tool.finished`` the protocol-v2 stream used to say
nothing at all. A 160-second ``flutter build`` that printed nothing reached the
operator as a card frozen on "running" for the whole wait — indistinguishable
from a wedged command, and from a client that had stopped listening (hermes
``runtime-queue.md`` RW3; live receipts in RW5's commit). While any tool element
of a streamed turn is live, this beats every :data:`TOOL_HEARTBEAT_SECONDS`:

``{"type": "tool.progress", "protocol_version": 2, "turn_id", "seq", "id",
"name", "tool_call_id", "elapsed_ms", "timeout_seconds", "pid",
"seconds_since_output", "output_chars", "output_tail"}``

``"progress_state", "progress", "progress_total", "progress_message",
"progress_phase", "expected_ms", "seconds_since_progress", "progress_updates"}``

``pid`` .. ``output_tail`` are the foreground command the call is blocked on,
joined by the live-turn registry on the tool's worker thread — ``null`` for a
tool that runs no foreground command. ``output_tail`` is bounded, ANSI-stripped
and secret-masked by the same operator filter the finished frame's ``output``
uses.

The ``progress_*`` fields are an MCP call's server-reported progress
(``notifications/progress`` for the ``_meta.progressToken`` hermes sends on
``tools/call``; :mod:`tools.mcp_progress_relay`), joined the same way:

- ``progress_state``: ``"reported"`` once the server has sent at least one
  notification for this call; ``"none_reported"`` for an MCP call whose server
  has sent none (the beat still goes out — the console says "no progress
  reported"); ``null`` for a tool that is not an MCP call.
- ``progress`` / ``progress_total``: the newest notification's numbers, as the
  server sent them (``progress_total`` ``null`` when it sent none).
- ``progress_message``: its ``message``, ANSI-stripped, secret-masked, at most
  :data:`TOOL_PROGRESS_MESSAGE_CHARS`.
- ``progress_phase`` / ``expected_ms``: the ``phase`` (string) and
  ``expected_ms`` (expected total duration, integer ms) a server states in the
  notification's ``_meta`` — at its top level or under one vendor key (the
  launcher QA server's ``_meta.stagec_qa_build``); ``null`` when never stated.
  The newest stated value is kept.
- ``seconds_since_progress``: seconds since the newest notification.
- ``progress_updates``: how many notifications this call has received (``0``
  with ``"none_reported"``).

The newest report rides the next beat, so the console sees a report at most
:data:`TOOL_HEARTBEAT_SECONDS` after the server sent it; ``elapsed_ms`` is the
call's own clock either way.

One daemon thread per turn, started by the first live tool and ended by the
turn's ``finish``; frames go out through the emitter's own locked writer, so a
beat can never interleave with a delta or enter the request context twice.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from agent_runtime import live_turns
from agent_runtime.profile_runner.operator_redaction import _safe_operator_output

__layer__ = "stores"
__all__ = [
    "TOOL_HEARTBEAT_SECONDS",
    "TOOL_PROGRESS_MESSAGE_CHARS",
    "TOOL_PROGRESS_TAIL_CHARS",
    "ToolHeartbeat",
    "tool_progress_frame",
]

#: Beat interval. Small enough that "no beat for 15 s" reads as a dead stream
#: to a client, large enough that a three-minute build costs ~36 frames.
TOOL_HEARTBEAT_SECONDS = 5.0
#: The tail a beat carries, after the operator filter's own line/char bounds.
TOOL_PROGRESS_TAIL_CHARS = 1200
#: The bound on an MCP server's progress ``message``, after the operator filter.
TOOL_PROGRESS_MESSAGE_CHARS = 400


def _strip_ansi(text: str) -> str:
    try:
        from tools.ansi_strip import strip_ansi

        return strip_ansi(text)
    except Exception:
        return text


def _bounded_tail(text: str) -> str:
    masked = _safe_operator_output("terminal", {"output": _strip_ansi(text or "")}) or ""
    return masked[-TOOL_PROGRESS_TAIL_CHARS:]


def _bounded_message(text: str | None) -> str | None:
    if text is None:
        return None
    masked = _safe_operator_output("terminal", {"output": _strip_ansi(text)}) or ""
    return masked[:TOOL_PROGRESS_MESSAGE_CHARS]


def _mcp_progress_fields(progress: Any) -> dict[str, Any]:
    """The ``progress_*`` frame fields for a call's ``McpProgress`` (all null for None)."""

    if progress is None:
        return {
            "progress_state": None,
            "progress": None,
            "progress_total": None,
            "progress_message": None,
            "progress_phase": None,
            "expected_ms": None,
            "seconds_since_progress": None,
            "progress_updates": None,
        }
    return {
        "progress_state": "reported" if progress.reported else "none_reported",
        "progress": progress.progress,
        "progress_total": progress.total,
        "progress_message": _bounded_message(progress.message),
        "progress_phase": progress.phase,
        "expected_ms": progress.expected_ms,
        "seconds_since_progress": progress.seconds_since_update,
        "progress_updates": progress.updates,
    }


def tool_progress_frame(turn_id: str, element: dict[str, Any], call: Any) -> dict[str, Any]:
    """One beat for one live tool element; ``call`` is its ``LiveToolCall`` or None."""

    started = element.get("started_mono")
    elapsed_ms = int(max(0.0, time.monotonic() - started) * 1000) if isinstance(started, float) else None
    foreground = getattr(call, "foreground", None)
    timeout = element.get("timeout_seconds")
    if foreground is not None and foreground.timeout_seconds is not None:
        # The command's ACTUAL deadline, as ``execute`` armed it, outranks the
        # started frame's planned one.
        timeout = int(foreground.timeout_seconds)
    return {
        "type": "tool.progress",
        "protocol_version": 2,
        "turn_id": turn_id,
        "seq": element.get("seq"),
        "id": element.get("id"),
        "name": element.get("name"),
        "tool_call_id": element.get("tool_call_id"),
        "elapsed_ms": elapsed_ms,
        "timeout_seconds": timeout if isinstance(timeout, int) else None,
        "pid": foreground.pid if foreground is not None else None,
        "seconds_since_output": foreground.seconds_since_output if foreground is not None else None,
        "output_chars": foreground.output_chars if foreground is not None else None,
        "output_tail": _bounded_tail(foreground.tail) if foreground is not None else None,
        **_mcp_progress_fields(getattr(call, "mcp_progress", None)),
    }


class ToolHeartbeat:
    """Beats turn liveness and live tool progress until the turn settles."""

    def __init__(self, emitter: Any, *, interval: float = TOOL_HEARTBEAT_SECONDS) -> None:
        self._emitter = emitter
        self._interval = float(interval)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def ensure_running(self) -> None:
        with self._lock:
            if self._stop.is_set() or (self._thread is not None and self._thread.is_alive()):
                return
            self._thread = threading.Thread(
                target=self._run, name=f"chat-tool-heartbeat-{self._emitter.turn_id}", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def beat(self) -> int:
        """Emit one beat per live tool element now; returns how many went out."""

        self._emitter._emit_chat_frame({
            "type": "turn.progress", "protocol_version": 2,
            "turn_id": self._emitter.turn_id,
            "elapsed_ms": int(max(0.0, time.monotonic() - self._emitter._started_at) * 1000),
            "next_heartbeat_after_ms": int(self._interval * 1000),
        })
        live = [
            element for element in list(self._emitter.elements)
            if element.get("kind") == "tool" and element.get("state") == "started"
        ]
        if not live:
            return 0
        view = live_turns.live_turn_view(self._emitter.turn_id)
        calls = {call.call_id: call for call in (view.tools if view is not None else ())}
        for element in live:
            frame = tool_progress_frame(self._emitter.turn_id, element, calls.get(element.get("tool_call_id")))
            self._emitter._emit_chat_frame(frame)
        return len(live)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.beat()
            except Exception:
                # A beat is presentation: a failed read must not end the turn's stream.
                continue
