"""What a chat turn tells the outside: event-log publishes and the protocol-v2 chat frame emitter.

Separate because it is the turn's only output channel — projection, metadata
and send-refused events, and the ``_ChatProtocolV2Emitter`` that writes frames.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Callable, Final, Mapping
import json
import sys
import time
import uuid
from agent_runtime.cli_format import emit_json
from agent_runtime.events import EventLog
from agent_runtime.mission_chat_turns import (
    MissionChatTurnPersistOutcome,
    TURN_STATE_PROJECTED,
    mission_chat_turn_record,
    transition_mission_chat_turn,
)
from agent_runtime.models import Event
from agent_runtime.persona_assignments import safe_assignment_text, safe_assignment_token
from hermes_time import now

__layer__ = "stores"
__all__ = [
    "_ChatProtocolV2Emitter",
    "_mission_chat_emit",
    "_publish_persona_chat_metadata_event",
    "_publish_persona_chat_projection_event",
    "_publish_persona_chat_send_refused_event",
]


def _publish_persona_chat_projection_event(
    *,
    session_id: str,
    client_message_id: str,
    turn_id: str,
    persona_id: str,
    persona_instance_id: str,
    active_session_id: str | None,
    native_revision: str | None,
) -> bool:
    """Notify stream consumers after the durable chat projection commits.

    The journal bit makes normal retries exactly-once. Event append deliberately
    precedes the bit: a crash between the two can duplicate a harmless rebuild
    notification, while the opposite order could permanently hide a committed
    reply from a running Launcher stream.
    """

    record = mission_chat_turn_record(
        session_id=session_id,
        client_message_id=client_message_id,
    ) or {}
    if record.get("state") != TURN_STATE_PROJECTED or record.get(
        "projection_event_emitted"
    ):
        return False
    try:
        EventLog().append(
            Event(
                type="persona_chat.projected",
                # Chat is the only lane (contract 45): a chat turn has no task
                # binding to report, so this is a constant rather than an
                # argv-sourced value that could only ever be None.
                task_id=None,
                run_id=None,
                persona_id=persona_id or None,
                ts=now(),
                payload={
                    "persona_instance_id": persona_instance_id,
                    "root_chat_session_id": session_id,
                    "active_session_id": active_session_id or session_id,
                    "client_message_id": client_message_id,
                    "turn_id": turn_id,
                    "native_revision": native_revision,
                    "change_kind": "projection_committed",
                },
                session_id=session_id,
                turn_id=turn_id,
            )
        )
    except Exception:
        # The reply is already durable. Leave the marker false so an
        # idempotent replay repairs the missed notification.
        return False
    outcome = transition_mission_chat_turn(
        session_id=session_id,
        client_message_id=client_message_id,
        turn_id=turn_id,
        state=TURN_STATE_PROJECTED,
        metadata={"projection_event_emitted": True},
        elements=record.get("elements") or [],
    )
    return outcome is MissionChatTurnPersistOutcome.PERSISTED


def _publish_persona_chat_metadata_event(
    *,
    session_id: str,
    persona_id: str,
    persona_instance_id: str,
) -> bool:
    """Notify stream consumers that SessionDB-only chat metadata changed."""

    try:
        EventLog().append(
            Event(
                type="persona_chat.metadata_updated",
                # See the projection event above: chat turns carry no task
                # binding under contract 45.
                task_id=None,
                run_id=None,
                persona_id=persona_id or None,
                ts=now(),
                payload={
                    "persona_instance_id": persona_instance_id,
                    "root_chat_session_id": session_id,
                    "change_kind": "auto_title_updated",
                },
                session_id=session_id,
            )
        )
        return True
    except Exception:
        return False


def _publish_persona_chat_send_refused_event(
    *,
    session_id: str,
    client_message_id: str | None,
    persona_id: str | None,
    persona_instance_id: str | None,
    error_kind: str,
    lease_owner: dict | None = None,
) -> bool:
    """Record that an operator send was REFUSED before any turn write happened.

    The refusal lanes are the one turn outcome with no durable trace by
    construction: every durable write a mission-chat turn performs lives inside
    ``_mission_chat_commit_turn``, under the chat-root lease, so a send refused
    on the way to that lease writes no operator row, no turn record, and no
    event. The 2026-08-09 investigation went looking for a message the operator
    had definitely sent and found it in exactly zero persistence surfaces —
    history, live log, and turn journal all showed only the turn that was
    holding the lease. A lost operator message was, by design, undiagnosable.

    This is the counter-record. It is deliberately a FACT ABOUT a send, not a
    copy of one:

    * ``client_message_id`` is the idempotency key the operator's client already
      owns, so a refused send can be correlated with the retry that eventually
      landed (or the absence of one) without the text ever leaving the client.
    * the message TEXT is not here and must never be added. Operator text has
      exactly two sanitising chokepoints — the chat persistence path and the
      live-log mirror — and both sit inside the lease this branch never took.
      Writing raw text here would put unsanitised operator prose into
      ``events.jsonl``, which is read by the snapshot/read-model pipeline and
      shipped to every consumer of it. ``error_kind`` plus the identity keys is
      what makes a loss diagnosable; the prose is what makes it a leak.
    * ``lease_owner`` is reduced to pid/kind/acquired_at. The sidecar is
      operator-written JSON read off disk best-effort; only the three scalar
      fields are copied so an oversized or attacker-shaped sidecar cannot ride
      into the payload (events are byte-capped, and a rejected append here would
      lose the very record this exists to keep).

    Returns True when the row landed. Never raises: a refusal that additionally
    failed to record is still a refusal, and the caller's typed envelope must
    reach the client unchanged.

    Registered as ``persona_chat.send_refused``. The first caller was the
    ``chat_busy`` branch — the refusal the incident produced and the only one
    that is genuinely transient. ``_cmd_mission_chat_message``'s three other
    pre-lease guards (``unknown_chat_session``, ``foreign_chat_session``,
    ``retired_persona_instance`` — the explicit-session ownership fences and
    the retired-target pre-flight/mint-race arms) are terminal and
    operator-visible by other means, but a caller cannot tell a terminal
    refusal from a transient one without first correlating it, so they are
    routed through here too: every pre-lease refusal costs one call site and
    leaves the same durable trace.
    """

    owner = lease_owner if isinstance(lease_owner, dict) else {}
    payload = {
        "root_chat_session_id": session_id,
        "client_message_id": safe_assignment_token(client_message_id) or None,
        "error_kind": str(error_kind),
        "persona_instance_id": safe_assignment_token(persona_instance_id) or None,
        "lease_owner_pid": owner.get("pid") if isinstance(owner.get("pid"), int) else None,
        "lease_owner_kind": safe_assignment_token(owner.get("observer_kind")) or None,
        "lease_acquired_at": (
            owner.get("acquired_at") if isinstance(owner.get("acquired_at"), (int, float)) else None
        ),
    }
    try:
        EventLog().append(
            Event(
                type="persona_chat.send_refused",
                # See the projection event above: chat turns carry no task
                # binding under contract 45.
                task_id=None,
                run_id=None,
                persona_id=safe_assignment_token(persona_id) or None,
                ts=now(),
                payload=payload,
                session_id=session_id,
            )
        )
        return True
    except Exception:
        return False


def _mission_chat_emit(args, data, plain=None, *, stream=None) -> None:
    """THE one place a mission-chat turn payload leaves this handler.

    Every terminal payload — refusal, replay, blocker, reply — goes out through
    here, so an in-process caller can take the payload DICT instead of scraping
    it back out of stdout.

    Why that matters, and why it is a seam rather than a convention: the
    agent-to-agent relay (``tools/agent_chat_tool.agent_chat_send``) invoked
    this handler in-process under ``contextlib.redirect_stdout`` and then parsed
    the captured text back into JSON. ``redirect_stdout`` rebinds
    ``sys.stdout`` PROCESS-GLOBALLY, so two concurrent relays — which is exactly
    what a detached ``wait: false`` dispatch introduces — would interleave into
    one buffer and, worse, briefly steal the serve process's own stdout
    protocol from every other thread. Handing the caller the dict removes the
    capture entirely.

    ``args.payload_sink`` (absent on every argparse Namespace, so the CLI and
    the serve bridge are untouched) is the seam. When it is present the payload
    is handed over and NOTHING is printed: the caller owns the transport, and a
    nested reply must never land in the OUTER turn's stdout capture. When it is
    absent this prints byte-for-byte what each call site printed before.

    ``plain`` is the non-JSON console line; ``None`` keeps the historical
    ``data["error"]``. ``stream`` overrides the ``args.stream`` read for the one
    site that had already resolved it into a local.
    """

    sink = getattr(args, "payload_sink", None)
    if callable(sink):
        sink(data)
        return
    streaming = getattr(args, "stream", False) if stream is None else stream
    if streaming:
        _emit_chat_final(data)
    else:
        print(emit_json(data) if args.json else (data["error"] if plain is None else plain))


def _emit_chat_final(payload: dict[str, object]) -> None:
    data = dict(payload)
    data["type"] = "chat.final"
    sys.stdout.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _emit_chat_frame(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


# Streamed delta chunks arrive far faster than the turn store can absorb full
# locked rewrites (O(file size) per persist). Delta-driven on_update flushes
# are therefore debounced to at most one per interval; segment boundaries,
# tool events, and the handler-owned write-ahead/terminal persists stay
# immediate and unthrottled.
_CHAT_TURN_INCREMENTAL_FLUSH_INTERVAL_SECONDS = 0.25


class _ChatProtocolV2Emitter:
    """Mission Control chat stream protocol v2 — the ONLY delta wire shape.

    C8 retired the legacy ``chat.delta`` lane (ruling 0: one shape per token);
    callers still emit the terminal ``chat.final`` envelope themselves. These
    v2 frames carry the one ordering authority: ``turn_id`` (the turn anchor,
    minted from ``client_message_id``) plus a per-turn element ``seq``.
    """

    def __init__(
        self,
        *,
        turn_id: str | None,
        client_message_id: str | None,
        on_update=None,
        emit_frames: bool = True,
        clock=time.monotonic,
        turn_phases=None,
    ):
        import contextvars as _contextvars
        import threading as _threading

        safe_turn = safe_assignment_token(turn_id) or f"turn_{uuid.uuid4().hex[:12]}"
        self.turn_id = safe_turn
        self.client_message_id = safe_assignment_text(client_message_id, limit=200) or None
        self._on_update = on_update
        self._emit_frames = bool(emit_frames)
        # The turn's phase timeline, or None for callers that do not keep one
        # (tests, and any future emitter user outside the chat handler). The
        # emitter takes exactly ONE mark from it — `provider_first_byte` — and
        # never reads a mark back.
        self._turn_phases = turn_phases
        # Guard for that mark, and the reason the cost of this whole plan is
        # per-turn rather than per-token: `delta()` runs once per delta, and
        # this boolean is all it costs after the first one. `TurnPhaseMarks`
        # enforces first-mark-wins on its own side too — belt and braces,
        # because a guard at the call site is not a property anything can
        # assert, and the mark rides a worker thread.
        self._provider_first_byte_marked = False
        # Streaming deltas fire from the provider's worker thread. Under
        # `harness serve` the stdout proxy tags each line with a request-id
        # ContextVar that new threads do NOT inherit, so frames written from
        # the worker thread went out with id=null and the Launcher's
        # per-request frame router dropped them — the console showed nothing
        # until turn end. Capture the request context here (handler thread,
        # request id set) and emit every frame inside it; the lock keeps the
        # single Context from being entered concurrently (RuntimeError).
        self._turn_context = _contextvars.copy_context()
        self._emit_lock = _threading.Lock()
        # Debounce bookkeeping only — element timing fields keep using
        # time.monotonic directly so an injected test clock cannot skew them.
        self._clock = clock
        self._last_on_update_flush: float | None = None
        self._finishing = False
        self._finished = False
        self._seq = 0
        self._started_at = time.monotonic()
        self._current_segment: dict[str, object] | None = None
        self._segment_count = 0
        self._tool_count = 0
        self._active_tools: dict[str, list[dict[str, object]]] = {}
        self.elements: list[dict[str, object]] = []
        self._emit_chat_frame(
            {
                "type": "turn.start",
                "protocol_version": 2,
                "turn_id": self.turn_id,
                "client_message_id": self.client_message_id,
            }
        )

    def delta(self, delta: str | None) -> None:
        if not delta:
            return
        if not self._provider_first_byte_marked:
            # FIRST provider byte this process has seen. Marked here rather
            # than inside the provider client because this is the earliest site
            # the turn owns, and the plan explicitly declines provider-client
            # surgery for it. An empty delta is not a byte — the guard above
            # already returned.
            self._provider_first_byte_marked = True
            if self._turn_phases is not None:
                self._turn_phases.mark("provider_first_byte")
        segment = self._ensure_segment()
        text = str(delta)
        segment["text"] = str(segment.get("text") or "") + text
        self._emit_chat_frame(
            {
                "type": "segment.delta",
                "protocol_version": 2,
                "turn_id": self.turn_id,
                "seq": segment["seq"],
                "id": segment["id"],
                "text": text,
            }
        )
        self._notify_update(immediate=False)

    def progress(self, payload: dict[str, object] | None) -> None:
        if not isinstance(payload, dict):
            return
        handler = _PROGRESS_EVENTS.get(str(payload.get("type") or "run.progress"))
        if handler is None:
            return
        self.end_segment(state="settled")
        handler(self, payload)
        self._notify_update()

    def end_segment(self, *, state: str = "settled") -> None:
        segment = self._current_segment
        if segment is None:
            return
        segment["state"] = state
        segment["duration_ms"] = _elapsed_ms(segment.get("started_at"))
        self._emit_chat_frame(
            {
                "type": "segment.end",
                "protocol_version": 2,
                "turn_id": self.turn_id,
                "seq": segment["seq"],
                "id": segment["id"],
                "state": state,
                "duration_ms": segment["duration_ms"],
            }
        )
        self._current_segment = None
        self._notify_update()

    def finish(
        self,
        *,
        state: str,
        input_tokens: object = None,
        output_tokens: object = None,
        total_tokens: object = None,
    ) -> None:
        # Idempotent: a crash-path caller may reach finish() after the success
        # path already finished — a second turn.end frame would corrupt the
        # stream protocol. on_update is suppressed for the whole finish window:
        # the caller's terminal persist is the single settling write, and an
        # extra incremental "running" persist here would race it.
        if self._finished:
            return
        self._finished = True
        self._finishing = True
        try:
            self.end_segment(state="settled" if state == "completed" else state)
            self._emit_chat_frame(
                {
                    "type": "turn.end",
                    "protocol_version": 2,
                    "turn_id": self.turn_id,
                    "state": state,
                    "duration_ms": _elapsed_ms(self._started_at),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                }
            )
        finally:
            self._finishing = False

    def _ensure_segment(self) -> dict[str, object]:
        if self._current_segment is not None:
            return self._current_segment
        self._seq += 1
        self._segment_count += 1
        segment = {
            "turn_id": self.turn_id,
            "seq": self._seq,
            "id": f"{self.turn_id}_seg_{self._segment_count}",
            "kind": "segment",
            "seg_type": "answer" if self._tool_count else "plan",
            "state": "streaming",
            "text": "",
            "started_at": time.monotonic(),
        }
        segment["ttft_ms"] = _elapsed_ms(self._started_at)
        self._current_segment = segment
        self.elements.append(segment)
        self._emit_chat_frame(
            {
                "type": "segment.start",
                "protocol_version": 2,
                "turn_id": self.turn_id,
                "seq": segment["seq"],
                "id": segment["id"],
                "seg_type": segment["seg_type"],
                "ttft_ms": segment["ttft_ms"],
            }
        )
        # No on_update here: the only caller is delta(), which notifies right
        # after appending its text — flushing before the append would burn the
        # debounce window on an empty segment.
        return segment

    def _tool_started(self, payload: dict[str, object]) -> None:
        self._seq += 1
        self._tool_count += 1
        name = _tool_name_from_progress(payload)
        command = _safe_stream_text(payload.get("command_full")) or _safe_stream_text(
            payload.get("command_label")
        )
        tool = {
            "turn_id": self.turn_id,
            "seq": self._seq,
            "id": f"{self.turn_id}_tool_{self._tool_count}",
            "kind": "tool",
            "name": name,
            "state": "started",
            "args": _safe_stream_text(payload.get("summary")),
            "command": command,
            "status": _safe_stream_text(payload.get("status")),
            "summary": _safe_stream_text(payload.get("summary")),
        }
        # Generic input record (already scrubbed/bounded at the progress sink).
        # Block-preserving: key-per-line structure is the rendering contract.
        tool_input = _safe_stream_block(payload.get("tool_input"), limit=1200)
        if tool_input:
            tool["tool_input"] = tool_input
        self.elements.append(tool)
        self._active_tools.setdefault(name, []).append(tool)
        self._emit_chat_frame(
            {
                "type": "tool.started",
                "protocol_version": 2,
                "turn_id": self.turn_id,
                "seq": tool["seq"],
                "id": tool["id"],
                "name": name,
                "args": _safe_stream_text(payload.get("summary")),
                "command": command,
                "tool_input": tool.get("tool_input"),
            }
        )

    def _match_started_tool(self, name: str, payload: dict[str, object]) -> dict[str, object] | None:
        """Which STARTED element this finished event belongs to.

        Measured defect (turn-efficiency plan bucket f, Stage 6): two tools of
        the same name started concurrently and this matched by NAME alone, then
        `pop()`ed — LIFO. So finish-A landed on the element started SECOND and
        finish-B on the element started first, and because a finished payload's
        `tool_input` overrides the started one, the elements came out crossed:
        `[0]`'s summary naming one skill while its `tool_input` named the other,
        and `[1]` the reverse. Two `skill_view` calls, two `read_file` calls and
        two more `read_file` calls all landed that way in one live turn record.

        The plan said "key by tool-call id". **There is no tool-call id here**:
        the runner's progress contract is `(event, tool_name, invocation,
        result)` (`agent_runtime/profile_runner.py`
        `_progress_payload_from_callback`) and carries no identifier at all. The
        identity that DOES reach both events is the invocation itself — rendered
        to the `tool_input` block for most tools, and to `command_full` /
        `command_label` for the terminal class, whose `tool_input` is
        deliberately suppressed against the event cap. So the match is on those,
        in that order.

        The fallback when neither side carries an identity is FIFO, not the old
        LIFO: concurrent starts of one tool finish in start order often enough
        that arrival order is the better guess, and it is the guess that was
        measurably wrong before.
        """
        pending = self._active_tools.get(name) or []
        if not pending:
            return None
        finished_command = _safe_stream_text(payload.get("command_full")) or _safe_stream_text(
            payload.get("command_label")
        )
        identities = (
            ("tool_input", _safe_stream_block(payload.get("tool_input"), limit=1200)),
            ("command", finished_command),
        )
        for field, value in identities:
            if not value:
                continue
            for index, candidate in enumerate(pending):
                if candidate.get(field) == value:
                    return pending.pop(index)
        return pending.pop(0)

    def _tool_finished(self, payload: dict[str, object]) -> None:
        name = _tool_name_from_progress(payload)
        tool = self._match_started_tool(name, payload)
        if tool is None:
            self._seq += 1
            self._tool_count += 1
            tool = {
                "turn_id": self.turn_id,
                "seq": self._seq,
                "id": f"{self.turn_id}_tool_{self._tool_count}",
                "kind": "tool",
                "name": name,
            }
            self.elements.append(tool)
        tool["state"] = "finished"
        tool["status"] = _safe_stream_text(payload.get("status")) or "ok"
        tool["duration_ms"] = payload.get("duration_ms")
        files = payload.get("changed_files") or payload.get("files_touched") or []
        if isinstance(files, list):
            tool["files"] = [safe_assignment_text(item, limit=240) for item in files if safe_assignment_text(item, limit=240)]
        # Carry-through started command if the finished payload omits it.
        command = (
            _safe_stream_text(payload.get("command_full"))
            or _safe_stream_text(payload.get("command_label"))
            or tool.get("command")
        )
        if command:
            tool["command"] = command
        detail = _safe_stream_text(payload.get("detail"))
        if detail:
            tool["detail"] = detail
        output = _safe_stream_text(payload.get("output"), limit=8000)
        if output:
            tool["output"] = output
        exit_code = _safe_exit_code_value(payload.get("exit_code"))
        if exit_code is not None:
            tool["exit_code"] = exit_code
        # T7: the todo tool's structured checklist rides the finished event so the
        # operator console can render it (the store is otherwise in-memory only).
        # Producer-bounded already (profile_runner `_todo_state_payload`); the
        # turn-store re-bounds it in `_safe_elements`.
        # T9d: carry an explicit EMPTY list too (`isinstance(...)`, not
        # `and todo_state`) — a cleared checklist emits `todo_state: []`, which the
        # launcher resolver distinguishes from absence to clear the panel. A
        # non-todo tool never carries the key (the producer returns None for it).
        todo_state = payload.get("todo_state")
        if isinstance(todo_state, list):
            tool["todo_state"] = todo_state
        # Generic input/result record (scrubbed/bounded at the progress sink;
        # block-preserving). Input carries through from the started element when
        # the finished payload omits it, mirroring the command carry-through.
        tool_input = _safe_stream_block(payload.get("tool_input"), limit=1200) or tool.get("tool_input")
        if tool_input:
            tool["tool_input"] = tool_input
        # Patch observability: the local diff artifact's path (same
        # `_safe_stream_text` grade `command` rides — paths survive it) plus the
        # +/− counts and the grammar. Scrubbed and bounded at the progress sink;
        # this is the live-turn carrier of the same four fields the snapshot
        # lane carries, so a streaming tile and a reloaded one agree.
        patch_artifact = _safe_stream_text(payload.get("patch_artifact"), limit=500)
        if patch_artifact:
            tool["patch_artifact"] = patch_artifact
        for count_key in ("patch_adds", "patch_dels"):
            count = payload.get(count_key)
            if isinstance(count, int) and not isinstance(count, bool):
                tool[count_key] = count
        patch_mode = _safe_stream_text(payload.get("patch_mode"), limit=20)
        if patch_mode:
            tool["patch_mode"] = patch_mode
        self._emit_chat_frame(
            {
                "type": "tool.finished",
                "protocol_version": 2,
                "turn_id": self.turn_id,
                "seq": tool["seq"],
                "id": tool["id"],
                "name": name,
                "status": tool["status"],
                "duration_ms": tool.get("duration_ms"),
                "files": tool.get("files") or [],
                "command": tool.get("command"),
                "detail": tool.get("detail"),
                "output": tool.get("output"),
                "exit_code": tool.get("exit_code"),
                "tool_input": tool.get("tool_input"),
                "tool_result": tool.get("tool_result"),
                **({"todo_state": tool["todo_state"]} if "todo_state" in tool else {}),
                # Absent-when-absent, like todo_state: a non-patch tool never
                # carries these keys at all, so the launcher's "no affordance"
                # branch is reached by absence rather than by a null sentinel.
                **{
                    key: tool[key]
                    for key in ("patch_artifact", "patch_adds", "patch_dels", "patch_mode")
                    if key in tool
                },
            }
        )

    def _notify_update(self, *, immediate: bool = True) -> None:
        # Debounced (immediate=False) callers are the streamed-delta path:
        # they flush at most once per interval. Segment boundaries and tool
        # events flush immediately — they are rare and carry the trace
        # visibility operators debug from. A delta suppressed here is never
        # lost: `elements` accumulates in place, so the next flush of any
        # flavor (interval, boundary, tool, terminal) carries the full text.
        if self._on_update is None or self._finishing:
            return
        now = self._clock()
        if not immediate:
            last = self._last_on_update_flush
            if last is not None and (now - last) < _CHAT_TURN_INCREMENTAL_FLUSH_INTERVAL_SECONDS:
                return
        self._last_on_update_flush = now
        try:
            self._on_update(self)
        except Exception:
            pass

    def ack(self, trace_payload: dict | None) -> None:
        """Presentation-only pre-trace acknowledgment frame (C8).

        The moment the model commits to a tool path, the console gets a typed
        ``turn.ack`` v2 frame carrying the canned "about to work" copy. It is
        NEVER durable: not an element, not a turn-store flush, not a SessionDB
        row — live content supersedes it and replay never shows it. When
        frames are suppressed (non-stream turns) this is a no-op.
        """
        if not isinstance(trace_payload, dict):
            return
        from agent_runtime.transcript_order import pre_trace_ack_text

        self._emit_chat_frame(
            {
                "type": "turn.ack",
                "protocol_version": 2,
                "turn_id": self.turn_id,
                "text": pre_trace_ack_text(trace_payload),
            }
        )

    def _emit_chat_frame(self, payload: dict[str, object]) -> None:
        if not self._emit_frames:
            return
        with self._emit_lock:
            self._turn_context.run(_emit_chat_frame, payload)



#: The protocol-v2 progress vocabulary: a trace payload's ``type`` -> the
#: emitter method that renders it as a tool element. Every other type is not a
#: tool element and is ignored. Dispatched through the instance, so a method
#: replaced on one emitter is the one that runs.
_PROGRESS_EVENTS: Final[Mapping[str, Callable[[_ChatProtocolV2Emitter, dict[str, object]], None]]] = MappingProxyType(
    {
        "run.tool.started": lambda emitter, payload: emitter._tool_started(payload),
        "run.tool.finished": lambda emitter, payload: emitter._tool_finished(payload),
    }
)

def _safe_stream_text(value: object, *, limit: int = 800) -> str | None:
    return safe_assignment_text(value, limit=limit) or None


def _safe_stream_block(value: object, *, limit: int) -> str | None:
    """Newline-PRESERVING stream text for the tool input/result record.

    ``safe_assignment_text`` whitespace-collapses, which would fold the
    key-per-line block (the rendering contract for the console's Input/Result
    dropdowns) into one unreadable line. The value was already secret-scrubbed
    and bounded at the progress sink; this only re-bounds and strips NULs."""

    text = str(value or "").replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return None
    if len(text) > limit:
        text = f"{text[:limit]}\n…(rest truncated)…"
    return text


def _safe_exit_code_value(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _elapsed_ms(started_at: object) -> int | None:
    try:
        started = float(started_at)
    except Exception:
        return None
    return max(0, int((time.monotonic() - started) * 1000))


def _tool_name_from_progress(payload: dict[str, object]) -> str:
    return safe_assignment_token(payload.get("tool_name") or payload.get("tool")) or "tool"
