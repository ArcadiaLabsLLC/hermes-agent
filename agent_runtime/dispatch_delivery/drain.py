"""The dispatch-store drain, its daemon thread, and the in-process liveness/status readers."""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Any, Callable

from .accounting import (
    _LAST_IDLE_PROBE,
    _delivery_outcome,
    _drain_state_path,
    _record_sender_busy,
    _telemetry,
    _write_drain_state,
    read_delivery_drain_state,
)
from .completions import drain_background_completions
from .forge import DEFAULT_DRAIN_POLICY, DrainPolicy, forge_delivery_turn, format_dispatch_delivery
from .vocabulary import (
    DEFAULT_DRAIN_INTERVAL_SECONDS,
    DRAIN_MIRROR_HEARTBEAT_SECONDS,
    GATE_FORGE_BUSY,
    GATE_FORGE_FAILED,
    GATE_FORGE_REJECTED,
    GATE_UNCLAIMED,
    MAX_DELIVERIES_PER_PASS,
    ORPHAN_SWEEP_INTERVAL_SECONDS,
    bounce_reason,
    delivery_client_message_id,
    terminal_forge_rejections,
    transient_forge_refusals,
)

__layer__ = "lanes"

logger = logging.getLogger(__name__)


#: The live drain thread, or None. Read by the capability binding: "serve is
#: running" was only ever a PROXY for "a consumer exists", and the drain starts
#: best-effort, so a serve whose drain failed used to go on promising deliveries
#: nothing would perform.
_drain_thread: threading.Thread | None = None
#: Guards the registration/teardown pair above, so a restart and an old loop's
#: teardown cannot interleave into "registered, then immediately cleared".
_drain_lock = threading.Lock()


def delivery_drain_status() -> dict[str, Any]:
    """What the delivery drain last did and why — for ``harness status --json``.

    Three sources, in order: this process's own live telemetry, the durable
    mirror left by whichever process runs the drain, or nothing at all. The
    ``live`` flag is this process's :func:`delivery_drain_is_live` when the
    answer is in-process; from the mirror it is the WRITER's last claim, which a
    reader tempers with ``written_at``.
    """

    try:
        if delivery_drain_is_live():
            payload = _telemetry.snapshot()
            payload["live"] = True
            payload["source"] = "in_process"
            payload["pid"] = os.getpid()
            payload["written_at"] = None
            return payload
        mirror = read_delivery_drain_state()
        if isinstance(mirror, dict):
            payload = dict(mirror)
            payload["source"] = "state_file"
            payload["live"] = bool(payload.get("live"))
            return payload
    except Exception:
        logger.debug("delivery drain status unavailable", exc_info=True)
    return {"live": False, "source": "absent"}


def delivery_drain_is_live() -> bool:
    """Whether a delivery drain is actually running in THIS process.

    The honest answer to "can a background completion reach this session later",
    and the reason the mission-chat capability binding is not just a serve check.
    """

    thread = _drain_thread
    return bool(thread is not None and thread.is_alive())


# --------------------------------------------------------------------------
# the drain
# --------------------------------------------------------------------------


def drain_once(
    *, forge: Callable | None = None, limit: int | None = None, policy: DrainPolicy | None = None
) -> dict[str, int]:
    """One delivery pass. Never raises; returns a per-pass tally.

    A pass that cannot read the store, cannot resolve a sender, or finds every
    sender busy is a normal outcome, not an error — the completions are durable
    and the next pass tries again.
    """

    from .. import dispatch_store

    budget = int(limit or MAX_DELIVERIES_PER_PASS)
    lane = DispatchDrain(dispatch_store, forge or forge_delivery_turn, policy)
    try:
        rows = dispatch_store.pending_deliveries(limit=budget * 4)
    except Exception:
        logger.debug("dispatch delivery drain could not read the store", exc_info=True)
        return lane.tally
    for row in rows:
        if lane.tally["delivered"] >= budget:
            break
        lane.deliver_one(row)
    return lane.tally


