"""The two CLI entry points, ``_cmd_serve`` and ``_cmd_serve_connect``, and the stdio pipe claim.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from hermes_cli.harness_parts.serve.argv_lane import bind_harness_parser
from hermes_cli.harness_parts.serve.constants import (
    DEFAULT_POOL_SIZE,
)
from hermes_cli.harness_parts.serve.boot import (
    _prewarm_persona_chat_actors,
    _prewarm_provider_runtime,
    _prewarm_read_model_snapshot,
    install_harness_skills_at_boot,
)
from hermes_cli.harness_parts.serve.loop import (
    serve_loop,
)

__layer__ = "lanes"

__all__ = [
    "SERVE_CONNECT_NO_SERVICE_EXIT_CODE",
    "SERVE_CONNECT_REJECTED_EXIT_CODE",
    "SERVE_CONNECT_TRANSPORT_EXIT_CODE",
    "_claim_protocol_pipes",
    "_cmd_serve",
    "_cmd_serve_connect",
    "_raw_fd_lines",
]


def _raw_fd_lines(fd: int):
    """Yield lines from [fd] as they arrive on an OPEN interactive pipe.

    Reads the descriptor directly (``os.read`` returns per pipe write, lines
    are assembled manually) instead of iterating a text wrapper, so no stdio
    layer can buffer a request until EOF."""
    buffer = b""
    while True:
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            chunk = b""
        if not chunk:
            if buffer:
                yield buffer.decode("utf-8", errors="replace")
            return
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            yield line.decode("utf-8", errors="replace")


def _claim_protocol_pipes() -> tuple[int, int]:
    """Move the NDJSON protocol onto private descriptors and detach fd 0/1.

    Handlers spawn subprocesses (git for dirty state, proof runners, …) that
    inherit the standard descriptors. With serve's stdin pipe left on fd 0,
    any child that reads stdin blocks forever against the Launcher's open
    pipe — ``git status`` deadlocked the whole status handler (observed live
    2026-07-08; the piped smoke passed only because a closed pipe is
    instant EOF). A child writing raw output to an inherited fd 1 would
    likewise corrupt the frame stream. Serve therefore dups the protocol
    pipes to private fds and points fd 0 at the null device (children read
    EOF) and fd 1 at the null device (stray child writes vanish; every
    handler print already flows through the contextvar proxy)."""
    protocol_in = os.dup(0)
    protocol_out = os.dup(1)
    devnull_read = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull_read, 0)
    os.close(devnull_read)
    devnull_write = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull_write, 1)
    os.close(devnull_write)
    return protocol_in, protocol_out


def _cmd_serve(args, *, harness_parser: Callable[[Any], None] | None = None) -> int:
    """``hermes harness serve``. *harness_parser* is the harness's parser-tree
    builder, bound into the argv lane (``hermes_cli.harness`` passes it; a harness
    part may not import that module — W0-G6)."""

    # Started before anything else this command does: everything from process
    # creation up to here is the interpreter + hermes import tax, and it is the
    # single largest term in a cold boot.
    from agent_runtime.boot_timeline import BootTimeline

    timeline = BootTimeline()
    if not getattr(args, "ndjson", False):
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "unsupported_transport",
                    "detail": "hermes harness serve currently requires --ndjson (schema v1)",
                }
            )
        )
        return 2
    if getattr(args, "service", False) and getattr(args, "no_socket", False):
        # Refused rather than accepted-and-degraded, because what the
        # combination asks for is a process with no way in and no way out: a
        # service parks past stdin EOF, and the socket lane is the only lane a
        # ``drain`` can arrive on. On Windows there is not even a SIGTERM to
        # fall back to. The two flags each stay valid alone.
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "unsupported_combination",
                    "detail": (
                        "--service needs the socket lane: it is the only "
                        "transport a drain can reach a detached runtime on"
                    ),
                }
            )
        )
        return 2
    if harness_parser is not None:
        bind_harness_parser(harness_parser)
    protocol_in, protocol_out = _claim_protocol_pipes()
    writer = os.fdopen(protocol_out, "w", encoding="utf-8", newline="\n")
    # Function-local on purpose: this file is exec'd into harness.py's globals.
    from agent_runtime.root_anchor import publish_store_root_anchor

    def _wake_reader() -> None:
        """Unblock a reader parked on an idle protocol pipe after a drain.

        Closing the descriptor makes the in-progress (or next) ``os.read``
        fail, which ``_raw_fd_lines`` already treats as end-of-stream. The
        second close in the ``finally`` below is a harmless no-op.
        """

        try:
            os.close(protocol_in)
        except OSError:
            pass

    try:
        return serve_loop(
            _raw_fd_lines(protocol_in),
            writer,
            pool_size=getattr(args, "pool_size", DEFAULT_POOL_SIZE)
            or DEFAULT_POOL_SIZE,
            boot_timeline=timeline,
            snapshot_prewarm=_prewarm_read_model_snapshot,
            # The production wiring for both warmups. The provider one is
            # injected here rather than hardcoded in the loop (EG-3.2): it is
            # policy, it now runs BEHIND the read-model build on one thread, and
            # a loop unit test must not import the OpenAI SDK to observe a ready
            # frame.
            provider_prewarm=_prewarm_provider_runtime,
            # Third and last on that one thread. Injected here for the same
            # reason the provider warmup is: it is policy, and a loop unit test
            # must not construct a persona agent to observe a ready frame.
            actor_prewarm=_prewarm_persona_chat_actors,
            root_anchor=publish_store_root_anchor,
            # The installed-skill join. ON here and nowhere else, the same
            # contract as ``root_anchor`` beside it and for a sharper version of
            # the same reason: this one WRITES into the machine's shared skills
            # root, so a ``serve_loop`` unit test must never be able to fire it.
            skill_install=install_harness_skills_at_boot,
            drain_wakeup=_wake_reader,
            # ``os._exit``, not ``sys.exit``: after a drain TIMEOUT the
            # interpreter cannot be trusted to come down at all — the
            # concurrent.futures atexit hook joins worker threads, and the
            # stuck ones are precisely why the deadline fired. Every frame is
            # flushed at emit, so nothing observable is lost.
            hard_exit=os._exit,
            # The durable service's transport. ON here and nowhere else: every
            # ``serve_loop`` unit test observes the byte-identical stdio loop
            # unless it asks for the socket by name.
            socket_lane=not getattr(args, "no_socket", False),
            # L-h. ON only when the operator (or the launcher) says so: the
            # default serve is still the launcher's stdio child and still dies
            # with the pipe it was born on.
            service=getattr(args, "service", False),
            # RL-16. ON here and nowhere else, the same contract as
            # ``root_anchor`` and ``skill_install`` beside it: arming it
            # registers an atexit hook and signal handlers on THIS process, and
            # this is the only caller whose process is the runtime.
            record_end_reason=True,
        )
    finally:
        try:
            writer.flush()
        except Exception:
            pass
        try:
            os.close(protocol_in)
        except OSError:
            pass


# ── the first real client ────────────────────────────────────────────────────
#
# ``harness serve connect`` is the operator/agent lane onto the socket: it
# resolves the root's live service from the registry, performs the mandatory
# hello, and prints what it got as JSON. It exists for three reasons, in order
# of importance:
#
# 1. A transport with no client is a transport nobody has proven. This performs
#    the REAL handshake against the REAL auth token over the REAL socket.
# 2. ``--drain`` gives the durable service its restart verb from the outside —
#    the thing slice 2 could describe but could not exercise, because a drain
#    over stdio ends the only connection that could observe it.
# 3. It is the shape the Launcher's client will mirror when it migrates.

#: Nothing LIVE to connect to for this root — either no registered socket
#: service at all, or one the registry classified as anything other than
#: ``live``. Both are "do not connect", and the second is the more important
#: one: a serve's port outlives the serve, so a dead entry names an address
#: some other local process may now be answering on.
SERVE_CONNECT_NO_SERVICE_EXIT_CODE = 4
#: The service is there; this client could not authenticate to it.
SERVE_CONNECT_REJECTED_EXIT_CODE = 5
#: The connection itself failed (refused, timed out, died mid-handshake).
SERVE_CONNECT_TRANSPORT_EXIT_CODE = 6


def _emit_connect_report(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, default=str, indent=2))


def _connect_refusal(store_root: Any, target: Any, token: Any) -> tuple[dict[str, Any] | None, int]:
    """The FIRST reason this client will not dial *target*, and its exit code; ``(None, 0)`` to proceed.

    Three refusals, in the order a caller can fix them: no socket service is
    registered, the one registered is not ``live``, or this root has no token.
    """

    if target is None:
        return {
            "ok": False,
            "error": "no_socket_service",
            "detail": (
                "no live serve with a socket transport is registered for this "
                "runtime root"
            ),
            "runtime_root": str(store_root),
        }, SERVE_CONNECT_NO_SERVICE_EXIT_CODE
    if not target.live:
        # The half of the credential-disclosure defect that lives on the client.
        # A registry row classified ``stale_dead_pid`` names a port whose owner
        # is gone, and a local port is reusable the moment its owner dies — so
        # connecting here means handshaking with whatever took it over. That is
        # not a theory: with the old raw-token hello, an impostor listening on a
        # dead serve's port harvested the real token. The token no longer
        # travels, and this connect still refuses, by name.
        return {
            "ok": False,
            "error": "socket_service_not_live",
            "classification": target.classification,
            "detail": (
                "the only socket service registered for this runtime root is "
                f"classified {target.classification!r}, not 'live'; its port may "
                "now belong to another process, so this client will not "
                "handshake with it"
            ),
            "runtime_root": str(store_root),
            "target": target.payload(),
        }, SERVE_CONNECT_NO_SERVICE_EXIT_CODE
    if not token:
        # Fails CLOSED, and says which side is missing: a client with no token
        # cannot authenticate, and pretending otherwise would send a hello that
        # can only ever be rejected.
        return {
            "ok": False,
            "error": "no_auth_token",
            "detail": "this runtime root has no serve auth token to present",
            "runtime_root": str(store_root),
            "target": target.payload(),
        }, SERVE_CONNECT_REJECTED_EXIT_CODE
    return None, 0


#: The frames that END a drain as seen from the client (a held-open
#: ``drain_timeout`` with ``terminal: false`` is progress, not an ending).
_DRAIN_TERMINAL_EVENTS: frozenset[str] = frozenset(
    {"drain_complete", "drain_timeout", "drain_abandoned", "drain_in_progress"}
)


def _is_held_deadline(frame: dict[str, Any]) -> bool:
    """A deadline lapse HELD OPEN by a chat turn in flight: the service is still
    serving and will re-arm, so this is progress, not an ending. Reading it as
    terminal would report a restart that has not happened."""

    return frame.get("event") == "drain_timeout" and frame.get("terminal") is False


def _drain_over(connection: Any, deadline: Any) -> dict[str, Any]:
    """Ask for the drain and read to its TERMINAL frame; the report's drain keys."""

    # ``force`` is mandatory on the socket lane — this verb IS the
    # deliberate operator restart, so it says so rather than being
    # refused by the service it is trying to replace.
    request: dict[str, Any] = {"op": "drain", "force": True}
    if deadline is not None:
        request["deadline_seconds"] = float(deadline)
    connection.send(request)
    # Read to the TERMINAL frame, not to the first one: the drain's
    # evidence (what it refused, what it completed) is on the terminal
    # frame, and a client that stopped at ``draining`` would report a
    # restart it never watched finish.
    observed: list[dict[str, Any]] = []
    while True:
        frame = connection.read_frame()
        if frame is None:
            break
        observed.append(frame)
        if frame.get("event") in _DRAIN_TERMINAL_EVENTS and not _is_held_deadline(frame):
            break
    return {
        "drain": observed,
        "drain_outcome": observed[-1].get("event") if observed else "no_frames",
        "drain_deadline_holds": len([frame for frame in observed if _is_held_deadline(frame)]),
    }


