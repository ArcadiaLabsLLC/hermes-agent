"""The delivery drain's vocabulary: the provenance marker, the bounds, the reasons, the forge-refusal classes."""

from __future__ import annotations

__layer__ = "models"


#: Provenance stamped on every forged delivery turn. The launcher renders turns
#: by origin, so this is what lets a delivered result read as a delivered result
#: instead of as something the operator typed.
#:
#: This is the PREFIX, not the whole value — see :func:`delivery_requested_by`.
DELIVERY_REQUESTED_BY = "harness-delivery"

#: Bound on the reply carried into the delivery message. Mirrors the relay
#: tool's own reply bound and ``dispatch_store.REPLY_LIMIT``: past this, the
#: answer belongs in the thread it was written in, which the block points at.
#: Fenced against a one-sided edit by
#: ``tests/agent_runtime/test_mirrored_constant_fences.py``.
REPLY_LIMIT = 8000


def terminal_forge_rejections() -> frozenset[str]:
    """``error_kind`` values a RETRY can never turn into a delivery.

    The attempt cap exists to converge rows that are genuinely undeliverable
    (their chat root deleted, say) — a budget for TRANSIENT failure. It is the
    wrong instrument entirely for a GUARD VERDICT: a foreign-root refusal, an
    unknown persona, a retired instance are pure functions of state that a
    delivery attempt does not touch, so attempt eight is refused for exactly the
    reason attempt one was. Burning all eight buys nothing, costs ~40 s of drain
    passes, and — worst of it — ends with ``attempt_cap`` written to
    ``delivery_error``, which is what the operator's Activity panel then shows
    instead of the verdict that actually happened. That is precisely how the
    2026-08-24 ``foreign_chat_session`` outage (dispatch-2540634d5cf3) presented:
    the panel said the attempts ran out, never that a guard said no.

    Derived from the OWNED vocabulary rather than re-spelled, so a kind added to
    ``mission_chat_outcome`` cannot quietly fall out of this class: every
    admission refusal, plus the chat-root refusals MINUS ``chat_busy`` — the one
    member of that family which is a live-operator race and the definition of
    transient (it keeps the refund path below).

    Everything not named here — busy, lease contention, transport, an exception
    out of the forge — keeps the existing cap/refund semantics.
    """

    from ..mission_chat_outcome import (
        ADMISSION_ERROR_KINDS,
        CHAT_ROOT_ERROR_KINDS,
        ChatErrorKind,
    )

    kinds = (set(ADMISSION_ERROR_KINDS) | set(CHAT_ROOT_ERROR_KINDS)) - {
        ChatErrorKind.CHAT_BUSY
    }
    return frozenset(str(kind) for kind in kinds)


def transient_forge_refusals() -> frozenset[str]:
    """``error_kind`` values that name a LIVE RACE, so the attempt is refunded.

    ``chat_busy`` was the only member while the busy seam gave one answer.
    ``chat_turn_duplicate_in_flight`` (2026-08-24) is the second, and it is
    stronger evidence of the same thing: it says the root is busy running THIS
    dispatch's own delivery turn. ``delivery_client_message_id`` derives the
    idempotency key from the dispatch id rather than minting one per attempt
    (deliberately — it is what makes the chat lane's replay dedupe work), so
    this lane genuinely re-presents an in-flight id and genuinely sees the new
    kind. Burning an attempt for it would walk a perfectly deliverable
    completion toward ``dropped`` for the crime of being answered right now.
    """

    from ..mission_chat_outcome import ChatErrorKind

    return frozenset(
        {
            str(ChatErrorKind.CHAT_BUSY),
            str(ChatErrorKind.CHAT_TURN_DUPLICATE_IN_FLIGHT),
        }
    )

#: How often the drain looks for work. Deliberately unhurried — a completion is
#: not latency-critical, and every pass costs a lease probe plus a journal read
#: on a process that is also running turns.
DEFAULT_DRAIN_INTERVAL_SECONDS = 5.0

