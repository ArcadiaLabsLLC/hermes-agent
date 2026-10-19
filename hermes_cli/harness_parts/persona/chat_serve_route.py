"""``hermes harness mission-chat message`` from a shell HANDS the turn to the live serve.

A send typed in a shell used to run the whole turn in that shell's process, with
that shell's ``HERMES_HOME``: on 2026-10-09 a Claude session sending
``--persona neko_supervisor`` under the root home resolved the ``neko`` profile
with no Codex login and exited 2, while the serve one socket away held the right
home and credentials. So a parsed CLI send now rides the serve's argv lane — the
same door ``harness query`` (``agent_runtime/harness_query/serve_route.py``) and
``harness stream`` (``hermes_cli/harness_parts/stream_relay.py``) use: resolve the
socket target and token, hello, send ``{id, argv}``, copy the ``line`` frames to
stdout until the ``exit`` frame, and return its code. The serve runs the very
handler this process would have run, inside its own home.

Only a send that came off the parser routes. The in-process door
(``agent_runtime.mission_chat_door``) calls ``_cmd_mission_chat_message`` itself
and never reaches this function; inside a serve request (``current_serve_request_id``
bound) the serve IS the runtime; ``--in-process`` forces the old path (the
detached dispatch child passes it, since its spawner chose the process). With no
live serve, or a hello the serve refuses, the turn runs in-process and one stderr
line says why. Once the argv is sent the turn belongs to the serve: a failure
after that point never re-runs it here.
"""

from __future__ import annotations

import os
import sys
from typing import Any, TextIO

from hermes_cli.harness_parts.stream_relay import write_relay_line

__layer__ = "lanes"
__all__ = [
    "NOT_FORWARDED",
    "SEND_CLIENT_NAME",
    "SEND_FLAGS",
    "cmd_mission_chat_send",
    "relay_send_via_serve",
    "send_argv",
]

SEND_CLIENT_NAME = "harness-chat-send"

#: Bounds the dial and the hello only; the turn itself runs as long as it runs.
_DIAL_SECONDS = 10.0
#: An idle read lap, not a deadline: a lap that times out just reads again.
_READ_LAP_SECONDS = 30.0

#: ``(dest, flag, kind)`` for every option of ``mission-chat message`` the serve
#: must see. ``kind`` is ``"value"`` (passed when not None), ``"float"``/``"int"``
#: (spelled numerically), ``"flag"`` (passed when true) or ``"list"`` (one flag per item). A test walks the real
#: parser: every key is here or in ``NOT_FORWARDED``, so a new flag cannot be
#: dropped silently.
SEND_FLAGS: tuple[tuple[str, str, str], ...] = (
    ("persona_id", "--persona", "value"),
    ("persona_instance_id", "--persona-instance-id", "value"),
    ("session_id", "--session-id", "value"),
    ("new_session", "--new-session", "flag"),
    ("clarify_token", "--clarify-token", "value"),
    ("title", "--title", "value"),
    ("message", "--message", "value"),
    ("provider", "--provider", "value"),
    ("model", "--model", "value"),
    ("use_agent_default", "--use-agent-default", "flag"),
    ("surface_prompt", "--surface-prompt", "value"),
    ("agents_file", "--agents-file", "value"),
    ("intent_hint", "--intent-hint", "value"),
    ("requested_by", "--requested-by", "value"),
    ("client_message_id", "--client-message-id", "value"),
    ("idempotency_key", "--idempotency-key", "value"),
    ("retry_of", "--retry-of", "value"),
    ("images", "--image", "list"),
    ("files", "--file", "list"),
    ("stream", "--stream", "flag"),
    ("max_seconds", "--max-seconds", "float"),
    ("compression_threshold_tokens", "--compression-threshold-tokens", "int"),
    ("compression_protect_first_n", "--compression-protect-first-n", "int"),
    ("compression_protect_last_n", "--compression-protect-last-n", "int"),
    ("relay_chain", "--relay-chain", "value"),
    ("relay_deadline_epoch", "--relay-deadline-epoch", "float"),
    ("requested_by_session", "--requested-by-session", "value"),
    ("defer_thread_policy", "--defer-thread-policy", "flag"),
    ("json", "--json", "flag"),
)


