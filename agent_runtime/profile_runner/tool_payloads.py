"""Tool started/finished and dev-work payloads, patch-mode and file-label
fields, the todo-state payload, and the safe label/exit-code/summary coercions.
"""

from __future__ import annotations

import json
from typing import Any
import re

from agent_runtime.profile_runner.dispatch_payloads import (
    _agent_chat_dispatch_fields,
    _agent_chat_dispatch_reply_fields,
    _agent_chat_dispatch_thread_fields,
    _agent_chat_target_label,
)
from agent_runtime.profile_runner.operator_redaction import (
    _attach_tool_io,
    _line_has_secret,
    _looks_sensitive_or_pathish,
    _patch_paths_from_invocation,
    _safe_exit_code,
    _safe_file_labels,
    _safe_operator_command,
    _safe_operator_output,
    _safe_operator_paths,
    _safe_operator_target,
    _safe_tool_result_detail,
)

__layer__ = "policy"

__all__ = [
    "_PATCH_MODES",
    "_TODO_STATE_MAX_CONTENT",
    "_TODO_STATE_MAX_ID",
    "_TODO_STATE_MAX_ITEMS",
    "_TODO_STATE_VALID_STATUS",
    "_candidate_file_values",
    "_collapse_todo_ws",
    "_dev_work_payload",
    "_duration_ms",
    "_patch_diff_fields",
    "_patch_mode_token",
    "_safe_command_label",
    "_safe_label",
    "_safe_reasoning_summary",
    "_safe_skill_identifier_from_value",
    "_safe_skill_tool_name",
    "_todo_items_from",
    "_todo_state_payload",
    "_tool_finished_payload",
    "_tool_started_payload",
]


def _tool_started_payload(event_type: str, tool_name: str | None, *, invocation: Any = None) -> dict[str, Any]:
    payload = {"type": event_type, "phase": "tool", "step": "tool_started", "status": "started"}
    if tool_name:
        payload["tool_name"] = tool_name
        payload["summary"] = f"Started tool {tool_name}"
    else:
        payload["summary"] = "Started tool"
    agent_chat_label = _agent_chat_target_label(tool_name, invocation)
    if agent_chat_label:
        payload["target_label"] = agent_chat_label
        payload["summary"] = f"Started tool {tool_name}: {agent_chat_label}"
        # Additive G2 dispatch fields (structured target + full order). The
        # started event is the authoritative carrier; the launcher merges the
        # started/finished pair so finished-only is not needed here.
        payload.update(_agent_chat_dispatch_fields(tool_name, invocation))
        return payload
    command_label = _safe_command_label(invocation)
    if command_label:
        payload["command_label"] = command_label
        if tool_name:
            payload["summary"] = f"Started tool {tool_name}: {command_label}"
    command_full = _safe_operator_command(invocation)
    if command_full:
        payload["command_full"] = command_full
    target_label = _safe_operator_target(invocation)
    if target_label:
        payload["target_label"] = target_label
        if tool_name and not command_label:
            payload["summary"] = f"Started tool {tool_name}: {target_label}"
    skill_name = _safe_skill_tool_name(tool_name, invocation)
    if skill_name:
        payload["skill_name"] = skill_name
    _attach_tool_io(payload, invocation=invocation)
    return payload


def _tool_finished_payload(event_type: str, tool_name: str | None, *, duration: Any, is_error: bool, result: Any, invocation: Any = None) -> dict[str, Any]:
    status = "failed" if is_error else "passed"
    payload = {"type": event_type, "phase": "tool", "step": "tool_finished", "status": status}
    if tool_name:
        payload["tool_name"] = tool_name
    duration_ms = _duration_ms(duration)
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    exit_code = _safe_exit_code((result or {}).get("exit_code") if isinstance(result, dict) else None)
    if exit_code is not None:
        payload["exit_code"] = exit_code
    skill_name = _safe_skill_tool_name(tool_name, invocation) or _safe_skill_tool_name(tool_name, result)
    if skill_name:
        payload["skill_name"] = skill_name
    dev_work_payload = _dev_work_payload(tool_name, status=status, result=result, invocation=invocation)
    if dev_work_payload:
        # No target echo and NO generic tool_input/tool_result for dev-work
        # tools: changed_paths/changed_files ARE the record, and the raw
        # invocation/result carry the diff body and machine-absolute paths
        # that this lane deliberately never persists.
        payload.update(dev_work_payload)
        return payload
    target_label = (
        _agent_chat_target_label(tool_name, invocation) or _safe_operator_target(invocation)
    )
    if target_label:
        payload["target_label"] = target_label
    subject = f"tool {tool_name}" if tool_name else "tool"
    if duration_ms is not None:
        payload["summary"] = f"Finished {subject}: {status} in {duration_ms}ms"
    else:
        payload["summary"] = f"Finished {subject}: {status}"
    detail = _safe_tool_result_detail(tool_name, result)
    if detail:
        payload["detail"] = detail
    command_label = _safe_command_label(invocation)
    if command_label:
        payload["command_label"] = command_label
    command_full = _safe_operator_command(invocation)
    if command_full:
        payload["command_full"] = command_full
    output = _safe_operator_output(tool_name, result)
    if output:
        payload["output"] = output
    todo_state = _todo_state_payload(tool_name, result, invocation)
    if todo_state is not None:
        payload["todo_state"] = todo_state
    # Where the relay landed. Additive: the started event's
    # dispatch_target/dispatch_order are untouched, and a lane that cannot name
    # a thread (detached dispatch, refusal) emits nothing at all.
    payload.update(_agent_chat_dispatch_thread_fields(tool_name, result))
    # ...and what came back. Finished-only, like the thread id: a reply is a
    # result fact, so the started event stays byte-identical.
    payload.update(_agent_chat_dispatch_reply_fields(tool_name, result))
    # agent_chat_send input is already first-class (dispatch_target/dispatch_order
    # on the started event) — re-attaching the order as tool_input would spend
    # the same bytes twice against the event cap. Its RESULT still attaches.
    _attach_tool_io(
        payload,
        invocation=None if tool_name == "agent_chat_send" else invocation,
        result=result,
    )
    return payload


