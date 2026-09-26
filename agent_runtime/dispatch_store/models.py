"""The dispatch row's vocabulary and codec (a vocabulary/table module —
floor-exempt): states, delivery states, drop reasons, re-arm outcomes and their
wire error kinds, the text and media bounds, row ↔ dict, the media-map shape
check.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any

from ..serde import bounded_text

__layer__ = "models"


_TABLE = "mission_chat_dispatches"


DELIVERY_PENDING = "pending"
DELIVERY_DELIVERED = "delivered"
DELIVERY_DROPPED = "dropped"

STATE_RUNNING = "running"
STATE_COMPLETED = "completed"
STATE_ERROR = "error"
STATE_UNKNOWN = "unknown"

#: The states a dispatch can END in. ``running`` is the only non-terminal one;
#: everything else is a completion the sender is owed an answer about, including
#: ``error`` and ``unknown`` — "it failed" and "nobody knows" are results a
#: waiting agent must receive, not rows to quietly bury.
TERMINAL_STATES = (STATE_COMPLETED, STATE_ERROR, STATE_UNKNOWN)

#: How long a delivery claim is honoured before another consumer may take it.
#: Same 300 s the delegation lane uses: long enough that a slow forge is not
#: raced, short enough that a claimant killed mid-delivery does not strand the
#: completion until the next reboot.
CLAIM_EXPIRY_SECONDS = 300.0
#: Terminal after this many failed delivery attempts. An unroutable row (its
#: chat root deleted, say) must converge instead of replaying forever.
MAX_DELIVERY_ATTEMPTS = 8

#: Why the attempt cap gave up, recorded on the ROW and not only on the event.
#: One constant because the two must never drift: the Activity projection reads
#: the row and the operator reads the projection, so a reason that lives only in
#: the event log renders as the useless "undelivered".
DROP_REASON_ATTEMPT_CAP = "attempt_cap"

#: Gateway Stage 7 (R8). Why a cross-install dispatch gave up: every attempt to
#: reach the paired install was a TRANSPORT failure, so the target never
#: answered and never refused.
#:
#: **This is the one place Stage 7 knowingly departs from R8's wording, and the
#: departure is what makes the ruling keep its own promise.** R8 says an offline
#: target "converges to ``dropped``". ``dropped`` is a DELIVERY state and it
#: means *the sender was never told* — which is exactly backwards for this case,
#: because "the other machine is not answering" is the single most useful thing
#: the sending agent could be told, and a ``dropped`` row is indistinguishable
#: in the Activity panel from a dispatch that evaporated. So the attempts CAP is
#: R8's, unchanged and spelled from the same
#: :data:`MAX_DELIVERY_ATTEMPTS` constant rather than a second number, and what
#: it converges to is a terminal ``error`` completion carrying this reason —
#: which then travels the ordinary delivery lane and lands in the sender's chat.
#: R8's naming half is honoured on the row, in the ``dispatch.completed`` event
#: and in the sentence the sender reads.
REMOTE_UNREACHABLE_REASON = "peer_unreachable"

#: Prefix for the OTHER terminal give-up: the forge refused this row for a
#: DETERMINISTIC reason (a guard verdict — foreign root, unknown persona,
#: retired instance). Spelled ``forge_rejected:<error_kind>`` on the row, so the
#: Activity panel renders the actual verdict instead of ``attempt_cap`` — which
#: is what an operator saw for 40 seconds' worth of eight identical refusals.
DROP_REASON_FORGE_REJECTED = "forge_rejected"

#: Outcomes of :func:`rearm_delivery`. A verb refusing a row must be able to say
#: WHICH refusal it was, so these are values rather than a bare ``False``.
REARM_REARMED = "rearmed"
REARM_NOT_FOUND = "not_found"
REARM_ALREADY_DELIVERED = "already_delivered"
REARM_NOT_DROPPED = "not_dropped"

#: The wire ``error_kind`` for each re-arm refusal, and for a store that could
#: not be read at all. Declared HERE, beside the outcomes they name, because
#: this module owns them — the CLI verb reads this table instead of re-spelling
#: the values, exactly as ``relay_policy`` and ``target_policy`` own theirs.
#: Registered for the record in
#: ``mission_chat_outcome.DELEGATED_ERROR_KIND_SOURCES``.
REARM_ERROR_KINDS = {
    REARM_NOT_FOUND: "dispatch_not_found",
    REARM_ALREADY_DELIVERED: "dispatch_already_delivered",
    REARM_NOT_DROPPED: "dispatch_not_dropped",
}
ERROR_KIND_DISPATCH_STORE_UNAVAILABLE = "dispatch_store_unavailable"

#: What :func:`~agent_runtime.dispatch_store.delivery.rearm_delivery` answers for
#: each delivery state (rule 12: the three-arm ladder as a table). Only a DROPPED
#: row is re-armed; a delivered one refuses (the sender was told), a pending one
#: refuses (it is already queued). A state not listed answers
#: :data:`REARM_NOT_DROPPED` — the refusal, never the write.
REARM_OUTCOME_BY_STATE: Mapping[str, str] = {
    DELIVERY_DELIVERED: REARM_ALREADY_DELIVERED,
    DELIVERY_PENDING: REARM_NOT_DROPPED,
    DELIVERY_DROPPED: REARM_REARMED,
}

#: Bound on the stored ask/reply text. The reply bound matches the relay tool's
#: own ``_REPLY_LIMIT`` (``tools/agent_chat_tool.py``) and the delivery lane's
#: ``dispatch_delivery.REPLY_LIMIT``; nothing downstream ever needs more, and the
#: store is not a transcript (the thread itself is, and the row points at it).
#: The three spellings are FENCED, not merely documented:
#: ``tests/agent_runtime/test_mirrored_constant_fences.py`` asserts they are
#: equal, because three bounds that disagree truncate one answer twice.
ASK_LIMIT = 4000
REPLY_LIMIT = 8000

_RETENTION_SECONDS = 7 * 24 * 60 * 60
_MAX_RETAINED_TERMINAL = 200


def mint_dispatch_id() -> str:
    """A dispatch handle. Short, opaque, and stable across processes."""

    return f"dispatch-{uuid.uuid4().hex[:12]}"


#: Bound on ONE completion's media map, and on the two strings each row carries.
#: The map arrives from ANOTHER INSTALL, so it is not merely large-by-accident
#: input, it is input a peer chooses — and this row is written into a database
#: this install reads on every media index. The mint on the far side is already
#: bounded (``media_handles.MAX_REPLY_ARTIFACTS``); this is the same bound
#: enforced by the RECEIVER, because a bound only the sender applies is a bound.
MEDIA_MAP_LIMIT = 16
MEDIA_REFERENCE_LIMIT = 1024
MEDIA_HANDLE_LIMIT = 128


def _media_rows(media: Any) -> list[dict[str, Any]]:
    """Normalise a completion's media map into the four keys the row stores.

    Shape-checked and bounded HERE rather than trusted, because this is the
    door between a peer's answer and this install's durable store. Anything that
    is not a row of the right shape is dropped: a malformed entry is a picture
    that will not resolve, and keeping it would only move the failure to the
    fetch, where it reads as a server fault instead of as an absent handle.

    Semantic validation — is that handle well formed, is that extension in the
    image allowlist — is deliberately NOT here. ``media_handles`` owns those
    rules and re-applies them every time it folds a stored row into a scope
    (``remote_artifacts_from_completions``), so a store that learned them would
    be a second copy of a policy, free to disagree with the first.
    """

    if not isinstance(media, list):
        return []
    rows: list[dict[str, Any]] = []
    for entry in media:
        if len(rows) >= MEDIA_MAP_LIMIT:
            break
        if not isinstance(entry, dict):
            continue
        reference = bounded_text(entry.get("reference"), MEDIA_REFERENCE_LIMIT)
        handle = bounded_text(entry.get("handle"), MEDIA_HANDLE_LIMIT)
        if not reference or not handle:
            continue
        size = entry.get("size_bytes")
        rows.append(
            {
                "reference": reference,
                "handle": handle,
                "media_type": bounded_text(entry.get("media_type"), 120),
                "size_bytes": int(size)
                if isinstance(size, int) and not isinstance(size, bool)
                else 0,
            }
        )
    return rows


def _row_to_dict(row: tuple) -> dict[str, Any]:
    (
        dispatch_id,
        sender_session_id,
        sender_persona_id,
        target_persona,
        target_instance_id,
        target_session_id,
        title,
        ask,
        state,
        notify_operator,
        dispatched_at,
        completed_at,
        updated_at,
        result_json,
        delivery_state,
        delivery_attempts,
        delivered_at,
        owner_pid,
        owner_started_at,
        relay_chain_json,
        delivery_error,
        remote_install_id,
    ) = row
    try:
        result = json.loads(result_json) if result_json else None
    except Exception:
        result = None
    try:
        relay_chain = json.loads(relay_chain_json) if relay_chain_json else []
    except Exception:
        relay_chain = []
    return {
        "dispatch_id": dispatch_id,
        "sender_session_id": sender_session_id or "",
        "sender_persona_id": sender_persona_id or "",
        "target_persona": target_persona or "",
        "target_instance_id": target_instance_id or "",
        "target_session_id": target_session_id or "",
        "title": title or "",
        "ask": ask or "",
        "state": state or "",
        "notify_operator": bool(notify_operator),
        "dispatched_at": float(dispatched_at or 0.0),
        "completed_at": float(completed_at) if completed_at else None,
        "updated_at": float(updated_at or 0.0),
        "result": result,
        "delivery_state": delivery_state or DELIVERY_PENDING,
        "delivery_attempts": int(delivery_attempts or 0),
        "delivered_at": float(delivered_at) if delivered_at else None,
        "owner_pid": int(owner_pid) if owner_pid else None,
        "owner_started_at": int(owner_started_at) if owner_started_at else None,
        "relay_chain": relay_chain if isinstance(relay_chain, list) else [],
        "delivery_error": delivery_error or "",
        # Empty string, never None: "this dispatch is local" is a fact every row
        # carries, and a consumer that had to tell absent from empty would be
        # deciding what a row written before Stage 7 meant.
        "remote_install_id": remote_install_id or "",
    }


_SELECT = f"""SELECT dispatch_id, sender_session_id, sender_persona_id, target_persona,
                     target_instance_id, target_session_id, title, ask, state,
                     notify_operator, dispatched_at, completed_at, updated_at,
                     result_json, delivery_state, delivery_attempts, delivered_at,
                     owner_pid, owner_started_at, relay_chain_json, delivery_error,
                     remote_install_id
              FROM {_TABLE}"""
