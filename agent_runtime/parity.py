"""Snapshot parity / observability primitives (S0 of the read-model architecture).

The Mission Control snapshot is a lossy projection of harness truth. Historically
every drop (truncation, redaction, identity mismatch, mode gate) was *silent*, so
when the UI diverged nobody could say what was dropped or why. These primitives
turn drops into data:

* :func:`events_watermark` — a cheap source-position marker (event-log byte
  offset + last event ts) so a snapshot is self-dating and a reader can tell how
  far behind it is.

The drop side-channel, :class:`~agent_runtime.projection_accountant.ProjectionAccountant`
(and the by-design vs anomalous ruling), lives in ``projection_accountant`` (models):
it is a pure counter, and the policy projections that record into it must not reach
this module's event-log stat.

See `Launcher_Brain/20 — Active Initiatives/mission-control-snapshot-architecture.md`.
"""

from __future__ import annotations

from typing import Any

from hermes_time import now

from . import event_rotation
from .projection_accountant import _safe_text

__layer__ = "stores"

PARITY_ENVELOPE_VERSION = 1


def core_event_offset(core: Any) -> int | None:
    """The offset a CORE says its own content reaches, or ``None`` if unknown.

    The core's INTRINSIC position, not the frame's: ``parity.watermark.
    event_offset`` is captured at the instant the build starts reading (that is
    what ``7204896978`` pinned), so it is a LOWER bound on the content — events
    after it may already be folded in, but nothing before it can be missing.
    That direction is what makes it usable as a floor.

    ``None`` for a core with no watermark (an unreadable log at build time, a
    pair persisted before the field existed) and it must stay ``None`` rather
    than ``0``: zero is a real position and would make every such core look
    infinitely behind — see :func:`events_watermark` on the same trap.

    It lives HERE, beside the producer of the field it reads, because two
    consumers need the same answer and had grown two spellings of it: the
    stream's MCF-Q1 frame guard (``stream._full_core_batch_frames``) and the
    same-offset demote reuse (``demote_core_reuse``). A second spelling of "how
    far does this core reach" is how two guards come to disagree about the one
    question the whole read-model turns on.
    """

    if not isinstance(core, dict):
        return None
    parity = core.get("parity")
    if not isinstance(parity, dict):
        return None
    watermark = parity.get("watermark")
    if not isinstance(watermark, dict):
        return None
    value = watermark.get("event_offset")
    return None if value is None else int(value)


def events_position() -> dict[str, Any]:
    """Capture the event log's source position **now**, with no `last_event_ts`.

    Split out of :func:`events_watermark` so a producer whose CONTENT is read
    over a long window can capture its position BEFORE it starts reading and
    stamp that, instead of a stat taken after it finished. See
    :func:`events_watermark`'s "which instant does the offset describe" block —
    the two directions are not symmetric, and only one of them is safe.

    Carries ``captured_at`` so the instant travels WITH the offset: a position
    handed across a multi-second build must not be re-dated at the far end, or
    the envelope would claim a freshness the number does not have.
    """

    try:
        offset = event_rotation.log_end_offset()
    except OSError as exc:
        return {
            "event_offset": None,
            "event_offset_error": _safe_text(f"{type(exc).__name__}: {exc}"),
            "captured_at": now(),
        }
    return {"event_offset": offset, "captured_at": now()}


def events_watermark(*, last_event_ts: Any = None, position: dict[str, Any] | None = None) -> dict[str, Any]:
    """Source-position marker for the append-only event log.

    ``event_offset`` is the log's total byte size — the cursor a streaming tailer
    would resume from (S1) — read cheaply via ``stat`` without scanning the log.
    Under rotation (C6a) that is the LOGICAL tail (live base offset + live slice
    size), spanning sealed slices, so ``iter_from_offset(event_offset)`` still
    resolves to "nothing past the tail". Equals ``getsize(events.jsonl)`` in the
    pristine (pre-rotation) state. ``last_event_ts`` is passed in by the caller
    (which has already tailed the log for the snapshot) so this stays O(1).

    **An unreadable log yields ``None``, never ``0``.** The stat can fail — on
    this runtime's platform routinely, under AV scanning or a share violation —
    and it used to be swallowed into ``offset = 0``, indistinguishable from a
    genuinely empty log. Zero is the single most damaging value this field can
    carry, because every reader treats it as a real position: the stream
    resumes a tailer from byte 0 — replaying the ENTIRE log as fresh activity at
    the root of every Mission Control surface — and the checkpoint watermark
    records it as a position actually reached.

    Two of the readers that made this rule are gone: ``read_model.snapshot_watermark``
    documented the exact trap in its own docstring while this producer was still
    minting one, and the projector read a 0 offset as "caught up, no new rows".
    Stage 6 (2026-08-22) deleted both with the ``read_model.db`` lane. The rule
    did NOT go with them — it is a property of this producer, and this docstring
    is now its only home, which is why the argument is stated here in full rather
    than delegated to a module that no longer exists.

    ``None`` + ``event_offset_error`` is the typed unknown (the ``cron``
    orphan-sweep shape): a reader that cannot act without a position has to say
    so and resync, rather than guess a plausible one.

    **Which instant the offset describes, and why the two directions are not
    symmetric.** A consumer reads this number as "the core beside it contains
    everything up to here". For a producer that assembles its content over a
    window rather than in an instant, that claim is only honest if the offset is
    captured BEFORE the first section is read:

    * offset captured BEFORE the content — the offset is a LOWER bound. Content
      may be newer than the offset, so events after it replay as deltas the
      client has already folded. Idempotent, and the direction
      ``_full_core_batch_frames`` already takes (it drains the batch, then
      builds).
    * offset captured AFTER the content — the offset counts events the content
      does NOT carry. The client folds the core, advances its watermark past
      those events, and the stream resumes its tail from that offset, so they
      are never replayed. Whatever they created is **gone from the client until
      an unrelated full core happens by.**

    Measured 2026-08-21: an agent dropped onto the office canvas while a
    snapshot build was in flight vanished from Mission Control by exactly this
    route, while every agent that predated the build survived.

    ``build_snapshot``'s cache write-back already states this rule for its OWN
    stat set, in as many words: "PRE-build, deliberately: a stat set taken after
    the build would absorb any write that landed while the build ran, and the
    next process would then serve a core missing that write as authoritative"
    (see ``core_cache.write_back``). This producer took the opposite reading of
    the same log for the same build. Pass ``position`` from
    :func:`events_position` to capture the honest end.
    """

    captured = dict(position) if position is not None else events_position()
    offset = captured.get("event_offset")
    captured_at = captured.get("captured_at")
    if offset is None:
        return {
            "event_offset": None,
            "event_offset_error": captured.get("event_offset_error"),
            "last_event_ts": last_event_ts,
            "captured_at": captured_at,
        }
    return {"event_offset": offset, "last_event_ts": last_event_ts, "captured_at": captured_at}
