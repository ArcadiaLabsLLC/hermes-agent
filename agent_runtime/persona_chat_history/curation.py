"""A session's persisted rows curated into the operator transcript, with its revision and cursor.

Separate because it is the transcript's one policy: which row renders, as
which role, in which order, and what the redaction verdict is.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from ..mission_chat_turns import mission_chat_turn_elements, mission_chat_turn_records
from ..persona_assignments import safe_assignment_text, safe_assignment_token
from ..relay_policy import parse_harness_delivery_marker, parse_relay_sender_marker
from ..runtime_hud import extract_runtime_context_envelope, extract_skill_preload_envelope
from ..transcript_order import TURN_SEQ_OPERATOR, TURN_SEQ_TERMINAL
from .markers import (
    _carry_run_budget,
    _ordered_message_rows,
    _silent_turn_marker_row,
    _terminal_turn_marker_rows,
)
from .text import (
    _curate_chat_message_text,
    _iso_timestamp,
    _safe_display_body_text,
    _safe_message_role,
)
from .vocabulary import (
    CHAT_READ_FAILED,
    CHAT_READ_UNAVAILABLE,
    CHAT_REDACTION_UNKNOWN,
    PERSONA_CHAT_MESSAGE_TEXT_LIMIT,
    PERSONA_HARNESS_DELIVERY_KIND,
    PERSONA_PRE_TRACE_ACK_FINISH_REASON,
    PERSONA_PRE_TRACE_ACK_KIND,
    PERSONA_RELAYED_MESSAGE_KIND,
    canonical_persona_chat_turn_id,
    logical_persona_chat_client_message_id,
)

__layer__ = "policy"
__all__ = [
    "_safe_curated_messages",
    "_history_revision",
    "_encode_history_cursor",
    "_decode_history_cursor",
]


def _safe_curated_messages(
    session_db: Any | None,
    *,
    session_id: str,
) -> tuple[list[dict[str, Any]], str, dict[str, Any] | None]:
    """Return every redaction-safe operator-facing row for one logical chat.

    Snapshot callers continue to take a bounded tail through
    :func:`_safe_recent_messages`; the on-demand authority pages this complete
    ordered list with opaque cursors.

    Third element: ``None`` when the transcript was READ, otherwise a typed
    ``{"error_kind", "detail"}`` block naming why it was not. It is the only
    thing separating "this chat is empty" from "this chat could not be opened" —
    both used to arrive as ``[], "safe"``. Reachable against a live SQLite file
    under a running serve: lock contention, corruption, schema drift.
    """

    if session_db is None:
        return (
            [],
            CHAT_REDACTION_UNKNOWN,
            {
                "error_kind": CHAT_READ_UNAVAILABLE,
                "detail": "no SessionDB is bound for this runtime, so this chat's transcript was never read",
            },
        )
    try:
        lineage_loader = getattr(session_db, "get_messages_as_conversation", None)
        try:
            native_tip = session_db.resolve_resume_session_id(session_id)
        except Exception:
            native_tip = session_id
        raw_messages = (
            lineage_loader(native_tip, include_ancestors=True)
            if callable(lineage_loader)
            else session_db.get_messages(session_id)
        )
    except Exception as exc:
        return (
            [],
            CHAT_REDACTION_UNKNOWN,
            {
                "error_kind": CHAT_READ_FAILED,
                "detail": safe_assignment_text(
                    f"{type(exc).__name__}: {exc}", limit=240
                )
                or type(exc).__name__,
            },
        )
    rows: list[dict[str, Any]] = []
    redacted = False
    assistant_client_message_ids: set[str] = set()
    seen_logical_rows: set[tuple[str, str, str]] = set()
    # Silent-turn bookkeeping, deliberately two collections rather than one.
    #
    # A turn can persist SEVERAL empty assistant rows — the live incident has
    # one turn with three and the delivery turn after it with two, because each
    # retry writes its own row. One marker per turn is the honest projection, so
    # candidates are keyed by LOGICAL turn id and the last one wins (it is how
    # the turn actually ended).
    #
    # And a marker may only survive if the turn produced no visible reply at
    # all: a turn whose first attempt came back empty and whose retry spoke is a
    # turn the operator SAW. ``assistant_client_message_ids`` cannot answer that
    # — it is populated for every agent row including the empty ones — so
    # visible turns are tracked separately and subtract candidates at the end.
    visible_agent_logical_ids: set[str] = set()
    silent_turn_candidates: dict[str, dict[str, Any]] = {}
    # ONE read of this chat's turn journal, shared by the reply rows below and
    # by the terminal-marker rows appended after them. The journal is a
    # per-session file with no read cache, so fetching it again per row — just
    # to add one small key — would have turned a bounded page into N file reads.
    turn_records = mission_chat_turn_records(session_id=session_id)
    turn_records_by_message = {
        str(record.get("client_message_id") or ""): record for record in turn_records
    }
    # Curate the agent's raw working transcript into an operator-facing one.
    # The bound session is the agent's internal session, so its raw rows are
    # verbose tick-context prompts (role=user) and serialized decision dicts
    # (role=assistant) plus tool/system noise. We surface only clean operator
    # turns and decision summaries; scaffolding/tool/system rows are dropped.
    for index, raw in enumerate(raw_messages or []):
        if not isinstance(raw, dict):
            continue
        role = _safe_message_role(raw.get("role"))
        if role not in {"operator", "agent"}:
            continue
        client_message_id = safe_assignment_text(
            raw.get("platform_message_id")
            or raw.get("message_id")
            or raw.get("client_message_id"),
            limit=240,
        )
        logical_client_message_id = logical_persona_chat_client_message_id(
            client_message_id
        )
        turn_id = canonical_persona_chat_turn_id(client_message_id)
        if role == "agent" and logical_client_message_id:
            assistant_client_message_ids.add(logical_client_message_id)
        raw_content = raw.get("content") or raw.get("text")
        runtime_context = None
        skill_preload = None
        if role == "operator":
            # Composition order is message · skill_preload · runtime_context,
            # so strip the end-anchored HUD envelope first; the skill-preload
            # envelope is end-anchored on the remainder.
            raw_content, runtime_context = extract_runtime_context_envelope(raw_content)
            raw_content, skill_preload = extract_skill_preload_envelope(raw_content)
        curated = _curate_chat_message_text(role, raw_content)
        if not curated:
            # The curator says "not presentable AS WRITTEN", which covers both
            # the tool-call scaffolding this drop was built for and the turn
            # that genuinely ended in silence. Only the latter earns a marker;
            # everything else keeps falling through exactly as before.
            marker = _silent_turn_marker_row(
                session_id=session_id,
                index=index,
                raw=raw,
                role=role,
                raw_content=raw_content,
                client_message_id=client_message_id,
                turn_id=turn_id,
            )
            if marker is not None and logical_client_message_id:
                silent_turn_candidates[logical_client_message_id] = marker
            continue
        if role == "agent" and logical_client_message_id:
            # This turn SPOKE. Recorded before redaction can replace the body:
            # a redacted reply is still a reply the operator was shown, and
            # marking its turn silent would be a second, worse lie.
            visible_agent_logical_ids.add(logical_client_message_id)
        text, status = _safe_display_body_text(
            curated,
            fallback="Message hidden by redaction boundary",
            limit=PERSONA_CHAT_MESSAGE_TEXT_LIMIT,
        )
        if not text:
            continue
        if status == "redacted":
            redacted = True
        row = {
            "id": safe_assignment_text(raw.get("id"), limit=120)
            or f"{session_id}:{index}",
            "role": role,
            "text": text,
            "timestamp": _iso_timestamp(
                raw.get("created_at")
                or raw.get("timestamp")
                or raw.get("time")
                or raw.get("updated_at")
            ),
            "redaction_status": status,
        }
        if runtime_context is not None:
            row["runtime_context"] = runtime_context
        if skill_preload is not None:
            row["skill_preload"] = skill_preload
        # PRE-C8 RESIDUE PATH: acks stopped entering SessionDB with C8 (they
        # are a presentation-only `turn.ack` stream frame now), but rows
        # persisted before that still carry the finish_reason marker
        # (archive-never-delete). Keep re-emitting the typed kind so the
        # Launcher's persisted-row render path can keep suppressing them
        # structurally. New turns can never take this branch.
        is_pre_trace_ack = role == "agent" and (
            safe_assignment_token(raw.get("finish_reason"))
            == PERSONA_PRE_TRACE_ACK_FINISH_REASON
        )
        if is_pre_trace_ack:
            row["kind"] = PERSONA_PRE_TRACE_ACK_KIND
        # RELAY SENDER ATTRIBUTION: an incoming role="user" row persisted by the
        # agent_chat_send relay lane carries the sending agent's identity in
        # finish_reason (relay_from:<persona>:<instance>) — the same typed-marker
        # -in-finish_reason precedent as the pre_trace_ack rows above. Surface it
        # as a typed kind + sender fields so the conversation projection can
        # attribute the message to the sending AGENT rather than the operator.
        # Operator/CLI sends (finish_reason=None) parse to None → skipped, so the
        # operator row is byte-identical to today.
        # HARNESS DELIVERY ATTRIBUTION: a dispatch delivery turn is forged into
        # the SENDER's own thread as a role="user" row, so at rest it is
        # indistinguishable from an operator message — the same defect the
        # relay marker below retires, one lane over. The two facts carried are
        # what the row settles and whether the operator was flagged; both come
        # from the marker because by the time this is read the dispatch has
        # already left every live projection.
        if role == "operator":
            delivery = parse_harness_delivery_marker(raw.get("finish_reason"))
            relay_sender = (
                None
                if delivery is not None
                else parse_relay_sender_marker(raw.get("finish_reason"))
            )
            if delivery is not None:
                row["kind"] = PERSONA_HARNESS_DELIVERY_KIND
                row["delivery_dispatch_id"] = delivery.dispatch_id
                row["delivery_notify_operator"] = delivery.notify_operator
                row["delivery_state"] = delivery.state
            elif relay_sender is not None:
                row["kind"] = PERSONA_RELAYED_MESSAGE_KIND
                row["relay_sender_persona_id"] = relay_sender.persona_id
                row["relay_sender_instance_id"] = relay_sender.instance_id
        if client_message_id:
            logical_key = (role, logical_client_message_id or client_message_id, text)
            if logical_key in seen_logical_rows:
                continue
            seen_logical_rows.add(logical_key)
            row["client_message_id"] = client_message_id
            if turn_id:
                row["turn_id"] = turn_id
            # C8 ordering key: the turn anchor is the canonical logical turn id;
            # intra-turn position is stamped HERE (one authority) — the
            # operator message opens its turn, the recorded reply closes it.
            # Elements between them carry the emitter's 1..N seq. Pre-C8 ack
            # rows carry no anchor and stay on the fallback order.
            if role == "operator":
                row["turn_seq"] = TURN_SEQ_OPERATOR
            elif role == "agent" and not is_pre_trace_ack:
                row["turn_seq"] = TURN_SEQ_TERMINAL
        if role == "agent" and client_message_id:
            elements = mission_chat_turn_elements(
                session_id=session_id,
                client_message_id=logical_client_message_id,
            )
            if elements:
                row["turn_elements"] = elements
            # "What bounded this turn?" — carried verbatim off the turn record
            # (see mission_chat_turns._JOURNAL_RUN_BUDGET_FIELD). The row shapes
            # here are an explicit allowlist, so an unknown key does NOT ride
            # through on its own; this is the additive extension that lets the
            # cockpit read the block the settle point persisted. Read-only: the
            # projection reads the journal, it never writes it.
            _carry_run_budget(
                row, turn_records_by_message.get(str(logical_client_message_id or ""))
            )
        rows.append(row)
    rows.extend(
        marker
        for logical_id, marker in silent_turn_candidates.items()
        if logical_id not in visible_agent_logical_ids
    )
    rows.extend(
        _terminal_turn_marker_rows(
            session_id=session_id,
            assistant_client_message_ids=assistant_client_message_ids,
            records=turn_records,
        )
    )
    rows = _ordered_message_rows(rows)
    # Third element ``None``: the transcript WAS read, so "safe" here is an
    # observation about content that actually passed through the redactor.
    return rows, "redacted" if redacted else "safe", None


def _history_revision(
    session_id: str,
    messages: list[dict[str, Any]],
    *,
    session_db: Any | None = None,
) -> str:
    """Stable revision for cache invalidation without exposing transcript text."""

    if session_db is not None:
        try:
            from ..persona_chat_continuity import native_history_revision

            return native_history_revision(session_db, session_id)
        except Exception:
            pass
    payload = json.dumps(messages, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{session_id}:{digest}"


def _encode_history_cursor(session_id: str, before_id: str) -> str:
    payload = json.dumps(
        {"v": 1, "session_id": session_id, "before_id": before_id},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_history_cursor(value: str) -> dict[str, Any] | None:
    try:
        token = str(value or "").strip()
        padded = token + "=" * (-len(token) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if not isinstance(decoded, dict) or decoded.get("v") != 1:
            return None
        if not safe_assignment_text(decoded.get("before_id"), limit=160):
            return None
        return decoded
    except Exception:
        return None
