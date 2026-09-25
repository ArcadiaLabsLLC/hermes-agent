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
    "_build_caller",
    "_log_agents_readiness_split",
    "_log_snapshot_build_core",
    "_record_build_info",
    "_timed_section",
]


def _log_snapshot_build_core(*, caller: str, generation: int | None, snapshot: Any) -> None:
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
    """

    facts = build_receipt_facts(snapshot)
    logger.info(
        "snapshot_build_core role=%s caller=%s generation=%s build_ms=%s offset=%s "
        "sections_top=%s pid=%d",
        BUILD_ROLE_LED,
        caller,
        "-" if generation is None else int(generation),
        "unknown" if facts["build_ms"] is None else int(facts["build_ms"]),
        "unknown" if facts["offset"] is None else int(facts["offset"]),
        facts["sections_top"],
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
        os.getpid(),
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
