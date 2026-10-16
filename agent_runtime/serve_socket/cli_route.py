"""One CLI-to-serve route: relay a ``harness …`` argv to the live serve, with one fallback rule.

Plan: ``docs/agent-runtime-harness/planned/cli-serve-route-2026-10-15.md``. Before this
module two callers each carried the same dial/auth/hello/frame loop
(``harness_query.serve_route.query_via_serve`` and
``hermes_cli.harness_parts.persona.chat_serve_route.relay_send_via_serve``), and each
decided for itself when a failure meant "run it here instead". Now there is one loop,
:func:`relay_argv`, returning a typed :class:`RelayOutcome`, and one rule,
:meth:`RelayOutcome.runs_locally`, keyed by the caller's :class:`FallbackPolicy`:

* ``READ`` — any failure runs the verb locally (a read cannot split anything).
* ``WRITE`` — only NO live serve runs it locally (no socket target, or this process is
  the serve; the store's own lock then guards the write). A live serve that could not be
  reached, refused the request, timed out or failed mid-request is a non-zero exit with
  the reason, never a local run: a write the serve does not see, or a double write.
* ``TURN_HANDOFF`` — ``mission-chat message``'s documented rule: before the argv is sent
  the turn may still run here; once it is sent the turn is the serve's and is never
  re-run here.
"""

from __future__ import annotations

import os
import socket
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

__layer__ = "lanes"

__all__ = [
    "FallbackPolicy",
    "RelayKind",
    "RelayOutcome",
    "relay_argv",
]


class FallbackPolicy(str, Enum):
    READ = "read"
    WRITE = "write"
    TURN_HANDOFF = "turn_handoff"


class RelayKind(str, Enum):
    #: The serve ran the argv; ``code`` is its exit code.
    SERVED = "served"
    #: No live serve for this root (no socket target), or this process IS the serve.
    NO_SERVE = "no_serve"
    #: A live serve exists but nothing was sent: no auth token, dial or hello failed.
    UNREACHED = "unreached"
    #: The argv was sent and the request ended without an exit: an error frame, a
    #: draining refusal, a closed connection or a broken lane.
    REFUSED = "refused"


#: The frames that end one request. ``draining`` answers a request the serve will not run.
_TERMINAL_EVENTS = frozenset({"exit", "error", "draining"})


@dataclass(frozen=True, slots=True)
class RelayOutcome:
    kind: RelayKind
    reason: str = ""
    code: int | None = None
    lines: tuple[str, ...] = ()
    request_id: str = ""
    pid: int | None = None
    boot_id: str | None = None

    def runs_locally(self, policy: FallbackPolicy) -> bool:
        """The one fallback rule (module docstring). ``SERVED`` never runs locally."""

        if self.kind is RelayKind.SERVED:
            return False
        if policy is FallbackPolicy.READ:
            return True
        if policy is FallbackPolicy.TURN_HANDOFF:
            return self.kind in (RelayKind.NO_SERVE, RelayKind.UNREACHED)
        return self.kind is RelayKind.NO_SERVE


def _this_pid() -> int:
    """This process's pid — one name, so the self-dial guard is testable."""

    return os.getpid()


