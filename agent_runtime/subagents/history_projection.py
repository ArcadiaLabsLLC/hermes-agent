"""Bounded, redacted projections of native results; absent facts stay absent."""
import math

from agent_runtime.redaction import scrub_secret_values

__layer__ = "policy"

TEXT_LIMIT = 65536


def history_text(value, limit=TEXT_LIMIT):
    return scrub_secret_values(value[:limit]) if isinstance(value, str) else None


def history_number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def result_projection(entry, *, goal, source, started, finished):
    text_fields = ("summary", "error", "model", "exit_reason", "failure_reason", "cost_status", "timeout_phase", "stall_phase")
    number_fields = ("api_calls", "duration_seconds", "cost_usd", "schema_retries", "timeout_seconds",
                     "timed_out_after_seconds", "last_event_age", "stalled_after_quiet_seconds",
                     "stall_threshold_seconds", "stall_grace_seconds")
    result = {key: history_text(entry.get(key)) for key in text_fields}
    result.update({key: history_number(entry.get(key)) for key in number_fields})
    result.update({key: entry.get(key) if type(entry.get(key)) is bool else None
                   for key in ("truncated", "schema_valid", "missed_steer")})
    tokens = entry.get("tokens") if isinstance(entry.get("tokens"), dict) else {}
    result.update(goal=history_text(goal, 4096), status=history_text(entry.get("status"), 64) or "unknown",
                  source=source, started_at=history_number(started), completed_at=history_number(finished),
                  task_index=entry.get("task_index") if type(entry.get("task_index")) is int else None,
                  input_tokens=history_number(tokens.get("input")), output_tokens=history_number(tokens.get("output")))
    errors = entry.get("schema_errors")
    result["schema_errors"] = [history_text(e, 2048) for e in errors[:20] if isinstance(e, str)] if isinstance(errors, list) else []
    trace = entry.get("tool_trace")
    # Only public result fields cross this boundary; no messages or diagnostics.
    result["tool_trace"] = [{"tool": history_text(row.get("tool"), 256),
        "input_summary": history_text(row.get("input_summary"), 2048), "status": history_text(row.get("status"), 64),
        "args_bytes": history_number(row.get("args_bytes")), "result_bytes": history_number(row.get("result_bytes"))}
        for row in trace[:100] if isinstance(row, dict)] if isinstance(trace, list) else []
    result["content_truncated"] = any(isinstance(entry.get(key), str) and len(entry[key]) > TEXT_LIMIT for key in (*text_fields, "tool_trace"))
    result["content_truncated"] |= isinstance(trace, list) and len(trace) > 100
    result["content_truncated"] |= isinstance(goal, str) and len(goal) > 4096
    if isinstance(trace, list):
        result["content_truncated"] |= any(isinstance(row, dict) and any(
            isinstance(row.get(key), str) and len(row[key]) > limit
            for key, limit in (("tool", 256), ("input_summary", 2048), ("status", 64))) for row in trace)
    processes = []
    for key in ("handed_off_processes", "orphaned_processes", "unread_completions"):
        rows = entry.get(key)
        if not isinstance(rows, list):
            continue
        result["content_truncated"] |= len(rows) > 20
        for row in rows[:20]:
            if isinstance(row, dict):
                result["content_truncated"] |= any(isinstance(row.get(field), str) and len(row[field]) > 2048
                    for field in ("session_id", "command", "note", "output_tail"))
                processes.append({"kind": key, **{field: history_text(row.get(field), 2048)
                    for field in ("session_id", "command", "note", "output_tail")},
                    "runtime_seconds": history_number(row.get("runtime_seconds")),
                    "exit_code": row.get("exit_code") if type(row.get("exit_code")) is int else None})
    result["processes"] = processes
    result["content_truncated"] |= isinstance(errors, list) and (len(errors) > 20 or any(isinstance(e, str) and len(e) > 2048 for e in errors))
    return result


def tree_projection(payload):
    children = payload.get("subagents")
    if not isinstance(children, list):
        return None
    rows = []
    seen = set()
    for child in children[:256]:
        if not isinstance(child, dict):
            continue
        identifier = child.get("subagent_id") or child.get("id")
        if not isinstance(identifier, str) or not identifier or len(identifier) > 512 or identifier in seen:
            continue
        seen.add(identifier)
        row = {key: history_text(child.get(key), 4096) for key in
               ("parent_id", "goal", "model", "status", "delegation_id", "last_tool")}
        row.update(subagent_id=identifier[:512],
                   **{key: history_number(child.get(key)) for key in ("depth", "started_at", "tool_count")},
                   child_ref=None, controllable=False, accepting_steer=False)
        rows.append(row)
    return {"label": history_text(payload.get("label"), 4096),
            "started_at": history_number(payload.get("started_at")),
            "finished_at": history_number(payload.get("finished_at")),
            "children": rows, "truncated": len(children) > len(rows)}
