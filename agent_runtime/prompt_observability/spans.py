"""The observability row's own sub-span accounting (chat-turn-prep Stage 6 item 2).

Separate because it is thread-local instrument state every other module in the
package bills into, and an instrument must not import what it measures.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Any

__layer__ = "policy"
__all__ = [
    "OBSERVABILITY_TIMING_KEYS",
    "PROMPT_OBSERVABILITY_TIMINGS_KEY",
    "_SPAN_CATALOG_WALK",
    "_SPAN_SHARED_CATALOG",
    "_accumulate_span",
    "_reset_observability_spans",
    "_observability_span_ms",
    "_note_catalog_walk",
    "_observability_catalog_walks",
    "_mission_chat_memory_loaded",
]


# ── chat-turn-prep Stage 6 item 2: this row's own sub-spans ──────────────────
#
# ``observability_built − context_built`` is ONE number on the phase block and
# it read 438–1,718 ms live (§0.1) and 270–937 ms in the §0.3 sandbox. The
# profile said where it goes — the resolver's two skill-root walks (357 ms), the
# installed-catalog TTL miss (129 ms) and ``build_shared_catalog``'s per-file
# content hashing (336 ms cold) — but a profile is not a receipt, and Stage 8's
# remedy is judged on these three plus the 0/1 that says whether the 15 s
# catalog TTL was hit.
#
# THREAD-LOCAL, and the accumulation happens where the work happens rather than
# at the top call site: the catalog walk runs from two places inside this build
# (the builder's own call and the resolver's union pass) and the shared catalog
# from a third, so timing the call sites would bill one of three walks. The
# builder resets the accumulator when it opens its skill block and reads it when
# the block closes, so what it collects is exactly this build's.
#
# The snapshot lane calls the same functions on the builder thread and simply
# never reads the accumulator; a build there resets nothing and costs two
# ``time.monotonic()`` reads per walk.

#: The keys this row contributes, in the order the builder performs them. The
#: handler folds them onto the turn's ``profile_timing``; the store's
#: ``safe_turn_profile_timing`` is what bounds them.
OBSERVABILITY_TIMING_KEYS: tuple[str, ...] = (
    "observability_skill_rows_ms",
    "observability_catalog_walk_ms",
    "observability_shared_catalog_ms",
    "observability_catalog_cached",
)


#: The field the built row carries :data:`OBSERVABILITY_TIMING_KEYS` under, on
#: its way to the handler. Never persisted — see
#: :func:`persist_prompt_observability_context`.
PROMPT_OBSERVABILITY_TIMINGS_KEY = "timings"


_SPAN_CATALOG_WALK = "catalog_walk"


_SPAN_SHARED_CATALOG = "shared_catalog"


_span_state = threading.local()


def _span_totals() -> dict[str, float]:
    totals = getattr(_span_state, "totals", None)
    if totals is None:
        totals = {}
        _span_state.totals = totals
    return totals


@contextmanager
def _accumulate_span(name: str):
    """Add this block's monotonic duration to ``name`` on THIS thread.

    Never raises and never swallows: an instrument may not change what the
    build does, in either direction.
    """

    started = time.monotonic()
    try:
        yield
    finally:
        totals = _span_totals()
        totals[name] = totals.get(name, 0.0) + max(0.0, time.monotonic() - started)


def _reset_observability_spans() -> None:
    _span_state.totals = {}
    _span_state.walks = 0


def _observability_span_ms(name: str) -> int:
    return max(0, int(_span_totals().get(name, 0.0) * 1000))


def _note_catalog_walk() -> None:
    """Count a catalog MISS. The count, not the duration, is what
    ``observability_catalog_cached`` reports: a walk that finished under half a
    millisecond still walked, and rounding it to ``0 ms`` must not be allowed to
    report the TTL as having held."""

    _span_state.walks = int(getattr(_span_state, "walks", 0)) + 1


def _observability_catalog_walks() -> int:
    return int(getattr(_span_state, "walks", 0))


def _mission_chat_memory_loaded(persona: Any) -> bool:
    """Whether the mission-chat lane loads this persona's bound-profile memory.

    Mirrors ``GPTPersonaRuntime.mission_chat_reply`` (skip_memory is gated on
    ``include_profile_memory``); kept here so the observability report reflects
    the real prompt flag instead of a hardcoded assumption."""
    return bool(getattr(persona, "include_profile_memory", False))
