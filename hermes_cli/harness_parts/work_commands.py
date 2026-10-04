"""``harness work``: list, peek and cancel the running background work.

Split from ``runtime_commands`` (H2 sheet leftover, lane h10b-refac): the
running-work verb family and the confirmation-target helper only it calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from hermes_cli.harness_support import (
    ERROR_EXIT_CODES,
    _error_envelope,
    _list_envelope,
    _object_envelope,
    _print_stage42,
    _require_yes,
    _sort_rows,
)

__layer__ = "lanes"
__all__ = [
    "_cmd_work_restart",
    "WorkCancelOutcome",
    "WorkCancelVerdict",
    "_cmd_work_cancel",
    "_cmd_work_list",
    "_cmd_work_peek",
    "_work_cancel_outcome",
    "_work_target_details",
]


# --- `harness work` — running background work -------------------------------
#
# Every import below is function-local — the convention from before lane H1,
# when these bodies were exec'd into hermes_cli/harness.py's globals.


def _work_target_details(row: dict) -> dict:
    """The identifying facts a confirmation prompt must show before a kill.

    Deliberately the human-recognisable ones — what it is, which agent owns it,
    which OS process it maps to — because ``terminal:sess-8f2c`` alone tells an
    operator nothing about whether this is the build they want stopped or the
    dev server they do not.
    """

    owner = row.get("owner") or {}
    return {
        "work_id": row.get("work_id"),
        "kind": row.get("kind"),
        "label": row.get("label"),
        "command": row.get("command") or None,
        "pid": row.get("pid"),
        "pid_verified": row.get("pid_verified"),
        "status": row.get("status"),
        "elapsed_seconds": row.get("elapsed_seconds"),
        "owner_persona_instance_id": owner.get("persona_instance_id"),
        "owner_session_id": owner.get("session_id"),
    }


def _cmd_work_list(args) -> int:
    from agent_runtime.projection_accountant import ProjectionAccountant
    from agent_runtime.running_work import RUNNING_WORK_KINDS, build_running_work

    kind = str(getattr(args, "kind", None) or "").strip()
    if kind and kind not in RUNNING_WORK_KINDS:
        _print_stage42(
            _error_envelope(
                "invalid_request",
                f"unknown work kind {kind!r}",
                safe_details={"supported": list(RUNNING_WORK_KINDS)},
            ),
            args=args,
            default_output="json",
        )
        return ERROR_EXIT_CODES["invalid_request"]

    # The snapshot lane accounts its drops through the parity envelope; without
    # an accountant here the CLI lane silently shed the same rows (exited PIDs,
    # recycled PIDs, capped lanes) with nothing to say so. Same projection, same
    # accounting.
    accountant = ProjectionAccountant("running_work")
    projection = build_running_work(accountant)
    rows = [row for row in projection["rows"] if not kind or row.get("kind") == kind]
    rows = _sort_rows(rows, getattr(args, "sort", None))

    limit = getattr(args, "limit", None)
    truncated = False
    if isinstance(limit, int) and limit > 0 and len(rows) > limit:
        rows = rows[:limit]
        truncated = True

    envelope = _list_envelope("running_work", rows, truncated=truncated)
    # Per-source health rides the SAME envelope as the rows, never a separate
    # call: a consumer that reads the rows without the health block would read
    # an unreadable lane as "nothing running", which is the one answer this
    # projection exists to make impossible.
    envelope["sources"] = projection["sources"]
    envelope["counts"] = projection["counts"]
    # Machine-local context, carried in its OWN block rather than folded into a
    # lane's health prose. It is what tells an operator staring at an empty list
    # WHICH home the projection read — the difference between "nothing is
    # running" and "nothing is running over there". Not contract: a consumer
    # renders it, never branches on it.
    #
    # Attached only when the projection published it, and never defaulted. This
    # block is a DIAGNOSTIC, so it must not be able to take the verb down (a
    # required-key read here would turn a missing diagnostic into a dead
    # `work list`), and it must not be fabricated either — a producer that
    # stopped publishing it should be visible by its absence, not papered over
    # with an invented home.
    ambient = projection.get("ambient")
    if isinstance(ambient, dict):
        envelope["ambient"] = ambient
    envelope["completeness"] = accountant.summary()
    _print_stage42(envelope, args=args, default_output="json")
    return 0


def _cmd_work_peek(args) -> int:
    from agent_runtime.running_work import peek_work

    payload = peek_work(str(getattr(args, "work_id", "") or ""))
    if not payload.get("found"):
        _print_stage42(
            _error_envelope(
                "invalid_request" if payload.get("error") == "malformed_work_id" else "not_found",
                payload.get("error") or "no running work with that id",
                safe_details={"work_id": payload.get("work_id")},
            ),
            args=args,
            default_output="json",
        )
        return ERROR_EXIT_CODES[
            "invalid_request" if payload.get("error") == "malformed_work_id" else "not_found"
        ]
    _print_stage42(
        _object_envelope("work_peek", payload), args=args, default_output="json"
    )
    return 0


class WorkCancelVerdict(Enum):
    """Every way ``harness work cancel`` can end — one member per exit path.

    Deliberately not a string Enum: the verdict is an internal decision, never
    a wire word, and string values would re-declare words the wire already
    owns (``cancel_work``'s ``"cancelled"`` status, the error codes)."""

    NOT_FOUND = auto()
    SUPERSEDED = auto()
    CONFIRMATION_REQUIRED = auto()
    DRY_RUN = auto()
    REFUSED = auto()
    CANCELLED = auto()


@dataclass(frozen=True)
class WorkCancelOutcome:
    """What one cancel request decided: the verdict, the exit code a caller
    branches on, and the envelope to print.

    ``envelope`` is ``None`` for exactly one verdict,
    ``CONFIRMATION_REQUIRED``: that refusal is printed by the ONE confirmation
    chokepoint (``harness_support._require_yes``), which names the target
    itself, so this verb never prints a competing envelope of its own.
    """

    verdict: WorkCancelVerdict
    exit_code: int
    envelope: dict | None


def _work_cancel_outcome(args) -> WorkCancelOutcome:
    """Decide one cancel request. The only effects are the confirmation
    chokepoint's own refusal print and, on the last path, the kill itself."""

    from agent_runtime.running_work import cancel_work, find_work_row
    from agent_runtime.running_work.surface import _cancel_is_superseded

    work_id = str(getattr(args, "work_id", "") or "")
    row = find_work_row(work_id)
    if row is None:
        return WorkCancelOutcome(
            WorkCancelVerdict.NOT_FOUND,
            ERROR_EXIT_CODES["not_found"],
            _error_envelope(
                "not_found",
                "no running work with that id",
                safe_details={"work_id": work_id},
            ),
        )

    issued_at = str(getattr(args, "issued_at", None) or "").strip()
    started_at = str(row.get("started_at") or "")
    if _cancel_is_superseded(issued_at, started_at):
        return WorkCancelOutcome(
            WorkCancelVerdict.SUPERSEDED,
            ERROR_EXIT_CODES["stale_revision"],
            _error_envelope(
                "stale_revision",
                "cancel was issued before this work started; superseded",
                safe_details={
                    "work_id": work_id,
                    "issued_at": issued_at,
                    "started_at": started_at,
                },
            ),
        )

    target = _work_target_details(row)
    if not _require_yes(
        args,
        message=(
            f"Cancelling {target['kind']} work {target['label']!r} "
            f"(pid={target['pid']}) requires --yes."
        ),
        safe_details=target,
    ):
        return WorkCancelOutcome(
            WorkCancelVerdict.CONFIRMATION_REQUIRED,
            ERROR_EXIT_CODES["confirmation_required"],
            None,
        )

    if getattr(args, "dry_run", False):
        return WorkCancelOutcome(
            WorkCancelVerdict.DRY_RUN,
            0,
            _object_envelope(
                "work_cancel",
                {"dry_run": True, "would_cancel": target, "cancelled": False},
            ),
        )

    result = cancel_work(work_id, reason=str(getattr(args, "reason", "") or "operator_cancel"))
    # ``cancel_requested``: an announced build's writer was asked to end it (build plan §7).
    if result.get("status") not in ("cancelled", "cancel_requested"):
        code = str(result.get("code") or "internal_error")
        return WorkCancelOutcome(
            WorkCancelVerdict.REFUSED,
            ERROR_EXIT_CODES.get(code, 1),
            _error_envelope(
                code,
                str(result.get("detail") or f"cancel refused: {code}"),
                safe_details={**target, "detail": result.get("detail")},
            ),
        )

    # ``status``/``code``/``kind`` are stripped from the spread: the first
    # two are already expressed by the exit code, and ``kind`` would
    # overwrite the envelope's own kind discriminator.
    return WorkCancelOutcome(
        WorkCancelVerdict.CANCELLED,
        0,
        _object_envelope(
            "work_cancel",
            {
                "cancelled": True,
                "target": target,
                **{
                    key: value
                    for key, value in result.items()
                    if key not in {"status", "code", "kind"}
                },
            },
        ),
    )


def _cmd_work_cancel(args) -> int:
    outcome = _work_cancel_outcome(args)
    if outcome.envelope is not None:
        _print_stage42(outcome.envelope, args=args, default_output="json")
    return outcome.exit_code


def _cmd_work_restart(args) -> int:
    """``harness work restart`` — the argv mirror of ``runtime.work.restart`` (build plan §7).

    The same decision as the method: find the row, the shared ``issued_at`` replay guard,
    then ``builds.control.restart_build``. No confirmation: a detected build restarts through
    the same path as every row (owner call 2) — the row already shows what it will run.
    """

    from agent_runtime.builds.control import restart_build
    from agent_runtime.running_work import find_work_row
    from agent_runtime.running_work.surface import _cancel_is_superseded

    work_id = str(getattr(args, "work_id", "") or "")
    row = find_work_row(work_id)
    if row is None or row.get("kind") != "build":
        envelope = _error_envelope("not_found", "no running build with that id", safe_details={"work_id": work_id})
        _print_stage42(envelope, args=args, default_output="json")
        return ERROR_EXIT_CODES["not_found"]
    issued_at = str(getattr(args, "issued_at", None) or "").strip()
    if _cancel_is_superseded(issued_at, str(row.get("started_at") or "")):
        envelope = _error_envelope("stale_revision", "restart was issued before this build started; superseded",
                                   safe_details={"work_id": work_id, "issued_at": issued_at})
        _print_stage42(envelope, args=args, default_output="json")
        return ERROR_EXIT_CODES["stale_revision"]
    result = restart_build(row)
    if result.get("status") != "restarted":
        envelope = _error_envelope("invalid_payload", f"restart refused: {result.get('detail') or result.get('code')}",
                                   safe_details={"work_id": work_id, "code": result.get("code"), "detail": result.get("detail")})
        _print_stage42(envelope, args=args, default_output="json")
        return ERROR_EXIT_CODES.get("invalid_payload", 1)
    _print_stage42(_object_envelope("work_restart", result), args=args, default_output="json")
    return 0
