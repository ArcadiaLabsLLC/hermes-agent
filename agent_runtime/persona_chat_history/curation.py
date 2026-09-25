"""A session's persisted rows curated into the operator transcript, with its revision and cursor.

Separate because it is the transcript's one policy: which row renders, as
which role, in which order, and what the redaction verdict is. The per-role
steps are ``ROLE_CURATORS`` (one curator per transcript role); the steps every
row shares, and the accumulators across rows, are :class:`CurationState`.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from ..clock import iso_timestamp
from ..mission_chat_turns.reads import (
    mission_chat_turn_elements,
    mission_chat_turn_records,
)
from ..serde import safe_assignment_text, safe_assignment_token
from ..relay_policy import parse_harness_delivery_marker, parse_relay_sender_marker
from ..runtime_hud.envelopes import (
    extract_runtime_context_envelope,
    extract_skill_preload_envelope,
)
from ..transcript_order import TURN_SEQ_OPERATOR, TURN_SEQ_TERMINAL
from .markers import (
    _carry_run_budget,
    _ordered_message_rows,
    _silent_turn_marker_row,
    _terminal_turn_marker_rows,
)
from .text import (
    _curate_chat_message_text,
    _safe_display_body_text,
)
from .vocabulary import (
    CHAT_READ_FAILED,
    MessageRole,
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
    "CurationState",
    "ROLE_CURATORS",
    "RoleCurator",
    "RowContext",
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
        raw_messages = _read_raw_messages(session_db, session_id)
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
    state = CurationState.for_session(session_id)
    # Curate the agent's raw working transcript into an operator-facing one.
    # The bound session is the agent's internal session, so its raw rows are
    # verbose tick-context prompts (role=user) and serialized decision dicts
    # (role=assistant) plus tool/system noise. We surface only clean operator
    # turns and decision summaries; scaffolding/tool/system rows are dropped —
    # a role with no curator in ``ROLE_CURATORS`` is skipped by the table.
    for index, raw in enumerate(raw_messages or []):
        if not isinstance(raw, dict):
            continue
        role = MessageRole.from_wire(raw.get("role"))
        curator = ROLE_CURATORS.get(role) if role is not None else None
        if curator is not None:
            state.curate(index, raw, curator)
    # Third element ``None``: the transcript WAS read, so "safe" here is an
    # observation about content that actually passed through the redactor.
    return state.finish(), "redacted" if state.redacted else "safe", None


def _read_raw_messages(session_db: Any, session_id: str) -> Any:
    """The chat's persisted rows across its native compression lineage (raises on a failed read)."""

    lineage_loader = getattr(session_db, "get_messages_as_conversation", None)
    try:
        native_tip = session_db.resolve_resume_session_id(session_id)
    except Exception:
        native_tip = session_id
    return (
        lineage_loader(native_tip, include_ancestors=True)
        if callable(lineage_loader)
        else session_db.get_messages(session_id)
    )


@dataclass
class RowContext:
    """One persisted row on its way to the transcript: what every curator step reads."""

    index: int
    raw: dict[str, Any]
    role: MessageRole
    client_message_id: str | None
    logical_client_message_id: str | None
    turn_id: str | None


class RoleCurator(Protocol):
    """The role-specific steps of curating one row; the shared steps live on :class:`CurationState`."""

    role: MessageRole

    def before_curation(self, state: "CurationState", ctx: RowContext) -> None: ...

    def strip_envelopes(self, raw_content: Any) -> tuple[Any, Any, Any]: ...

    def on_visible(self, state: "CurationState", ctx: RowContext) -> None: ...

    def annotate(self, row: dict[str, Any], ctx: RowContext) -> bool: ...

    def turn_seq(self, is_pre_trace_ack: bool) -> int | None: ...

    def after_row(self, state: "CurationState", row: dict[str, Any], ctx: RowContext) -> None: ...


