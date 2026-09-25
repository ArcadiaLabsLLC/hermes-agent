"""The argv lane: one request's record, the harness parser, and ``dispatch_argv`` with
its three typed exits (RL-24).
"""

from __future__ import annotations

import argparse
import threading
import time
from typing import Any, Callable

from hermes_cli.harness_parts.serve.constants import (
    _CHAT_TURN_COMMANDS,
    _LONG_RUN_COMMANDS,
)

__layer__ = "lanes"

__all__ = [
    "HarnessParserUnbound",
    "bind_harness_parser",
    "ARGV_ROOT",
    "ArgvRootUnsupported",
    "HandlerExit",
    "_ArgvRequest",
    "_build_harness_parser",
    "_clean_argv_root",
    "_system_exit_code",
    "dispatch_argv",
]


class _ArgvRequest:
    __slots__ = (
        "rid",
        "argv",
        "is_chat_turn",
        "is_long_run",
        "is_runtime_stream",
        "cancel_event",
        "key",
        "owner",
        "sink",
        "turn_request_id",
        "submitted_monotonic",
        "started_monotonic",
        "progress_monotonic",
    )

    def __init__(
        self,
        rid: str,
        argv: list[str],
        *,
        owner: str = "stdio",
        sink: Any = None,
        turn_request_id: str | None = None,
    ):
        self.rid = rid
        self.argv = argv
        tail = argv[1:] if argv and argv[0] == "harness" else argv
        self.is_chat_turn = any(
            tuple(tail[: len(shape)]) == shape for shape in _CHAT_TURN_COMMANDS
        )
        #: A generate verb that runs for minutes. Derived from the same argv
        #: tail, by the same prefix match, so the two marks cannot disagree
        #: about where a command name starts — and a sibling flag rather than a
        #: `holds_drain` union because the drain frame reports the two
        #: separately: an operator asking why a restart is waiting needs to know
        #: WHICH kind of work is holding it, and the counts have different
        #: cures (a chat turn ends in seconds; a generation may be fifteen
        #: minutes from done).
        self.is_long_run = any(
            tuple(tail[: len(shape)]) == shape for shape in _LONG_RUN_COMMANDS
        )
        self.is_runtime_stream = bool(tail and tail[0] == "stream")
        self.cancel_event = threading.Event()
        #: Which connection asked. ``stdio`` for the inherited pipe.
        self.owner = owner
        #: The inflight-table key. Request ids are chosen by CLIENTS, so two
        #: connections may legitimately both use ``req-1``; the table is keyed
        #: per owner so neither can collide with — or cancel — the other's work.
        #: Stdio keeps the bare id, so its frames and its drain reports are
        #: byte-identical to the single-transport loop.
        self.key = rid if owner == "stdio" else f"{owner}:{rid}"
        #: Where this request's frames go. None means stdout.
        self.sink = sink
        #: Set only for a turn started by the METHOD lane (gateway Stage 3): the
        #: ``turn_request_id`` whose accept receipt this worker settles when it
        #: exits. ``None`` for every argv request, including the argv chat turns
        #: a local launcher sends — the receipt exists to close the RPC lane's
        #: accept window and a local send never opens one.
        self.turn_request_id = turn_request_id
        #: When the dispatcher took it. Set HERE rather than in ``_run``,
        #: because the gap between the two is the whole point: it is the time
        #: the request spent in the pool's queue, and that time is invisible to
        #: the worker that eventually runs it.
        self.submitted_monotonic = time.monotonic()
        #: When a pool worker entered ``_run``, or ``None`` while still queued.
        #: This single field is the difference between "the pool is full and
        #: your request has not started" and "your request is running and its
        #: side effects may already have landed" — which used to be the same
        #: silence on the wire.
        self.started_monotonic: float | None = None
        #: When the liveness pump last described this request, so a long turn
        #: is reported on a cadence rather than on every pump tick.
        self.progress_monotonic: float | None = None


#: The harness parser tree's builder (``harness_parts.parser.build_parser``),
#: BOUND by the parser's ``serve`` trampoline (``parser.machine._cmd_serve``)
#: before a serve runs, so this package never imports the parser package (which
#: imports every verb family): the lane only borrows the tree per request.
_harness_parser_builder: Callable[[Any], None] | None = None


class HarnessParserUnbound(RuntimeError):
    """``dispatch_argv`` ran before anything bound the harness parser."""


def bind_harness_parser(build_parser: Callable[[Any], None]) -> None:
    """Bind the function that adds the ``harness`` tree to a subparsers action."""

    global _harness_parser_builder
    _harness_parser_builder = build_parser


