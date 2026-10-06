"""Fork-owned short wire descriptions; retain live upstream documentation.

The registry keeps upstream's schema text (``tool_describe`` serves it). The brief
reaches the wire through :func:`brief_request_tools`, which the eternia-harness
plugin registers as ``llm_request`` middleware: it replaces ``description`` by tool
name in the final provider kwargs and never touches parameters — except for the
promoted MCP tools (:func:`promoted_brief`), whose parameter descriptions are clipped
too, since the server's whole manual would otherwise ride every turn. No built-in is
briefed at registration (``terminal``, the last, left 2026-09-26, lane PF-1). A
brief exists only while it is shorter than upstream's text: ``vision_analyze`` left 2026-09-24 (lane REDS3) once upstream's
own diet (#97339) undercut it.
"""

import json
from typing import Any, Dict, Iterable, Optional

BRIEF_DESCRIPTIONS = {
    'browser_navigate': 'Load a URL before other browser_* calls; returns a compact snapshot '
                        'with ref IDs. Use for interactive pages; prefer text retrieval or '
                        'terminal fetching for plain text/API endpoints.',
    'write_file': 'Replace a whole file, creating parent directories and reporting new syntax '
                  'errors. Read existing files first; unread or changed-file overwrites are '
                  'refused. Use patch for targeted edits; prefer this over shell writes.',
    'terminal': 'Run shell commands; cwd/exported env persist. Use background=true for '
                'long tasks (exit notice by default; notify=false opts out); pty=true for interactive CLIs. Prefer file tools '
                'for file work. Call tool_describe for lifecycle/platform details.',
    # Moved out of the upstream tool files 2026-09-24 (lane MECH): the fork's
    # trimmed wire text, upstream's schema text left as shipped.
    "todo_list": "Session task list for 3+ steps; no args reads it. For requested batches, enumerate every instance; split phases via parent. Keep ONE item in_progress; mark complete only when verified done. If a task fails, cancel it and add a revised item. Not durable memory.",
    "close_terminal": "Close the read-only GUI tab for a background process (desktop only): drops the view, does NOT kill the process (output keeps buffering; reopen from the status stack). Disambiguator: to stop the process use process_manage(action='kill').",
    "process_manage": "Background processes: wait returns partial output on timeout. submit appends Enter to answer prompts; write sends raw bytes, no newline. Subagents must handoff surviving processes. Call tool_describe for ownership and retention details.",
    "read_terminal": "Read what is currently shown in the Hermes desktop GUI's embedded terminal pane (desktop only). No args = visible screen + total_lines; pass start_line/count to page scrollback. Returns a JSON viewport.",
    "web_search": "Search the web (up to 5 results: title, URL, description). Backend operators like site:, filetype:, intitle:, -term, and \"exact phrase\" may work. Disambiguator: use web_extract to read a specific page.",
    "web_extract": "Extract clean markdown/text from web page or PDF URLs (no LLM summarization). Large pages return a head+tail window with a saved-file path to read the rest. Disambiguator: for interactive or failed pages use the browser tools; to find pages use web_search.",
    "patch": "Targeted find-and-replace file edits with fuzzy matching; returns a unified diff and auto-runs syntax checks. Supply path, old_string and new_string. Disambiguator: use instead of shell sed/awk; use write_file for full rewrites.",
    "search_files": "Search file contents (target='content', regex, ripgrep-backed) or find files by name/glob (target='files', sorted by mtime). Disambiguator: use instead of shell grep/rg/find/ls.",
    "browser_snapshot": "Get a text accessibility-tree snapshot of the current page with ref IDs (@e1...) for browser_click/type. full=false compact (default), full=true complete. Oversized snapshots are truncated/summarized and the complete text is saved to a file whose path is in the output. Disambiguator: browser_navigate already returns one -- use this to refresh after the page changes.",
    "browser_click": "Click an element by its snapshot ref ID (e.g. @e5). Requires a prior browser_snapshot.",
    "browser_type": "Type text into an input field by its snapshot ref ID (clears the field first).",
    "browser_scroll": "Scroll the page in a direction to reveal content above or below the viewport.",
    "browser_back": "Go back to the previous page in browser history.",
    "browser_press": "Press a keyboard key (Enter to submit, Tab to navigate, or a shortcut).",
    "browser_get_images": "List all images on the current page with URLs and alt text (find images to analyze with vision_analyze).",
    "browser_vision": "Screenshot the current page to inspect it visually (CAPTCHAs, layout, visual checks). Native-vision models see it next turn; others get an auxiliary text analysis. Returns screenshot_path (share via MEDIA:<path>). Requires browser_navigate first.",
    "browser_console": "Get the current page's console output and uncaught JS errors (log/warn/error/info); pass `expression` to evaluate JS in the page and return the result. Use to catch silent JS/API failures. Requires browser_navigate first.",
    # Moved out of the upstream tool files 2026-09-24 (lane MOVE-A): each file
    # carried its own brief (clarify, execute_code) or a FULL_* copy
    # (session_search); upstream's text now stays in the registry.
    "clarify": "Ask 1-5 independent questions in one call. Put options only in choices, recommended first; omit for free text. Responses preserve order. Decide low-stakes matters yourself; terminal owns dangerous-command confirmation.",
    "execute_code": (
        "Run Python in a persistent session kernel via `from hermes_tools import ...` "
        "(web_search, web_extract, read_file, write_file, search_files, patch, terminal). "
        "Use for 3+ chained calls with logic/filter/loop; use plain calls otherwise. "
        "State survives calls; timeout/interruption loses it. 5-min / 50KB stdout / 50-call limits; "
        "print your result. Truncated stdout includes a full-output file. "
        "Call tool_describe for available tools, helper imports and execution-mode guidance."
    ),
    "session_search": "Search conversation history (FTS5): query to discover; session_id + around_message_id to scroll; session_id to read; no args for recent. Paste returned link verbatim when citing a session. If given a live source (URL/file/account), inspect that first. Call tool_describe for shapes and search syntax.",
    # Lane REDS3 2026-09-24: the 2026-09-21 merge (f443c9ab35) took upstream's
    # READ_FILE_SCHEMA text whole, dropping the fork's inline brief; the brief
    # rides the middleware now and tool_describe serves the live registry text.
    "read_file": "Read a text file with line numbers and pagination (offset/limit; large reads "
                 "truncate on a line boundary with next_offset). Auto-extracts .ipynb/.docx/.xlsx/"
                 ".pptx, .doc/.ppt/.xls, PDF (text layer), OpenDocument, RTF, EPUB and SQLite. "
                 "Cannot read images/binary -- use vision_analyze for images; prefer this over "
                 "shell cat/head/tail.",
}

