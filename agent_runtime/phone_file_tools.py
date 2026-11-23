"""A phone agent's file tools: read, search and edit files in the phone's project folders, with no process.

Eternia row ``MC-PHONE-FILES-A-PHONE-AGENT-READS-AND-WRITES-ITS-PROJECT-FILES`` (plan
``PHONE_PROJECT_FOLDERS_FILE_TREE_2026-11-21.md`` §9 as corrected by review w1118a.79). Upstream's
``tools/file_tools.py`` runs every call through ``ShellFileOperations`` on the terminal backend
(``cat``, ``rg``, ``python3 -c``; ``_get_file_ops`` builds a terminal environment), and its lint and
search halves spawn too. A phone starts no process, so the phone wheel ships none of them
(``bundled-phone.yaml``). This module is the FORK-SIDE replacement, registered only where upstream's
does not run (:func:`upstream_file_tools_shipped`: the installed profile switches it off), by the phone's
embedded entry (:func:`ensure_phone_file_tools`), under upstream's own names and toolset
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
* **The desktop's arguments** (row ``RT-PHONE-FILE-TOOLS-ACCEPT-EVERY-DESKTOP-ARGUMENT``, owner: "the agent
  calls the same interface on all platform"): every schema takes upstream's parameters exactly, and
  ``patch`` gets upstream's V4A layer by upstream's rule. What a phone cannot do yet is refused in
  words: a V4A Delete or Move (the writer has no checked delete or move).
* **Regex search** (row ``RT-PHONE-REGEX-SEARCH-RUNS-RIPGREPS-MATCHER-FROM-A-NATIVE-LIBRARY``, owner RULED
  2026-11-21): a content pattern holding a regex character runs ripgrep's matcher in process
  (``project_files.native_match``) when its library is loaded, else the ``regex`` package with
  ``timeout=`` (``project_files.fallback_match``) when it imports, else it is refused in words; never
  Python ``re`` on the caller's pattern. Regex stays a phone tool's: ``runtime.agent.files.grep`` keeps
  the spec's literal and wildcard.
"""

from __future__ import annotations

__layer__ = "lanes"

import json
import os
from dataclasses import dataclass
from typing import Any

__all__ = ["PHONE_FILE_TOOLS", "ensure_phone_file_tools", "register_phone_file_tools", "upstream_file_tools_shipped"]

#: Upstream's toolset and tool names: ``toolsets.TOOLSETS["file"]``.
TOOLSET = "file"


@dataclass(frozen=True)
class _Located:
    root: str  # the root folder on this device
    relative: str  # the path under it, in the spec's grammar
    shown: str  # the path the reply names: ``<slot>/<relative>``


def _bound_roots() -> dict[str, str]:
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


def _deepest_root_holding(folder: str, roots: dict[str, str]) -> tuple[str, str] | None:
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
    roots = _bound_roots()
    if not roots:
        raise ProjectFileRefusal("outside_root", "this device has no project folder yet")
    found = None
    if os.path.isabs(text):
        found = _deepest_root_holding(text, roots)
    else:
        turn = _turn_folder()
        if turn is not None and _deepest_root_holding(turn, roots) is not None:
            found = _deepest_root_holding(os.path.join(turn, text), roots)
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


def _phone_tool_answer(call, tool: str = "", path: Any = None) -> str:
    from agent_runtime.project_files.native_match import NativeMatchError, SearchCancelled
    from agent_runtime.project_files.rules import ProjectFileRefusal
    from agent_runtime.project_files.writer import WriteDenied
    from tools.registry import tool_error

    try:
        return json.dumps(call(), ensure_ascii=False)
    except SearchCancelled as stopped:
        return tool_error(str(stopped), code="interrupted")
    except NativeMatchError as failed:
        return tool_error(f"the regex search failed in ripgrep's matcher: {failed}", code="search_failed")
    except ProjectFileRefusal as refused:
        miss = _MISSES.get(tool) if refused.code in ("outside_root", "not_found") else None
        # MUTATION: drop the miss wording and a /doc path read on a phone is never taught its verb
        # (test_phone_file_tools: test_a_miss_reads_as_upstreams_so_the_generated_tree_teach_applies).
        message = f"{miss}: {path}. {refused.message}" if miss else refused.message
        return tool_error(message, code=refused.code)
    except WriteDenied as denied:
        return tool_error(denied.message, code="write_denied")