def _dev_work_payload(tool_name: str | None, *, status: str, result: Any, invocation: Any) -> dict[str, Any] | None:
    normalized_tool = (tool_name or "").lower()
    if normalized_tool in {"patch", "apply_patch"}:
        # The tool RESULT often returns no file list; the diff headers in the
        # INVOCATION are the reliable record of what an edit call touched.
        candidates = _candidate_file_values(result, None) or _patch_paths_from_invocation(invocation)
        labels = _safe_file_labels(candidates)
        operator_paths = _safe_operator_paths(candidates)
        payload: dict[str, Any] = {"phase": "dev_work", "step": "patch"}
        if operator_paths:
            payload["changed_paths"] = operator_paths
        payload["patch_mode"] = _patch_mode_token(normalized_tool, invocation)
        if labels:
            joined = ", ".join(labels[:4]) + ("…" if len(labels) > 4 else "")
            payload["changed_files"] = labels
            payload["files_touched"] = len(labels)
            payload["summary"] = f"Patched {len(labels)} files: {joined}"
            payload["detail"] = f"Changed files: {joined}"
            payload["patch_summary"] = f"Patched {len(labels)} files"
        elif status == "passed":
            payload["summary"] = "Patch completed; changed-file list unavailable"
            payload["patch_summary"] = "Patch completed"
        else:
            payload["summary"] = "Patch failed"
            payload["patch_summary"] = "Patch failed"
        if status == "passed":
            # The diff BODY stays on this machine (see patch_diff_artifacts) —
            # what joins the payload is the artifact's path and its +/− counts.
            # `diff` itself is never added to any payload here, and the tripwire
            # for that is test_profile_runner.py's
            # `test_progress_adapter_summarizes_patch_tool_result_without_raw_diff`
            # (it pins THIS payload's exact shape). The observability-lane test
            # guards the other half — the task lane's allowlist — but it builds
            # its own payload, so it cannot see a producer regression.
            payload.update(_patch_diff_fields(result))
        return payload
    if normalized_tool in {"write_file", "edit_file", "file.write", "file.edit"}:
        candidates = _candidate_file_values(result, invocation)
        labels = _safe_file_labels(candidates)
        operator_paths = _safe_operator_paths(candidates)
        payload = {"phase": "dev_work", "step": "write_file" if normalized_tool == "write_file" else "code_edit"}
        if operator_paths:
            payload["changed_paths"] = operator_paths
        if labels:
            joined = ", ".join(labels[:4]) + ("…" if len(labels) > 4 else "")
            payload["changed_files"] = labels
            payload["files_touched"] = len(labels)
            if len(labels) == 1:
                payload["summary"] = f"Wrote code file: {labels[0]}"
                payload["file_summary"] = "Wrote code file"
            else:
                payload["summary"] = f"Wrote code files: {len(labels)} files"
                payload["file_summary"] = "Wrote code files"
            payload["detail"] = f"Changed files: {joined}"
        elif status == "passed":
            payload["summary"] = "Wrote code file; changed-file list unavailable"
            payload["file_summary"] = "Wrote code file"
        else:
            payload["summary"] = "Code file write failed"
            payload["file_summary"] = "Code file write failed"
        return payload
    return None


