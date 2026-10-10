"""The serve's half of the busy-root send queue: stream a queued turn like a sent one.

A directly sent turn streams on its own request: every line the handler prints —
the protocol-v2 chat frames, then ``chat.final`` — reaches the requester as
``{"id": <rid>, "event": "line", "line": ...}``, and the request ends with
``{"id": <rid>, "event": "exit", "code": ...}``. A queued turn
(``agent_runtime.chat_root_send_runner``) has no request left: its own ended with
the "queued" answer. So it runs under a request id of its own,
``queued:<client_message_id>``, and its frames — the same frames, through the
same stdout proxy — go out on the CONTROL channel the settle push uses (the stdio
frame writer when a launcher reads it, and a broadcast to every authenticated
loopback connection). The chat frames carry ``client_message_id`` / ``turn_id``,
which is what ties them to the message the launcher shows as queued.
Contract: ``docs/agent-runtime-harness/planned/busy-root-queue-2026-10-10.md``.
"""

from __future__ import annotations

import contextlib
from typing import Any, Iterator

from hermes_cli.harness_parts.serve.frames import _request_id, _request_sink

__layer__ = "lanes"

__all__ = ["QueuedTurnStream", "queued_turn_runner_policy"]


class _ControlSink:
    """A request sink whose frames go out on the serve's control channel, and to the
    paired device that sent the send (``queued_turn_origin.queued_turn_peer``)."""

    __slots__ = ("_session", "_peer")

    def __init__(self, session: Any, peer: Any = None) -> None:
        self._session = session
        self._peer = peer

    def emit(self, frame: dict[str, Any]) -> None:
        self._session._deliver_control_frame(frame)
        if self._peer is not None:
            self._peer.emit(frame)


class QueuedTurnStream:
    """One queued turn's stream: its request id, its sink, its terminal frames."""

    def __init__(self, session: Any, rid: str, peer: Any = None) -> None:
        self.session = session
        self.rid = rid
        self.sink = _ControlSink(session, peer)

    def finish(self, exit_code: int, payload: dict | None) -> None:
        # The handler hands its terminal payload to the door's sink instead of
        # printing it, so ``chat.final`` is printed here — through the same
        # proxy, in this request's context — exactly once.
        if isinstance(payload, dict):
            from hermes_cli.harness_parts.persona.chat_events import _emit_chat_final

            _emit_chat_final(payload)
        self.session.stdout_proxy.flush_request(self.rid)
        self.session.stderr_proxy.flush_request(self.rid)
        self.sink.emit({"id": self.rid, "event": "exit", "code": int(exit_code)})


@contextlib.contextmanager
def _queued_turn_stream(session: Any, entry: Any) -> Iterator[QueuedTurnStream]:
    from agent_runtime.chat_root_send_runner import queued_request_id
    from agent_runtime.launcher_app_functions import bind_launcher_link, reset_launcher_link
    from hermes_cli.harness_parts.serve.queued_turn_origin import queued_turn_link, queued_turn_peer

    rid = queued_request_id(entry.client_message_id)
    stream = QueuedTurnStream(session, rid, queued_turn_peer(session, entry, rid))
    rid_token = _request_id.set(stream.rid)
    sink_token = _request_sink.set(stream.sink)
    link_token = bind_launcher_link(queued_turn_link(session, entry))
    try:
        yield stream
    finally:
        reset_launcher_link(link_token)
        _request_sink.reset(sink_token)
        _request_id.reset(rid_token)


def queued_turn_runner_policy(session: Any) -> Any:
    """The runner policy a serve starts its queued-send runner with."""

    from agent_runtime.chat_root_send_runner import RunnerPolicy

    return RunnerPolicy(stream=lambda entry: _queued_turn_stream(session, entry))