class _OperatorCurator:
    role = MessageRole.OPERATOR

    def before_curation(self, state: "CurationState", ctx: RowContext) -> None:
        return None

    def strip_envelopes(self, raw_content: Any) -> tuple[Any, Any, Any]:
        # Composition order is message · skill_preload · runtime_context,
        # so strip the end-anchored HUD envelope first; the skill-preload
        # envelope is end-anchored on the remainder.
        raw_content, runtime_context = extract_runtime_context_envelope(raw_content)
        raw_content, skill_preload = extract_skill_preload_envelope(raw_content)
        return raw_content, runtime_context, skill_preload

    def on_visible(self, state: "CurationState", ctx: RowContext) -> None:
        return None

    def annotate(self, row: dict[str, Any], ctx: RowContext) -> bool:
        # RELAY SENDER ATTRIBUTION: an incoming role="user" row persisted by the
        # agent_chat_send relay lane carries the sending agent's identity in
        # finish_reason (relay_from:<persona>:<instance>) — the same typed-marker
        # -in-finish_reason precedent as the pre_trace_ack rows. Surface it
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
        raw = ctx.raw
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
        return False

    def turn_seq(self, is_pre_trace_ack: bool) -> int | None:
        # C8 ordering key: the operator message opens its turn.
        return TURN_SEQ_OPERATOR

    def after_row(self, state: "CurationState", row: dict[str, Any], ctx: RowContext) -> None:
        return None


class _AgentCurator:
    role = MessageRole.AGENT

    def before_curation(self, state: "CurationState", ctx: RowContext) -> None:
        if ctx.logical_client_message_id:
            state.assistant_client_message_ids.add(ctx.logical_client_message_id)

    def strip_envelopes(self, raw_content: Any) -> tuple[Any, Any, Any]:
        return raw_content, None, None

    def on_visible(self, state: "CurationState", ctx: RowContext) -> None:
        if ctx.logical_client_message_id:
            # This turn SPOKE. Recorded before redaction can replace the body:
            # a redacted reply is still a reply the operator was shown, and
            # marking its turn silent would be a second, worse lie.
            state.visible_agent_logical_ids.add(ctx.logical_client_message_id)

    def annotate(self, row: dict[str, Any], ctx: RowContext) -> bool:
        # PRE-C8 RESIDUE PATH: acks stopped entering SessionDB with C8 (they
        # are a presentation-only `turn.ack` stream frame now), but rows
        # persisted before that still carry the finish_reason marker
        # (archive-never-delete). Keep re-emitting the typed kind so the
        # Launcher's persisted-row render path can keep suppressing them
        # structurally. New turns can never take this branch.
        is_pre_trace_ack = (
            safe_assignment_token(ctx.raw.get("finish_reason"))
            == PERSONA_PRE_TRACE_ACK_FINISH_REASON
        )
        if is_pre_trace_ack:
            row["kind"] = PERSONA_PRE_TRACE_ACK_KIND
        return is_pre_trace_ack

    def turn_seq(self, is_pre_trace_ack: bool) -> int | None:
        # C8 ordering key: the recorded reply closes its turn. Pre-C8 ack rows
        # carry no anchor and stay on the fallback order.
        return None if is_pre_trace_ack else TURN_SEQ_TERMINAL

    def after_row(self, state: "CurationState", row: dict[str, Any], ctx: RowContext) -> None:
        if not ctx.client_message_id:
            return
        elements = mission_chat_turn_elements(
            session_id=state.session_id,
            client_message_id=ctx.logical_client_message_id,
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
            row, state.turn_records_by_message.get(str(ctx.logical_client_message_id or ""))
        )


#: The transcript roles that render, each with its curator. ``MessageRole.SYSTEM``
#: has none, so a system row is skipped by the table — never by a fall-through.
ROLE_CURATORS: Mapping[MessageRole, RoleCurator] = MappingProxyType({
    MessageRole.OPERATOR: _OperatorCurator(),
    MessageRole.AGENT: _AgentCurator(),
})


