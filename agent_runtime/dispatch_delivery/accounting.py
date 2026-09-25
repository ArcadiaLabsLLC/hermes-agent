"""ACCOUNTING [A]: the typed idle probe, the bounded drain telemetry, and its cross-process mirror file."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils import atomic_json_write

from .vocabulary import (
    DELIVERED_REASON,
    DELIVERED_SILENT_REASON,
    DELIVERY_REASONS,
    DRAIN_DETAIL_LIMIT,
    DRAIN_OWNERLESS_WARN_AFTER,
    DRAIN_REPEAT_LOG_EVERY,
    DRAIN_STATE_FILENAME,
    MAX_DRAIN_OUTCOME_ROWS,
)

__layer__ = "stores"

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# accounting — NAME the gate that bounced a completion
#
# Every line in this section is ACCOUNTING [A]: it reads the values a delivery
# DECISION [D] was already taken on and records them. Nothing here may steer a
# decision, and the tagging is kept as comments at each non-obvious call site so
# the split stays legible. The 2026-08-11 incident (proc_379e2ddbbc4f) is the
# reason it exists: a completion sat undeliverable for ~5 consecutive passes and
# the gate that bounced it was structurally unknowable afterwards — the per-pass
# tally was discarded, the requeues logged nothing, and no store recorded a
# considered-and-bounced event.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class IdleProbe:
    """The typed reason :func:`_probe_sender_idle` answered as it did.

    ``is_idle`` is the DECISION (the bool ``_sender_is_idle`` has always
    returned); ``busy_sub``/``detail`` are ACCOUNTING. Four distinct causes used
    to collapse into one silent ``False``, which is precisely why the live stall
    could not be classified after the fact.
    """

    is_idle: bool
    busy_sub: str = ""
    detail: str = ""

    @staticmethod
    def idle() -> "IdleProbe":
        return IdleProbe(True)


#: Where :func:`_sender_is_idle` stashes the probe behind its bool so the drain
#: can name the gate WITHOUT re-probing (a second probe would be a second answer
#: — and, worse, a second lease acquisition).
#:
#: A ContextVar rather than a module global: the probe runs on the drain thread
#: and, in tests, on arbitrary threads. Single writer per context, no locking,
#: and correct per-thread reads. Cleared at the top of every per-event iteration
#: so a stale probe can never be attributed to the next event.
_LAST_IDLE_PROBE: ContextVar[IdleProbe | None] = ContextVar(
    "dispatch_delivery_last_idle_probe", default=None
)


@dataclass
class DrainBounce:
    """One ``(event_key, reason)`` outcome, with its occurrence count."""

    event_key: str
    reason: str
    detail: str
    count: int
    first_at: float
    last_at: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_key": self.event_key,
            "reason": self.reason,
            "detail": self.detail,
            "count": self.count,
            "first_at": self.first_at,
            "last_at": self.last_at,
        }


class _DrainTelemetry:
    """Bounded, in-memory "what did the drain last do, and why".

    Nothing here accumulates: ≤ :data:`MAX_DRAIN_OUTCOME_ROWS` outcome rows,
    truncated details, one fixed-size tally. It is written by the drain thread
    and read by ``harness status`` on the serve lane, so every mutation takes
    the lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started_at: float | None = None
        self.pass_count = 0
        self.last_pass_started_at: float | None = None
        self.last_pass_finished_at: float | None = None
        self.last_pass_tally: dict[str, int] = {}
        self.last_delivery_at: float | None = None
        self.last_delivery_key: str = ""
        #: Which of :data:`DELIVERY_REASONS` the last delivery was. Carried
        #: beside the key so a reader of ``last_delivery`` alone — which is the
        #: field a human checks first — cannot mistake a silent delivery for a
        #: visible one.
        self.last_delivery_reason: str = ""
        self.outcomes: "OrderedDict[tuple[str, str], DrainBounce]" = OrderedDict()
        #: Bumped whenever an outcome row is inserted or updated. The mirror
        #: writer compares it across a pass to decide whether anything happened
        #: worth persisting — an unchanged revision means an empty pass.
        self.outcome_revision = 0
        self._ownerless_streak: "OrderedDict[str, int]" = OrderedDict()
        self._ownerless_warned: set[str] = set()

    # -- writers ----------------------------------------------------------

    def reset(self) -> None:
        """Drop all recorded state. Test seam; never called in production."""

        with self._lock:
            self.started_at = None
            self.pass_count = 0
            self.last_pass_started_at = None
            self.last_pass_finished_at = None
            self.last_pass_tally = {}
            self.last_delivery_at = None
            self.last_delivery_key = ""
            self.last_delivery_reason = ""
            self.outcomes.clear()
            self.outcome_revision = 0
            self._ownerless_streak.clear()
            self._ownerless_warned.clear()

    def mark_started(self, when: float | None = None) -> None:
        with self._lock:
            self.started_at = float(when if when is not None else time.time())

    def note_pass_start(self, when: float | None = None) -> None:
        with self._lock:
            self.pass_count += 1
            self.last_pass_started_at = float(when if when is not None else time.time())

    def note_pass_finished(self, tally: dict[str, int]) -> None:
        with self._lock:
            self.last_pass_finished_at = time.time()
            self.last_pass_tally = dict(tally or {})

    def record_bounce(
        self, event_key: str, reason: str, detail: str = "", *, root: str = ""
    ) -> None:
        """Record one outcome for one event, and log it at a bounded rate.

        Both :data:`DELIVERY_REASONS` travel this same call — the field is "last
        outcomes", not "last failures", so "what did the drain last do" has a
        complete answer rather than one that only ever shows the bad half.
        """

        key = (str(event_key or ""), str(reason or ""))
        now = time.time()
        text = str(detail or "")[:DRAIN_DETAIL_LIMIT]
        delivered = key[1] in DELIVERY_REASONS
        with self._lock:
            row = self.outcomes.get(key)
            if row is None:
                if len(self.outcomes) >= MAX_DRAIN_OUTCOME_ROWS:
                    self.outcomes.popitem(last=False)
                self.outcomes[key] = DrainBounce(
                    event_key=key[0],
                    reason=key[1],
                    detail=text,
                    count=1,
                    first_at=now,
                    last_at=now,
                )
                count = 1
            else:
                row.count += 1
                row.last_at = now
                row.detail = text
                count = row.count
            self.outcome_revision += 1
            if delivered:
                self.last_delivery_at = now
                self.last_delivery_key = key[0]
                self.last_delivery_reason = key[1]
        if count == 1 or count % DRAIN_REPEAT_LOG_EVERY == 0:
            if key[1] == DELIVERED_SILENT_REASON:
                # WARNING, not info: the delivery mechanism worked perfectly and
                # the operator still learned nothing, which is the one outcome
                # nobody goes looking for because everything upstream of it
                # succeeded.
                logger.warning(
                    "delivery drain delivered %s INTO SILENCE root=%s detail=%s",
                    key[0],
                    root,
                    text,
                )
            elif delivered:
                logger.info(
                    "delivery drain delivered %s root=%s detail=%s",
                    key[0],
                    root,
                    text,
                )
            else:
                logger.info(
                    "delivery drain bounced %s reason=%s detail=%s root=%s%s",
                    key[0],
                    key[1],
                    text,
                    root,
                    f" (x{count})" if count > 1 else "",
                )

    def note_ownerless_streak(self, root: str, *, ownerless: bool) -> int:
        """Track consecutive ownerless lease probes for one root.

        Returns the streak length WHEN a WARNING is owed (once per episode),
        else 0. A probe that succeeds — or that fails for any other sub-reason —
        ends the episode, so the next stale lock warns again.
        """

        name = str(root or "")
        if not name:
            return 0
        with self._lock:
            if not ownerless:
                self._ownerless_streak.pop(name, None)
                self._ownerless_warned.discard(name)
                return 0
            streak = self._ownerless_streak.pop(name, 0) + 1
            self._ownerless_streak[name] = streak
            while len(self._ownerless_streak) > MAX_DRAIN_OUTCOME_ROWS:
                evicted, _ = self._ownerless_streak.popitem(last=False)
                self._ownerless_warned.discard(evicted)
            if streak >= DRAIN_OWNERLESS_WARN_AFTER and name not in self._ownerless_warned:
                self._ownerless_warned.add(name)
                return streak
            return 0

    # -- readers ----------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """A plain-JSON-able copy of everything above."""

        with self._lock:
            return {
                "started_at": self.started_at,
                "pass_count": self.pass_count,
                "last_pass_started_at": self.last_pass_started_at,
                "last_pass_finished_at": self.last_pass_finished_at,
                "last_pass_tally": dict(self.last_pass_tally),
                "last_delivery": {
                    "event_key": self.last_delivery_key,
                    "at": self.last_delivery_at,
                    "reason": self.last_delivery_reason,
                },
                "outcomes": [row.as_dict() for row in self.outcomes.values()],
            }