class DispatchDrain:
    """One pass of the dispatch-store lane, one row at a time.

    The same shape as ``completions.BackgroundDrain`` so the two lanes read
    alike: :meth:`own` -> :meth:`probe` -> :meth:`claim` -> :meth:`forge_turn`
    -> :meth:`settle`, each either handing the row on or ending it.
    """

    def __init__(self, store: Any, forge: Callable, policy: DrainPolicy | None = None) -> None:
        self.store = store
        self.forge = forge
        self.policy = policy or DEFAULT_DRAIN_POLICY
        self.tally = {"considered": 0, "delivered": 0, "busy": 0, "dropped": 0, "failed": 0}

    def deliver_one(self, row: dict[str, Any]) -> None:
        self.tally["considered"] += 1
        # A — a probe stashed for a PREVIOUS row must never be attributed to
        # this one. Cleared per event, never carried across.
        _LAST_IDLE_PROBE.set(None)
        target = self.own(row)
        if target is None:
            return
        dispatch_id, root, owner = target
        # The dispatch lane's event identity, so a bounced dispatch and a
        # bounced queue completion read out of the same vocabulary.
        event_key = f"dispatch:{dispatch_id}"
        if not self.probe(root, event_key) or not self.claim(dispatch_id, root, event_key):
            return
        ok, payload, forge_error = self.forge_turn(row, dispatch_id, root, owner)
        self.settle(dispatch_id, root, event_key, ok, payload, forge_error)

    def own(self, row: dict[str, Any]) -> tuple[str, str, tuple[str, str]] | None:
        dispatch_id = str(row.get("dispatch_id") or "")
        root = str(row.get("sender_session_id") or "")
        if not dispatch_id:
            return None
        if not root:
            # Nowhere to deliver, ever. Terminal rather than retried, so it
            # stops occupying the queue — and recorded, so it is not silent.
            self.store.drop_delivery(dispatch_id, reason="no_sender_session")
            self.tally["dropped"] += 1
            return None
        owner = self.policy.sender_persona(root)
        if owner is None:
            self.store.drop_delivery(dispatch_id, reason="sender_session_unresolvable")
            self.tally["dropped"] += 1
            return None
        return dispatch_id, root, owner

    def probe(self, root: str, event_key: str) -> bool:
        if not self.policy.sender_is_idle(root):
            self.tally["busy"] += 1
            _record_sender_busy(event_key, root)  # A
            return False
        _telemetry.note_ownerless_streak(root, ownerless=False)  # A — episode over
        return True

    def claim(self, dispatch_id: str, root: str, event_key: str) -> bool:
        claim_id = f"serve-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        try:
            if not self.store.claim_delivery(dispatch_id, claim_id):
                _telemetry.record_bounce(  # A
                    event_key, GATE_UNCLAIMED, "store refused the claim", root=root
                )
                return False
        except Exception as exc:
            logger.debug("dispatch %s claim failed", dispatch_id, exc_info=True)
            _telemetry.record_bounce(event_key, GATE_UNCLAIMED, repr(exc), root=root)  # A
            return False
        return True

    def forge_turn(
        self, row: dict[str, Any], dispatch_id: str, root: str, owner: tuple[str, str]
    ) -> tuple[bool, dict[str, Any] | None, str]:
        persona_id, instance_id = owner
        try:
            ok, payload = self.forge(
                root_session_id=root,
                persona_id=persona_id,
                persona_instance_id=instance_id,
                message=format_dispatch_delivery(row),
                client_message_id=delivery_client_message_id(dispatch_id),
                dispatch_id=dispatch_id,
                notify_operator=bool(row.get("notify_operator")),
                state=str(row.get("state") or ""),
            )
        except Exception as exc:
            logger.warning("dispatch %s delivery turn failed", dispatch_id, exc_info=True)
            return False, None, repr(exc)  # A — the repr is the forge_error
        return ok, payload, ""

    def settle(
        self,
        dispatch_id: str,
        root: str,
        event_key: str,
        ok: bool,
        payload: dict[str, Any] | None,
        forge_error: str,
    ) -> None:
        if ok:
            self.store.mark_delivered(dispatch_id)
            self.tally["delivered"] += 1
            # The tally counts what moved through the QUEUE, which a silent
            # delivery genuinely did; the reason below is what carries whether
            # anyone saw it.
            reason, visibility_detail = _delivery_outcome(payload)  # A
            _telemetry.record_bounce(event_key, reason, visibility_detail, root=root)  # A
            return
        # The sender took its lease between the idle probe and the forge. That
        # is a RACE WITH A LIVE OPERATOR, not a failure — the completion is
        # perfectly deliverable and will be, moments later. Refund the attempt
        # the claim burned: without this, eight unlucky races walk a good
        # completion to a terminal `dropped` having never once failed.
        error_kind = str((payload or {}).get("error_kind") or "")
        # A DETERMINISTIC guard verdict is terminal on the FIRST occurrence: the
        # reply stays durable on the row, the real reason lands in
        # ``delivery_error`` where the Activity panel renders it, and the row
        # leaves the queue instead of replaying an identical refusal eight times.
        # ``harness mission-chat dispatch redeliver <id>`` re-arms it once the
        # verdict's cause is fixed. See :func:`vocabulary.terminal_forge_rejections`.
        if error_kind in terminal_forge_rejections():
            self.store.drop_delivery(
                dispatch_id,
                reason=f"{self.store.DROP_REASON_FORGE_REJECTED}:{error_kind}",
            )
            self.tally["dropped"] += 1
            _telemetry.record_bounce(  # A
                event_key, bounce_reason(GATE_FORGE_REJECTED, error_kind), forge_error, root=root
            )
            return
        busy = error_kind in transient_forge_refusals()
        self.store.release_delivery_claim(dispatch_id, refund_attempt=busy)
        if busy:
            self.tally["busy"] += 1
            _telemetry.record_bounce(event_key, GATE_FORGE_BUSY, "", root=root)  # A
            return
        self.tally["failed"] += 1
        failed = bounce_reason(GATE_FORGE_FAILED, error_kind or ("exception" if forge_error else "unknown"))
        _telemetry.record_bounce(event_key, failed, forge_error, root=root)  # A


