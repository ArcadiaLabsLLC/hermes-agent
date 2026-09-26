"""A trace entry -> conversation messages: progress/thinking rows, subagent prompts, tool calls."""

from __future__ import annotations

from typing import Any

from ..clock import parse_iso
from ..serde import safe_assignment_text, safe_assignment_token
from ..transcript_order import TURN_SEQ_CONTENT

from .vocabulary import (
    TRACE_BLOCKER_STATUSES,
    TRACE_FINAL_STATUSES,
    TRACE_HANDOFF_STATUSES,
    _TELEMETRY_SUMMARY_RE,
    _TOOL_FAILED_STATUSES,
    _TOOL_OK_STATUSES,
    _safe_conversation_list,
    _safe_conversation_text,
)

__layer__ = "policy"


def _conversation_trace_message(
    entry: dict[str, Any],
    *,
    channel_id: str,
    index: int,
    persona_id: str,
    persona_instance_id: str | None,
) -> dict[str, Any] | None:
    event = safe_assignment_token(entry.get("event"))
    if event in {"assignment_created", "assignment_closed"}:
        return _conversation_assignment_message(
            entry,
            channel_id=channel_id,
            index=index,
            parent_persona_id=persona_id,
        )
    if event != "progress":
        return None
    if entry.get("tool_name"):
        return None
    # Per-step reasoning renders as a first-class Thinking message — this is
    # the streamed think→act loop, one message per thinking callback, distinct
    # from the per-run summary emitted by _conversation_turn_messages.
    reasoning = _safe_conversation_text(entry.get("reasoning_summary"), limit=1200)
    if reasoning:
        refs: dict[str, Any] = {"source": "persona_chat_trace"}
        for key in ("task_id", "run_id", "stage_id"):
            value = safe_assignment_text(entry.get(key), limit=160)
            if value:
                refs[key] = value
        turn_id = safe_assignment_text(entry.get("turn_id"), limit=160)
        message = {
            "id": f"{channel_id}:thinking:{refs.get('run_id', 'run')}:{index}",
            "seq": 0,
            "timestamp": entry.get("ts"),
            "actor_persona_id": safe_assignment_token(entry.get("persona_id")) or persona_id,
            "actor_instance_id": persona_instance_id,
            "role": "agent",
            "kind": "thinking_summary",
            "status": safe_assignment_token(entry.get("status")) or "running",
            "display_title": "Thinking",
            "display_text": reasoning,
            "redaction_status": "safe",
            "refs": refs,
        }
        if turn_id:
            message["turn_id"] = turn_id
            message["turn_seq"] = TURN_SEQ_CONTENT
        return message
    summary = _safe_conversation_text(
        entry.get("summary") or entry.get("rationale"),
        limit=1200,
    )
    if not summary or _TELEMETRY_SUMMARY_RE.search(summary):
        return None
    status = safe_assignment_token(entry.get("status")) or "running"
    role = "blocker" if status in TRACE_BLOCKER_STATUSES else "proof" if "proof" in summary.lower() else "agent"
    kind = "blocker" if role == "blocker" else "proof" if role == "proof" else _conversation_kind_from_status(status)
    refs: dict[str, Any] = {"source": "persona_chat_trace"}
    for key in ("task_id", "run_id", "stage_id"):
        value = safe_assignment_text(entry.get(key), limit=160)
        if value:
            refs[key] = value
    turn_id = safe_assignment_text(entry.get("turn_id"), limit=160)
    message = {
        "id": f"{channel_id}:progress:{refs.get('run_id', 'run')}:{index}",
        "seq": 0,
        "timestamp": entry.get("ts"),
        "actor_persona_id": safe_assignment_token(entry.get("persona_id")) or persona_id,
        "actor_instance_id": persona_instance_id,
        "role": role,
        "kind": kind,
        "status": status,
        "display_title": _conversation_title_for_kind(kind),
        "display_text": summary,
        "redaction_status": "safe",
        "refs": refs,
    }
    if turn_id:
        message["turn_id"] = turn_id
        message["turn_seq"] = TURN_SEQ_CONTENT
    return message