#: The promoted-MCP brief (lane h-prompt-tools S2): a server's manual rides every turn once
#: its tool is promoted eager (``tools.tool_search_downstream.PROMOTED_MCP_TOOLS``), so the wire
#: carries the first sentence (at most this many chars) and every parameter description clipped
#: to the second bound. The registry keeps the server's text: ``tool_describe`` serves the full
#: description AND the full ``parameters`` from it, one call away.
PROMOTED_BRIEF_DESCRIPTION_CHARS = 300
PROMOTED_BRIEF_PARAMETER_CHARS = 120
PROMOTED_BRIEF_SUFFIX = " Full reference: tool_describe."


def _clip(text: str, cap: int) -> str:
    return text if len(text) <= cap else text[: cap - 1].rstrip() + "…"


def _first_sentence(text: str) -> str:
    """The text up to its first sentence end (a "." then a space, past 40 chars), clipped."""
    text = " ".join(str(text or "").split())
    for index in range(40, len(text)):
        if text[index] == "." and (index + 1 == len(text) or text[index + 1] == " "):
            return _clip(text[: index + 1], PROMOTED_BRIEF_DESCRIPTION_CHARS)
    return _clip(text, PROMOTED_BRIEF_DESCRIPTION_CHARS)


def _clipped_schema(node: Any) -> Any:
    """A JSON schema with every nested ``description`` clipped; structure and types kept whole."""
    if isinstance(node, dict):
        return {
            key: (_clip(value, PROMOTED_BRIEF_PARAMETER_CHARS)
                  if key == "description" and isinstance(value, str) else _clipped_schema(value))
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_clipped_schema(item) for item in node]
    return node


def promoted_brief(target: Dict[str, Any]) -> Dict[str, Any]:
    """A promoted MCP tool's function body with its brief description and clipped parameters."""
    rewritten = {**target, "description": _first_sentence(target.get("description") or "") + PROMOTED_BRIEF_SUFFIX}
    for key in ("parameters", "input_schema"):
        if isinstance(target.get(key), dict):
            rewritten[key] = _clipped_schema(target[key])
    return rewritten


def _briefed(entry: Any) -> Optional[Dict[str, Any]]:
    """``entry`` with its brief description, or None when it needs no rewrite.

    Three payload shapes: chat completions (``{"type": "function", "function": {...}}``),
    Responses (``{"type": "function", "name", "description", ...}``) and Anthropic
    (``{"name", "description", "input_schema"}``).
    """
    if not isinstance(entry, dict):
        return None
    inner = entry.get("function")
    target = inner if isinstance(inner, dict) else entry
    name = target.get("name")
    brief = BRIEF_DESCRIPTIONS.get(name)
    if brief is None:
        from tools.tool_search_downstream import PROMOTED_MCP_TOOLS

        if name not in PROMOTED_MCP_TOOLS or str(target.get("description") or "").endswith(PROMOTED_BRIEF_SUFFIX):
            return None
        rewritten = promoted_brief(target)
    elif target.get("description") == brief:
        return None
    else:
        rewritten = {**target, "description": brief}
    return {**entry, "function": rewritten} if target is inner else rewritten


def brief_request_tools(request: Any) -> Optional[Dict[str, Any]]:
    """The provider kwargs with every briefed tool's description replaced, or None if unchanged."""
    if not isinstance(request, dict) or not isinstance(request.get("tools"), list):
        return None
    tools = list(request["tools"])
    changed = False
    for index, entry in enumerate(tools):
        rewritten = _briefed(entry)
        if rewritten is not None:
            tools[index] = rewritten
            changed = True
    return {**request, "tools": tools} if changed else None


def wire_tool_chars(tool_defs: Iterable[Any]) -> Dict[str, int]:
    """``{name: chars}`` of each tool definition as the WIRE carries it: briefed, compact JSON.

    The measurement behind the prompt-surface receipt (lane h-prompt-tools S0) and the
    tool-visibility token figure; tokens are derived from it by upstream's chars/4 rule
    (``tools.tool_search_catalog.CHARS_PER_TOKEN``), never a tokenizer the venv lacks.
    A definition without a name is skipped."""
    out: Dict[str, int] = {}
    for entry in tool_defs or ():
        if not isinstance(entry, dict):
            continue
        wired = _briefed(entry) or entry
        inner = wired.get("function")
        name = str((inner if isinstance(inner, dict) else wired).get("name") or "")
        if not name:
            continue
        try:
            out[name] = len(json.dumps(wired, ensure_ascii=False, separators=(",", ":"), default=str))
        except (TypeError, ValueError):
            out[name] = len(str(wired))
    return out