def _int_at_least(value: Any, default: int, low: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, number)


def _whole_text(where: _Located) -> str:
    """The whole (capped) text of the file at ``where``, read through the reader's pages."""

    from agent_runtime.project_files.reader import read
    from agent_runtime.project_files.rules import ProjectFileRefusal

    if not where.relative:
        raise ProjectFileRefusal("not_a_file", f"not a file: {where.shown}")
    text, offset = "", 0
    while True:  # the reader pages by code points; a line window reads the whole (capped) file
        page = read(where.root, where.relative, offset=offset)
        text += page["content"]
        offset = page.get("next") or 0
        if not offset:
            return text


def read_file(args: dict, **_kw: Any) -> str:
    def call() -> dict:
        where = _locate(args.get("path"))
        lines = _whole_text(where).splitlines()
        # Upstream's defaults and bounds (``normalize_read_pagination``): offset from 1, limit 2000 at most.
        start = _int_at_least(args.get("offset"), 1, 1)
        # MUTATION: drop the ceiling and a limit past 2000 reads past upstream's maximum
        # (test_phone_file_tools: test_read_file_takes_upstreams_offset_and_limit).
        limit = min(_int_at_least(args.get("limit"), READ_LIMIT, 1), READ_LIMIT)
        window = lines[start - 1:start - 1 + limit]
        numbered = "\n".join(f"{start + index}|{line}" for index, line in enumerate(window))
        reply = {"path": where.shown, "content": numbered, "total_lines": len(lines)}
        if start - 1 + limit < len(lines):
            reply["next_offset"] = start + limit
        return reply

    return _phone_tool_answer(call, "read_file", args.get("path"))


def write_file(args: dict, **_kw: Any) -> str:
    def call() -> dict:
        from agent_runtime.project_files.writer import write

        where = _locate(args.get("path"))
        return {**write(where.root, where.relative, args.get("content")), "path": where.shown}

    return _phone_tool_answer(call)


def _refuse(message: str):
    from agent_runtime.project_files.rules import ProjectFileRefusal

    return ProjectFileRefusal("bad_argument", message)


def _choice(args: dict, name: str, default: str, allowed: tuple[str, ...]) -> str:
    value = args.get(name)
    value = default if value is None else value
    if value not in allowed:
        raise _refuse(f"{name} must be one of {', '.join(allowed)}, not {value!r}")
    return value


def patch(args: dict, **_kw: Any) -> str:
    def call() -> dict:
        from agent_runtime.project_files.writer import patch as replace

        # Upstream's handler takes both shapes from any model, whatever its schema advertised.
        if _choice(args, "mode", "replace", ("replace", "patch")) == "patch":
            return _apply_v4a(args.get("patch"))
        where = _locate(args.get("path"))
        done = replace(where.root, where.relative, args.get("old_string"), args.get("new_string"),
                       replace_all=args.get("replace_all") is True)
        # MUTATION: drop the diff and a replace edit draws no View diff in the chat (the runner's
        # ``record_patch_diff`` finds none) (test_phone_file_tools:
        # test_a_replace_patch_answers_the_diff_the_runner_records_as_a_v4a_patch_does).
        return {**done.answer, "path": where.shown, "diff": _unified_diff(done.before, done.after, where.shown)}

    return _phone_tool_answer(call)


def _unified_diff(before: str | None, after: str, shown: str) -> str:
    """The one spelling of a phone edit's diff, for both ``patch`` arms (upstream's ``patch_tool``
    answers one too): what the runner's ``patch_diff_artifacts.record_patch_diff`` records and
    Eternia's View diff opens. ``before`` is None for a file the edit creates."""

    import difflib

    return "".join(difflib.unified_diff(
        (before or "").splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile="/dev/null" if before is None else f"a/{shown}", tofile=f"b/{shown}"))


