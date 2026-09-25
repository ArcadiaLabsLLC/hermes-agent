"""The shape of one mirror line: role, keys, origin fields, masked text, the codec.

Pure (no process state, no file I/O): the role normalization, the logical
client key, the two origin-field translations (live marker and backfilled
projection row), the session-id-as-filename guard, the per-line secret masking
and text bound, and the line codec (encode / decode). Every other module of the
package reads the line through here.
"""

from __future__ import annotations

import json
from typing import Any

from hermes_time import now

from agent_runtime.redaction import TEXT_SECRET_ASSIGNMENT_RE

__layer__ = "policy"


#: Per-line text cap. Matches the ``agent_chat_send`` reply bound so one mirror
#: line can never be larger than the largest reply the lane will hand back.
LIVE_LOG_TEXT_LIMIT = 8000


#: Same masking vocabulary the read projection uses.
_REDACTED_LINE = "[redacted line — contained a secret]"


def _decode_lines(blob: bytes) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in blob.decode("utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _now_iso() -> str:
    try:
        return now().isoformat()
    except Exception:  # pragma: no cover - a timestamp is not load-bearing
        return ""


def _iso_or_now(value: Any) -> str:
    text = str(value or "").strip()
    return text or _now_iso()


def _normalized_role(value: Any) -> str:
    role = str(value or "").strip().lower()
    if role in {"user", "operator"}:
        return "operator"
    if role in {"assistant", "agent"}:
        return "agent"
    if role == "system":
        return "system"
    return role or "unknown"


def _safe_token(value: Any, *, limit: int) -> str:
    text = str(value or "").strip().replace("\x00", "")
    return text[:limit]


def _logical_client_key(value: Any) -> str:
    """The durable operator-turn identity behind a persisted row's id.

    The runtime's native flush stamps non-user rows ``<client_message_id>:
    <role>:<index>``; the live hooks carry the bare id. Deduping on the raw
    value would let a materialized file and a live append both claim the same
    reply. One spelling, borrowed from the projection that already owns this
    normalization.
    """

    token = _safe_token(value, limit=240)
    if not token:
        return ""
    try:
        from ..persona_chat_history import logical_persona_chat_client_message_id

        return logical_persona_chat_client_message_id(token) or token
    except Exception:  # pragma: no cover - defensive
        return token


def _backfilled_delivery_fields(message: dict[str, Any]) -> dict[str, str]:
    """Mirror-vocabulary origin fields for a row read back from the projection.

    The live path decodes the finish_reason marker directly
    (:func:`_relay_sender_fields`); backfill only ever sees the already-typed
    projection row, so this is the second and last place the two vocabularies
    meet. Keyed on the typed kind, never on prose.
    """

    from ..persona_chat_history import PERSONA_HARNESS_DELIVERY_KIND

    if _safe_token(message.get("kind"), limit=64) != PERSONA_HARNESS_DELIVERY_KIND:
        return {}
    fields: dict[str, str] = {"origin": "harness_delivery"}
    dispatch_id = _safe_token(message.get("delivery_dispatch_id"), limit=200)
    if dispatch_id:
        fields["dispatch_id"] = dispatch_id
    fields["dispatch_state"] = (
        _safe_token(message.get("delivery_state"), limit=40) or "unknown"
    )
    if message.get("delivery_notify_operator"):
        fields["notify_operator"] = "1"
    return fields


def _relay_sender_fields(relay_marker: Any) -> dict[str, str]:
    """Origin fields for an incoming row, decoded from its finish_reason marker.

    Two non-operator origins ride that one column, and BOTH are invisible in the
    mirror without this. A relayed teammate message reads as the operator — the
    attribution defect the conversation projection carries ``relay_sender_*`` to
    avoid — and a forged dispatch DELIVERY reads as the operator too, which is
    worse here than in the UI: the mirror's whole purpose is machine
    consumption, and a head agent grepping a teammate's thread would attribute
    the runtime's own delivery to the human, with nothing in the line to say
    otherwise.

    Kept as ONE helper over one column rather than two: the marker vocabularies
    are mutually exclusive by construction (``relay_policy`` owns both), so a
    second call site would only create a chance for them to disagree.
    """

    if not relay_marker:
        return {}
    try:
        from ..relay_policy import (
            parse_harness_delivery_marker,
            parse_relay_sender_marker,
        )

        delivery = parse_harness_delivery_marker(relay_marker)
        sender = None if delivery is not None else parse_relay_sender_marker(relay_marker)
    except Exception:  # pragma: no cover - defensive
        return {}
    if delivery is not None:
        fields: dict[str, str] = {"origin": "harness_delivery"}
        if delivery.dispatch_id:
            fields["dispatch_id"] = _safe_token(delivery.dispatch_id, limit=200)
        # `or "unknown"` to match the backfill path exactly. The two
        # vocabularies are deliberately identical — that is what makes a
        # backfilled line and a live one indistinguishable to a consumer — so a
        # fallback on one side and not the other is a real divergence, however
        # unreachable it looks today.
        fields["dispatch_state"] = _safe_token(delivery.state, limit=40) or "unknown"
        if delivery.notify_operator:
            fields["notify_operator"] = "1"
        return fields
    if sender is None:
        return {}
    fields = {}
    if sender.persona_id:
        fields["relay_sender_persona_id"] = _safe_token(sender.persona_id, limit=160)
    if sender.instance_id:
        fields["relay_sender_instance_id"] = _safe_token(sender.instance_id, limit=160)
    return fields


def _safe_session_token(value: Any) -> str:
    token = _safe_token(value, limit=240)
    # A session id becomes a FILENAME here. Anything path-shaped is refused
    # rather than sanitized: the ids this lane mints are
    # ``persona_chat_<handle>_<hex>``, so a value carrying a separator is not a
    # session id we should be mirroring in the first place.
    if not token or any(ch in token for ch in ('/', '\\', ':', '*', '?', '"', '<', '>', '|')):
        return ""
    if token in {".", ".."}:
        return ""
    return token


def _mirror_text(value: Any) -> str:
    text = str(value or "").replace("\x00", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [
        _REDACTED_LINE if TEXT_SECRET_ASSIGNMENT_RE.search(line) else line.rstrip()
        for line in text.split("\n")
    ]
    normalized = "\n".join(lines).strip()
    if len(normalized) > LIVE_LOG_TEXT_LIMIT:
        # Truncation must be visible, never silent — same posture as the
        # persisted-transcript cap.
        normalized = normalized[:LIVE_LOG_TEXT_LIMIT].rstrip() + " … [truncated]"
    return normalized


def _encode(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)
