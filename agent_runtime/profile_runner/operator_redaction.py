"""The operator-facing scrubbers: commands, outputs, key/value blocks, tool
input/result, targets and paths — what an operator's tool-IO view may show.
"""

from __future__ import annotations

import json
from typing import Any
import re

from agent_runtime.redaction import safe_file_labels
from agent_runtime.serde import strict_int
__layer__ = "policy"

__all__ = [
    "_ABSOLUTE_PATHISH_RE",
    "_OPERATOR_COMMAND_MAX",
    "_OPERATOR_OUTPUT_MAX_CHARS",
    "_OPERATOR_OUTPUT_MAX_LINES",
    "_OPERATOR_PATH_SENSITIVE_MARKERS",
    "_OPERATOR_SECRET_MARKERS",
    "_OPERATOR_TARGET_MAX",
    "_OPERATOR_TARGET_PATH_KEYS",
    "_OPERATOR_TARGET_QUERY_KEYS",
    "_OPERATOR_TERMINAL_TOOLS",
    "_OPERATOR_TOOL_INPUT_MAX",
    "_OPERATOR_TOOL_RESULT_MAX",
    "_PATCH_HEADER_RE",
    "_TOOL_RESULT_ECHO_KEYS",
    "_attach_tool_io",
    "_is_error_result",
    "_line_has_secret",
    "_operator_path_sensitive",
    "_patch_paths_from_invocation",
    "_render_kv_line_token",
    "_render_operator_kv_block",
    "_safe_operator_command",
    "_safe_operator_output",
    "_safe_operator_paths",
    "_safe_operator_target",
    "_safe_operator_tool_input",
    "_safe_operator_tool_result",
    "_safe_tool_result_detail",
    "_scrub_operator_block_head",
]


# Operator-console field extractors. These feed the trusted Mission Control
# operator chat (the v2 stream + persisted turn elements) and are deliberately
# LESS strict than `_safe_command_label` (which is path-stripped for Telegram and
# other surfaces): the operator wants to see the real command and its output,
# including paths. Secrets are still scrubbed line-by-line and everything is
# bounded. Do NOT route these into untrusted surfaces.
_OPERATOR_SECRET_MARKERS = (
    "password",
    "passwd",
    "api_key",
    "apikey",
    "api-key",
    "authorization",
    "bearer ",
    "credential",
    "secret",
    "private_key",
    "private-key",
    "access_key",
    "session_token",
    " token=",
    "x-api-key",
    "sk-",
)


_OPERATOR_COMMAND_MAX = 1000


_OPERATOR_OUTPUT_MAX_LINES = 200


_OPERATOR_OUTPUT_MAX_CHARS = 8000


_OPERATOR_TERMINAL_TOOLS = {
    "terminal",
    "shell",
    "bash",
    "sh",
    "command",
    "run_command",
    "run",
    "code_execution",
    "code_execution_tool",
    "execute",
    "exec",
}


def _line_has_secret(line: str) -> bool:
    lowered = line.lower()
    return any(marker in lowered for marker in _OPERATOR_SECRET_MARKERS)


def _safe_operator_command(invocation: Any) -> str | None:
    if not isinstance(invocation, dict):
        return None
    command = invocation.get("command") or invocation.get("cmd")
    if not isinstance(command, str):
        return None
    text = command.strip()
    if not text:
        return None
    # Scrub a command that itself embeds a secret (e.g. `curl -H "authorization: …"`).
    if _line_has_secret(text):
        return "[command withheld — contained a secret]"
    if len(text) > _OPERATOR_COMMAND_MAX:
        text = f"{text[: _OPERATOR_COMMAND_MAX - 1]}…"
    return text