def _conversation_assignment_message(
    entry: dict[str, Any],
    *,
    channel_id: str,
    index: int,
    parent_persona_id: str,
) -> dict[str, Any] | None:
    target_persona_id = safe_assignment_token(entry.get("persona_id")) or "agent"
    title = _safe_conversation_text(entry.get("title"), limit=240)
    message = _safe_conversation_text(entry.get("message"), limit=1200)
    if not title and not message:
        return None
    parts = [f"Prompted {target_persona_id}."]
    if title:
        parts.append(f"Stage: {title}")
    if message:
        parts.append(f"Prompt: {message}")
    proof_targets = _safe_conversation_list(entry.get("proof_targets"), limit=160)
    if proof_targets:
        parts.append("Proof expected: " + "; ".join(proof_targets))
    allowed_decisions = _safe_conversation_list(entry.get("allowed_decisions"), limit=80)
    if allowed_decisions:
        parts.append("Allowed decisions: " + ", ".join(allowed_decisions))
    refs: dict[str, Any] = {"source": "persona_assignment"}
    event = safe_assignment_token(entry.get("event"))
    if event:
        refs["event"] = event
    for key in ("task_id", "stage_id", "assignment_id", "persona_instance_id", "repo"):
        value = safe_assignment_text(entry.get(key), limit=160)
        if value:
            refs[key] = value
    return {
        "id": f"{channel_id}:assignment:{refs.get('assignment_id', index)}",
        "seq": 0,
        "timestamp": entry.get("ts"),
        "actor_persona_id": parent_persona_id,
        "actor_instance_id": None,
        "target_persona_id": target_persona_id,
        "target_persona_instance_id": safe_assignment_text(entry.get("persona_instance_id"), limit=160),
        "role": "agent",
        "kind": "handoff",
        "status": "delivered",
        "display_title": "Subagent prompt",
        "display_text": "\n".join(parts),
        "redaction_status": "safe",
        "refs": refs,
    }


def _conversation_tool_call_messages(
    entries: list[Any],
    *,
    channel_id: str,
    persona_id: str,
    persona_instance_id: str | None,
    accountant: Any = None,
) -> list[dict[str, Any]]:
    """Collapse tool_started/tool_finished trace pairs into one tool_call each.

    The trace lane already carries redaction-safe tool rows; this pairs them by
    ``(run_id, tool_name)`` in timestamp order so the conversation shows one
    compact row per call — running until its finish row lands, then ok/failed
    with a duration. Ids are ``{channel}:tool:{run}:{ordinal}`` (ordinal = the
    call's index within its run), stable across polls.
    """

    messages: list[dict[str, Any]] = []
    open_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    ordinals: dict[str, int] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        event = safe_assignment_token(entry.get("event"))
        if event not in {"tool_started", "tool_finished"}:
            continue
        turn_id = safe_assignment_text(entry.get("turn_id"), limit=160)
        real_run_id = safe_assignment_text(entry.get("run_id"), limit=160)
        bucket_id = turn_id or real_run_id or "run"
        tool_name = safe_assignment_text(entry.get("tool_name"), limit=120) or "tool"
        key = (bucket_id, tool_name)
        summary = _safe_conversation_text(entry.get("summary"), limit=1200)
        files = _safe_conversation_list(entry.get("files"), limit=200)
        if event == "tool_started":
            if accountant is not None:
                accountant.consider(1)
            ordinal = ordinals.get(bucket_id, 0)
            ordinals[bucket_id] = ordinal + 1
            message = _tool_call_message(
                channel_id=channel_id,
                persona_id=persona_id,
                persona_instance_id=persona_instance_id,
                bucket_id=bucket_id,
                run_id=real_run_id,
                turn_id=turn_id,
                ordinal=ordinal,
                tool_name=tool_name,
                status="running",
                timestamp=entry.get("ts"),
                summary=summary,
                files=files,
                stage_id=safe_assignment_text(entry.get("stage_id"), limit=160),
                task_id=safe_assignment_text(entry.get("task_id"), limit=160),
                entry=entry,
            )
            message["_started_ts"] = entry.get("ts")
            open_by_key.setdefault(key, []).append(message)
            messages.append(message)
            continue
        status = _tool_status_token(entry.get("status"))
        pending = open_by_key.get(key)
        if pending:
            message = pending.pop(0)
            message["status"] = status
            message["tool"]["status"] = status
            if summary:
                message["display_text"] = summary
            if files:
                message["tool"]["files"] = files
            _merge_tool_detail(message["tool"], entry)
            started = parse_iso(message.pop("_started_ts", None))
            finished = parse_iso(entry.get("ts"))
            if "duration_ms" not in message["tool"] and started is not None and finished is not None and finished >= started:
                message["tool"]["duration_ms"] = int((finished - started).total_seconds() * 1000)
            continue
        if accountant is not None:
            accountant.consider(1)
        ordinal = ordinals.get(bucket_id, 0)
        ordinals[bucket_id] = ordinal + 1
        messages.append(
            _tool_call_message(
                channel_id=channel_id,
                persona_id=persona_id,
                persona_instance_id=persona_instance_id,
                bucket_id=bucket_id,
                run_id=real_run_id,
                turn_id=turn_id,
                ordinal=ordinal,
                tool_name=tool_name,
                status=status,
                timestamp=entry.get("ts"),
                summary=summary,
                files=files,
                stage_id=safe_assignment_text(entry.get("stage_id"), limit=160),
                task_id=safe_assignment_text(entry.get("task_id"), limit=160),
                entry=entry,
            )
        )
    for message in messages:
        message.pop("_started_ts", None)
    if accountant is not None and messages:
        accountant.include(len(messages))
    return messages


