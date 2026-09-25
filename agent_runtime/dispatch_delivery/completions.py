"""The background-completion lane: ownership, the durable claim/settle, the steer, drain_background_completions."""

from __future__ import annotations

import logging
from typing import Any, Callable

from .accounting import (
    _LAST_IDLE_PROBE,
    _delivery_outcome,
    _event_key,
    _record_sender_busy,
    _telemetry,
)
from .forge import _sender_is_idle, _sender_persona, forge_delivery_turn
from .vocabulary import (
    MAX_BACKGROUND_DELIVERY_ATTEMPTS,
    STEER_ACK_SECONDS,
    _transient_forge_refusals,
)

__layer__ = "lanes"

logger = logging.getLogger(__name__)


#: Per-event failure counts for the LEDGERLESS half of the queue lane, keyed by
#: the event's own identity. Process-local by nature — the queue it guards is
#: process-local too, and so is the class of event it covers.
_background_attempts: dict[str, int] = {}


def _owns_event_with_accounting(evt: dict[str, Any]) -> bool:
    """The queue's ownership filter — same boolean, now visible when it says no.

    DECISION [D]: byte-identical to the ``lambda evt:
    _chat_root_of_completion(evt) is not None`` it replaces. Upstream's
    ``drain_notifications`` re-queues a non-owned event internally, where the
    caller cannot see it, so this closure — which IS ours — is the only place
    ``not_owned`` can be observed without editing an upstream file.

    ACCOUNTING [A]: the ``record_bounce`` line, and nothing else.
    """

    root = _chat_root_of_completion(evt)
    if root is None and _orphaned_persona_root(evt) is not None:
        return True  # taken off the queue to be DROPPED, loudly, by the drain
    if root is None:
        try:  # A — accounting must never be able to change the answer below
            _telemetry.record_bounce(
                _event_key(evt),
                "not_owned",
                f"session_key={str(evt.get('session_key') or '')!r}",
            )
        except Exception:  # pragma: no cover - defensive
            logger.debug("drain ownership accounting failed", exc_info=True)
        return False
    return True


# --------------------------------------------------------------------------
# background-completion lane (delegate_task / terminal notifications)
# --------------------------------------------------------------------------


def _chat_root_of_completion(evt: dict[str, Any]) -> str | None:
    """The persona chat root a queued completion belongs to, or None.

    POSITIVE proof, in the sense ``drain_notifications`` means it: the event has
    to NAME a session that resolves to a live persona instance's chat lane in
    this runtime. Gateway and CLI sessions resolve to nothing here and are left
    queued for their own consumers rather than adopted — the #64484 rule, which
    is why this returns None instead of guessing.
    """

    for key in ("origin_ui_session_id", "parent_session_id", "session_key", "session_id"):
        candidate = str(evt.get(key) or "").strip()
        if not candidate.startswith("persona_chat_"):
            continue
        if _sender_persona(candidate) is not None:
            return candidate
    return None


def _orphaned_persona_root(evt: dict[str, Any]) -> str | None:
    """The persona chat root a PROCESS completion names when nobody owns it now, else None.

    The persona-instance-gone drop the owner ruling of 2026-09-24 gives this lane (it used
    to live in ``tools/process_registry.py``'s late-notify block): a ``terminal``
    completion stamped with a ``persona_chat_`` root whose instance was retired has
    nowhere to land, and re-queueing it would spin forever. Only a store that ANSWERS
    "no owner" counts — an unreadable lookup returns None (absence of proof is not
    proof of absence), and any owned candidate means the event is deliverable.
    """

    if str(evt.get("type") or "") != "completion":
        return None
    orphan = None
    for key in ("origin_ui_session_id", "parent_session_id", "session_key", "session_id"):
        candidate = str(evt.get(key) or "").strip()
        if not candidate.startswith("persona_chat_"):
            continue
        try:
            owner = _sender_persona(candidate)
        except Exception:
            logger.debug("owner lookup failed for %s", candidate, exc_info=True)
            return None
        if owner is not None:
            return None
        orphan = orphan or candidate
    return orphan


