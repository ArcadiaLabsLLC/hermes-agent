"""``harness serve settles`` / ``harness serve settles rearm`` — the argv fallback (D2.05).

The method lane is first (``runtime.settles.list`` / ``runtime.settles.rearm``,
``agent_runtime/serve_rpc/settles.py``); these verbs are thin over the SAME store
functions so a shell without a launcher can read the outbox and revive an
``undelivered`` settle. The live serve's pusher sends a re-armed record on its
next tick; with no launcher attached it is undelivered again after
``NO_LISTENER_SECONDS``.
"""

from __future__ import annotations

import json
from typing import Any

__layer__ = "lanes"

__all__ = ["_cmd_serve_settles", "_cmd_serve_settles_rearm"]

#: Exit code for a refusal (unknown id, already acked, a bad ``--state``).
_REFUSED = 2


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, default=str, indent=2))


def _cmd_serve_settles(args) -> int:
    """List the settle outbox: counts per state, then each record."""

    from agent_runtime.chat_turn_settles import SettleRefusal, settles_listing

    try:
        listing = settles_listing(state=getattr(args, "state", None))
    except ValueError:
        _emit({"ok": False, "reason": SettleRefusal.STATE_INVALID,
               "detail": "--state must be pending, undelivered or acked"})
        return _REFUSED
    if getattr(args, "json", False):
        _emit({"ok": True, **listing})
        return 0
    counts = listing["counts"]
    print(" ".join(f"{state}={counts[state]}" for state in sorted(counts)))
    for row in listing["settles"]:
        reason = f" ({row['undelivered_reason']})" if row.get("undelivered_reason") else ""
        print(f"{row['settle_id'][:12]}  {row['state']}{reason}  attempts={row['attempts']}"
              f"  rearms={row['rearm_count']}  {row['client_message_id']}")
    return 0


#: Exit code when a live serve could not take the write (cli-serve-route write rule).
_SERVE_RELAY_FAILED = 1
_REARM_CLIENT_NAME = "harness-settles-rearm"


def rearm_argv(args) -> list[str]:
    """The argv the serve runs: this same re-arm. Inside the serve's request it runs
    store-direct, because ``current_serve_request_id()`` is bound there (the marker
    ``mission-chat message`` uses too), so the CLI contract gains no flag."""

    argv = ["harness", "serve", "settles", "rearm", str(getattr(args, "ref", "") or "")]
    if getattr(args, "session_id", None):
        argv.append(f"--session-id={args.session_id}")
    if getattr(args, "json", False):
        argv.append("--json")
    return argv


def _relay_rearm(args) -> int | None:
    """Hand the re-arm to the live serve; its exit code, or ``None`` to re-arm here.

    A WRITE under the shared CLI route's rule (``cli_route.FallbackPolicy.WRITE``): only
    NO live serve re-arms locally — the store lock then guards it. A live serve that
    could not be reached or failed the request is a non-zero exit with the reason; the
    re-arm never also runs here, because the serve's outbox pusher would not see it.
    """

    import sys

    from agent_runtime.serve_socket.cli_route import FallbackPolicy, RelayKind, relay_argv

    outcome = relay_argv(
        rearm_argv(args),
        client=_REARM_CLIENT_NAME,
        sink=lambda line: print(line, flush=True),
        err_sink=lambda line: print(line, file=sys.stderr, flush=True),
        request_prefix="settles-rearm",
    )
    if outcome.runs_locally(FallbackPolicy.WRITE):
        return None
    if outcome.kind is RelayKind.SERVED:
        return int(outcome.code or 0)
    _emit({"ok": False, "reason": "serve_relay_failed", "detail": outcome.reason,
           "answered_by": {"lane": "none", "serve_pid": outcome.pid}})
    return _SERVE_RELAY_FAILED


def _answered_by() -> dict[str, Any]:
    from hermes_cli.harness_parts.serve.frames import current_serve_request_id

    return {"lane": "serve" if current_serve_request_id() is not None else "direct"}


def _cmd_serve_settles_rearm(args) -> int:
    """Re-arm one settle by settle id or client message id (+ ``--session-id``).

    Outside a serve request a live serve does the write (``_relay_rearm``); the
    store-direct body below is the in-serve form and the no-serve fallback.
    """

    from hermes_cli.harness_parts.serve.frames import current_serve_request_id

    if current_serve_request_id() is None:
        code = _relay_rearm(args)
        if code is not None:
            return code

    from agent_runtime.chat_turn_settles import (
        RearmResult,
        SettleRefusal,
        rearm_settle,
        resolve_settle_ref,
    )

    settle_id = resolve_settle_ref(getattr(args, "ref", None), session_id=getattr(args, "session_id", None))
    if settle_id is None:
        _emit({"ok": False, "reason": SettleRefusal.SETTLE_REF_REQUIRED})
        return _REFUSED
    result, record = rearm_settle(settle_id)
    if result is RearmResult.NOT_FOUND:
        _emit({"ok": False, "reason": SettleRefusal.SETTLE_NOT_FOUND, "settle_id": settle_id})
        return _REFUSED
    if result is RearmResult.ACKED:
        _emit({"ok": False, "reason": SettleRefusal.SETTLE_ACKED, "settle_id": settle_id})
        return _REFUSED
    _emit({"ok": True, "rearmed": result is RearmResult.REARMED, "settle": record.as_row(),
           "answered_by": _answered_by()})
    return 0
