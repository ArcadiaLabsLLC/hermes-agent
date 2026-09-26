"""What a core build records and when it stands aside: the Stage 5/7 deferral
for active turns, the one snapshot-build receipt, and the stream attach /
denied log lines."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

from ..request_control import request_cancelled
from ..snapshot.receipts import BUILD_CALLER_UNKNOWN, BUILD_SECTIONS_WAIT_THRESHOLD_MS, build_receipt_facts

from .vocabulary import BATCH_REASON_DEMOTE, SNAPSHOT_DEMOTE_DEFERRAL_MAX_MS, _SNAPSHOT_DEMOTE_DEFERRAL_POLL_SECONDS, logger

__layer__ = "stores"


def _agent_runs_in_flight() -> int | None:
    """Real agent runs this process is inside right now, or ``None`` if unaskable.

    Deliberately NOT a second "a turn is running" authority: this forwards to
    ``agent_runtime.profile_runner.agent_runs_in_flight``, the signal the Stage-2
    prewarm yield rule already takes its decision on. Minting a second counter
    here is how two answers to one question drift.

    ``None`` is the honest answer when the module cannot be consulted at all
    (import shape, a partially initialized process). The caller treats unknown
    as "do not defer" — a deferral is an optimization, and an optimization that
    fires on an unmeasured premise is the failure mode this whole plan exists to
    end.
    """

    try:
        from ..profile_runner.workdir import agent_runs_in_flight

        return int(agent_runs_in_flight())
    except Exception:
        return None


def _chat_turns_admitted() -> int | None:
    """Mission-chat turns this process is inside right now, or ``None``.

    chat-turn-prep CP-2's counter (``agent_runtime.turn_activity``), forwarded
    the same way and under the same "``None`` is unaskable" rule as
    :func:`_agent_runs_in_flight` above — and, like it, NOT a second authority:
    the counter lives in one module and this is a read of it.

    **Stage 6 reads this for the RECEIPT only.** The deferral's decision is
    still ``_agent_runs_in_flight()`` alone. This number rides the
    ``snapshot_build_deferred`` line so that the window Stage 5 can never see —
    a turn between its anchor and ``write_ahead``, where 2,796–3,172 ms of
    §0.1's turns 1 and 2 went — is visible on the same receipt BEFORE Stage 7
    changes what the deferral does about it.
    """

    try:
        from ..turn_activity import chat_turns_admitted

        return int(chat_turns_admitted())
    except Exception:
        return None


def _a_turn_holds_the_gil(*, admitted: int | None, in_flight: int | None) -> bool:
    """Is a mission-chat turn occupying this process right now?

    CP-2 in one expression: an ADMITTED turn owns the GIL, not only a RUNNING
    one. The two counters answer different halves of one turn — ``admitted``
    from the handler's anchor, ``in_flight`` from ``ProfileAgentRunner.run()``
    — and the union is the whole of it.

    **``None`` is unknown, and unknown is not a veto.** Both forwarders answer
    ``None`` when their module cannot be consulted at all. Stage 5's rule —
    treat unknown as "do not defer", because an optimization that fires on an
    unmeasured premise is the failure mode this plan exists to end — is
    preserved exactly: an unreadable counter contributes nothing. What it must
    NOT do is cancel a deferral the OTHER counter already earned, which is why
    this is a union of two independently-falsy reads rather than a single
    fused gauge.
    """

    return bool(admitted) or bool(in_flight)


def _defer_demote_build_for_active_turns(
    *,
    reason: str,
    caller: str,
    sleeper: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
) -> int:
    """Hold a demote-cadence core build while an agent run is in flight.

    Returns the milliseconds actually waited — ``0`` when nothing was in flight,
    when the counter could not be read, or when this is not the demote lane.

    **Scope, stated because the exclusions are the safety argument.** ONLY
    ``reason == BATCH_REASON_DEMOTE`` defers. The boot/hydrate job
    (``stream_frames``' ``boot_job``, which rides ``accept_inflight=True``) and
    the ``full_core`` lane — a client's first frame, and every batch with the
    patch lane off — are a consumer WAITING on an answer, not a cadence
    rebuilding state nobody asked for; making an operator's first paint wait on
    a chat turn would trade the inflation this removes for a worse one.

    **The window is slightly wider than the plan's.** The plan says defer while a
    turn is between ``write_ahead`` and ``stream_done``;
    ``agent_runs_in_flight()`` counts from ``ProfileAgentRunner.run()``'s entry
    to its exit, which opens marginally earlier (the run still has admission and
    profile-context install to do) and closes marginally later. That is
    deliberate — it is the SAME signal the prewarm yields on, and one authority
    with a slightly generous window beats two authorities that agree today — and
    it is bounded by the ceiling above either way.

    **A deferred build still counts as overlapping if it then overlaps.**
    Nothing here touches the build ledger: ``builds_overlapped`` is computed
    from the ledger's own spans, so a build that waited 1,000 ms and started
    anyway inside a turn is still counted against that turn. The deferral must
    not be able to launder its own failures out of the receipt.
    """

    if reason != BATCH_REASON_DEMOTE:
        return 0
    if not _a_turn_holds_the_gil(
        admitted=_chat_turns_admitted(), in_flight=_agent_runs_in_flight()
    ):
        return 0
    _sleep = sleeper if sleeper is not None else time.sleep
    _now = clock if clock is not None else time.monotonic
    started = _now()
    deadline = started + (SNAPSHOT_DEMOTE_DEFERRAL_MAX_MS / 1000.0)
    while True:
        if request_cancelled():
            break
        now_s = _now()
        if now_s >= deadline:
            break
        if not _a_turn_holds_the_gil(
            admitted=_chat_turns_admitted(), in_flight=_agent_runs_in_flight()
        ):
            break
        _sleep(
            min(
                _SNAPSHOT_DEMOTE_DEFERRAL_POLL_SECONDS,
                max(0.0, deadline - now_s),
            )
        )
    waited_ms = max(0, int((_now() - started) * 1000))
    if waited_ms > 0:
        # Closed vocabulary, ids and timings only (07-observability census
        # style): the lane, who paid, how long, what the bound was, and what was
        # still running when the wait ended. Never a persona, a chat root, or a
        # display name.
        # ``admitted_at_exit`` (chat-turn-prep Stage 6, CP-2) is the second
        # window on the same line: ``runs_in_flight_at_exit`` says whether a
        # RUN was still going, and this says whether a TURN was admitted —
        # which is the state §0.1's turns 1 and 2 were in for three seconds
        # while this lane saw nothing. Stage 6 recorded it; Stage 7 decides on
        # it, and BOTH are now sampled freshly here rather than reported from
        # whichever poll happened to end the loop. A receipt that answers "what
        # was true when this build was released" has to read at the release: a
        # ``runs_in_flight_at_exit`` carried over from the last poll would be
        # one poll stale on the deadline path, which is the exact path whose
        # honesty matters most (the bound elapsed, so something was still
        # holding, and the line has to say which of the two it was).
        admitted = _chat_turns_admitted()
        in_flight = _agent_runs_in_flight()
        logger.info(
            "snapshot_build_deferred reason=%s caller=%s waited_ms=%d "
            "runs_in_flight_at_exit=%s admitted_at_exit=%s bound_ms=%d",
            reason,
            caller,
            waited_ms,
            "unknown" if in_flight is None else int(in_flight),
            "unknown" if admitted is None else int(admitted),
            SNAPSHOT_DEMOTE_DEFERRAL_MAX_MS,
        )
    return waited_ms


def _log_snapshot_build(
    *,
    reason: str,
    waited_ms: int,
    offset: int | None,
    events: int | None = None,
    snapshot: dict[str, Any] | None = None,
    build_info: dict[str, Any] | None = None,
    core_source: str | None = None,
) -> None:
    """Record one caller's WAIT for a ``build_snapshot()`` and what it cost.

    **Why this is not the heartbeat's number.** The liveness envelope below
    already ships a ``snapshot_build`` activity block, but its ``elapsed_ms``
    is a MID-BUILD sample taken on the heartbeat cadence (5s from
    ``harness serve``): a 6.5s build reports one sample at ~5000 and a warm
    1.2s build reports NOTHING, because it finishes before the first
    heartbeat is due. Neither value is the total. This line is the total,
    taken on the build thread itself, and it is the exact number the
    2026-08-16 performance pass spent hours reconstructing by subtraction
    from ``events_archive/*.jsonl`` timestamps and then by profiling an
    isolated probe copy of the runtime root.

    **Why the number is now called ``waited_ms``.** It was ``elapsed_ms``, and
    that name is what let three of these lines read as three builds on the
    2026-08-17 boot: the value is measured around ``build_snapshot()`` at the
    CALL SITE, and under coalescing that call may be a short ride on a build
    somebody else led. So this line reports the caller's WAIT, and
    ``build_ms`` — read off the parity envelope of the core it actually got —
    reports the build underneath it. ``role``/``caller``/``generation`` say
    which of the two happened (see
    :data:`agent_runtime.snapshot.BUILD_ROLE_LED` and friends), and the build
    itself has its own one-per-build receipt
    (``snapshot_build_core``). ``elapsed_ms`` is still emitted, with the same
    value as ``waited_ms``, for one release: a launcher in the field parses it.

    ``offset`` anchors the cost to the watermark the resulting frame carries,
    so a build can be tied back to the events that paid for it; ``reason``
    names the lane that paid (``hydrate`` / ``demote`` / ``resync`` /
    ``full_core``). A number with no anchor is barely better than no number.

    ``pid`` is the JOIN KEY across the repo boundary (BO-3). A launcher boot
    receipt and a serve's ``agent.log`` had no common identifier at all: the
    only joins available were wall-clock matching — across a live zone trap, the
    diag log's header being UTC while its per-line stamps are local
    time-of-day — and ``build_ms``+``sections_top`` equality, the deliberate
    weak join the launcher's own ``mission_boot_timeline`` documents as weak.
    The launcher already holds this number three ways (the spawn's
    ``process.pid``, and the ``booting``/``ready`` frames' ``pid``); hermes
    logged it nowhere.

    **An additive field, not a formatter change.** ``%(process)d`` on the
    formatter was considered and rejected: it re-shapes EVERY line this runtime
    emits, so every existing grep that anchors on the family token's neighbour
    breaks at once. ``pid=`` goes LAST on all three of the families a boot
    investigation joins on (this one, ``snapshot_build_core``,
    ``stream_attach``), so no existing adjacency moves and a reader that ignores
    the key behaves exactly as before.

    Rides the ordinary ``Logger`` family, so ``hermes serve`` (mode ``gui``)
    lands it in ``<HERMES_HOME>/logs/agent.log`` at INFO with no extra flag.
    """

    facts = build_receipt_facts(snapshot)
    info = build_info if isinstance(build_info, dict) else {}
    build_ms = facts["build_ms"]
    if build_ms is None and isinstance(info.get("build_ms"), (int, float)):
        build_ms = int(info["build_ms"])
    line = (
        "snapshot_build reason=%s waited_ms=%d elapsed_ms=%d build_ms=%s "
        "role=%s caller=%s generation=%s offset=%s events=%s"
    )
    values: list[Any] = [
        reason,
        int(waited_ms),
        # The deprecated twin, deliberately the SAME value rather than a second
        # measurement — a rename that shipped two different numbers under two
        # keys would be worse than the name it replaced.
        int(waited_ms),
        "unknown" if build_ms is None else int(build_ms),
        str(info.get("role") or "unknown"),
        str(info.get("caller") or BUILD_CALLER_UNKNOWN),
        "-" if info.get("generation") is None else int(info["generation"]),
        "unknown" if offset is None else int(offset),
        "-" if events is None else int(events),
    ]
    # The section split rides a WAIT line only when the build under it was slow
    # enough that "of what?" is the next question (HC-0). Every build carries its
    # own split on its ``snapshot_build_core`` receipt regardless.
    if build_ms is not None and int(build_ms) >= BUILD_SECTIONS_WAIT_THRESHOLD_MS:
        line += " sections_top=%s"
        values.append(facts["sections_top"])
    # W3-H2: present ONLY when this caller ran no build at all because the core
    # of the previous demote build at this same offset was still valid. Absent
    # on every ordinary line, so no existing adjacency moves and a reader that
    # does not know the key behaves exactly as before. ``build_ms`` above stays
    # the ORIGINAL build's cost — the build underneath this frame — because a
    # ``build_ms=0`` would be a lie about a build that really did cost seconds.
    if core_source is not None:
        line += " core_source=%s"
        values.append(str(core_source))
    # LAST, after the conditional split, so "pid is the last field" holds on
    # both shapes of this line — see the docstring for why it is additive here
    # rather than a formatter change.
    line += " pid=%d"
    values.append(os.getpid())
    logger.info(line, *values)


def log_stream_attach(*, op: str, purpose: str, **fields: Any) -> None:
    """ONE line per ATTACHMENT to the shared stream, at subscribe time.

    Three different calls attach a reader to the same producer — the socket
    lane's ``{"op":"subscribe"}``, the RPC office lane's
    ``runtime.office.subscribe``, and ``hermes harness stream`` on a terminal —
    and until this line existed the serve child's own log named NONE of them.
    Two costs of that silence, both paid: the 2026-08-17 boot's third hydrate
    rider could not be identified at all (the subscriber census had to be
    reconstructed from timestamps, and one attachment stayed unattributed), and
    a 12 MB serve-child log carried zero ``office`` lines, which made
    "is the office push lane even attached?" unanswerable from the log the
    operator actually has (plan §8 item 5).

    ``op`` is the call as the client made it; ``purpose`` is what the attachment
    is FOR. Both, because neither implies the other: two ops can serve one
    purpose (the office lane and the legacy stream both fold patches) and one op
    serves several (``subscribe`` is the boot hydrate and every resubscribe).

    ``pid`` rides LAST (BO-3), the same additive field the two build families
    carry, so an attachment and the builds it paid for join on one key instead
    of on wall clocks across a timezone boundary. It is emitted here rather than
    left to each caller's ``**fields`` precisely because the callers are three
    different modules: a field each of them had to remember is a field one of
    them would eventually not.

    Single-homed here, next to the build lines a reader greps alongside it, and
    imported function-locally by the two non-stream callers so this module's
    projection-import weight stays off their import paths. Never raises: an
    instrument must not be the reason a subscribe fails.
    """

    try:
        extras = " ".join(
            f"{key}={'-' if value is None else value}" for key, value in fields.items()
        )
        logger.info(
            "stream_attach op=%s purpose=%s%s pid=%d",
            op,
            purpose,
            f" {extras}" if extras else "",
            os.getpid(),
        )
    except Exception:  # pragma: no cover - observability must never fail a lane
        pass


def log_stream_denied(
    *, reason: str, lane: Any, connection: str, **fields: Any
) -> None:
    """ONE line per REFUSED attachment — the other half of ``stream_attach``.

    An attachment that succeeded said so here since EG-2.1; an attachment that
    was turned away said nothing anywhere, and the cost of that asymmetry is
    measured: on 2026-09-04 the Windows cockpit's stream to the Mac died 7 ms
    after its subscribe, and neither machine held a record of which of the five
    denials it was. The reason existed only in the launcher's memory and went
    out with the connection (dialable-addresses §8, R-D26). A refusal is the one
    outcome an operator has to reconstruct, so it is the one the log must carry.

    ``lane`` leads because it is what the client ASKED for and the only field
    that can name a lane this serve does not have; ``reason`` and ``connection``
    follow so a grep for one denial reads the same left-to-right as the attach
    line beside it. ``pid`` rides LAST for the same reason it does there — the
    denial and the builds around it join on one key rather than on wall clocks.

    ``lane`` is the only value on this line taken straight off the wire, so it
    is the only one rendered through a fence: whitespace would split one
    ``key=value`` pair into two and let a client write fields into the operator's
    log. No device id is ever emitted — the connection key already identifies
    the connection to anyone reading this serve's own log, and it does not
    identify the device to anyone who is not.

    Never raises, for the reason its sibling gives: an instrument must not be
    the reason a lane fails, and a refusal path is the worst place to learn it.
    """

    try:
        safe_lane = "-".join(str(lane).split())[:64] or "-"
        extras = " ".join(
            f"{key}={'-' if value is None else value}" for key, value in fields.items()
        )
        logger.info(
            "stream_denied lane=%s reason=%s connection=%s%s pid=%d",
            safe_lane,
            reason,
            connection,
            f" {extras}" if extras else "",
            os.getpid(),
        )
    except Exception:  # pragma: no cover - observability must never fail a lane
        pass