def _steer_into_busy_turn(
    evt: dict[str, Any], root: str, owner: tuple[str, str], text: str, key: str
) -> bool:
    """Deliver a PROCESS completion into the turn running on ``root``. True when accepted.

    Owner ruling 2026-09-24: a background-process completion that arrives while its
    thread is mid-turn is a STEER into that turn, not a separate turn queued after it.
    The path is upstream's steer door, ``AIAgent.steer(text)`` (appended to the next tool
    result by ``apply_pending_steer_to_tool_results``), reached through the mission-chat
    steer inbox the live turn already watches (``mission_chat_steer``). A turn with no
    steer handle, or one that ends before acknowledging, answers "not accepted" and the
    caller re-queues — the idle turn then carries it, so nothing is lost.
    """

    if str(evt.get("type") or "") != "completion":
        return False
    try:
        from ..mission_chat_steer import submit_mission_chat_steer
        from ..paths import store_root

        result = submit_mission_chat_steer(
            runtime_root=store_root(),
            session_id=root,
            message=text,
            client_message_id=f"bg-steer-{key}",
            persona_id=owner[0],
            persona_instance_id=owner[1],
            timeout_seconds=STEER_ACK_SECONDS,
        )
    except Exception:
        logger.debug("completion steer into %s failed", root, exc_info=True)
        return False
    return bool(result.get("ok")) and result.get("execution_state") == "accepted"


def _claim_durable_completion(evt: dict[str, Any]) -> str | None:
    """Claim a queued completion's durable row. ``""`` when it has none.

    Three outcomes, and the middle one is why this is not a bool:

    * ``""`` — LEDGERLESS. The event is not a ``delegate_task`` completion (a
      ``terminal`` notification, say), or its producer never persisted a row, or
      the store could not be reached. Delivery proceeds and the process-local
      attempt counter governs it.
    * a claim id — the row was ``async_delegations``-backed and is now ours for
      this pass. The claim itself counted the attempt.
    * ``None`` — the row exists and is NOT claimable: another consumer holds it,
      or it already settled. The caller must not deliver.

    A store this process cannot reach fails OPEN, deliberately: the ledger is
    accounting, the forge is the operator's answer, and refusing to deliver a
    finished result because a bookkeeping table was unreadable would trade the
    defect above for a strictly worse one. The cost is a possible duplicate
    delivery, which the chat lane's ``client_message_id`` replay already
    converges, and it is logged rather than silent.
    """

    if str(evt.get("type") or "") != "async_delegation":
        return ""
    try:
        from tools.async_delegation import claim_event_delivery
    except Exception:
        logger.debug("durable completion claim unavailable", exc_info=True)
        return ""
    try:
        return claim_event_delivery(evt, "harness-serve")
    except Exception:
        logger.warning(
            "could not claim durable completion %s; delivering unclaimed",
            evt.get("delegation_id"),
            exc_info=True,
        )
        return ""


def _settle_durable_completion(
    evt: dict[str, Any], claim: str, *, delivered: bool
) -> None:
    """Write a delivery outcome back to the row that owns it. Never raises.

    ``delivered`` acknowledges; anything else releases the claim so another
    consumer — or this drain on a later pass — may retry, with the row's own
    attempt budget deciding when retrying stops. A ledgerless event (empty
    *claim*) has nothing to settle.
    """

    if not claim:
        return
    try:
        from tools.async_delegation import (
            complete_event_delivery,
            release_event_delivery,
        )
    except Exception:  # pragma: no cover - defensive
        logger.debug("durable completion settle unavailable", exc_info=True)
        return
    try:
        if delivered:
            complete_event_delivery(evt, claim)
        else:
            release_event_delivery(evt, claim)
    except Exception:
        logger.warning(
            "could not settle durable completion %s (delivered=%s)",
            evt.get("delegation_id"),
            delivered,
            exc_info=True,
        )


