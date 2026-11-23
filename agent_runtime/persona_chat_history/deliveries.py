"""A chat's dispatch deliveries, read off its stored rows' delivery markers, never off its transcript.

Separate because it is the frame's one transcript-free read of what a chat's rows say: the
agent-list frame carries each chat's session row only (owner ruling 2026-11-23, "Yes, titles
only"), and Eternia's dispatch banners were the one frame-wide reader of the transcript tail
(``conversation.messages[].delivery``). A forged delivery turn stores its facts in the row's
``finish_reason`` marker (:func:`agent_runtime.relay_policy.parse_harness_delivery_marker`), so
the banners' list is one indexed read of that column over the chat's lineage: no message
bodies, no curation (RT-FU-EVERY-NEKO-REPLY-RE-READS-THE-WHOLE-LIVE-CHAT-BEFORE-ETERNIA-SHOWS-IT).
"""

from __future__ import annotations

from typing import Any

from ..relay_policy import HARNESS_DELIVERY_FINISH_REASON_PREFIX, parse_harness_delivery_marker
from ..serde import safe_assignment_text

__layer__ = "stores"
__all__ = ["CHAT_DISPATCH_DELIVERIES_KEPT", "chat_dispatch_deliveries"]

#: The newest deliveries a chat's row carries: the banners announce a NEW one, and a frame
#: holds a few turns' worth at most between two reads.
CHAT_DISPATCH_DELIVERIES_KEPT = 20


def chat_dispatch_deliveries(session_db: Any, session_id: str) -> list[dict[str, Any]] | None:
    """The chat's newest dispatch deliveries, oldest first, one per dispatch; ``None`` when unread.

    Each is the delivery block a transcript row carries (``dispatch_id``, ``notify_operator``,
    ``state``, ``target_session_id``, ``target_name``). ``None`` (no answer, never ``[]``) when
    the store cannot be asked, so a reader falls back rather than reading "no deliveries".
    """

    read_all = getattr(session_db, "_read_all", None)
    if not callable(read_all) or not session_id:
        return None
    try:
        tip = session_db.resolve_resume_session_id(session_id)
        lineage = getattr(session_db, "_resume_lineage_ids", None)
        session_ids = [value for value in (lineage(tip) if callable(lineage) else [tip]) if value]
        if not session_ids:
            return None
        marks = ",".join("?" for _ in session_ids)
        rows = read_all(
            f"SELECT finish_reason FROM messages WHERE session_id IN ({marks})"
            " AND finish_reason LIKE ? AND (active = 1 OR compacted = 1)"
            " ORDER BY id DESC LIMIT ?",
            (*session_ids, HARNESS_DELIVERY_FINISH_REASON_PREFIX + "%", CHAT_DISPATCH_DELIVERIES_KEPT * 2),
        )
    except Exception:
        return None
    newest_first: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        origin = parse_harness_delivery_marker(row["finish_reason"])
        dispatch_id = safe_assignment_text(getattr(origin, "dispatch_id", None), limit=160)
        # MUTATION: drop the ``seen`` check and test_chat_dispatch_deliveries' resent-delivery row reddens.
        if origin is None or not dispatch_id or dispatch_id in seen:
            continue
        seen.add(dispatch_id)
        newest_first.append({
            "dispatch_id": dispatch_id,
            "notify_operator": bool(origin.notify_operator),
            "state": safe_assignment_text(origin.state, limit=32) or "unknown",
            "target_session_id": safe_assignment_text(origin.target_session_id, limit=240) or "",
            "target_name": safe_assignment_text(origin.target_name, limit=160) or "",
        })
        if len(newest_first) >= CHAT_DISPATCH_DELIVERIES_KEPT:
            break
    return list(reversed(newest_first))
