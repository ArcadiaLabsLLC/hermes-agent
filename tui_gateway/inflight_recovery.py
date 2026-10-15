"""Segment boundaries on the existing inflight text, not another event history."""


def record(session, kind, payload):
    turn = session.get("inflight_turn")
    handler = _RECORDERS.get(kind)
    if turn and handler:
        handler(turn, payload.get("text"))


def _append_reasoning(turn, text):
    turn["reasoning"] = turn.get("reasoning", "") + str(text or "")


def _finish_reasoning(turn, text):
    _replace_tail(turn, "reasoning", text)


def _finish_segment(turn, text):
    _replace_tail(turn, "assistant", text)
    turn.setdefault("segment_ends", []).append({
        field: len(turn.get(field) or "") for field in ("assistant", "reasoning")})


def _replace_tail(turn, field, text):
    boundaries = turn.get("segment_ends") or []
    start = boundaries[-1][field] if boundaries else 0
    current = str(turn.get(field) or "")
    value = current[:start] + str(text or "")
    if not value.startswith(current):
        turn["revision"] = turn.get("revision", 0) + 1
    turn[field] = value


_RECORDERS = {
    "reasoning.delta": _append_reasoning,
    "thinking.delta": _append_reasoning,
    "reasoning.available": _finish_reasoning,
    "message.interim": _finish_segment,
}