def _apply_v4a(text: Any) -> dict:
    """A V4A patch (upstream's ``parse_v4a_patch``), every file checked before any is written.

    Add and Update only: the writer has a checked write and patch but no checked delete or move, so
    a patch holding either is refused whole. Each file's path is ``_locate``'s (confined to a project
    folder) and its write is :func:`writer.checked_text`'s then :func:`writer.write`'s. Hunks match
    exactly, as the phone's replace does (upstream matches them fuzzily)."""

    from agent_runtime.project_files.rules import ProjectFileRefusal
    from agent_runtime.project_files.writer import checked_text, write
    from tools.patch_parser import OperationType, parse_v4a_patch

    if not isinstance(text, str) or not text.strip():
        raise _refuse("mode='patch' needs the V4A patch text in patch")
    operations, error = parse_v4a_patch(text)
    if error:
        raise _refuse(error)
    if not operations:
        raise _refuse("the patch holds no Add File or Update File operation")
    # MUTATION: drop this refusal and a Delete File op is applied as an empty Update or skipped
    # (test_phone_file_tools: test_a_v4a_delete_or_move_is_refused_in_words_and_nothing_is_written).
    unsupported = [op for op in operations if op.operation in (OperationType.DELETE, OperationType.MOVE)]
    if unsupported:
        named = ", ".join(f"{op.operation.value} {op.file_path}" for op in unsupported)
        raise _refuse(f"Delete File and Move File are not available on a phone yet ({named}); nothing "
                      "was written. Use Add File and Update File, or write_file.")
    staged: dict[tuple[str, str], list] = {}  # (root, relative) -> [where, text before, text after]
    for op in operations:
        where = _locate(op.file_path)
        key = (where.root, where.relative)
        if key in staged:
            current = staged[key][2]
        else:
            current = checked_text(where.root, where.relative)
            staged[key] = [where, current, current]
        if op.operation is OperationType.ADD:
            if current is not None:
                raise _refuse(f"{where.shown}: file already exists — use Update File, not Add File")
            after = "\n".join(line.content for hunk in op.hunks for line in hunk.lines if line.prefix == "+")
        else:
            if current is None:
                raise ProjectFileRefusal("not_found", f"nothing at {where.shown}")
            after = _apply_hunks(current, op.hunks, where.shown)
        staged[key][2] = after
    created, modified, diffs = [], [], []
    for where, before, after in staged.values():
        write(where.root, where.relative, after)
        (created if before is None else modified).append(where.shown)
        diffs.append(_unified_diff(before, after, where.shown))
    return {"success": True, "diff": "\n".join(diffs), "files_modified": modified, "files_created": created}


def _apply_hunks(text: str, hunks: list, shown: str) -> str:
    """``text`` with each V4A hunk applied by exact match: its old lines found once (after its hint
    when they are found more than once), or an addition-only hunk put after its hint or at the end."""

    for hunk in hunks:
        old = "\n".join(line.content for line in hunk.lines if line.prefix != "+")
        new = "\n".join(line.content for line in hunk.lines if line.prefix != "-")
        if old == new and old:
            continue
        hint = hunk.context_hint
        if not old:
            at = text.find(hint) if hint and text.count(hint) == 1 else -1
            if hint and text.count(hint) > 1:
                raise _refuse(f"{shown}: context hint '{hint}' is ambiguous ({text.count(hint)} occurrences)")
            if at < 0:
                text = text.rstrip("\n") + "\n" + new + "\n"
            else:
                eol = text.find("\n", at)
                text = text + "\n" + new if eol < 0 else text[:eol + 1] + new + "\n" + text[eol + 1:]
            continue
        found = text.count(old)
        start = 0
        if found > 1 and hint and text.count(hint) == 1:
            start = text.find(hint)
            found = 1 if text.find(old, start) >= 0 else 0
        if found == 0:
            raise _refuse(f"{shown}: a hunk's lines were not found exactly (a phone matches hunks "
                          "exactly; read the file and copy its lines)")
        if found > 1:
            raise _refuse(f"{shown}: a hunk's lines are found {found} times; add context or a unique @@ hint @@")
        at = text.find(old, start)
        text = text[:at] + new + text[at + len(old):]
    return text


#: The characters that make a pattern a regular expression; a pattern holding none of them means the
#: same as literal text, and is searched by the spec's literal matcher.
REGEX_CHARACTERS = frozenset(".^$*+?()[]{}|\\")