#: Namespace keys the serve is not told: the parser's routing keys, this
#: process's ``--in-process``, and the ``harness``-level ``--output/--quiet/
#: --no-color/--fields``, which the turn handler never reads (``--json``, the
#: one it does, rides as the leaf flag). Spelled before the verb they would
#: also hide the argv from the serve's chat-turn match (``_CHAT_TURN_COMMANDS``).
NOT_FORWARDED = frozenset(
    {
        "command",
        "harness_command",
        "mission_chat_command",
        "func",
        "in_process",
        "output",
        "quiet",
        "no_color",
        "fields",
    }
)


def _spell(args: Any, flags: tuple[tuple[str, str, str], ...]) -> list[str]:
    argv: list[str] = []
    for dest, flag, kind in flags:
        value = getattr(args, dest, None)
        if kind == "flag":
            if value:
                argv.append(flag)
        elif kind == "list":
            argv.extend(f"{flag}={item}" for item in value or ())
        elif value is not None:
            if kind == "float":
                text = repr(float(value))
            elif kind == "int":
                text = str(int(value))
            else:
                text = str(value)
            # ``--flag=value`` so a value that starts with ``-`` (a message
            # like "-h") is never read as an option by the serve's parser.
            argv.append(f"{flag}={text}")
    return argv


def send_argv(args: Any) -> list[str]:
    """The argv the serve runs: this send, every option spelled out."""

    return ["harness", "mission-chat", "message", *_spell(args, SEND_FLAGS)]


def _this_pid() -> int:
    """This process's pid — one name, so the self-dial guard is testable."""

    return os.getpid()


def _say(why: str) -> None:
    try:
        sys.stderr.write(f"mission-chat message: running in-process ({why})\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        pass


#: Why a send ran in-process, by the shared route's reason (one stderr line each).
_IN_PROCESS_WHY = {
    "no_live_serve_socket": "no live serve for this runtime root",
    "this_process_is_the_serve": "this process is the serve",
    "no_auth_token": "no serve auth token",
    "hello_rejected": "serve refused the hello",
}


def relay_send_via_serve(args: Any, *, out: TextIO | None = None) -> int | None:
    """Hand this send to the live serve; its exit code, or ``None`` to run in-process.

    The dial, hello and frame loop are the shared CLI route's
    (``agent_runtime.serve_socket.cli_route.relay_argv``) under its ``TURN_HANDOFF``
    rule: in-process only while nothing was sent; once the argv is on the wire the turn
    is the serve's and a failure is exit 1, never a second run here.
    """

    from agent_runtime.serve_socket.cli_route import FallbackPolicy, RelayKind, relay_argv

    sink = sys.stdout if out is None else out
    sent: list[str] = []
    try:
        outcome = relay_argv(
            send_argv(args),
            client=SEND_CLIENT_NAME,
            sink=lambda line: write_relay_line(sink, line),
            err_sink=lambda line: write_relay_line(sys.stderr, line),
            dial_seconds=_DIAL_SECONDS,
            read_lap_seconds=_READ_LAP_SECONDS,
            request_prefix="chat-send",
            on_sent=sent.append,
            self_pid=lambda: _this_pid(),
        )
    except KeyboardInterrupt:
        rid = sent[0] if sent else "(not sent)"
        write_relay_line(sys.stderr, f"mission-chat message: detached; the serve keeps request {rid}")
        return 130
    if outcome.runs_locally(FallbackPolicy.TURN_HANDOFF):
        reason = outcome.reason
        if reason.startswith("transport_failed:"):
            _say(f"serve handshake failed: {reason.split(':', 1)[1]}")
        else:
            _say(_IN_PROCESS_WHY.get(reason, reason))
        return None
    if outcome.kind is RelayKind.SERVED:
        return int(outcome.code or 0)
    reason, rid = outcome.reason, outcome.request_id
    if reason == "serve_closed_connection":
        write_relay_line(sys.stderr, f"mission-chat message: serve closed request {rid}")
    elif reason.startswith("transport_failed:"):
        write_relay_line(sys.stderr, f"mission-chat message: serve lane broke: {reason.split(':', 1)[1]}")
    else:
        write_relay_line(sys.stderr, f"mission-chat message: serve error: {reason}")
    return 1


def cmd_mission_chat_send(args: Any) -> int:
    """The parser's ``mission-chat message`` func: the serve's turn when one is live."""

    from hermes_cli.harness_parts.persona import chat_turn_message
    from hermes_cli.harness_parts.serve.frames import current_serve_request_id

    if not getattr(args, "in_process", False) and current_serve_request_id() is None:
        code = relay_send_via_serve(args)
        if code is not None:
            return code
    return chat_turn_message._cmd_mission_chat_message(args)