def _build_harness_parser() -> argparse.ArgumentParser:
    """A fresh top-level parser holding only the harness tree. Built per
    request: cheap next to any handler, and avoids sharing one parser
    across pool threads."""

    builder = _harness_parser_builder
    if builder is None:
        raise HarnessParserUnbound(
            "the serve argv lane has no harness parser; the serve trampoline binds it "
            "(bind_harness_parser) before serving"
        )
    parser = argparse.ArgumentParser(prog="hermes")
    subparsers = parser.add_subparsers(dest="command")
    builder(subparsers)
    return parser


def _system_exit_code(exc: SystemExit) -> int:
    """``SystemExit.code`` as an int, by the interpreter's own conventions.

    ``None`` is success and a non-int (a message string, the shape
    ``sys.exit("usage: …")`` produces) is the shell's generic failure — the
    normalisation the request loop has always applied, written once now that
    two call sites need it.
    """

    raw = exc.code
    if isinstance(raw, int):
        return raw
    return 0 if raw is None else 2


#: The ONE argv root this lane owns. ``_build_harness_parser`` builds the
#: harness tree and nothing else, so every other root — ``profile``, ``agent``,
#: ``gateway`` — reaches the parser only to be rejected by it (RL-24/R-C11).
ARGV_ROOT = "harness"


def _clean_argv_root(value: Any) -> str:
    """The rejected root, safe to put on a frame: printable, one line, bounded.

    The value came off the wire, and a refusal that echoes an unbounded caller
    string is how a rejection becomes a write amplifier. Sixteen characters is
    longer than every root this CLI has.
    """

    text = "".join(ch for ch in str(value or "") if ch.isprintable()).strip()
    return text[:16]


class HandlerExit(SystemExit):
    """A ``SystemExit`` raised by a request HANDLER, after the parser bound it.

    The distinction this type exists to make is the whole of RL-24. The
    launcher's stale-child fallback re-runs an ``argv_parse_failed`` argv on a
    fresh CLI, and it is allowed to do that only because that word is supposed
    to mean "the parser refused this before anything ran". A handler that calls
    ``sys.exit()`` has already had its effect; reporting it with the parser's
    word invites a SECOND effect. So the handler's exit is converted here, at
    the only place that knows which of the two raised, and :func:`serve_loop`
    answers it with its own terminal frame.

    A ``SystemExit`` subclass on purpose: every other caller of
    :func:`dispatch_argv` — ``hermes_cli.main``, the test harness CLI — keeps
    the exact process behaviour it had, because to a plain ``except SystemExit``
    this IS one.
    """

    def __init__(self, code: int) -> None:
        super().__init__(code)
        #: The handler's exit code, already normalised to an int.
        self.handler_code = code


class ArgvRootUnsupported(SystemExit):
    """An argv whose root is not :data:`ARGV_ROOT`, refused BEFORE parsing.

    ``hermes profile delete <profile> --yes`` is a real CLI verb (R-C11), and
    the launcher rendered it into this lane for as long as the capability has
    existed. What it met was an argparse ``invalid choice`` — indistinguishable
    from a stale child that has not learned a new verb — so the launcher's
    fallback re-ran the identical argv the identical way, forever. Refusing by
    NAME, before a parser is built, is what lets the far side route the verb to
    the machine that owns it instead of retrying a lane that can never carry it.
    """

    def __init__(self, root: str) -> None:
        super().__init__(2)
        #: The rejected root, exactly as it arrived (bounded when framed).
        self.root = root


def dispatch_argv(argv: list[str]) -> int:
    """Parse and run one request exactly as ``hermes <argv…>`` would,
    including the harness error-envelope contract.

    Three ways out, and they are deliberately three different exceptions
    (RL-24): :class:`ArgvRootUnsupported` before anything is built, a bare
    ``SystemExit`` from ``parse_args`` — which the loop maps to
    ``argv_parse_failed``, unchanged — and :class:`HandlerExit` from the
    handler. Only the middle one means "nothing ran".
    """
    from hermes_cli.harness_support import emit_harness_error

    root = argv[0] if argv else ""
    if root != ARGV_ROOT:
        raise ArgvRootUnsupported(str(root))

    # Everything from here to ``func`` is the PARSER's. A ``SystemExit`` out of
    # either ``parse_args`` call — a usage error, or the ``--help`` exit-0 for a
    # root verb with no handler — propagates as itself and is the only thing the
    # loop is allowed to call a parse failure.
    parser = _build_harness_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.parse_args([*argv, "--help"])  # exits 0 after printing help
        return 0
    try:
        code = func(args)
    except SystemExit as exc:
        raise HandlerExit(_system_exit_code(exc)) from exc
    except BaseException as exc:  # mirror hermes_cli.main harness dispatch
        return emit_harness_error(exc, args=args)
    return code if isinstance(code, int) else 0