def _content_matcher(pattern: Any):
    """The matcher for a content ``pattern``: None for plain text (the reader's literal matcher), else a
    regex matcher in the ruled order — ripgrep's (native), the ``regex`` package's, or refused in words.

    Never Python ``re``: nothing here or below it compiles the caller's pattern with ``re``."""

    from agent_runtime.project_files import fallback_match, native_match
    from agent_runtime.project_files.patterns import check_pattern

    if not isinstance(pattern, str):
        raise _refuse("pattern must be text")
    held = sorted(set(pattern) & REGEX_CHARACTERS)
    if not held:
        return None
    check_pattern(pattern)
    # MUTATION: skip the native step and a phone with ripgrep's library searches with the fallback
    # (test_project_files_native_match: test_a_phone_search_files_regex_runs_ripgreps_matcher).
    if native_match.available():
        return native_match.RegexLines.compile(pattern, cancel=native_match.turn_cancel())
    fallback = fallback_match.RegexPackageLines.compile(pattern, cancel=native_match.turn_cancel())
    if fallback is not None:
        return fallback
    # MUTATION: answer with Python ``re`` here and the caller's pattern runs unbounded
    # (test_project_files_native_match: test_with_neither_engine_a_regex_is_refused_in_words_never_run_by_re).
    raise _refuse(f"regex search needs ripgrep's matcher or the regex package, and this phone has neither; "
                  f"the pattern holds {' '.join(held)}. Search for plain text without those characters.")


def _places(path: Any) -> list[_Located]:
    """Where a search looks: ``path``, or by default (``.``) the turn's folder when it is in a project
    folder, else every project folder."""

    if path is None or (isinstance(path, str) and path.strip() in ("", ".")):
        roots = _bound_roots()
        turn = _turn_folder()
        if turn is not None and _deepest_root_holding(turn, roots) is not None:
            return [_locate(turn)]
        return [_Located(root, "", name) for name, root in sorted(roots.items())]
    return [_locate(path)]


def _is_file(where: _Located) -> bool:
    return bool(where.relative) and os.path.isfile(os.path.join(where.root, where.relative))


def _found_files(places: list[_Located], glob: Any, order: str, deadline) -> list[str]:
    from agent_runtime.project_files.reader import tree_entries

    found: list[tuple[str, str]] = []  # (shown, real path)
    for where in places:
        if _is_file(where):
            raise _refuse(f"target='files' searches a folder, and {where.shown} is a file")
        _, entries = tree_entries(where.root, where.relative or None, glob=glob, deadline=deadline)
        name = where.shown.split("/", 1)[0]
        found.extend((f"{name}/{entry['path']}", os.path.join(where.root, *entry["path"].split("/")))
                     for entry in entries)
    if order == "modified":
        def modified(item: tuple[str, str]) -> float:
            deadline.check()
            try:
                return os.stat(item[1], follow_symlinks=False).st_mtime
            except OSError:
                return 0.0

        # MUTATION: drop the sort and order='modified' lists discovery order
        # (test_phone_file_tools: test_search_takes_every_desktop_argument_over_the_reader).
        found.sort(key=modified, reverse=True)
    return [shown for shown, _ in found]


def _content_hits(places: list[_Located], pattern: str, glob: Any, context: int, deadline,
                  matcher=None) -> list[dict]:
    from agent_runtime.project_files.patterns import LinePattern
    from agent_runtime.project_files.reader import grep_matches
    from agent_runtime.project_files.replies import grep_lines

    hits: list[dict] = []
    for where in places:
        name = where.shown.split("/", 1)[0]
        if _is_file(where):  # upstream's path may name one file
            found = grep_lines(where.relative, _whole_text(where), matcher or LinePattern.parse(pattern),
                               deadline, context)
        else:
            _, found = grep_matches(where.root, pattern, where.relative or None, glob=glob,
                                    deadline=deadline, context=context, matcher=matcher)
        hits.extend({**hit, "path": f"{name}/{hit['path']}"} for hit in found)
    return hits