#: The two patch grammars, and the only two tokens ``patch_mode`` may carry.
#: A value from an invocation is admitted only if it is one of these — an
#: unrecognized mode falls back to the tool's own default rather than putting
#: caller-supplied prose on the wire.
_PATCH_MODES = ("replace", "patch")


def _patch_mode_token(normalized_tool: str, invocation: Any) -> str:
    """Which patch grammar this call used: ``replace`` (old/new string) or
    ``patch`` (V4A).

    The invocation is the authority when it names a valid mode. Absent that, the
    default is the tool's: ``patch`` defaults to replace mode exactly like
    ``patch_tool(mode="replace")`` does, and ``apply_patch`` is V4A-only.
    """

    if isinstance(invocation, dict):
        mode = str(invocation.get("mode") or "").strip().lower()
        if mode in _PATCH_MODES:
            return mode
    return "patch" if normalized_tool == "apply_patch" else "replace"


def _patch_diff_fields(result: Any) -> dict[str, Any]:
    """Write the call's diff to the local artifact store and name it.

    Lazy import: the artifact module touches the store root, and this module is
    imported in contexts (tests, tooling) that resolve one only when they must.
    Best-effort by construction — ``record_patch_diff`` swallows its own
    failures, and an empty dict here means the tile renders without the viewer
    affordance, never that the turn breaks.
    """

    try:
        from ..patch_diff_artifacts import record_patch_diff

        fields = record_patch_diff(result)
    except Exception:
        return {}
    return fields if isinstance(fields, dict) else {}


def _candidate_file_values(result: Any, invocation: Any) -> list[Any]:
    values: list[Any] = []
    for source in (result, invocation):
        if not isinstance(source, dict):
            continue
        for key in ("files_modified", "modified_files", "changed_files", "files", "path", "file_path", "target_path"):
            value = source.get(key)
            if isinstance(value, list):
                values.extend(value)
            elif value:
                values.append(value)
    return values


def _safe_command_label(invocation: Any) -> str | None:
    if not isinstance(invocation, dict):
        return None
    command = invocation.get("command") or invocation.get("cmd")
    if not isinstance(command, str):
        return None
    text = " ".join(command.strip().split())
    if not text:
        return None
    lowered = text.lower()
    if any(marker in lowered for marker in ("secret", "token", "password", "api_key", "apikey", "authorization", "bearer", "credential", "cookie", "private_key", "sk-")):
        return None
    text = text.replace("\\", "/")
    if re.search(r"(^|\s)([A-Za-z]:/|//|/home/|/users/|/x/|/c/|~)", text.lower()):
        return None
    return f"{text[:237]}..." if len(text) > 240 else text


def _safe_skill_tool_name(tool_name: str | None, value: Any) -> str | None:
    if (tool_name or "").lower() != "skill_view":
        return None
    return _safe_skill_identifier_from_value(value)


def _safe_skill_identifier_from_value(value: Any) -> str | None:
    if isinstance(value, str):
        return _safe_label(value)
    if not isinstance(value, dict):
        return None
    for key in ("skill_name", "skill", "identifier", "name"):
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip():
            return _safe_label(raw)
    for key in ("input", "tool_input", "invocation", "metadata", "result"):
        nested = value.get(key)
        found = _safe_skill_identifier_from_value(nested)
        if found:
            return found
    return None


# Bounds for the todo checklist mirrored onto the trace/turn-store lane. The
# store itself caps content at MAX_TODO_CONTENT_CHARS (4000) / MAX_TODO_ITEMS
# (256); the operator-console projection is a COMPACT checklist, so the wire
# copy is tighter — a checklist row is a short line, and the frame must stay
# minimal (T7: smallest honest emit, no snapshot-frame growth beyond a bounded
# payload).
#
# Over-cap content is marked with an ellipsis, never dropped silently.
#
# T9c: id/content are whitespace-collapsed to the SAME shape the persist
# re-bound (`mission_chat_turns._safe_todo_state`, via `safe_assignment_text`)
# produces — whitespace runs collapsed to single spaces. The persist lane
# re-runs `safe_assignment_text` over THIS output, and that function is
# idempotent on an already-collapsed string (including the over-cap
# `…`-terminated form), so the live `tool.finished` frame and the reloaded
# turn-store element carry byte-identical text. (Before T9c the producer only
# `.strip()`ped, so multi-line/multi-space content diverged: the live lane kept
# the internal whitespace the persist lane collapsed.)
_TODO_STATE_MAX_ITEMS = 64


_TODO_STATE_MAX_CONTENT = 240


_TODO_STATE_MAX_ID = 120


_TODO_STATE_VALID_STATUS = {"pending", "in_progress", "completed", "cancelled"}