def drain_background_completions(*, forge: Callable | None = None) -> dict[str, int]:
    """Deliver ``delegate_task(background)`` / ``terminal`` completions.

    These already publish to ``process_registry.completion_queue`` — the CLI and
    the gateway have drained it for a long time; serve never did, which is the
    only reason those tools had to be refused on the persona-chat lane. With
    this drain running, the same completions become delivery turns through the
    same forged-turn path a dispatch uses, so the two lanes cannot diverge in
    how a background result reaches an agent.

    Ownership is proven per event, not assumed per process: an event that does
    not name a resolvable persona chat root is re-queued untouched.

    The durable row is settled through ITS OWN authority, not a second ledger
    ------------------------------------------------------------------------
    ``delegate_task`` completions are persisted to ``async_delegations`` before
    they are ever queued, and that row carries the whole delivery protocol:
    ``delivery_state``, ``delivery_attempts``, ``delivery_claim``,
    ``delivered_at``. The gateway, the interactive CLI and the TUI gateway have
    always driven it through ``claim_event_delivery`` /
    ``complete_event_delivery`` / ``release_event_delivery``. Serve was the one
    consumer that did not: it drained the in-memory queue, forged a real turn,
    and left the row ``pending`` with ``delivery_attempts: 0`` forever.

    That was not cosmetic. Three things followed from it, and a live 2026-08-10
    delegation (``deleg_1f53b4be``) exhibited all three at once — a completion
    that HAD been delivered into the operator's thread while every durable field
    said no attempt was ever made:

    * **The forensics lied in the worst direction.** ``delivery_attempts: 0`` on
      a delivered row reads as "the drain never picked it up", which is the one
      conclusion the evidence cannot support and the first one an investigator
      draws.
    * **Every serve delivery was re-armed for replay.** ``restore_undelivered_
      completions`` selects exactly ``state != 'running' AND delivery_state =
      'pending'``, so serve's own successful deliveries were re-queued at the
      next boot. The chat lane's ``client_message_id`` replay dedup is what has
      been absorbing them — an idempotency guard silently doing a ledger's job,
      and only for as long as the turn journal retains the record.
    * **Retention could not do its job.** ``_prune_durable_records`` deletes
      ``delivery_state='delivered'`` rows first and falls back to evicting the
      OLDEST pending ones; with nothing ever marked delivered, the fallback is
      the only path, so undelivered work is what gets dropped.

    So the claim is taken here, after the idle probe (never before — a burnt
    attempt for losing a race with a live operator is the failure class the
    dispatch lane already had to fix) and before the forge, and the outcome is
    written back to the row that owns it. A claim this process cannot take means
    another consumer holds it or the row already settled: the event leaves the
    queue rather than spinning, because the durable row — not this queue — is
    the authority on whether the completion is still owed.

    A LEDGERLESS event (a ``terminal`` notification; a completion whose producer
    never persisted a row) claims nothing, and only those fall back to the
    process-local :data:`MAX_BACKGROUND_DELIVERY_ATTEMPTS` counter. Without it
    such an event re-queues every five seconds forever — an invisible hot loop
    that also blocks the queue behind it — so past the cap it is dropped with a
    WARNING naming it, because an event that can never be delivered should end
    loudly rather than spin quietly.
    """

    tally = {
        "considered": 0,
        "delivered": 0,
        "requeued": 0,
        "failed": 0,
        "abandoned": 0,
        "unclaimed": 0,
        "dropped": 0,
        "steered": 0,
    }
    forge = forge or forge_delivery_turn
    try:
        from tools.process_registry import process_registry
    except Exception:
        return tally

    _telemetry.note_pass_start()  # A — a pass with no finish is a HUNG pass
    try:
        pairs = process_registry.drain_notifications(
            # D — the boolean is byte-identical to the `lambda evt:
            # _chat_root_of_completion(evt) is not None` this replaces. The
            # named function exists so `not_owned` is visible: upstream
            # re-queues a rejected event INSIDE drain_notifications, where the
            # caller can never see it, and this closure is ours.
            owns_event=_owns_event_with_accounting,
            skip_poll_observed=False,
        )
    except Exception:
        logger.debug("background completion drain failed", exc_info=True)
        _telemetry.note_pass_finished(tally)  # A
        return tally

    for evt, text in pairs:
        # A — a probe stashed for a PREVIOUS event must never be attributed to
        # this one. Cleared per event, never carried across.
        _LAST_IDLE_PROBE.set(None)
        tally["considered"] += 1
        root = _chat_root_of_completion(evt)
        owner = _sender_persona(root) if root else None
        # The queue has no durable per-event id, so the dedup key is derived
        # from the event's own stable identity (the process/delegation id plus
        # its type) rather than minted per attempt. Derived ONCE per event and
        # reused by both the forge's client_message_id below and the accounting
        # rows, so the two can never name the same completion differently.
        key = _event_key(evt)
        orphan = _orphaned_persona_root(evt) if root is None else None
        if orphan is not None:
            # The instance that spawned it is gone: DROP, and say so. A silently
            # abandoned completion is the failure class this lane exists to retire.
            logger.warning(
                "process completion %s dropped: no persona instance owns chat root %s",
                key,
                orphan,
            )
            tally["dropped"] += 1
            _telemetry.record_bounce(key, "persona_instance_missing", f"root={orphan}", root=orphan)
            continue
        if root is None or owner is None or not text:
            # Ownership was proven at drain time; if it cannot be re-proven now
            # the event goes BACK on the queue rather than being dropped.
            process_registry.completion_queue.put(evt)
            tally["requeued"] += 1
            # A — name WHICH operand failed, tested in the order the `or`
            # expression above already evaluates them.
            if root is None:
                reason = "no_root"
                detail = f"session_key={str(evt.get('session_key') or '')!r}"
            elif owner is None:
                reason = "owner_unresolved"
                detail = f"root={root}"
            else:
                reason = "empty_text"
                detail = f"root={root}"
            _telemetry.record_bounce(key, reason, detail, root=root or "")
            continue
        if not _sender_is_idle(root):
            if _steer_into_busy_turn(evt, root, owner, text, key):
                tally["steered"] += 1
                _telemetry.record_bounce(key, "steered", f"root={root}", root=root)  # A
                continue
            process_registry.completion_queue.put(evt)
            tally["requeued"] += 1
            _record_sender_busy(key, root)  # A
            continue
        _telemetry.note_ownerless_streak(root, ownerless=False)  # A — episode over
        persona_id, instance_id = owner
        # Taken AFTER the idle probe: a claim burnt on a busy sender would spend
        # a durable attempt on a race with a live operator, which is the exact
        # over-counting the dispatch lane's `refund_attempt` had to undo.
        claim = _claim_durable_completion(evt)
        if claim is None:
            # The row is not ours to deliver: another consumer holds the claim,
            # or it already settled. Not re-queued — spinning on a completion
            # somebody else owns is how a queue silently starves the events
            # behind it.
            tally["unclaimed"] += 1
            _telemetry.record_bounce(  # A
                key,
                "unclaimed",
                "durable row held by another consumer, or already settled",
                root=root,
            )
            continue
        durable = bool(claim)
        if (
            not durable
            and _background_attempts.get(key, 0) >= MAX_BACKGROUND_DELIVERY_ATTEMPTS
        ):
            # Terminal, and LOUD. A silently-abandoned completion is the failure
            # class this whole lane exists to retire, so it leaves a named log
            # line rather than disappearing off the queue.
            #
            # Only ledgerless events reach here. A durable one converges through
            # its own row instead: the release below drops it to a terminal
            # state once its attempts are spent, and the claim above then
            # refuses it for good.
            logger.warning(
                "abandoning background completion %s after %d failed deliveries into %s",
                key,
                MAX_BACKGROUND_DELIVERY_ATTEMPTS,
                root,
            )
            _background_attempts.pop(key, None)
            tally["abandoned"] += 1
            _telemetry.record_bounce(  # A
                key,
                "abandoned",
                f"{MAX_BACKGROUND_DELIVERY_ATTEMPTS} failed deliveries, dropped for good",
                root=root,
            )
            continue
        forge_error = ""  # A
        try:
            ok, payload = forge(
                root_session_id=root,
                persona_id=persona_id,
                persona_instance_id=instance_id,
                message=text,
                client_message_id=f"bg-completion-{key}",
            )
        except Exception as exc:
            logger.warning("background completion delivery failed", exc_info=True)
            ok, payload = False, None
            forge_error = repr(exc)  # A
        if ok:
            # Acknowledge on the row that owns the question. Without this the
            # next boot's restore sweep re-queues a completion this process
            # already delivered.
            _settle_durable_completion(evt, claim, delivered=True)
            _background_attempts.pop(key, None)
            tally["delivered"] += 1
            reason, visibility_detail = _delivery_outcome(payload)  # A
            _telemetry.record_bounce(  # A
                key,
                reason,
                "; ".join(
                    part
                    for part in (
                        f"producer_started_at={evt.get('started_at')!r}",
                        visibility_detail,
                    )
                    if part
                ),
                root=root,
            )
            continue
        _settle_durable_completion(evt, claim, delivered=False)
        process_registry.completion_queue.put(evt)
        # Same rule the dispatch lane follows: losing a race with a live
        # operator is not a failure, so a `chat_busy` refusal does not count
        # against the cap.
        error_kind = str((payload or {}).get("error_kind") or "")
        if error_kind in _transient_forge_refusals():
            tally["requeued"] += 1
            _telemetry.record_bounce(key, "forge_busy", "", root=root)  # A
        elif durable:
            # The durable row counted this attempt at claim time; counting it
            # here as well is the second ledger, so the tally records the
            # failure and nothing else does.
            tally["failed"] += 1
            _telemetry.record_bounce(  # A
                key,
                f"forge_failed:{error_kind or ('exception' if forge_error else 'unknown')}",
                forge_error,
                root=root,
            )
        else:
            _background_attempts[key] = _background_attempts.get(key, 0) + 1
            tally["failed"] += 1
            _telemetry.record_bounce(  # A
                key,
                f"forge_failed:{error_kind or ('exception' if forge_error else 'unknown')}",
                forge_error,
                root=root,
            )
    _telemetry.note_pass_finished(tally)  # A
    return tally
