"""The build's log lines: the core build line, the agents-readiness split
receipt, build info, the caller label and section timing.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Any

from agent_runtime.snapshot.context import logger
from agent_runtime.snapshot.receipts import (
    BUILD_CALLER_UNKNOWN,
    BUILD_ROLE_LED,
    build_receipt_facts,
)

__layer__ = "policy"

__all__ = [
    "AGENTS_READINESS_SPLIT_RECEIPT",
    "BUILD_REASON_UNKNOWN",
    "EXECUTOR_IN_PROCESS",
    "EXECUTOR_WORKER",
    "SNAPSHOT_BUILD_SHADOW_RECEIPT",
    "_build_caller",
    "_build_reason",
    "_log_snapshot_build_shadow",
    "receipt_pid",
    "set_receipt_pid",
    "_log_agents_readiness_split",
    "_log_snapshot_build_core",
    "_record_build_info",
    "_timed_section",
]


#: How a build was executed (h-snap-worker): in the resident snapshot worker
#: process, or on this interpreter. The GIL claim of a build rides on this field,
#: never on a new key on the parity envelope or the turn record (ruling R6).
EXECUTOR_WORKER = "worker"
EXECUTOR_IN_PROCESS = "in_process"

#: The trigger's second half when the caller did not seed one.
BUILD_REASON_UNKNOWN = "-"

#: The shadow validation build's receipt (ruling R3 + the owner's accounting ask):
#: the same facts as ``snapshot_build_core`` under its own family name, because it
#: is NOT a led build -- it serves no caller, holds no coalescer slot and is not in
#: ``builds_overlapped`` -- and a ``role=led`` grep must keep counting led builds.
SNAPSHOT_BUILD_SHADOW_RECEIPT = (
    "snapshot_build_shadow caller=%s reason=shadow build_ms=%s offset=%s sections_top=%s "
    "executor=%s turns=%s worker_pid=%s pid=%d"
)

#: The pid a build-time receipt names. A worker build's receipts are written by
#: the SERVE (ruling R5: one writer per ``agent.log``) and must join the serve's
#: ``snapshot_build_core`` on ``pid``; the worker entry sets this to the serve pid.
_RECEIPT_PID: int | None = None


def receipt_pid() -> int:
    """The ``pid=`` a build-time receipt carries: the serve's, even inside the worker."""

    return os.getpid() if _RECEIPT_PID is None else int(_RECEIPT_PID)


def set_receipt_pid(pid: int | None) -> None:
    """The worker entry's one call (and a test's reset)."""

    global _RECEIPT_PID
    _RECEIPT_PID = None if pid is None else int(pid)


def _pid_field(pid: int | None) -> str:
    return "-" if pid is None else str(int(pid))


def _log_snapshot_build_core(
    *,
    caller: str,
    generation: int | None,
    snapshot: Any,
    reason: str = BUILD_REASON_UNKNOWN,
    executor: str = EXECUTOR_IN_PROCESS,
    turns: str = "-",
    worker_pid: int | None = None,
) -> None:
    """ONE line per ACTUAL build, emitted by the caller that ran it.

    Every other line about a build is a WAIT (``agent_runtime.stream``'s
    ``snapshot_build``), and until this line existed the two were
    indistinguishable: the 2026-08-17 boot's three "concurrent builds" were one
    build plus two riders logging their waits, and the most expensive build of
    that boot — the serve prewarm — logged nothing at all, because nothing on
    its path had a line to emit. Grep ``role=led`` for the build count.

    Emitted on the default-store coalesced path only. An injected-store build
    (tests, doctors, a detail-fetch catalog capture) is a fixture, not a boot,
    and printing one line per unit test would bury the boot's own lines.

    ``pid`` rides LAST (BO-3): this line, ``stream.py``'s ``snapshot_build`` and
    ``stream_attach`` are the three families a boot investigation joins on, and
    until this field existed a launcher boot receipt and a serve's ``agent.log``
    shared no identifier at all — the joins available were wall-clock matching
    across the diag log's UTC-header/local-lines zone trap, and
    ``build_ms``+``sections_top`` equality, which the launcher's own
    ``mission_boot_timeline`` documents as a deliberately weak join. Additive,
    never a formatter change: ``%(process)d`` re-shapes every line this runtime
    emits and breaks every grep that anchors on a field's neighbour.

    Rides the ordinary ``Logger`` family, so ``hermes serve`` lands it in
    ``<HERMES_HOME>/logs/agent.log`` at INFO with no extra flag.

    **The accounting fields (h-snap-worker, owner ask 2026-10-06)**, all BEFORE
    ``pid``: ``reason`` (with ``caller``, the build's trigger), ``executor``
    (``worker`` / ``in_process`` -- which interpreter's GIL paid), ``turns`` (the
    admitted chat turns the build overlapped, ``agent_runtime.turn_activity``'s
    watch; ``-`` for none) and ``worker_pid`` (``-`` in process).
    ``hermes harness observe snapshot-builds`` derives its summary from these.
    """

    facts = build_receipt_facts(snapshot)
    logger.info(
        "snapshot_build_core role=%s caller=%s generation=%s build_ms=%s offset=%s "
        "sections_top=%s reason=%s executor=%s turns=%s worker_pid=%s pid=%d",
        BUILD_ROLE_LED,
        caller,
        "-" if generation is None else int(generation),
        "unknown" if facts["build_ms"] is None else int(facts["build_ms"]),
        "unknown" if facts["offset"] is None else int(facts["offset"]),
        facts["sections_top"],
        reason or BUILD_REASON_UNKNOWN,
        executor,
        turns or "-",
        _pid_field(worker_pid),
        os.getpid(),
    )


