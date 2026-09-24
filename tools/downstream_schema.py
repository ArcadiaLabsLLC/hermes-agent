"""Fork-owned short wire descriptions; retain live upstream documentation.

The registry keeps upstream's schema text (``tool_describe`` serves it). The brief
reaches the wire through :func:`brief_request_tools`, which the eternia-harness
plugin registers as ``llm_request`` middleware: it replaces ``description`` by tool
name in the final provider kwargs and never touches parameters. Two built-ins
(``terminal``, ``vision_analyze``) still opt in at registration through
:func:`brief_schema`; the middleware is idempotent over them.
"""

from typing import Any, Dict, Optional

BRIEF_DESCRIPTIONS = {
    'browser_navigate': 'Load a URL before other browser_* calls; returns a compact snapshot '
                        'with ref IDs. Use for interactive pages; prefer text retrieval or '
                        'terminal fetching for plain text/API endpoints.',
    'write_file': 'Replace a whole file, creating parent directories and reporting new syntax '
                  'errors. Read existing files first; unread or changed-file overwrites are '
                  'refused. Use patch for targeted edits; prefer this over shell writes.',
    'terminal': 'Run shell commands; cwd/exported env persist. Use background=true with '
                'notify=true for long tasks; pty=true for interactive CLIs. Prefer file tools '
                'for file work. Call tool_describe for lifecycle/platform details.',
    # Moved out of the upstream tool files 2026-09-24 (lane MECH): the fork's
    # trimmed wire text, upstream's schema text left as shipped.
    "todo_list": "Session task list for 3+ steps; no args reads it. For requested batches, enumerate every instance; split phases via parent. Keep ONE item in_progress; mark complete only when verified done. If a task fails, cancel it and add a revised item. Not durable memory.",
    "close_terminal": "Close the read-only GUI tab for a background process (desktop only): drops the view, does NOT kill the process (output keeps buffering; reopen from the status stack). Disambiguator: to stop the process use process_manage(action='kill').",
    "process_manage": "Background processes: wait returns partial output on timeout. submit appends Enter to answer prompts; write sends raw bytes, no newline. notify requests a receipt in a new persona turn: end this turn. Subagents must handoff surviving processes. Call tool_describe for ownership and retention details.",
    "read_terminal": "Read what is currently shown in the Hermes desktop GUI's embedded terminal pane (desktop only). No args = visible screen + total_lines; pass start_line/count to page scrollback. Returns a JSON viewport.",
    "web_search": "Search the web (up to 5 results: title, URL, description). Backend operators like site:, filetype:, intitle:, -term, and \"exact phrase\" may work. Disambiguator: use web_extract to read a specific page.",
    "web_extract": "Extract clean markdown/text from web page or PDF URLs (no LLM summarization). Large pages return a head+tail window with a saved-file path to read the rest. Disambiguator: for interactive or failed pages use the browser tools; to find pages use web_search.",
    "vision_analyze": "Load an image (URL, local path, or data URL) into the conversation so you can see it. Native-vision models read the pixels next turn; others get an auxiliary text description. Disambiguator: use whenever the user references an image; read_file cannot read binaries.",
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
}

_registered_full = {}


def brief_schema(name: str, schema: dict) -> dict:
    """Keep upstream text for tool_describe and send the fork brief on the wire."""
    brief = BRIEF_DESCRIPTIONS.get(name)
    if brief is None:
        return schema
    full = schema.get("description")
    if isinstance(full, str) and full:
        _registered_full[name] = full
    return {**schema, "description": brief}


def registered_full_description(name: str) -> str | None:
    return _registered_full.get(name)


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
    brief = BRIEF_DESCRIPTIONS.get(target.get("name"))
    if brief is None or target.get("description") == brief:
        return None
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