def _todo_state_payload(tool_name: str | None, result: Any, invocation: Any) -> list[dict[str, str]] | None:
    """Minimal structured todo-checklist state for the operator console (T7).

    The ``todo`` tool keeps its list in-memory per session and re-injects it into
    the prompt; nothing on the trace/turn-store lane carried the list itself (the
    element ``args`` is a human summary and ``output`` is gated to terminal
    tools). This copies the tool RESULT — the authoritative post-write list (all
    statuses) returned by :func:`tools.todo_tool.todo_tool` — onto the finished
    event, bounded and validated. Falls back to the invocation's ``todos`` when
    the result is unparseable. Returns ``None`` for any non-todo tool or when no
    list is recoverable (unparseable result AND invocation) — absence means "no
    todo involvement", never fabricate. A recovered but EMPTY list returns an
    explicit ``[]`` (T9d): a todo write that clears the checklist must tell the
    operator console to clear it, a state distinct from absence."""

    if (tool_name or "").lower() not in {"todo", "todo_list"}:
        return None
    todos = _todo_items_from(result)
    if todos is None:
        todos = _todo_items_from(invocation)
    if todos is None:
        # Neither the result nor the invocation yielded a list — unrecoverable,
        # so stay silent (absent). This is NOT an empty checklist: a cleared list
        # comes back as ``[]`` from _todo_items_from and falls through to the
        # explicit-empty return below (T9d cleared-todo contract).
        return None
    items: list[dict[str, str]] = []
    for raw in todos[:_TODO_STATE_MAX_ITEMS]:
        if not isinstance(raw, dict):
            continue
        # T9c: collapse whitespace to the persisted `safe_assignment_text` shape
        # (id is a straight cap; content keeps the over-cap ellipsis, which the
        # persist re-run preserves because it operates on this already-collapsed
        # output). See the note on the bound constants above.
        item_id = _collapse_todo_ws(raw.get("id"))[:_TODO_STATE_MAX_ID] or "?"
        content = _collapse_todo_ws(raw.get("content"))
        status = str(raw.get("status", "")).strip().lower()
        if status not in _TODO_STATE_VALID_STATUS:
            status = "pending"
        if not content:
            content = "(no description)"
        elif len(content) > _TODO_STATE_MAX_CONTENT:
            content = content[: _TODO_STATE_MAX_CONTENT - 1] + "…"
        items.append({"id": item_id, "content": content, "status": status})
    # T9d: return ``items`` directly (NOT ``items or None``) so a recovered but
    # empty list stays an explicit ``[]`` — the cleared-checklist signal. ``None``
    # is reserved for non-todo tools / unrecoverable payloads (handled above).
    return items


def _collapse_todo_ws(value: Any) -> str:
    """Collapse whitespace runs to single spaces, mirroring the normalization in
    ``persona_assignments.safe_assignment_text`` (minus its length cap).

    The persist re-bound (``mission_chat_turns._safe_todo_state``) runs
    ``safe_assignment_text`` over THIS output; that function is idempotent on an
    already-collapsed string, so the live ``tool.finished`` frame and the
    reloaded turn-store element carry byte-identical todo text (T9c)."""

    return " ".join(str(value or "").replace("\x00", " ").split())


def _todo_items_from(source: Any) -> list[Any] | None:
    """Recover the ``todos`` list from a todo tool result/invocation.

    Accepts the JSON-string result (``{"todos": [...], "summary": {...}}``), a
    dict result/invocation carrying ``todos``, or a bare list. Returns ``None``
    when no list is recoverable."""

    value: Any = source
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
    if isinstance(value, dict):
        todos = value.get("todos")
        return todos if isinstance(todos, list) else None
    if isinstance(value, list):
        return value
    return None


def _duration_ms(value: Any) -> int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0 or number != number or number == float("inf"):
        return None
    return int(round(number * 1000))


def _safe_label(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or _looks_sensitive_or_pathish(text):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", text):
        return None
    return text


def _safe_reasoning_summary(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    """Reasoning text from a thinking callback, operator-grade.

    Two positional shapes reach this: the subagent relay
    ``("_thinking", first_line)`` and the structured emission
    ``("reasoning.available", "_thinking", text, None)`` — ``"_thinking"`` is
    the channel placeholder in both, never content. Paths are allowed
    (operator console); secret-bearing lines are masked in place.
    """

    candidates: list[Any] = [
        kwargs.get("reasoning_summary"),
        kwargs.get("summary"),
        kwargs.get("reasoning"),
    ]
    candidates.extend(arg for arg in args[1:4] if arg != "_thinking")
    for value in candidates:
        if not isinstance(value, str):
            continue
        masked = " ".join(
            "[redacted line — contained a secret]" if _line_has_secret(line) else line
            for line in value.strip().splitlines()
        )
        text = " ".join(masked.split())
        if not text:
            continue
        if len(text) > 500:
            text = f"{text[:497]}…"
        return text
    return None
