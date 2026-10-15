"""``hermes harness stream`` in its own process RIDES the live serve's build.

A standalone ``harness stream`` used to build a full Mission Control core in its
own process. While a serve owns the same store that is a second (or third) cold
build of the same thing on the same box, and at launch it is worse than
redundant: on 2026-10-06 (agent.log 20:22–20:24:56, serve pid 40444) two argv
children the launcher spawned through a serve recycle built 31 s and 51 s each
in-process (``snapshot_build_core role=led caller=cli reason=hydrate
executor=in_process``) while the serve's own first build, which they starved,
took 70 s. The same cold build on an idle box takes ~24 s.

So a standalone process asks the serve instead, over the loopback socket's argv
lane — the same door ``harness query`` uses (``agent_runtime/harness_query/
serve_route.py``). The serve runs ``harness stream`` inside its own process,
where the hydrate rides whatever build is in flight (``role=rode``), and this
process copies the serve's ``line`` frames to stdout byte for byte. The stdout
contract is unchanged; only who pays for the core moves.

Inside the serve (``current_serve_request_id()`` is bound) the verb builds as it
always did: the serve IS the builder. With no live serve, or a serve that
refuses before the first line, this process builds in-process exactly as before
and a ``stream_relay`` receipt names why.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import uuid
from typing import Any, TextIO

__layer__ = "lanes"
__all__ = ["RELAY_CLIENT_NAME", "relay_stream_via_serve", "stream_relay_argv", "write_relay_line"]

_log = logging.getLogger("agent_runtime.stream.relay")

RELAY_CLIENT_NAME = "harness-stream-relay"

#: Bounds the DIAL and the hello only. Once the request is running the read waits
#: as long as the serve takes: a cold boot build is silent for a minute and more
#: on a ``--max-frames 1`` one-shot, which emits no liveness frames by design.
_DIAL_SECONDS = 10.0
#: An idle read lap, not a deadline: a lap that times out just reads again.
_READ_LAP_SECONDS = 30.0

_TERMINAL_EVENTS = frozenset({"exit", "error"})


def _this_pid() -> int:
    """This process's pid — one name, so the self-dial guard is testable."""

    return os.getpid()


def stream_relay_argv(args: Any) -> list[str]:
    """The argv the serve runs: this request's flags, spelled out in full."""

    argv = [
        "harness",
        "stream",
        "--poll-interval",
        repr(float(getattr(args, "poll_interval", 0.25) or 0.25)),
        "--heartbeat-interval",
        repr(float(getattr(args, "heartbeat_interval", 5.0) or 5.0)),
        "--delta-debounce-ms",
        str(int(getattr(args, "delta_debounce_ms", 200) or 0)),
    ]
    max_frames = getattr(args, "max_frames", None)
    if max_frames is not None:
        argv += ["--max-frames", str(int(max_frames))]
    if bool(getattr(args, "resync", False)):
        argv.append("--resync")
    fold_entities = getattr(args, "fold_entities", None)
    if fold_entities is not None:
        # ``--fold-entities=`` keeps the empty declaration ("I fold nothing")
        # distinct from the absent one, exactly as the parser does.
        argv.append(f"--fold-entities={fold_entities}")
    return argv


def _receipt(lane: str, **fields: Any) -> None:
    try:
        tail = " ".join(f"{key}={value}" for key, value in fields.items())
        _log.info("stream_relay lane=%s %s pid=%d", lane, tail, os.getpid())
    except Exception:  # noqa: BLE001 - an instrument never fails the verb
        pass


def write_relay_line(out: TextIO, line: str) -> bool:
    try:
        out.write(line + "\n")
        out.flush()
        return True
    except (BrokenPipeError, OSError, ValueError):
        return False


def relay_stream_via_serve(args: Any, *, out: TextIO | None = None) -> int | None:
    """Relay this ``harness stream`` request through the live serve.

    Returns the exit code to return, or ``None`` when this process must build
    in-process (no live serve, no token, a refusal before the first line).
    """

    from agent_runtime import paths
    from agent_runtime.serve_auth import read_token
    from agent_runtime.serve_socket.client import ServeSocketClient
    from agent_runtime.serve_socket.target import resolve_socket_target

    sink = sys.stdout if out is None else out
    store_root = paths.store_root()
    target = resolve_socket_target(store_root)
    if target is None:
        _receipt("in_process", serve_fallback="no_live_serve_socket")
        return None
    if target.pid is not None and int(target.pid) == _this_pid():
        # The serve itself, reached without a bound request id: relaying would
        # send the request back into this process, which would relay it again.
        _receipt("in_process", serve_fallback="self")
        return None
    token = read_token(store_root)
    if not token:
        _receipt("in_process", serve_fallback="no_auth_token")
        return None
    connection = ServeSocketClient(target.host, target.port, timeout_seconds=_DIAL_SECONDS)
    rid = f"stream-relay-{uuid.uuid4().hex[:12]}"
    relayed = 0
    try:
        try:
            connection.connect()
            hello = connection.hello(token=token, client=RELAY_CLIENT_NAME)
        except Exception as exc:  # noqa: BLE001 - any dial failure builds in-process, by name
            _receipt("in_process", serve_fallback=f"transport_failed:{type(exc).__name__}")
            return None
        if not isinstance(hello, dict) or hello.get("event") != "hello_ok":
            _receipt("in_process", serve_fallback="hello_rejected")
            return None
        connection.set_timeout(_READ_LAP_SECONDS)
        connection.send({"id": rid, "argv": stream_relay_argv(args)})
        _receipt("serve", serve_pid=target.pid, boot_id=target.boot_id, request=rid)
        while True:
            try:
                frame = connection.read_frame()
            except socket.timeout:  # noqa: UP041 - an idle lap, not a failure
                continue
            if frame is None:
                if relayed == 0:
                    _receipt("in_process", serve_fallback="serve_closed_connection")
                    return None
                _receipt("serve", ended="serve_closed_connection", lines=relayed)
                return 1
            if frame.get("id") != rid:
                continue
            event = frame.get("event")
            if event == "line":
                if not write_relay_line(sink, str(frame.get("line") or "")):
                    # The consumer is gone; closing the socket ends the serve's reader.
                    return 0
                relayed += 1
            elif event == "stderr":
                write_relay_line(sys.stderr, str(frame.get("line") or ""))
            elif event in _TERMINAL_EVENTS:
                error = frame.get("error")
                if error and relayed == 0:
                    _receipt("in_process", serve_fallback=f"refused:{error}")
                    return None
                if error:
                    _receipt("serve", ended=f"error:{error}", lines=relayed)
                    return 1
                return int(frame.get("code") or 0)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # noqa: BLE001 - a broken lane mid-stream ends the stream
        if relayed == 0:
            _receipt("in_process", serve_fallback=f"transport_failed:{type(exc).__name__}")
            return None
        _receipt("serve", ended=f"transport_failed:{type(exc).__name__}", lines=relayed)
        return 1
    finally:
        connection.close()