#: Per-pass delivery cap. Ten completions landing at once must not turn into ten
#: back-to-back forged turns that monopolise the sender's thread.
MAX_DELIVERIES_PER_PASS = 3

#: How often the orphan sweep runs. Its own cadence, deliberately: it walks every
#: running row and probes PIDs, which is too expensive for the 5s delivery loop —
#: and boot-only, which is what it was, meant a dispatch whose process died could
#: sit ``running`` in the HUD for as long as serve stayed up.
ORPHAN_SWEEP_INTERVAL_SECONDS = 60.0

#: Attempt cap for queue-backed background completions that have NO durable row
#: to count on — ``terminal`` notifications, and any completion whose producer
#: never persisted it. Without a cap a persistently-failing event would requeue
#: every drain pass forever.
#:
#: ``delegate_task`` completions are deliberately NOT counted here: they DO have
#: a durable row, ``async_delegations``, whose ``delivery_attempts`` column is
#: the authority the gateway, the interactive CLI and the TUI gateway have all
#: counted against since the lane shipped. Two counters for one completion is a
#: second ledger, which is the whole defect this cap must not reintroduce.
MAX_BACKGROUND_DELIVERY_ATTEMPTS = 8


#: Outcome rows telemetry keeps. Keyed by ``(event_key, reason)`` so a stuck
#: event occupies ONE row per reason with a rising ``count`` rather than a
#: growing list. Bounded by construction: past this, the oldest row is evicted.
MAX_DRAIN_OUTCOME_ROWS = 32

#: Per-row detail bound. Details carry owner payloads and exception reprs, both
#: of which are unbounded at the source.
DRAIN_DETAIL_LIMIT = 240

#: Re-log an unchanged ``(event_key, reason)`` pair every Nth repeat — ≈ once a
#: minute at the 5s cadence. Per-pass logging of a stuck event is spam that
#: buries the pass that matters.
DRAIN_REPEAT_LOG_EVERY = 12

#: Consecutive ``lease_busy_ownerless`` probes on one root before the escalation
#: WARNING. ONE sample is not evidence: the lease release order is
#: unlink-owner-then-unlock (``persona_chat_continuity``), so a releasing holder
#: caught mid-window looks exactly like a stale lock. Repeats are the proof.
DRAIN_OWNERLESS_WARN_AFTER = 3

#: The two reasons a forged turn that RAN is recorded under. Both are
#: deliveries — the row settles, the queue moves, the completion is gone from it
#: — but only ``delivered`` put something on the operator's screen.
#:
#: 2026-08-11, the defect this split exists for: the drain called ``ok`` from the
#: forge "delivered" and stopped there. One delivery turn's model returned no
#: content three times over, so the completion notice landed in the thread and
#: was answered by nothing at all — while the log line, ``last_delivery`` and
#: ``harness status`` all reported a clean delivery. A report that cannot tell
#: "the operator has been told" from "the operator has been told nothing" is
#: worse than no report, because it is the one that gets trusted.
DELIVERED_REASON = "delivered"
DELIVERED_SILENT_REASON = "delivered_silent"

#: Both of the above. Membership here is what makes an outcome count as a
#: delivery for ``last_delivery`` — a silent delivery is still the last thing
#: this drain delivered, and hiding it from that field would restore exactly the
#: blindness the split is here to end.
DELIVERY_REASONS = frozenset({DELIVERED_REASON, DELIVERED_SILENT_REASON})