def _tool_call_message(
    *,
    channel_id: str,
    persona_id: str,
    persona_instance_id: str | None,
    bucket_id: str,
    run_id: str | None,
    turn_id: str | None,
    ordinal: int,
    tool_name: str,
    status: str,
    timestamp: Any,
    summary: str | None,
    files: list[str],
    stage_id: str | None,
    task_id: str | None,
    entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    refs: dict[str, Any] = {"source": "persona_chat_trace", "tool_name": tool_name}
    if run_id:
        refs["run_id"] = run_id
    if stage_id:
        refs["stage_id"] = stage_id
    if task_id:
        refs["task_id"] = task_id
    tool: dict[str, Any] = {"tool_name": tool_name, "status": status}
    if files:
        tool["files"] = files
    if entry is not None:
        _merge_tool_detail(tool, entry)
    message = {
        "id": f"{channel_id}:tool:{bucket_id}:{ordinal}",
        "seq": 0,
        "timestamp": timestamp,
        "actor_persona_id": persona_id,
        "actor_instance_id": persona_instance_id,
        "role": "agent",
        "kind": "tool_call",
        "status": status,
        "display_title": f"Tool · {tool_name}",
        "display_text": summary or f"Tool {tool_name}",
        "redaction_status": "safe",
        "refs": refs,
        "tool": tool,
    }
    if turn_id:
        message["turn_id"] = turn_id
        # C8 ordering key: turn-anchored content without an emitter seq sits in
        # the content band — after the turn's operator row, before its terminal
        # reply — keeping its relative order among band peers from the fallback.
        message["turn_seq"] = TURN_SEQ_CONTENT
    return message


# Operator-detail fields carried from a trace entry onto the tool_call payload.
# The values were already operator-sanitized (secret-scrubbed, bounded) when the
# trace entry was rendered; this is a straight, newest-wins merge.
_TOOL_DETAIL_STR_FIELDS = (
    "command", "target", "detail", "output",
    # First-class agent-to-agent dispatch (G2): the target persona chip + the
    # full order, carried onto the tool{} payload under the same names the
    # launcher reads. Already operator-sanitized upstream; straight newest-wins.
    "dispatch_target", "dispatch_order",
    # ...plus the thread the relay landed in, so the console's dispatch tile can
    # open the other half of the exchange. Newest-wins like its siblings: the
    # started entry has no thread yet, the finished entry supplies it.
    "dispatch_target_session_id",
    # ...plus the reply that came back and who sent it, so the console's tile
    # renders the exchange. Newest-wins for the same reason: only the finished
    # entry can carry an answer.
    "dispatch_reply", "dispatch_reply_from",
    # ...plus the patch call's local diff artifact and the grammar it used, so
    # the console's patch tile can offer to open the diff. Newest-wins like its
    # siblings: only the finished entry has an artifact to name.
    "patch_artifact", "patch_mode",
    # Generic tool input/result record (tools with no dedicated detail field) —
    # feeds the console's collapsed Input/Result dropdowns.
    "tool_input", "tool_result",
)
_TOOL_DETAIL_INT_FIELDS = ("duration_ms", "exit_code", "patch_adds", "patch_dels")


def _merge_tool_detail(tool: dict[str, Any], entry: dict[str, Any]) -> None:
    for field in _TOOL_DETAIL_STR_FIELDS:
        value = entry.get(field)
        if isinstance(value, str) and value.strip():
            tool[field] = value
    for field in _TOOL_DETAIL_INT_FIELDS:
        value = entry.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            tool[field] = value
    paths = entry.get("paths")
    if isinstance(paths, list) and paths:
        tool["paths"] = [str(item) for item in paths if str(item or "").strip()][:12]
    skill_id = entry.get("skill_id")
    if isinstance(skill_id, str) and skill_id.strip():
        tool["skill_id"] = skill_id.strip()


def _tool_status_token(value: Any) -> str:
    status = safe_assignment_token(value) or ""
    if status in _TOOL_FAILED_STATUSES:
        return "failed"
    if status in _TOOL_OK_STATUSES or not status:
        return "ok"
    return status


#: A progress row's status -> the conversation kind it renders as, first hit;
#: any other status is an ``agent_update``.
TRACE_STATUS_KINDS: tuple[tuple[frozenset[str], str], ...] = (
    (TRACE_HANDOFF_STATUSES, "handoff"),
    (TRACE_FINAL_STATUSES, "final"),
)


def _conversation_kind_from_status(status: str) -> str:
    return next((kind for statuses, kind in TRACE_STATUS_KINDS if status in statuses), "agent_update")


def _conversation_title_for_kind(kind: str) -> str:
    return {
        "handoff": "Handoff",
        "proof": "Proof update",
        "blocker": "Blocked",
        "final": "Final update",
    }.get(kind, "Agent update")
