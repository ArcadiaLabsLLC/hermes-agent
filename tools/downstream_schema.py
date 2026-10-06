"""Fork-owned one-line wire descriptions; the full documentation stays in the registry.

Every tool on the wire is COLLAPSED (lane h-prompt-brief, owner ask 2026-10-05): its
``description`` becomes one sentence and its parameter schema rides whole, so the tool
stays directly callable while its manual is one ``tool_describe`` away. The rewrite is
:func:`brief_request_tools`, which the eternia-harness plugin registers as ``llm_request``
middleware; the registry and upstream's tool files keep their text, and ``tool_describe``
serves it (``tools.tool_full_descriptions`` for the fork's mirrored registrations).

The one-liner is, in order: the hand-written entry in :data:`BRIEF_DESCRIPTIONS` (the one
table, for tools whose first sentence is not a usable summary or whose upstream text the
fork compressed); the promoted-MCP brief (:func:`promoted_brief`, which also clips the
server's parameter prose); else the first sentence of the tool's own text
(:func:`_first_sentence`). :data:`KEEP_FULL_WIRE_DESCRIPTIONS` names the tools whose
correct use depends on their longer text; they ride unchanged or with their table entry.
"""

import json
from typing import Any, Dict, Iterable, Optional

#: The one table of hand-written wire text: one sentence each, except the tools in
#: :data:`KEEP_FULL_WIRE_DESCRIPTIONS`. An entry exists only while it is shorter than the
#: text ``tool_describe`` serves (``vision_analyze`` left 2026-09-24, lane REDS3).
BRIEF_DESCRIPTIONS = {
    "browser_navigate": "Load a URL before other browser_* calls and get a compact snapshot with ref IDs; "
                        "prefer web_extract or terminal for plain text and API endpoints.",
    "write_file": "Replace a whole file (creating parent directories) after reading it; use patch for "
                  "targeted edits.",
    # Kept multi-sentence (KEEP_FULL_WIRE_DESCRIPTIONS): background/pty semantics.
    "terminal": "Run shell commands; cwd/exported env persist. Use background=true for "
                "long tasks (exit notice by default; notify=false opts out); pty=true for interactive CLIs. Prefer file tools "
                "for file work. Call tool_describe for lifecycle/platform details.",
    "todo_list": "Session task list for 3+ step work (no args reads it; keep ONE item in_progress and mark "
                 "complete only when verified).",
    "close_terminal": "Close a background process's GUI tab (desktop only) without killing it; "
                      "process_manage(action='kill') stops the process.",
    "process_manage": "Wait on, poll, write to, submit to or kill background processes started with "
                      "terminal(background=true).",
    "read_terminal": "Read the Hermes desktop GUI's embedded terminal pane (desktop only): the visible screen, "
                     "or scrollback via start_line/count.",
    "web_search": "Search the web (up to 5 results: title, URL, description); use web_extract to read a page.",
    "web_extract": "Extract clean markdown/text from web page or PDF URLs (no LLM summarization); use the "
                   "browser tools for interactive pages.",
    "patch": "Targeted find-and-replace file edits with fuzzy matching (path, old_string, new_string), "
             "returning a diff and a syntax check; use instead of sed/awk.",
    "search_files": "Search file contents (target='content', ripgrep regex) or find files by name/glob "
                    "(target='files'); use instead of grep/rg/find/ls.",
    "browser_snapshot": "Get a text accessibility-tree snapshot of the current page with ref IDs (@e1...) "
                        "for browser_click/type.",
    "browser_click": "Click an element by its snapshot ref ID (@e5), after a browser_snapshot.",
    "browser_type": "Type text into an input field by its snapshot ref ID (clears the field first).",
    "browser_scroll": "Scroll the page up or down to reveal content outside the viewport.",
    "browser_back": "Go back to the previous page in browser history.",
    "browser_press": "Press a keyboard key (Enter to submit, Tab to navigate, or a shortcut).",
    "browser_get_images": "List all images on the current page with URLs and alt text (find images to "
                          "analyze with vision_analyze).",
    "browser_vision": "Screenshot the current page to inspect it visually (layout, CAPTCHAs, visual checks); "
                      "returns screenshot_path.",
    "browser_console": "Read the current page's console output and JS errors, or evaluate JS via "
                       "`expression` (after browser_navigate).",
    # Kept multi-sentence (KEEP_FULL_WIRE_DESCRIPTIONS): who confirms a dangerous command.
    "clarify": "Ask 1-5 independent questions in one call. Put options only in choices, recommended first; omit for free text. Responses preserve order. Decide low-stakes matters yourself; terminal owns dangerous-command confirmation.",
    "execute_code": "Run Python in a persistent kernel that calls Hermes tools via `from hermes_tools import "
                    "...` for 3+ chained calls with logic (5-min / 50KB stdout / 50-call limits; print your "
                    "result; tool_describe lists the helpers).",
    "session_search": "Search conversation history (FTS5): query to discover, session_id + around_message_id "
                      "to scroll, session_id to read, no args for recent; given a live source, inspect that "
                      "first.",
    "read_file": "Read a text file with line numbers and pagination (offset/limit), auto-extracting office "
                 "docs, PDF, EPUB and SQLite; use vision_analyze for images.",
    # Lane h-prompt-brief: first sentences that do not summarize the tool.
    "skill_view": "Load a skill's SKILL.md and its linked_files list, or one linked file via file_path.",
    "browser_exec": "Drive a real web browser by running Python with pre-imported browser helpers (call "
                    "tool_describe for the helper API first); never guess credentials at a login wall.",
    "tool_describe": "Load the full description and JSON schema of any tool: a deferred one before "
                     "tool_call, or a listed one whose one-line description is not enough.",
}