def _handshake(connection: Any, report: dict[str, Any], token: str, client_build: Any) -> int | None:
    """The hello; the refusal's exit code, or ``None`` once ``hello_ok`` is in the report."""

    from agent_runtime.serve_socket import ServeHelloProtocolError

    try:
        hello = connection.hello(
            token=token, client=report["client"], client_build=client_build
        )
    except ServeHelloProtocolError as exc:
        # Either the peer refused us before the challenge (its typed reason
        # is the answer) or what is on this port does not speak this
        # contract. Neither is a case for sending a credential anyway.
        report["error"] = (
            "hello_rejected" if exc.reason else "hello_contract_mismatch"
        )
        report["detail"] = exc.detail
        report["reason"] = exc.reason
        report["hello"] = exc.frame
        return SERVE_CONNECT_REJECTED_EXIT_CODE
    report["server_hello"] = connection.server_hello
    report["hello"] = hello
    if not isinstance(hello, dict) or hello.get("event") != "hello_ok":
        report["error"] = (
            "hello_rejected" if isinstance(hello, dict) else "no_hello_reply"
        )
        return SERVE_CONNECT_REJECTED_EXIT_CODE
    # L-h item 3, lifted to the TOP of the report rather than left to be
    # dug out of the greeting: "is the thing I just reached a durable
    # service, and who started it" is the first question an operator
    # running this verb has, and the second is what they should type to
    # stop it. Read off the hello this connection actually completed, so
    # it cannot disagree with the frame printed below it. ``None`` when the
    # service predates the field — never guessed as False, which would say
    # "this runtime dies with its starter" about a runtime that does not.
    report["service"] = hello.get("service")
    report["starter_pid"] = hello.get("starter_pid")
    return None