def _log_snapshot_build_shadow(
    *, caller: str, snapshot: Any, executor: str, turns: str = "-", worker_pid: int | None = None
) -> None:
    """The shadow validation build's own line (:data:`SNAPSHOT_BUILD_SHADOW_RECEIPT`)."""

    facts = build_receipt_facts(snapshot)
    logger.info(
        SNAPSHOT_BUILD_SHADOW_RECEIPT,
        caller,
        "unknown" if facts["build_ms"] is None else int(facts["build_ms"]),
        "unknown" if facts["offset"] is None else int(facts["offset"]),
        facts["sections_top"],
        executor,
        turns or "-",
        _pid_field(worker_pid),
        os.getpid(),
    )


#: The ``agents_readiness`` split receipt, format-pinned by
#: ``tests/agent_runtime/test_agents_readiness_attribution.py``.
#:
#: ``sections_ms["agents_readiness"]`` times TWO different walks and always has.
#: Its NAME says readiness, so every remedy plan that read the section off a
#: build log convicted ``profile_readiness_for_persona`` — and on this section
#: that is the smaller half. Measured against the operator's own profiles root
#: (5 runtime personas, 2026-08-22): the first build in a process costs 4,001 ms,
#: of which the summary/tool-visibility half is 3,054 ms and the readiness walk
#: 947 ms; every build after it in the same process costs 183 ms, split 36 / 146.
#: The halves also move for unrelated reasons — the visibility half is the tool
#: registry populate and the ``check_fn`` sweep, the walk is profile config plus
#: skill resolution — so one number over both cannot attribute either.
#:
#: A LOG line rather than two parity keys: see the argument at the call site.
#: Timings only, and it rides beside ``snapshot_build_core`` in ``agent.log`` so
#: the two join on ``pid`` without a wall-clock match.
AGENTS_READINESS_SPLIT_RECEIPT = (
    "snapshot_agents_readiness walk_ms=%d tool_visibility_ms=%d pid=%d"
)


def _log_agents_readiness_split(split: dict[str, int]) -> None:
    """Emit the section's two halves — or nothing at all if it never ran.

    An empty ``split`` means the section did not execute, which is not the same
    fact as "both halves cost 0 ms" and must not be spelled the same way. A
    section that RAN and cost nothing does report its two zeros: that is a
    measurement, and suppressing it would make a cheap build indistinguishable
    from a skipped one in the other direction.
    """

    if not split:
        return
    logger.info(
        AGENTS_READINESS_SPLIT_RECEIPT,
        int(split.get("walk_ms", 0)),
        int(split.get("tool_visibility_ms", 0)),
        receipt_pid(),
    )


def _record_build_info(
    build_info: dict | None,
    *,
    role: str,
    caller: str,
    generation: int | None,
    snapshot: Any = None,
) -> None:
    """Fill the caller's ``build_info`` out-param. Never raises, never reads.

    The dict belongs to the CALLER (one per caller, by construction — that is
    what makes the role matrix in
    ``tests/agent_runtime/test_snapshot_build_logging.py`` able to convict a
    hardcoded role). ``build_ms`` rides along so a caller can name the cost of
    the build it rode without re-deriving the envelope.
    """

    if build_info is None:
        return
    build_info["role"] = role
    build_info["caller"] = caller
    build_info["generation"] = generation
    if snapshot is not None:
        build_info["build_ms"] = build_receipt_facts(snapshot)["build_ms"]


def _build_reason(build_info: dict | None) -> str:
    """Why the caller asked (``demote`` / ``hydrate`` / ``boot`` …), pre-seeded like
    ``caller``; :data:`BUILD_REASON_UNKNOWN` when it was not."""

    if not isinstance(build_info, dict):
        return BUILD_REASON_UNKNOWN
    text = str(build_info.get("reason") or "").strip()
    return "".join(text.split()) or BUILD_REASON_UNKNOWN


def _build_caller(build_info: dict | None) -> str:
    """Who is asking, in their own words — the ONE input side of ``build_info``.

    Pre-seeded by the caller (``{"caller": "hub"}``); everything else in the
    dict is filled by the builder. Threaded rather than inferred because the
    builder genuinely cannot know: hub, cli, prewarm and the office lane all
    reach the same function through the same call.
    """

    if not isinstance(build_info, dict):
        return BUILD_CALLER_UNKNOWN
    caller = build_info.get("caller")
    text = str(caller).strip() if caller is not None else ""
    return text or BUILD_CALLER_UNKNOWN


@contextmanager
def _timed_section(sink: dict[str, int], key: str):
    """Accumulate wall time (ms) for a build section into ``sink[key]``.

    Additive/observability only — powers the parity envelope's ``sections_ms``
    next to ``build_ms``. Accumulates (``+=``) so a section timed across more than
    one span sums rather than overwrites. Keys are stable and lowercase.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        sink[key] = sink.get(key, 0) + int(max(0.0, (time.perf_counter() - start)) * 1000)