def _safe_operator_output(tool_name: str | None, result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    if (tool_name or "").lower() not in _OPERATOR_TERMINAL_TOOLS:
        return None
    raw = result.get("output")
    if not isinstance(raw, str):
        raw = result.get("stdout")
    if not isinstance(raw, str):
        return None
    text = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return None
    lines = [
        "[redacted line — contained a secret]" if _line_has_secret(line) else line
        for line in text.split("\n")
    ]
    truncated = False
    if len(lines) > _OPERATOR_OUTPUT_MAX_LINES:
        lines = lines[-_OPERATOR_OUTPUT_MAX_LINES :]
        truncated = True
    text = "\n".join(lines)
    if len(text) > _OPERATOR_OUTPUT_MAX_CHARS:
        text = text[-_OPERATOR_OUTPUT_MAX_CHARS :]
        truncated = True
    if truncated:
        text = f"…(earlier output truncated)…\n{text}"
    return text


# Generic tool-call input/result record (the "what was it called with / what
# came back" lane). Terminal-class calls keep their dedicated fields
# (command_full / output) and dev-work calls keep changed_paths; every tool
# call additionally gets a bounded, secret-scrubbed rendering of its raw
# invocation and result when no dedicated field captured them — so the
# operator console never has to show a bare "no detail was emitted" row.
# Dict payloads render one `key: <json>` line per top-level key so the
# per-line secret scrub drops only the offending pair, never the whole record.
_OPERATOR_TOOL_INPUT_MAX = 1000


_OPERATOR_TOOL_RESULT_MAX = 1600


# Result-envelope keys that dedicated payload fields already carry.
_TOOL_RESULT_ECHO_KEYS = ("exit_code",)


def _render_kv_line_token(value: Any) -> str:
    """One-line rendering of a dict KEY (or the last-resort repr). Newlines and
    NULs are REMOVED (not replaced with spaces) — the per-line secret scrub
    keys on contiguous marker words, so a hostile key like ``"pass\\nword"``
    must reconstitute to ``password`` on ONE line rather than split the marker
    across two lines and defeat every scrub layer downstream."""

    return re.sub(r"[\r\n\x00]+", "", str(value))


def _render_operator_kv_block(value: Any) -> str | None:
    try:
        if isinstance(value, dict):
            text = "\n".join(
                f"{_render_kv_line_token(key)}: {json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)}"
                for key, item in value.items()
            )
        elif isinstance(value, str):
            text = value
        else:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        # Last-resort repr, itself guarded: str() can re-raise on pathological
        # values (RecursionError on deep nesting). Losing the IO record is
        # acceptable; losing the WHOLE tool event (via the sink's best-effort
        # boundary swallowing the raise) is not.
        try:
            text = _render_kv_line_token(value)
        except Exception:
            return None
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return text or None


def _scrub_operator_block_head(text: str, *, limit: int) -> str | None:
    """Per-line secret scrub, HEAD-bounded: the leading keys/fields are the
    operator signal (unlike command output, where the tail is), so truncation
    keeps the front and marks the cut explicitly. A record whose EVERY line was
    redacted carries zero signal — dropped whole rather than persisted as a
    marker-only blob."""

    kept_any = False
    lines: list[str] = []
    for line in text.split("\n"):
        if _line_has_secret(line):
            lines.append("[redacted line — contained a secret]")
        else:
            lines.append(line)
            if line.strip():
                kept_any = True
    if not kept_any:
        return None
    out = "\n".join(lines).strip()
    if not out:
        return None
    if len(out) > limit:
        out = f"{out[:limit]}\n…(rest truncated)…"
    return out


def _safe_operator_tool_input(invocation: Any) -> str | None:
    if not isinstance(invocation, dict) or not invocation:
        return None
    rendered = _render_operator_kv_block(invocation)
    if rendered is None:
        return None
    return _scrub_operator_block_head(rendered, limit=_OPERATOR_TOOL_INPUT_MAX)


def _safe_operator_tool_result(result: Any) -> str | None:
    if result is None:
        return None
    if isinstance(result, dict):
        slim = {key: item for key, item in result.items() if key not in _TOOL_RESULT_ECHO_KEYS}
        if not slim:
            return None
        rendered = _render_operator_kv_block(slim)
    else:
        rendered = _render_operator_kv_block(result)
    if rendered is None:
        return None
    return _scrub_operator_block_head(rendered, limit=_OPERATOR_TOOL_RESULT_MAX)


def _attach_tool_io(payload: dict[str, Any], *, invocation: Any, result: Any = None) -> None:
    """Attach the generic ``tool_input`` / ``tool_result`` record to a tool payload.

    Dedicated fields stay authoritative and are never duplicated against the
    4KB event cap: a call whose input already surfaced as a command keeps
    command_full as its input record, and a terminal-class call's result IS its
    ``output`` tail. Everything else gets the generic record.
    """

    if "command_full" not in payload and "command_label" not in payload:
        tool_input = _safe_operator_tool_input(invocation)
        if tool_input:
            payload["tool_input"] = tool_input
    if result is not None and "output" not in payload:
        tool_result = _safe_operator_tool_result(result)
        if tool_result:
            payload["tool_result"] = tool_result


_OPERATOR_TARGET_MAX = 300


_OPERATOR_TARGET_PATH_KEYS = ("path", "file_path", "target_path", "file", "filename", "directory", "dir")


_OPERATOR_TARGET_QUERY_KEYS = ("pattern", "query", "glob", "regex", "search", "name")


# Diff/patch header forms the runner sees in the wild: the OpenAI apply_patch
# envelope (*** Update|Add|Delete File: path), unified diff (+++ b/path), and
# git headers (diff --git a/p b/p).
_PATCH_HEADER_RE = re.compile(
    r"^\*\*\* (?:Update|Add|Delete) File: (.+?)\s*$"
    r"|^\+\+\+ b/(.+?)\s*$"
    r"|^diff --git a/\S+ b/(\S+)\s*$",
    re.MULTILINE,
)


# Bare-word markers for operator path/target scrubbing: stricter than
# _OPERATOR_SECRET_MARKERS (bare "token", not just " token=") because a path
# named private_token.dart must never surface, even relative.
_OPERATOR_PATH_SENSITIVE_MARKERS = (
    "secret", "token", "password", "passwd", "api_key", "apikey",
    "authorization", "bearer", "credential", "cookie", "private_key", "sk-",
)


_ABSOLUTE_PATHISH_RE = re.compile(r"^([A-Za-z]:/|//|/|~)")


def _operator_path_sensitive(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _OPERATOR_PATH_SENSITIVE_MARKERS)


def _safe_operator_target(invocation: Any) -> str | None:
    """Operator-console label for what a read/search/list tool acted on.

    Operator-grade but path-disciplined: repo-relative paths surface verbatim;
    absolute paths are trimmed to their trailing segments; anything carrying a
    secret-looking token is dropped. Do NOT route into untrusted surfaces; the
    Telegram-safe lane stays ``command_label``.
    """

    if not isinstance(invocation, dict):
        return None

    def _clean(value: Any) -> str | None:
        text = " ".join(str(value).strip().split()).replace("\\", "/")
        if not text or _line_has_secret(text) or _operator_path_sensitive(text):
            return None
        if _ABSOLUTE_PATHISH_RE.match(text):
            segments = [segment for segment in text.split("/") if segment]
            if len(segments) < 2:
                return None
            text = "…/" + "/".join(segments[-3:])
        return text

    path = next(
        (
            cleaned
            for key in _OPERATOR_TARGET_PATH_KEYS
            if isinstance(invocation.get(key), str) and invocation.get(key).strip()
            if (cleaned := _clean(invocation.get(key))) is not None
        ),
        None,
    )
    query = next(
        (
            cleaned
            for key in _OPERATOR_TARGET_QUERY_KEYS
            if isinstance(invocation.get(key), str) and invocation.get(key).strip()
            if (cleaned := _clean(invocation.get(key))) is not None
        ),
        None,
    )
    if query and path:
        label = f"{query} in {path}"
    else:
        label = query or path
    if not label:
        return None
    return f"{label[: _OPERATOR_TARGET_MAX - 1]}…" if len(label) > _OPERATOR_TARGET_MAX else label


def _patch_paths_from_invocation(invocation: Any) -> list[str]:
    """Changed-file paths recovered from the patch text itself.

    The patch tool's RESULT frequently returns no file list ("changed-file
    list unavailable"), but the file paths are right there in the diff headers
    of the INVOCATION. Parsing them makes edit calls legible to the operator.
    """

    if not isinstance(invocation, dict):
        return []
    text = next(
        (
            invocation.get(key)
            for key in ("patch", "diff", "patch_text", "input", "content")
            if isinstance(invocation.get(key), str) and invocation.get(key).strip()
        ),
        None,
    )
    if not text:
        return []
    paths: list[str] = []
    for match in _PATCH_HEADER_RE.finditer(text):
        raw = next((group for group in match.groups() if group), None)
        if not raw:
            continue
        cleaned = raw.strip().replace("\\", "/")
        if not cleaned or cleaned == "/dev/null" or _line_has_secret(cleaned):
            continue
        if cleaned not in paths:
            paths.append(cleaned)
        if len(paths) >= 20:
            break
    return paths


def _safe_operator_paths(values: list[Any]) -> list[str]:
    """Operator-grade changed-path list: RELATIVE paths only, bounded.

    Absolute paths never surface (machine-identifying); their basenames still
    reach the operator through ``changed_files``. Secret-looking names drop.
    """

    paths: list[str] = []
    for item in values:
        text = " ".join(str(item or "").strip().split()).replace("\\", "/")
        if not text or _line_has_secret(text) or _operator_path_sensitive(text):
            continue
        if _ABSOLUTE_PATHISH_RE.match(text):
            continue
        if len(text) > 200:
            text = f"…{text[-199:]}"
        if text not in paths:
            paths.append(text)
        if len(paths) >= 12:
            break
    return paths


def _safe_tool_result_detail(tool_name: str | None, result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    normalized_tool = (tool_name or "").lower()
    if normalized_tool == "patch":
        files = result.get("files_modified") or result.get("modified_files") or result.get("files")
        labels = safe_file_labels(files)
        if labels:
            return f"Patch modified {len(labels)} files: {', '.join(labels[:4])}{'…' if len(labels) > 4 else ''}"
        if result.get("success") is True:
            return "Patch completed successfully; no file list returned."
    return None


def _is_error_result(result: Any) -> bool:
    if isinstance(result, dict):
        if result.get("error") or result.get("success") is False:
            return True
        # Harness tool envelope: a top-level ok:false IS the failure verdict
        # (agent_chat_send, harness verbs). Missing this projected failed
        # dispatches as status="passed" → green OK chips on the operator
        # console for sends that never reached their target (2026-07-23).
        if result.get("ok") is False:
            return True
        exit_code = strict_int(result.get("exit_code"))
        if exit_code is not None:
            return exit_code != 0
    if isinstance(result, str):
        lowered = result.strip().lower()
        if lowered.startswith(("error", "traceback", "exception")) or '"success": false' in lowered:
            return True
        # Serialized harness envelope. Parse-confirm before trusting the
        # substring so a tool result that merely CONTAINS such text (e.g. a
        # read_file of a JSON fixture) can never be misread as a failure —
        # only a top-level {"ok": false, ...} object counts.
        if lowered.startswith("{") and ('"ok": false' in lowered or '"ok":false' in lowered):
            try:
                parsed = json.loads(result)
            except (ValueError, TypeError):
                return False
            return isinstance(parsed, dict) and parsed.get("ok") is False
    return False
