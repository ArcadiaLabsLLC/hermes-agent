"""A phone agent's file tools: read, search and edit files in the phone's project folders, with no process.

Eternia row ``MC-PHONE-FILES-A-PHONE-AGENT-READS-AND-WRITES-ITS-PROJECT-FILES`` (plan
``PHONE_PROJECT_FOLDERS_FILE_TREE_2026-11-21.md`` §9 as corrected by review w1118a.79). Upstream's
``tools/file_tools.py`` runs every call through ``ShellFileOperations`` on the terminal backend
(``cat``, ``rg``, ``python3 -c``; ``_get_file_ops`` builds a terminal environment), and its lint and
search halves spawn too. A phone starts no process, so the phone wheel ships none of them
(``bundled-phone.yaml``). This module is the FORK-SIDE replacement, registered only where upstream's
module is not shipped (:func:`register_phone_file_tools`), under upstream's own names and toolset
(``file``: ``read_file``, ``write_file``, ``patch``, ``search_files``) so a model's habits, the skills
that name them and the eternia-harness ``pre_tool_call`` guard all apply unchanged. Upstream's bytes
are untouched; ``tools.terminal_tool`` stays out of the phone's import closure.

* **One reader for the person's view and the agent's tools**: reads and searches are
  ``project_files.reader``'s (the rule spec both Eternia and hermes follow); writes are
  ``project_files.writer``'s one checked path (spec, confinement, the agent's write guards).
* **Roots are the phone's project folders**: the slots bound on this device (``workspace_slots``),
  each admissible as ``agent_tree`` admits one (never the namespace itself, home or a disk root). A
  path is absolute inside one of them, relative to the turn's working folder when that is inside
  one, or a tree path ``<slot>/<path>``. Anything else is refused ``outside_root``, never resolved
  against the process's own folder.
"""

from __future__ import annotations

__layer__ = "lanes"

import json
import os
from dataclasses import dataclass
from typing import Any

__all__ = ["PHONE_FILE_TOOLS", "register_phone_file_tools", "upstream_file_tools_shipped"]

#: Upstream's toolset and tool names: ``toolsets.TOOLSETS["file"]``.
TOOLSET = "file"
#: Lines a read gives when the call names no ``limit``.
DEFAULT_LINES = 500


@dataclass(frozen=True)
class _Located:
    root: str  # the root folder on this device
    relative: str  # the path under it, in the spec's grammar
    shown: str  # the path the reply names: ``<slot>/<relative>``


def _roots() -> dict[str, str]:
    """``{slot name: folder}`` for every project folder bound on this device that may be served."""

    from agent_runtime.project_files.agent_tree import _admissible
    from agent_runtime.workspace_slots import authorized_roots_bound_here

    roots: dict[str, str] = {}
    for bound in authorized_roots_bound_here():
        folder = os.path.realpath(str(bound.path))
        if bound.slot not in roots and "/" not in bound.slot and _admissible(folder):
            roots[bound.slot] = folder
    return roots


def _turn_folder() -> str | None:
    from agent.runtime_cwd import scope_terminal_cwd

    try:
        folder = (scope_terminal_cwd() or os.environ.get("TERMINAL_CWD") or "").strip()
    except Exception:  # health: allow BLE001 -- a refusal scope gives no folder; tree and absolute paths still work
        return None
    return folder if os.path.isabs(folder) else None


def _under(folder: str, roots: dict[str, str]) -> tuple[str, str] | None:
    """The deepest root holding ``folder`` (lexically; the reader resolves links) and the rest."""

    best: tuple[str, str] | None = None
    target = os.path.normpath(folder)
    for name, root in roots.items():
        if target == root or target.startswith(root.rstrip(os.sep) + os.sep):
            if best is None or len(root) > len(roots[best[0]]):
                best = (name, os.path.relpath(target, root))
    return best


def _locate(path: Any) -> _Located:
    from agent_runtime.project_files.rules import ProjectFileRefusal

    if not isinstance(path, str) or not path.strip():
        raise ProjectFileRefusal("invalid_path", "the path is required")
    text = os.path.expanduser(path.strip())
    roots = _roots()
    if not roots:
        raise ProjectFileRefusal("outside_root", "this device has no project folder yet")
    found = None
    if os.path.isabs(text):
        found = _under(text, roots)
    else:
        turn = _turn_folder()
        if turn is not None and _under(turn, roots) is not None:
            found = _under(os.path.join(turn, text), roots)
        if found is None:  # a tree path: ``<slot>/<path>``
            head, _, rest = text.replace("\\", "/").partition("/")
            if head in roots:
                found = (head, rest or ".")
    if found is None:
        names = ", ".join(sorted(roots))
        raise ProjectFileRefusal("outside_root", f"{path} is not in a project folder on this device ({names})")
    name, relative = found
    relative = "" if relative in (".", "") else relative.replace(os.sep, "/")
    return _Located(roots[name], relative, f"{name}/{relative}" if relative else name)


#: Upstream's miss wording for a read and a search (``tools/file_tools.py``): a miss on a phone says
#: it the same way, so the GenUI teach (``generated_tree_teach``: a ``/doc`` path handed to a host
#: file tool is taught the app-function verb) applies unchanged.
_MISSES = {"read_file": "File not found", "search_files": "Path not found"}


