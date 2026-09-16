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