def search_files(args: dict, **_kw: Any) -> str:
    def call() -> dict:
        from agent_runtime.project_files.patterns import Deadline

        raw = args.get("target")
        target = {"grep": "content", "find": "files"}.get(raw, raw)  # upstream's handler maps both
        target = _choice({"target": target}, "target", "content", ("content", "files"))
        order = _choice(args, "order", "discovery", ("discovery", "modified"))
        mode = _choice(args, "output_mode", "content", ("content", "files_only", "count"))
        limit = _int_at_least(args.get("limit"), SEARCH_LIMIT, 1)
        offset = _int_at_least(args.get("offset"), 0, 0)
        context = _int_at_least(args.get("context"), 0, 0)
        pattern = args.get("pattern")
        places = _places(args.get("path"))
        deadline = Deadline()  # one deadline over every folder searched
        reply: dict[str, Any] = {"pattern": pattern, "target": target}
        if target == "files":
            files = _found_files(places, pattern, order, deadline)
            return {**reply, "files": files[offset:offset + limit], "total_count": len(files),
                    "truncated": offset + limit < len(files)}
        file_glob = args.get("file_glob")
        matcher = _content_matcher(pattern)
        try:
            hits = _content_hits(places, pattern, file_glob or None, context, deadline, matcher)
        finally:
            if matcher is not None:
                matcher.close()
        if mode == "content":
            # MUTATION: page from 0 and offset is ignored (test_phone_file_tools:
            # test_search_takes_every_desktop_argument_over_the_reader).
            items = hits
            reply["matches"] = items[offset:offset + limit]
        else:
            counts: dict[str, int] = {}
            for hit in hits:
                counts[hit["path"]] = counts.get(hit["path"], 0) + 1
            items = list(counts)
            page = items[offset:offset + limit]
            reply.update({"files": page} if mode == "files_only" else {"counts": {p: counts[p] for p in page}})
        return {**reply, "total_count": len(hits), "truncated": offset + limit < len(items)}

    return _phone_tool_answer(call, "search_files", args.get("path"))


# ---- Schemas: upstream's parameters exactly (``tools/file_tools.py``), phone-true descriptions ----
#
# Names, types, enums, defaults, minimum and maximum and required equal upstream's
# (test_phone_file_tools: test_the_phone_schemas_equal_upstreams_parameters reds on any drift).
# A description differs only where upstream's words are false on a phone: no document extraction,
# no lint or LSP, no fuzzy patch match, no ripgrep process, no read-before-write refusal.

#: Upstream's ``DEFAULT_READ_LIMIT``, which is also its schema's maximum.
READ_LIMIT = 2000
#: Upstream's ``search_files`` default ``limit``.
SEARCH_LIMIT = 50

_PATH = "absolute, relative to the current project folder, or <project>/<path>"

READ_FILE_SCHEMA = {
    "name": "read_file",
    "description": "Read a text file in this phone's project folders with line numbers and pagination. Output "
                   "format: 'LINE_NUM|CONTENT'. Use offset and limit for large files; a read that stops early "
                   "returns a next_offset. Text files only: documents are not extracted on a phone, and "
                   "binary files are refused.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": f"Path to the file to read ({_PATH})"},
            "offset": {"type": "integer", "description": "Line number to start reading from (1-indexed, default: 1)",
                       "default": 1, "minimum": 1},
            "limit": {"type": "integer", "description": "Maximum number of lines to read (default: 2000, max: 2000).",
                      "default": READ_LIMIT, "maximum": READ_LIMIT},
        },
        "required": ["path"],
    },
}

WRITE_FILE_SCHEMA = {
    "name": "write_file",
    "description": "Write content to a file in this phone's project folders, completely replacing existing "
                   "content. Creates parent directories automatically. OVERWRITES the entire file — use "
                   "'patch' for targeted edits.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to write (will be created if it doesn't "
                                                      f"exist, overwritten if it does; {_PATH})"},
            "content": {"type": "string", "description": "Complete content to write to the file"},
        },
        "required": ["path", "content"],
    },
}

_PATCH_PROPERTIES = {
    "path": {"type": "string", "description": f"File path to edit ({_PATH})."},
    "old_string": {"type": "string", "description": "Exact text to find and replace, matched exactly (a phone "
                   "does no fuzzy matching). Must be unique in the file unless replace_all=true. Include "
                   "surrounding context lines to ensure uniqueness."},
    "new_string": {"type": "string", "description": "Replacement text. Pass empty string '' to delete the "
                                                    "matched text."},
    "replace_all": {"type": "boolean", "description": "Replace all occurrences instead of requiring a unique "
                                                      "match (default: false)", "default": False},
}