#: The one telemetry instance. Module-level for the same reason
#: ``_background_attempts`` is: the queue it accounts for is process-local.
_telemetry = _DrainTelemetry()


def _event_key(evt: dict[str, Any]) -> str:
    """The queue lane's dedup identity for an event.

    Extracted so the forged turn's ``client_message_id`` and the telemetry row
    are derived from ONE expression and can never drift into naming the same
    completion two different ways.
    """

    marker = str(
        evt.get("delegation_id") or evt.get("session_id") or uuid.uuid4().hex
    )[:40]
    return f"{evt.get('type', 'completion')}:{marker}"


def _delivery_outcome(payload: dict[str, Any] | None) -> tuple[str, str]:
    """Classify a forged turn that came back ``ok``: visible, or silent.

    ACCOUNTING [A], never a DECISION. Both outcomes settle, acknowledge and
    drain identically, and that is deliberate: re-queuing a silent delivery
    would re-forge into the very transcript that produced the silence — a loop,
    with a duplicate notice per lap — and the completion notice IS in the
    thread either way. The turn happened. It just answered with nothing.

    The drain does not decide this — it READS it. ``TurnVisibility`` is the one
    authority (``agent_runtime.turn_visibility``); the handler stamps a typed
    block on every payload carrying a reply, and ``from_payload`` falls back to
    the reply text only for a payload that predates the block, which a
    long-running serve process will keep producing until it restarts.

    Only PROVEN silence is reported as silence. An unknown verdict — no payload,
    no reply key, a stub forge from another lane — stays ``delivered``:
    manufacturing silence out of missing evidence is the same lie pointed the
    other way.
    """

    from ..turn_visibility import TurnVisibility

    visibility = TurnVisibility.from_payload(payload)
    if not visibility.is_silent:
        return DELIVERED_REASON, ""
    return DELIVERED_SILENT_REASON, visibility.describe()


