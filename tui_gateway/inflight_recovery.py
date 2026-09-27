"""Segment boundaries on the existing inflight text, not another event history."""


def record(session, kind, payload):
    turn = session.get("inflight_turn")
    if not turn:
        return
    if kind in {"reasoning.delta", "thinking.delta"}:
        turn["reasoning"] = turn.get("reasoning", "") + str(payload.get("text") or "")
    elif kind == "reasoning.available":
        _replace_tail(turn, "reasoning", payload.get("text"))
    elif kind == "message.interim":
        _replace_tail(turn, "assistant", payload.get("text"))
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