@dataclass
class CurationState:
    """What curating one chat accumulates across its rows."""

    session_id: str
    # ONE read of this chat's turn journal, shared by the reply rows and by the
    # terminal-marker rows appended after them. The journal is a per-session
    # file with no read cache, so fetching it again per row — just to add one
    # small key — would have turned a bounded page into N file reads.
    turn_records: list[dict[str, Any]]
    turn_records_by_message: dict[str, dict[str, Any]]
    rows: list[dict[str, Any]] = field(default_factory=list)
    redacted: bool = False
    assistant_client_message_ids: set[str] = field(default_factory=set)
    seen_logical_rows: set[tuple[str, str, str]] = field(default_factory=set)
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
    visible_agent_logical_ids: set[str] = field(default_factory=set)
    silent_turn_candidates: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def for_session(cls, session_id: str) -> "CurationState":
        turn_records = mission_chat_turn_records(session_id=session_id)
        return cls(
            session_id=session_id,
            turn_records=turn_records,
            turn_records_by_message={
                str(record.get("client_message_id") or ""): record for record in turn_records
            },
        )

    def curate(self, index: int, raw: dict[str, Any], curator: RoleCurator) -> None:
        client_message_id = safe_assignment_text(
            raw.get("platform_message_id")
            or raw.get("message_id")
            or raw.get("client_message_id"),
            limit=240,
        )
        ctx = RowContext(
            index=index,
            raw=raw,
            role=curator.role,
            client_message_id=client_message_id,
            logical_client_message_id=logical_persona_chat_client_message_id(client_message_id),
            turn_id=canonical_persona_chat_turn_id(client_message_id),
        )
        curator.before_curation(self, ctx)
        raw_content, runtime_context, skill_preload = curator.strip_envelopes(
            raw.get("content") or raw.get("text")
        )
        curated = _curate_chat_message_text(ctx.role, raw_content)
        if not curated:
            self._silent_candidate(ctx, raw_content)
            return
        curator.on_visible(self, ctx)
        text, status = _safe_display_body_text(
            curated,
            fallback="Message hidden by redaction boundary",
            limit=PERSONA_CHAT_MESSAGE_TEXT_LIMIT,
        )
        if not text:
            return
        if status == "redacted":
            self.redacted = True
        row = _message_row(ctx, session_id=self.session_id, text=text, status=status)
        if runtime_context is not None:
            row["runtime_context"] = runtime_context
        if skill_preload is not None:
            row["skill_preload"] = skill_preload
        is_pre_trace_ack = curator.annotate(row, ctx)
        if client_message_id and not self._first_logical_row(row, ctx, text, curator.turn_seq(is_pre_trace_ack)):
            return
        curator.after_row(self, row, ctx)
        self.rows.append(row)

    def _silent_candidate(self, ctx: RowContext, raw_content: Any) -> None:
        # The curator says "not presentable AS WRITTEN", which covers both
        # the tool-call scaffolding this drop was built for and the turn
        # that genuinely ended in silence. Only the latter earns a marker;
        # everything else keeps falling through exactly as before.
        marker = _silent_turn_marker_row(
            session_id=self.session_id,
            index=ctx.index,
            raw=ctx.raw,
            role=ctx.role,
            raw_content=raw_content,
            client_message_id=ctx.client_message_id,
            turn_id=ctx.turn_id,
        )
        if marker is not None and ctx.logical_client_message_id:
            self.silent_turn_candidates[ctx.logical_client_message_id] = marker

    def _first_logical_row(self, row: dict[str, Any], ctx: RowContext, text: str, turn_seq: int | None) -> bool:
        """Stamp the client ids and the C8 turn position; ``False`` for a repeat of a logical row."""

        logical_key = (ctx.role, ctx.logical_client_message_id or ctx.client_message_id or "", text)
        if logical_key in self.seen_logical_rows:
            return False
        self.seen_logical_rows.add(logical_key)
        row["client_message_id"] = ctx.client_message_id
        if ctx.turn_id:
            row["turn_id"] = ctx.turn_id
        # C8 ordering key: the turn anchor is the canonical logical turn id;
        # intra-turn position is stamped HERE (one authority) — the
        # operator message opens its turn, the recorded reply closes it.
        # Elements between them carry the emitter's 1..N seq. Pre-C8 ack
        # rows carry no anchor and stay on the fallback order.
        if turn_seq is not None:
            row["turn_seq"] = turn_seq
        return True

    def finish(self) -> list[dict[str, Any]]:
        rows = list(self.rows)
        rows.extend(
            marker
            for logical_id, marker in self.silent_turn_candidates.items()
            if logical_id not in self.visible_agent_logical_ids
        )
        rows.extend(
            _terminal_turn_marker_rows(
                session_id=self.session_id,
                assistant_client_message_ids=self.assistant_client_message_ids,
                records=self.turn_records,
            )
        )
        return _ordered_message_rows(rows)


def _message_row(ctx: RowContext, *, session_id: str, text: str, status: str) -> dict[str, Any]:
    raw = ctx.raw
    return {
        "id": safe_assignment_text(raw.get("id"), limit=120)
        or f"{session_id}:{ctx.index}",
        "role": ctx.role,
        "text": text,
        "timestamp": iso_timestamp(
            raw.get("created_at")
            or raw.get("timestamp")
            or raw.get("time")
            or raw.get("updated_at")
        ),
        "redaction_status": status,
    }


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