#: The busy sub-reasons :func:`~agent_runtime.dispatch_delivery.forge.
#: _probe_sender_idle` answers with — ``IdleProbe``'s own vocabulary, one entry
#: per distinct cause (the probe's docstring says what each one means). A probe
#: carrying anything else is refused at construction.
IDLE_JOURNAL_INFLIGHT = "journal_inflight"
IDLE_JOURNAL_UNREADABLE = "journal_unreadable"
IDLE_LEASE_BUSY_OWNED = "lease_busy_owned"
IDLE_LEASE_BUSY_OWNERLESS = "lease_busy_ownerless"
IDLE_LEASE_PROBE_ERROR = "lease_probe_error"
IDLE_SUB_REASONS: tuple[str, ...] = (
    IDLE_JOURNAL_INFLIGHT,
    IDLE_JOURNAL_UNREADABLE,
    IDLE_LEASE_BUSY_OWNED,
    IDLE_LEASE_BUSY_OWNERLESS,
    IDLE_LEASE_PROBE_ERROR,
)
#: What the ACCOUNTING says when it has no probe to read (a test overrode the
#: decision) or the probe carried no sub-reason. Never produced by the probe.
IDLE_UNPROBED = "unprobed"
IDLE_UNKNOWN = "unknown"

#: The gates a drain outcome is recorded under — the one vocabulary with
#: seventeen writers (every ``[D]`` site of both lanes) and one reader
#: (``_DrainTelemetry.snapshot``). A composite reason is ``<gate>:<detail>``;
#: the GATE is the part before the first colon, and only ``sender_busy``'s
#: detail is closed (:data:`IDLE_SUB_REASONS` + the two accounting words) —
#: ``forge_rejected`` / ``forge_failed`` carry a ``ChatErrorKind``, which
#: ``mission_chat_outcome`` owns. ``record_bounce`` refuses anything else.
#: Plain strings, not a StrEnum: ``dropped``-class words are spelled fork-wide
#: for other questions, and the gate must not count those (program batch-1 rule).
GATE_NOT_OWNED = "not_owned"
GATE_NO_ROOT = "no_root"
GATE_OWNER_UNRESOLVED = "owner_unresolved"
GATE_EMPTY_TEXT = "empty_text"
GATE_PERSONA_INSTANCE_MISSING = "persona_instance_missing"
GATE_SENDER_BUSY = "sender_busy"
GATE_STEERED = "steered"
GATE_UNCLAIMED = "unclaimed"
GATE_ABANDONED = "abandoned"
GATE_FORGE_REJECTED = "forge_rejected"
GATE_FORGE_BUSY = "forge_busy"
GATE_FORGE_FAILED = "forge_failed"
BOUNCE_GATES: tuple[str, ...] = (
    DELIVERED_REASON,
    DELIVERED_SILENT_REASON,
    GATE_NOT_OWNED,
    GATE_NO_ROOT,
    GATE_OWNER_UNRESOLVED,
    GATE_EMPTY_TEXT,
    GATE_PERSONA_INSTANCE_MISSING,
    GATE_SENDER_BUSY,
    GATE_STEERED,
    GATE_UNCLAIMED,
    GATE_ABANDONED,
    GATE_FORGE_REJECTED,
    GATE_FORGE_BUSY,
    GATE_FORGE_FAILED,
)


def bounce_reason(gate: str, detail: str) -> str:
    """The composite ``<gate>:<detail>`` spelling, written in one place."""

    return f"{gate}:{detail}"


def refused_bounce_reason(reason: str) -> str | None:
    """Why *reason* is outside the closed vocabulary, or ``None`` when it is inside."""

    gate, _, detail = str(reason or "").partition(":")
    if gate not in BOUNCE_GATES:
        return f"unknown gate {gate!r}"
    if gate == GATE_SENDER_BUSY and detail not in (*IDLE_SUB_REASONS, IDLE_UNPROBED, IDLE_UNKNOWN):
        return f"unknown sender_busy sub-reason {detail!r}"
    return None

#: The durable cross-process mirror of the state below, written under the
#: agent-runtime store root. REQUIRED, not a nicety: the launcher's visibility
#: probe runs ``harness status --json`` as a freshly spawned process, where the
#: drain's in-memory state does not exist.
#:
#: MUST NOT be added to any freshness fingerprint (serve's
#: ``_FINGERPRINT_ROOT_FILES``/``_FINGERPRINT_STORE_DIRS``,
#: ``running_work_store_paths()``, or ``stream._scope_fingerprint``): it changes
#: every ≤60s by design, which inside a fingerprint would hold the read-model
#: cache permanently cold and make the stream emit ``state.reconciled`` forever.
#: Same churn rationale as the per-session turn store's documented exclusion.
DRAIN_STATE_FILENAME = "dispatch_delivery_drain.json"

