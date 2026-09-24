"""Fork-owned short wire descriptions; retain live upstream documentation.

Only built-in registrations that explicitly opt in call this adapter. It never
changes parameters or mutates the source schema, and does not affect plugins.
"""

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