def _record_sender_busy(event_key: str, root: str) -> None:
    """Name the gate ``_sender_is_idle`` just closed. ACCOUNTING ONLY.

    Reads the probe the DECISION stashed rather than probing again. When a test
    has monkeypatched ``_sender_is_idle`` — ``tests/agent_runtime/
    test_dispatch_delivery.py`` does, BY NAME, and ~11 tests depend on that
    override biting — no probe ran for this call and the stash is None. That is
    recorded as ``sender_busy:unprobed``: the installed decision is honored
    bit-for-bit and accounting simply admits it could not observe it, rather
    than re-routing the decision through the probe and quietly making every one
    of those overrides vacuous.
    """

    probe = _LAST_IDLE_PROBE.get()
    if probe is None:
        _telemetry.record_bounce(
            event_key,
            "sender_busy:unprobed",
            "the idle decision was overridden, so no probe ran",
            root=root,
        )
        return
    sub = probe.busy_sub or "unknown"
    _telemetry.record_bounce(event_key, f"sender_busy:{sub}", probe.detail, root=root)
    streak = _telemetry.note_ownerless_streak(root, ownerless=sub == "lease_busy_ownerless")
    if streak:
        logger.warning(
            "persona chat root lease for %s is LOCKED with no owner for %d consecutive"
            " probes — stale byte-range lock suspected (see the 2026-08-11"
            " delivery-stall investigation)",
            root,
            streak,
        )


def _drain_state_path(store_root: Path | None = None) -> Path | None:
    """The mirror's path, or None when the runtime root cannot be resolved.

    Resolved ONCE at drain start (see :func:`start_delivery_drain`) and captured
    by the loop closure — never per pass. ``persona_profile_context`` flips
    ``HERMES_HOME`` process-globally for the duration of a persona turn in THIS
    process, so an ambient mid-pass resolution could land the mirror in whatever
    profile happened to be running. (``paths.store_root()`` is additionally
    pinned across those flips via ``HERMES_AGENT_RUNTIME_ROOT``; this is the
    belt to that pair of braces, and it is the mandatory half.)
    """

    try:
        root = Path(store_root) if store_root is not None else _paths_store_root()
        return root / DRAIN_STATE_FILENAME
    except Exception:
        return None


def _paths_store_root() -> Path:
    from .. import paths

    return paths.store_root()


def _write_drain_state(path: Path | None, *, live: bool) -> bool:
    """Atomically mirror the telemetry to *path*. Never raises.

    Accounting must not be able to kill the drain, so a failure here is a debug
    line and nothing else — the same contract serve's own best-effort wrappers
    hold.

    **Staged through ``atomic_json_write``, and the staging NAME is the reason.**
    The hand-rolled temp+replace this replaced staged ``path.with_suffix(".tmp")``
    — for this file, ``dispatch_delivery_drain.tmp``. The read-model cache's walk
    (``core_cache.build_input_fingerprint``) skips a staged temp only in the
    ``.<stem>_*.tmp`` shape ``atomic_json_write`` produces, so this mirror's
    transient was a store-root entry that appeared and vanished under any walk
    unlucky enough to land mid-write: a file whose PRESENCE flipped the key, on a
    60-second cadence, in a directory the cache is keyed on. The mirror's own
    target is excluded by name (``core_cache._EXCLUDED_STORE_ENTRIES`` imports
    :data:`DRAIN_STATE_FILENAME`); routing the staging through the one atomic-write
    authority is what makes the transient excluded too, rather than adding a
    second name to that set for a file that only exists for microseconds.
    """

    if path is None:
        return False
    try:
        payload = _telemetry.snapshot()
        payload["live"] = bool(live)
        payload["pid"] = os.getpid()
        payload["written_at"] = time.time()
        atomic_json_write(path, payload, indent=None, sort_keys=True)
        return True
    except Exception:
        logger.debug("delivery drain state mirror write failed", exc_info=True)
        return False


def read_delivery_drain_state(store_root: Path | None = None) -> dict[str, Any] | None:
    """The last mirrored drain state, or None when absent/unreadable/corrupt.

    The cross-process channel: a freshly spawned ``harness status --json`` has
    no drain of its own, so this file is the only place the serve process's
    answer survives. Judge staleness by ``written_at`` — older than ~90s and the
    writer is not the live drain any more.
    """

    path = _drain_state_path(store_root)
    if path is None:
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None