def relay_argv(
    argv: Sequence[str],
    *,
    client: str,
    sink: Callable[[str], Any] | None = None,
    err_sink: Callable[[str], Any] | None = None,
    dial_seconds: float = 10.0,
    read_lap_seconds: float | None = None,
    request_prefix: str = "relay",
    on_sent: Callable[[str], Any] | None = None,
    self_pid: Callable[[], int] | None = None,
) -> RelayOutcome:
    """Send *argv* to this root's live serve and read its reply to the end.

    ``sink`` receives each ``line`` frame as it arrives (then the outcome carries no
    lines); without one the lines are collected on the outcome. ``err_sink`` receives
    ``stderr`` frames. ``read_lap_seconds`` turns the read into idle laps — a lap that
    times out reads again, for a request that may run as long as it runs; without it the
    ``dial_seconds`` timeout bounds every read and a timeout is a ``REFUSED`` outcome.
    ``on_sent`` is called with the request id the moment the argv is on the wire.
    ``self_pid`` answers "which process am I" for the self-dial guard (default: this pid).
    ``KeyboardInterrupt`` propagates to the caller, which owns what a detach means.
    """

    from agent_runtime import paths
    from agent_runtime.serve_auth import read_token
    from agent_runtime.serve_socket.client import ServeSocketClient
    from agent_runtime.serve_socket.target import resolve_socket_target

    store_root = paths.store_root()
    target = resolve_socket_target(store_root)
    if target is None:
        return RelayOutcome(RelayKind.NO_SERVE, "no_live_serve_socket")
    pid, boot_id = target.pid, target.boot_id
    if pid is not None and int(pid) == (self_pid or _this_pid)():
        return RelayOutcome(RelayKind.NO_SERVE, "this_process_is_the_serve", pid=pid, boot_id=boot_id)
    token = read_token(store_root)
    if not token:
        return RelayOutcome(RelayKind.UNREACHED, "no_auth_token", pid=pid, boot_id=boot_id)
    connection = ServeSocketClient(target.host, target.port, timeout_seconds=dial_seconds)
    rid = f"{request_prefix}-{uuid.uuid4().hex[:12]}"
    try:
        try:
            connection.connect()
            # No client_build: computing the stamp shells out to git (2.9 s measured
            # 2026-10-01); the serve answers ``None`` (not comparable) for a client
            # that names none.
            hello = connection.hello(token=token, client=client)
        except Exception as exc:  # noqa: BLE001 - every dial failure is a typed outcome
            return RelayOutcome(RelayKind.UNREACHED, f"transport_failed:{type(exc).__name__}",
                                request_id=rid, pid=pid, boot_id=boot_id)
        if not isinstance(hello, dict) or hello.get("event") != "hello_ok":
            return RelayOutcome(RelayKind.UNREACHED, "hello_rejected", request_id=rid, pid=pid, boot_id=boot_id)
        if read_lap_seconds is not None:
            connection.set_timeout(read_lap_seconds)
        try:
            connection.send({"id": rid, "argv": [str(item) for item in argv]})
        except Exception as exc:  # noqa: BLE001 - a send that may have landed is not "unreached"
            return RelayOutcome(RelayKind.REFUSED, f"transport_failed:{type(exc).__name__}",
                                request_id=rid, pid=pid, boot_id=boot_id)
        if on_sent is not None:
            on_sent(rid)
        return _read_to_end(connection, rid, sink=sink, err_sink=err_sink,
                            idle_laps=read_lap_seconds is not None, pid=pid, boot_id=boot_id)
    finally:
        connection.close()


def _read_to_end(
    connection: Any,
    rid: str,
    *,
    sink: Callable[[str], Any] | None,
    err_sink: Callable[[str], Any] | None,
    idle_laps: bool,
    pid: int | None,
    boot_id: str | None,
) -> RelayOutcome:
    lines: list[str] = []

    def refused(reason: str) -> RelayOutcome:
        return RelayOutcome(RelayKind.REFUSED, reason, lines=tuple(lines), request_id=rid, pid=pid, boot_id=boot_id)

    while True:
        try:
            frame = connection.read_frame()
        except socket.timeout as exc:  # noqa: UP041 - an idle lap on a long request, else a real timeout
            if idle_laps:
                continue
            return refused(f"transport_failed:{type(exc).__name__}")
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 - a broken lane after the send
            return refused(f"transport_failed:{type(exc).__name__}")
        if frame is None:
            return refused("serve_closed_connection")
        if frame.get("id") != rid:
            continue
        event = frame.get("event")
        if event == "line":
            text = str(frame.get("line") or "")
            if sink is None:
                lines.append(text)
            else:
                sink(text)
        elif event == "stderr":
            if err_sink is not None:
                err_sink(str(frame.get("line") or ""))
        elif event in _TERMINAL_EVENTS:
            if event == "draining":
                return refused("serve_draining")
            error = frame.get("error")
            if error:
                return refused(str(error))
            return RelayOutcome(RelayKind.SERVED, code=int(frame.get("code") or 0), lines=tuple(lines),
                                request_id=rid, pid=pid, boot_id=boot_id)