PATCH_SCHEMA = {
    "name": "patch",
    "description": "Targeted find-and-replace edits in files in this phone's project folders. Matches exactly: "
                   "old_string must appear in the file as written. Finds a unique string and replaces it.",
    "parameters": {"type": "object", "properties": _PATCH_PROPERTIES,
                   "required": ["path", "old_string", "new_string"]},
}

_PATCH_V4A_DESCRIPTION = (
    "Targeted find-and-replace edits in files in this phone's project folders. Matches exactly: old text "
    "must appear in the file as written.\n\n"
    "REPLACE MODE (mode='replace', default): find a unique string and replace it. "
    "REQUIRED PARAMETERS: mode, path, old_string, new_string.\n"
    "PATCH MODE (mode='patch'): apply V4A multi-file patches for bulk changes (Add File and Update File; "
    "Delete File and Move File are not available on a phone yet). REQUIRED PARAMETERS: mode, patch."
)

_PATCH_V4A_PARAMS = {
    "mode": {"type": "string", "enum": ["replace", "patch"], "default": "replace",
             "description": "Edit mode. 'replace' (default): requires path + old_string + new_string. "
                            "'patch': requires patch content only."},
    "patch": {"type": "string", "description": "REQUIRED when mode='patch'. V4A format patch content. Format:\n"
                                               "*** Begin Patch\n*** Update File: path/to/file\n@@ context hint @@\n"
                                               " context line\n-removed line\n+added line\n*** End Patch"},
}


def _is_openai_family_main() -> bool:
    """Upstream's rule (``tools.file_tools._is_openai_family_main``, not shipped on a phone): the V4A
    layer is advertised to OpenAI-family mains only; fail closed to the replace-only schema.

    test_phone_file_tools: test_the_v4a_layer_follows_upstreams_rule reds when the two disagree."""

    try:
        from agent_runtime._upstream_doors import main_model_and_provider

        model, provider = (value.strip().lower() for value in main_model_and_provider())
    except Exception:  # health: allow BLE001 -- upstream's own fail-closed probe
        return False
    if provider in {"openai", "openai-chat", "openai-codex", "azure-openai", "codex"}:
        return True
    slug = model.split("/", 1)[-1]
    if slug.startswith(("gpt-", "gpt.", "chatgpt", "codex", "o1", "o3", "o4", "o5")):
        return True
    return "openai/" in model


def patch_schema_overrides() -> dict:
    """The V4A layer on ``patch``'s schema by upstream's rule (``_patch_schema_overrides``)."""

    if not _is_openai_family_main():
        return {}
    params = {"type": "object",
              "properties": {"mode": _PATCH_V4A_PARAMS["mode"], **_PATCH_PROPERTIES,
                             "patch": _PATCH_V4A_PARAMS["patch"]},
              "required": ["mode"]}
    return {"description": _PATCH_V4A_DESCRIPTION, "parameters": params}


SEARCH_FILES_SCHEMA = {
    "name": "search_files",
    "description": "Search file contents or find files by name in this phone's project folders.\n\n"
                   "Content search (target='content'): regex search inside files with ripgrep's engine, run in "
                   "process (a phone without it refuses a regex in words; plain text always works). Output "
                   "modes: full matches with line numbers, file paths only, or match counts.\n\nFile search (target='files'): Find files by name glob (e.g., '*.py', "
                   "'*config*'). Discovery order is the default; 'modified' lists newest first.",
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern for content search, or a file-name glob "
                                                         "(e.g., '*.py') for file search"},
            "target": {"type": "string", "enum": ["content", "files"], "description": "'content' searches inside "
                       "file contents, 'files' searches for files by name", "default": "content"},
            "path": {"type": "string", "description": "Directory or file to search in (default: the current "
                     "project folder, else every project folder)", "default": "."},
            "file_glob": {"type": "string", "description": "Filter files by name pattern in content search (e.g., "
                                                           "'*.py' to only search Python files)"},
            "limit": {"type": "integer", "description": "Maximum number of results to return (default: 50)",
                      "default": SEARCH_LIMIT},
            "offset": {"type": "integer", "description": "Skip first N results for pagination (default: 0)",
                       "default": 0},
            "order": {"type": "string", "enum": ["discovery", "modified"], "description": "File-search order: "
                      "'discovery' is traversal order; 'modified' is newest first; ignored for content",
                      "default": "discovery"},
            "output_mode": {"type": "string", "enum": ["content", "files_only", "count"], "description": "Output "
                            "format for content search: 'content' shows matching lines with line numbers, "
                            "'files_only' lists file paths, 'count' shows match counts per file",
                            "default": "content"},
            "context": {"type": "integer", "description": "Number of context lines before and after each match "
                                                          "(content search only)", "default": 0},
        },
        "required": ["pattern"],
    },
}