def _cmd_serve_connect(args) -> int:
    from agent_runtime import paths
    from agent_runtime.build_stamp import build_stamp
    from agent_runtime.serve_auth import read_token
    from agent_runtime.serve_socket import (
        HELLO_CONTRACT_VERSION,
        ServeHelloProtocolError,
        ServeSocketClient,
        resolve_socket_target,
    )

    store_root = paths.store_root()
    # ``allow_stale`` is asked for so the REFUSAL can name what it refused —
    # not so a non-live target can be used. Discovery itself returns live rows
    # only; this call is the diagnostic form, and the check below is the gate.
    target = resolve_socket_target(store_root, allow_stale=True)
    token = read_token(store_root) if target is not None and target.live else None
    refusal, code = _connect_refusal(store_root, target, token)
    if refusal is not None:
        _emit_connect_report(refusal)
        return code
    client_build = build_stamp().commit
    report: dict[str, Any] = {
        "ok": False,
        "runtime_root": str(store_root),
        "target": target.payload(),
        "client": getattr(args, "client", None) or "harness-serve-connect",
        "client_build": client_build,
        # Which handshake this client speaks. Stated in the report because the
        # next client of this lane is the Launcher, and "which contract did the
        # thing that worked use" must not be archaeology.
        "hello_contract": HELLO_CONTRACT_VERSION,
    }
    timeout = float(getattr(args, "timeout", 10.0) or 10.0)
    connection = ServeSocketClient(target.host, target.port, timeout_seconds=timeout)
    try:
        connection.connect()
    except OSError as exc:
        report["error"] = "connect_failed"
        report["detail"] = type(exc).__name__
        _emit_connect_report(report)
        return SERVE_CONNECT_TRANSPORT_EXIT_CODE
    try:
        refused = _handshake(connection, report, token, client_build)
        if refused is not None:
            _emit_connect_report(report)
            return refused
        if getattr(args, "probe", False):
            connection.send({"op": "version"})
            report["version"] = connection.read_frame()
        if getattr(args, "drain", False):
            report.update(_drain_over(connection, getattr(args, "deadline_seconds", None)))
        report["ok"] = True
        _emit_connect_report(report)
        return 0
    except OSError as exc:
        report["error"] = "transport_failed"
        report["detail"] = type(exc).__name__
        _emit_connect_report(report)
        return SERVE_CONNECT_TRANSPORT_EXIT_CODE
    except ServeHelloProtocolError as exc:  # pragma: no cover - defensive
        report["error"] = "hello_contract_mismatch"
        report["detail"] = exc.detail
        _emit_connect_report(report)
        return SERVE_CONNECT_REJECTED_EXIT_CODE
    finally:
        connection.close()