#: Tools whose correct use depends on more than one sentence (the lane's decision rule): they
#: ride with their table entry or, absent one, their own text unchanged.
KEEP_FULL_WIRE_DESCRIPTIONS = frozenset({
    "terminal",     # background/notify/pty semantics; dangerous-command approval is terminal's
    "clarify",      # who confirms a dangerous command; the 18/18 -> 7/18 clarify A/B
    "tool_search",  # the description IS the deferred catalog listing (ruling R3: stays full)
    "tool_call",    # local-vs-connector batching rules the bridge rejects on
})

#: A one-line wire description never exceeds this many chars (the promoted brief's bound).
ONE_LINE_MAX_CHARS = 300

#: The promoted-MCP brief (lane h-prompt-tools S2): a server's manual rides every turn once
#: its tool is promoted eager (``tools.tool_search_downstream.PROMOTED_MCP_TOOLS``), so the wire
#: carries the first sentence (at most this many chars) and every parameter description clipped
#: to the second bound. The registry keeps the server's text: ``tool_describe`` serves the full
#: description AND the full ``parameters`` from it, one call away.
PROMOTED_BRIEF_DESCRIPTION_CHARS = ONE_LINE_MAX_CHARS
PROMOTED_BRIEF_PARAMETER_CHARS = 120
PROMOTED_BRIEF_SUFFIX = " Full reference: tool_describe."


def _clip(text: str, cap: int) -> str:
    return text if len(text) <= cap else text[: cap - 1].rstrip() + "…"


_ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "vs.")


def _first_sentence(text: str) -> str:
    """The text up to its first sentence end (a "." then a space, past 40 chars, not an
    abbreviation), on one line, clipped to :data:`ONE_LINE_MAX_CHARS`."""
    text = " ".join(str(text or "").split())
    for index in range(40, len(text)):
        if (text[index] == "." and (index + 1 == len(text) or text[index + 1] == " ")
                and not text[: index + 1].endswith(_ABBREVIATIONS)):
            return _clip(text[: index + 1], ONE_LINE_MAX_CHARS)
    return _clip(text, ONE_LINE_MAX_CHARS)


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

        description = target.get("description")
        if name in PROMOTED_MCP_TOOLS:
            if str(description or "").endswith(PROMOTED_BRIEF_SUFFIX):
                return None
            rewritten = promoted_brief(target)
        elif name in KEEP_FULL_WIRE_DESCRIPTIONS or not isinstance(description, str):
            return None
        else:
            line = _first_sentence(description)
            if not line or line == description:
                return None
            rewritten = {**target, "description": line}
    elif target.get("description") == brief:
        return None
    else:
        rewritten = {**target, "description": brief}
    return {**entry, "function": rewritten} if target is inner else rewritten


def brief_request_tools(request: Any) -> Optional[Dict[str, Any]]:
    """The provider kwargs with every tool collapsed to its one-line description (parameters
    untouched outside the promoted MCP brief), or None if unchanged."""
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