PHONE_FILE_TOOLS: tuple[tuple[str, Any, dict], ...] = (
    ("read_file", read_file, READ_FILE_SCHEMA),
    ("write_file", write_file, WRITE_FILE_SCHEMA),
    ("patch", patch, PATCH_SCHEMA),
    ("search_files", search_files, SEARCH_FILES_SCHEMA),
)


#: Upstream's file tools: switched off on a phone, yet shipped there pinned in ``phone_forced/`` (kept code
#: imports it lazily and unguarded: ``agent.client_lifecycle``'s turn-end ``forget_file_state``).
UPSTREAM_MODULE = "tools.file_tools"


def upstream_file_tools_shipped() -> bool:
    """Whether this install runs upstream's file tools (every desktop does; the phone does not).

    The INSTALLED profile answers first (``module_presence.runs_here``, the feature gate's one question):
    the phone ships ``tools.file_tools`` pinned in its forced tree, mounted on ``tools.__path__``, so a
    presence probe finds it there (row RT-FU-THE-PHONE-GATE-JUDGES-THE-CODE-BEHIND-A-PHONE-AGENTS-FILE-TOOLS)."""

    from agent_runtime.module_presence import runs_here

    # MUTATION: back to a presence probe and the phone, where the forced tree makes the module findable,
    # registers nothing (test_phone_file_tools: test_the_phones_installed_profile_registers_them_though_upstreams_is_findable).
    return runs_here(UPSTREAM_MODULE)


def register_phone_file_tools(register) -> list[str]:
    """Register the four tools through ``register(name, toolset=, schema=, handler=, emoji=)`` (a plugin
    context's ``register_tool``, or the registry's own ``register``), only where upstream's are not
    shipped; the names registered."""

    # MUTATION: register them on a desktop too and they shadow upstream's file tools
    # (test_phone_file_tools: test_a_desktop_keeps_upstreams_file_tools).
    if upstream_file_tools_shipped():
        return []
    for name, handler, schema in PHONE_FILE_TOOLS:
        register(name, toolset=TOOLSET, schema=schema, handler=handler, emoji="📄")
    _layer_v4a_on_patch()
    return [name for name, _, _ in PHONE_FILE_TOOLS]


def ensure_phone_file_tools() -> list[str]:
    """The embedded entry's registration (``EmbeddedServe.start``): a phone ships no eternia-harness plugin,
    so nothing else registers them there, and the packager's walk keeps this module through that call.

    Upstream's module, where it ships pinned, is imported FIRST: its module-level ``registry.register``
    calls take the same names in the same toolset, so the first lazy import of it (the turn-end
    ``forget_file_state``) would otherwise put upstream's shell-backed tools back under the four names."""

    if upstream_file_tools_shipped():
        return []
    try:
        # MUTATION: skip this import and the phone's second turn runs upstream's read_file
        # (test_phone_bundle_turn_closure: test_three_phone_call_paths_run_on_only_what_the_phone_bundle_ships).
        import tools.file_tools
    except Exception:
        pass
    from tools.registry import registry

    return register_phone_file_tools(registry.register)


def _layer_v4a_on_patch() -> None:
    """Give the registered ``patch`` upstream's V4A layer, re-read at every schema build as upstream's is.

    A plugin's ``register_tool`` takes no ``dynamic_schema_overrides`` (upstream's ``registry.register``
    does), so it is set on the entry the registration made, found by its handler. Fork-side only."""

    from tools.registry import registry

    entry = registry.get_entry("patch")
    # MUTATION: skip this and an OpenAI-family main is never told patch takes a V4A patch
    # (test_phone_file_tools: test_a_registered_phone_patch_advertises_v4a_by_upstreams_rule).
    if entry is not None and entry.handler is patch:
        entry.dynamic_schema_overrides = patch_schema_overrides