def _answer(call, tool: str = "", path: Any = None) -> str:
    from agent_runtime.project_files.rules import ProjectFileRefusal
    from agent_runtime.project_files.writer import WriteDenied
    from tools.registry import tool_error

    try:
        return json.dumps(call(), ensure_ascii=False)
    except ProjectFileRefusal as refused:
        miss = _MISSES.get(tool) if refused.code in ("outside_root", "not_found") else None
        # MUTATION: drop the miss wording and a /doc path read on a phone is never taught its verb
        # (test_phone_file_tools: test_a_miss_reads_as_upstreams_so_the_generated_tree_teach_applies).
        message = f"{miss}: {path}. {refused.message}" if miss else refused.message
        return tool_error(message, code=refused.code)
    except WriteDenied as denied:
        return tool_error(denied.message, code="write_denied")


def _int(value: Any, default: int, low: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, number)


def read_file(args: dict, **_kw: Any) -> str:
    def call() -> dict:
        from agent_runtime.project_files.reader import read
        from agent_runtime.project_files.rules import ProjectFileRefusal

        where = _locate(args.get("path"))
        if not where.relative:
            raise ProjectFileRefusal("not_a_file", f"not a file: {where.shown}")
        text, offset = "", 0
        while True:  # the reader pages by code points; a line window reads the whole (capped) file
            page = read(where.root, where.relative, offset=offset)
            text += page["content"]
            offset = page.get("next") or 0
            if not offset:
                break
        lines = text.splitlines()
        start = _int(args.get("offset"), 1, 1)
        limit = _int(args.get("limit"), DEFAULT_LINES, 1)
        window = lines[start - 1:start - 1 + limit]
        numbered = "\n".join(f"{start + index}|{line}" for index, line in enumerate(window))
        reply = {"path": where.shown, "content": numbered, "total_lines": len(lines)}
        if start - 1 + limit < len(lines):
            reply["next_offset"] = start + limit
        return reply

    return _answer(call, "read_file", args.get("path"))


def write_file(args: dict, **_kw: Any) -> str:
    def call() -> dict:
        from agent_runtime.project_files.writer import write

        where = _locate(args.get("path"))
        return {**write(where.root, where.relative, args.get("content")), "path": where.shown}

    return _answer(call)


def patch(args: dict, **_kw: Any) -> str:
    def call() -> dict:
        from agent_runtime.project_files.writer import patch as replace

        where = _locate(args.get("path"))
        done = replace(where.root, where.relative, args.get("old_string"), args.get("new_string"),
                       replace_all=args.get("replace_all") is True)
        return {**done, "path": where.shown}

    return _answer(call)


def search_files(args: dict, **_kw: Any) -> str:
    def call() -> dict:
        from agent_runtime.project_files.reader import grep_matches
        from agent_runtime.project_files.rules import MAX_MATCHES

        pattern = args.get("pattern")
        if args.get("path"):
            places = [_locate(args.get("path"))]
        else:
            places = [_Located(root, "", name) for name, root in sorted(_roots().items())]
        matches: list[dict] = []
        for where in places:
            _, found = grep_matches(where.root, pattern, where.relative or None)
            name = where.shown.split("/", 1)[0]
            matches.extend({**match, "path": f"{name}/{match['path']}"} for match in found)
        return {"pattern": pattern, "matches": matches[:MAX_MATCHES], "truncated": len(matches) > MAX_MATCHES}

    return _answer(call, "search_files", args.get("path"))


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}


_PATH = {"type": "string", "description": "The file: absolute, relative to the current project folder, "
                                          "or <project>/<path>."}
PHONE_FILE_TOOLS: tuple[tuple[str, Any, dict], ...] = (
    ("read_file", read_file, _schema(
        "read_file", "Read a text file in one of this phone's project folders, as numbered lines.",
        {"path": _PATH, "offset": {"type": "integer", "description": "First line, 1-based (default 1)."},
         "limit": {"type": "integer", "description": f"Lines to read (default {DEFAULT_LINES})."}}, ["path"])),
    ("write_file", write_file, _schema(
        "write_file", "Write a whole text file in one of this phone's project folders (folders are made).",
        {"path": _PATH, "content": {"type": "string", "description": "The file's complete new text."}},
        ["path", "content"])),
    ("patch", patch, _schema(
        "patch", "Replace text in a file in one of this phone's project folders. old_string must be found "
                 "exactly once unless replace_all is true.",
        {"path": _PATH, "old_string": {"type": "string"}, "new_string": {"type": "string"},
         "replace_all": {"type": "boolean"}}, ["path", "old_string", "new_string"])),
    ("search_files", search_files, _schema(
        "search_files", "Find lines holding a literal text in this phone's project folders (all of them, or "
                        "under path).",
        {"pattern": {"type": "string", "description": "The literal text to find."}, "path": _PATH}, ["pattern"])),
)


def upstream_file_tools_shipped() -> bool:
    """Whether this install ships upstream's file tools (every desktop does; the phone wheel does not)."""

    import importlib.util

    try:
        return importlib.util.find_spec("tools.file_tools") is not None
    except (ImportError, ValueError):
        return False


def register_phone_file_tools(register) -> list[str]:
    """Register the four tools through ``register(name, toolset=, schema=, handler=, emoji=)`` (a plugin
    context's ``register_tool``), only where upstream's are not shipped; the names registered."""

    # MUTATION: register them on a desktop too and they shadow upstream's file tools
    # (test_phone_file_tools: test_a_desktop_keeps_upstreams_file_tools).
    if upstream_file_tools_shipped():
        return []
    for name, handler, schema in PHONE_FILE_TOOLS:
        register(name, toolset=TOOLSET, schema=schema, handler=handler, emoji="📄")
    return [name for name, _, _ in PHONE_FILE_TOOLS]