#: Heartbeat bound on mirror writes. A pass that changed nothing writes nothing
#: until this elapses, so an idle serve touches the file once a minute.
DRAIN_MIRROR_HEARTBEAT_SECONDS = 60.0


def delivery_client_message_id(dispatch_id: str) -> str:
    """The idempotency key for a dispatch's delivery turn.

    Derived from the dispatch id rather than minted per attempt, so the chat
    lane's EXISTING dedup (client-message-id replay + resend detection) makes a
    retried delivery converge on one turn instead of doubling the message. The
    store's claim protocol makes a double attempt unlikely; this makes a double
    TURN impossible, which is the part the sender would actually see.
    """

    return f"dispatch-delivery-{dispatch_id}"


def delivery_requested_by(
    dispatch_id: str, *, notify_operator: bool = False, state: str | None = None
) -> str:
    """The ``requested_by`` provenance a forged delivery turn is sent under.

    Shape: ``harness-delivery:<dispatch_id>:<0|1>:<state>``. Structured
    provenance in this field is the ESTABLISHED convention on this lane, not a
    new one — an ``agent_chat_send`` relay already travels as
    ``agent:<caller session id>`` and the mission-chat handler already decodes
    that into the marker its user row is typed with. A delivery follows the same
    road.

    Three facts ride along because the handler is the last place that has them
    and the persisted row is the last place they can be recovered from: WHICH
    dispatch this settles, whether the dispatching agent flagged the operator to
    be told, and HOW IT ENDED. Without the first two, a consumer would have to
    join against a ``running_work`` row that no longer exists by then (a
    dispatch leaves that projection the moment it stops running). Without the
    third, an ``error`` delivery is indistinguishable from a successful one
    except in prose — and ``pending_deliveries`` selects ``state != running``,
    so failures genuinely travel this lane.
    """

    from ..relay_policy import HARNESS_DELIVERY_UNKNOWN_STATE

    settled = (state or "").strip() or HARNESS_DELIVERY_UNKNOWN_STATE
    return (
        f"{DELIVERY_REQUESTED_BY}:{str(dispatch_id or '').strip()}:"
        f"{'1' if notify_operator else '0'}:{settled}"
    )


def parse_delivery_requested_by(value):
    """Decode a ``requested_by`` value into a ``HarnessDeliveryOrigin`` or None.

    Tolerates the bare ``harness-delivery`` (no suffix) that a pre-attribution
    build stamped: those rows are still deliveries and must still render as
    deliveries; they simply carry no dispatch id, no flag, and an ``unknown``
    outcome. Returns ``None`` for every other value, so operator, CLI,
    coordinator and relay sends are untouched.
    """

    from ..relay_policy import HARNESS_DELIVERY_UNKNOWN_STATE, HarnessDeliveryOrigin

    if not isinstance(value, str):
        return None
    token = value.strip()
    if token == DELIVERY_REQUESTED_BY:
        return HarnessDeliveryOrigin()
    prefix = f"{DELIVERY_REQUESTED_BY}:"
    if not token.startswith(prefix):
        return None
    parts = token[len(prefix):].split(":", 3)
    dispatch_id = parts[0].strip() if parts else ""
    flag = parts[1].strip() if len(parts) > 1 else ""
    state = parts[2].strip() if len(parts) > 2 else ""
    return HarnessDeliveryOrigin(
        dispatch_id=dispatch_id or None,
        notify_operator=flag == "1",
        state=state or HARNESS_DELIVERY_UNKNOWN_STATE,
    )


#: How long the drain waits for a live turn to acknowledge a completion steer. The turn's
#: inbox watcher polls every 50 ms; past this the completion is re-queued for its idle turn.
STEER_ACK_SECONDS = 2.0