def sweep_orphaned_dispatches() -> int:
    """Settle dispatches whose executing process is provably gone. Returns the count.

    Runs on the drain's own cadence, not only at boot. Boot-only was a real gap:
    a serve process can stay up for days, so a dispatch whose child died at 09:00
    stayed ``running`` — in the operator's HUD and in the sender's mental model —
    until the next restart. The sender was owed "the outcome is unknown" within a
    minute of it becoming true, not within a week.

    Identity-verified through the store's own sweep, which treats an unreadable
    start-time probe as absence of proof rather than as death.
    """

    from .. import dispatch_store

    try:
        return int((dispatch_store.restore_undelivered_dispatches() or {}).get("restored") or 0)
    except Exception:  # pragma: no cover - a sweep must never kill the drain
        logger.debug("dispatch orphan sweep failed", exc_info=True)
        return 0


def start_delivery_drain(
    *,
    stop_event: threading.Event,
    interval_seconds: float = DEFAULT_DRAIN_INTERVAL_SECONDS,
    policy: DrainPolicy | None = None,
) -> threading.Thread:
    """Run the drain on a daemon thread until *stop_event* is set.

    Daemon by contract: this loop must never be the reason a process cannot
    exit. Everything it would have done is durable, so the next boot picks it up
    — which is the same guarantee the restore-on-boot sweep provides.
    """

    # A — resolved ONCE, here, and captured by the loop closure below. Never
    # per pass: a persona turn flips HERMES_HOME process-globally while it runs
    # in THIS process, and an ambient mid-pass resolution would scatter the
    # mirror across whichever profile happened to be mid-turn.
    mirror_path = _drain_state_path()
    _telemetry.mark_started()  # A

    def _loop() -> None:
        global _drain_thread
        next_sweep = 0.0
        mirror_written_at = 0.0  # A — 0.0 makes the first pass write the file
        try:
            while not stop_event.wait(interval_seconds):
                revision_before = _telemetry.outcome_revision  # A
                try:
                    drain_once(policy=policy)
                except Exception:  # pragma: no cover - a drain must never die
                    logger.debug("dispatch delivery pass failed", exc_info=True)
                try:
                    drain_background_completions(policy=policy)
                except Exception:  # pragma: no cover
                    logger.debug("background completion pass failed", exc_info=True)
                # The orphan sweep runs on its own, slower cadence: it walks
                # every running row and probes PIDs, which is far too expensive
                # for the 5s delivery loop and far too rare for boot-only.
                now = time.monotonic()
                if now >= next_sweep:
                    next_sweep = now + ORPHAN_SWEEP_INTERVAL_SECONDS
                    sweep_orphaned_dispatches()
                # A — the cross-process mirror. Written when this pass changed
                # an outcome row, or once a heartbeat has elapsed. An idle serve
                # therefore touches the file once a minute and no more; a pass
                # that did nothing writes nothing.
                wall = time.time()
                if (
                    _telemetry.outcome_revision != revision_before
                    or (wall - mirror_written_at) >= DRAIN_MIRROR_HEARTBEAT_SECONDS
                ):
                    if _write_drain_state(mirror_path, live=True):
                        mirror_written_at = wall
        finally:
            # A — a dead drain must be legible from the file too, or a reader
            # cannot tell "no consumer" from "the mirror is simply old".
            _write_drain_state(mirror_path, live=False)
            # The capability binding reads this. A drain that died must stop the
            # runtime promising deliveries it can no longer make — the same
            # honesty rule that made the binding conditional in the first place.
            #
            # Cleared ONLY when this loop is still the registered drain. An
            # unconditional clear let an old loop's teardown null a drain that
            # had already been restarted, after which `delivery_drain_is_live()`
            # answered False forever and every dispatch was refused by a runtime
            # perfectly able to deliver.
            with _drain_lock:
                if _drain_thread is threading.current_thread():
                    _drain_thread = None

    thread = threading.Thread(
        target=_loop, name="harness-serve-dispatch-delivery", daemon=True
    )
    global _drain_thread
    with _drain_lock:
        _drain_thread = thread
    thread.start()
    return thread
