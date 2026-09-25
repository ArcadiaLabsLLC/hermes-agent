"""Shadow validation: rebuild once behind a served cached core and compare,
ignoring the keys that legitimately differ.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Iterator

from agent_runtime.core_cache.vocabulary import logger
from agent_runtime.core_cache.models import CoreFingerprint
from agent_runtime.core_cache.persist import write_back
from agent_runtime.core_cache.lane import (
    claim_shadow_slot,
    note_full_build_completed,
    shadow_build_scope,
)

__layer__ = "lanes"

__all__ = [
    "_SHADOW_IGNORED_PARITY_KEYS",
    "_SHADOW_IGNORED_TOP_KEYS",
    "_SHADOW_IGNORED_WATERMARK_KEYS",
    "_stripped",
    "compare_cores",
    "iter_fingerprint_paths",
    "maybe_start_shadow_validation",
    "shadow_validate",
]


# --------------------------------------------------------------------------- #
# Shadow validation
# --------------------------------------------------------------------------- #
#: The comparison ignores exactly the fields that describe THIS build rather
#: than the state it projected. Everything else — every section, every row,
#: every count — must agree, because a difference in any of them is the
#: input-closure gap §6.1 is about.
_SHADOW_IGNORED_PARITY_KEYS = frozenset(
    {
        "build_ms",
        "sections_ms",
        "generated_at",
        "projection_age_ms",
        "core_source",
        "core_stale",
        "freshness",
        "snapshot_bytes",
    }
)


_SHADOW_IGNORED_TOP_KEYS = frozenset({"generated_at", "parity", "runtime_paths_diagnostic"})


#: ``parity.watermark`` is compared, minus the clock that says WHEN it was
#: measured. The reason to compare it at all is ``event_offset``: two cores at
#: different log positions ARE a divergence, and one of the most informative
#: kinds. ``captured_at`` is the measurement's own timestamp — it moves on every
#: read by construction, so leaving it in would make every comparison diverge and
#: the whole window would report noise until somebody switched it off.
_SHADOW_IGNORED_WATERMARK_KEYS = frozenset({"captured_at"})


def compare_cores(cached: dict, rebuilt: dict) -> str | None:
    """The first section on which a cache-served core and a rebuild disagree.

    ``None`` means they agree. The NAME is the whole point of the return value:
    a boolean divergence receipt would tell an operator the cache is wrong
    without telling them which input class to widen.
    """

    from ..serde import to_jsonable

    left = to_jsonable(cached)
    right = to_jsonable(rebuilt)
    if not isinstance(left, dict) or not isinstance(right, dict):
        return "core"
    keys = sorted(set(left) | set(right))
    for key in keys:
        if key in _SHADOW_IGNORED_TOP_KEYS:
            continue
        if left.get(key) != right.get(key):
            return key
    left_parity = left.get("parity") if isinstance(left.get("parity"), dict) else {}
    right_parity = right.get("parity") if isinstance(right.get("parity"), dict) else {}
    for key in sorted(set(left_parity) | set(right_parity)):
        if key in _SHADOW_IGNORED_PARITY_KEYS:
            continue
        if key == "watermark":
            if _stripped(left_parity.get(key), _SHADOW_IGNORED_WATERMARK_KEYS) != _stripped(
                right_parity.get(key), _SHADOW_IGNORED_WATERMARK_KEYS
            ):
                return "parity.watermark"
            continue
        if left_parity.get(key) != right_parity.get(key):
            return f"parity.{key}"
    return None


def _stripped(value: Any, drop: frozenset[str]) -> Any:
    if not isinstance(value, dict):
        return value
    return {key: item for key, item in value.items() if key not in drop}


def shadow_validate(cached: dict, *, caller: str, build: Callable[[], dict], adopt: Callable[[dict], None] | None = None) -> str | None:
    """Rebuild in full, compare against the core we just served, report.

    The UP-4 pattern applied to this cache, and the mitigation that converts
    §6.1's input-closure risk into receipts. A divergence is LOUD (a warning
    naming the section) and the rebuilt core is ADOPTED — written back, so the
    next boot cannot be served the divergent copy, and handed to ``adopt`` so
    the lane that already painted can replace what it painted.

    Retirement is receipts-based and is NOT this stage's call: zero divergence
    receipts across the agreed window (TC-3's shape).

    **THE WINDOW CLOSES HERE, ON EVERY VERDICT (MCF-Q1).** This build IS the
    process's own full build — the one the lane's whole docstring says the armed
    window ends at. It was excluded from that rule while only the DIVERGENT
    verdict closed the lane, and the exclusion made the memo's stated safety
    bound ("the window is a BOOT — it ends at the first completed full build")
    vacuously false on exactly the boots the memo optimizes: on a cache-HIT boot
    no build ever completes through :func:`agent_runtime.snapshot.build_snapshot`,
    so nothing ever called :func:`note_full_build_completed` and every later
    ``build_snapshot()`` in that serve process was answered with the boot-time
    core — for the rest of the process's life. Measured on the operator's runtime
    2026-08-21: a second QA agent dropped onto the canvas at 15:33 was erased by
    four ``role=cache reason=demote`` frames stamped 89,849,656 / 89,849,871 /
    89,851,071 / 89,851,462, every one of them carrying a core whose OWN
    ``offset=89843335`` the ``core_source=cache`` receipt prints beside them.

    **WHAT TODAY'S CONFIG CONTENT-KEY FIX DID AND DID NOT DO.** It did not arm
    this trap; the trap was already live. The same log carries the same shape on
    2026-08-20 — a cache hit at ``offset=89567980`` at 18:30:05, then
    ``reason=demote role=cache offset=89568195`` at 18:30:11, and the pair again
    at 18:38 — a day before ``2f98eef3ee``. What that commit changed is the
    VERDICT. Those 2026-08-20 boots ended in ``snapshot_core_shadow_divergence
    section=parity.event_log_bytes`` about ten seconds in, and a divergence
    already closed the lane, so the exposure was ~10 s per boot and an erasing
    frame had to land inside it. With the flapping input content-keyed the shadow
    now says ``ok=true`` (15:24:11, 15:25:22) — and an agreeing verdict closed
    nothing, so the window went from ten seconds to the life of the process. The
    log only reaches back to 2026-08-20 10:56, so the honest bound is "at least a
    day older than the report, and structurally as old as the lane (EG-3.1,
    2026-08-17)".

    That history is also why this is not the whole fix. Closing the window on
    agreement retires the 2026-08-21 shape; the 2026-08-20 shape landed INSIDE a
    window that was going to close anyway, and only the frame-level guard in
    ``stream._full_core_batch_frames`` refuses that one — the frame-level half of
    this invariant, and the reason both halves shipped together.

    Closing here costs the boot NOTHING and that is why it is the right place:
    the riders this cache exists for (prewarm, hydrate, hub, cli) all arrive
    within about a second of each other and are answered from the shared consult
    long before this background build finishes (measured 6.5–7.6 s). What ends is
    the part that was never a saving — serving a boot-time core to builds issued
    minutes later.

    An ok=true verdict closes it, a divergence closes it, and a build that RAISED
    closes it too: a validation that could not run is not a licence to keep
    serving the thing it failed to validate.
    """

    try:
        with shadow_build_scope():
            rebuilt = build()
    except Exception:
        logger.warning("snapshot_core_shadow ok=false caller=%s reason=build", caller, exc_info=True)
        note_full_build_completed()
        return None
    section = compare_cores(cached, rebuilt)
    if section is None:
        logger.info("snapshot_core_shadow ok=true caller=%s divergence=none", caller)
        note_full_build_completed()
        return None
    # ADOPTION, in the order that matters: the divergent copy stops being
    # servable to the NEXT process first (the write-back), then this process
    # stops serving it (the lane closes), then whoever already painted is told
    # to replace what it painted. A receipt without adoption would leave the
    # operator reading about a canvas that is still wrong.
    write_back(rebuilt)
    logger.warning(
        "snapshot_core_shadow_divergence caller=%s section=%s — the persisted core "
        "disagreed with a full rebuild; the rebuilt core is adopted. Widen the "
        "fingerprint's input closure (agent_runtime/core_cache.py), never trust "
        "the cache harder.",
        caller,
        section,
    )
    note_full_build_completed()
    if adopt is not None:
        try:
            adopt(rebuilt)
        except Exception:  # pragma: no cover - an instrument must not fail a lane
            logger.warning("snapshot_core_shadow adopt failed", exc_info=True)
    return section


def maybe_start_shadow_validation(cached: dict, *, caller: str, build: Callable[[], dict], adopt: Callable[[dict], None] | None = None) -> bool:
    """Start the shadow build on a daemon thread, if this process's slot is free."""

    if not claim_shadow_slot():
        return False
    thread = threading.Thread(
        target=lambda: shadow_validate(cached, caller=caller, build=build, adopt=adopt),
        name="harness-core-shadow",
        daemon=True,
    )
    thread.start()
    return True


def iter_fingerprint_paths(fingerprint: CoreFingerprint) -> Iterator[str]:
    """Every path in a fingerprint — the §6.1 audit surface, enumerable."""

    for entry in fingerprint.entries:
        yield entry.path
