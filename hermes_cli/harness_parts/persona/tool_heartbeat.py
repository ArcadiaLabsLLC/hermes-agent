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

The last four are the foreground command the call is blocked on, joined by the
live-turn registry on the tool's worker thread — ``null`` for a tool that runs
no foreground command. ``output_tail`` is bounded, ANSI-stripped and
secret-masked by the same operator filter the finished frame's ``output`` uses.

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
__all__ = ["TOOL_HEARTBEAT_SECONDS", "TOOL_PROGRESS_TAIL_CHARS", "ToolHeartbeat", "tool_progress_frame"]

#: Beat interval. Small enough that "no beat for 15 s" reads as a dead stream
#: to a client, large enough that a three-minute build costs ~36 frames.
TOOL_HEARTBEAT_SECONDS = 5.0
#: The tail a beat carries, after the operator filter's own line/char bounds.
TOOL_PROGRESS_TAIL_CHARS = 1200


def _strip_ansi(text: str) -> str:
    try:
        from tools.ansi_strip import strip_ansi

        return strip_ansi(text)
    except Exception:
        return text


def _bounded_tail(text: str) -> str:
    masked = _safe_operator_output("terminal", {"output": _strip_ansi(text or "")}) or ""
    return masked[-TOOL_PROGRESS_TAIL_CHARS:]


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
    }


class ToolHeartbeat:
    """Beats ``tool.progress`` for an emitter's live tool elements until stopped."""

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

    def _retire_if_idle(self) -> bool:
        """End the thread when nothing is live, re-checked under the arming lock
        so a tool started between the empty beat and here is never left unbeaten."""

        with self._lock:
            if any(
                element.get("kind") == "tool" and element.get("state") == "started"
                for element in list(self._emitter.elements)
            ):
                return False
            self._thread = None
            return True

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                if self.beat() == 0 and self._retire_if_idle():
                    return
            except Exception:
                # A beat is presentation: a failed read must not end the turn's stream.
                continue
