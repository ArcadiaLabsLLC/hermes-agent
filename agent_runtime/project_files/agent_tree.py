"""An agent's files as ONE confined tree: its roots, enumerated by this engine, each a top-level folder.

Eternia row ``MC-PHONE-FILES-AN-AGENTS-FILES-ARE-SERVED-BY-ITS-ENGINE-AS-ONE-TREE`` (evidence
``docs/embedded_hermes/evidence/PHONE_FILES_DECISION_SECOND_READ_2026-11-21.md`` §4, amendments 2-4).
Another device's files are always read through that device's Hermes (owner, 2026-11-21); this is
what that Hermes serves, over ``runtime.agent.files.*`` (``serve_rpc/agent_files.py``).

The server design is the media lane's (``media_handles.py``): **enumerate, then resolve.**

* :func:`agent_roots` enumerates the agent's roots: the slots assigned to the persona instance and
  bound to a folder on THIS machine (``persona_slots.show_instance_slots``, the one owner of that
  fact). A root's name is its slot name; its folder never leaves this module.
* A caller names a file only by a path in the tree's grammar (``paths.parse_path``: relative,
  ``/``-separated, no ``.``/``..``, no absolute path, no drive letter). Its FIRST segment is looked
  up among the enumerated root names, and the rest is root-relative and read by ``reader`` under
  the rule spec (symlinks resolved and refused ``outside_root`` when they leave the root, ``.git``
  never read, 5 MiB per read). No step turns caller input into a folder of its own choosing.
* **No whole-disk browse.** A slot bound at a filesystem root, at the user's home, or at any folder
  holding this engine's home or store (secrets, the history database, config) is not served:
  :func:`_admissible` drops it from the enumeration, so it resolves like a name that does not exist.

The tree at its top (``path`` absent) lists the roots as folders; below that every reply is the
reader's, with each ``path`` prefixed by its root's name.
"""

from __future__ import annotations

__layer__ = "stores"

import os
from dataclasses import dataclass

from agent_runtime.project_files.paths import parse_path
from agent_runtime.project_files.reader import read as _read_root
from agent_runtime.project_files.patterns import Deadline, LinePattern, NameGlob
from agent_runtime.project_files.reader import grep_matches, search_header, tree_entries
from agent_runtime.project_files.replies import page
from agent_runtime.project_files.rules import DEFAULT_DEPTH, MAX_DEPTH, MAX_ENTRIES, MAX_MATCHES, ProjectFileRefusal

class AgentNotFound(LookupError):
    """No persona instance by that id on this engine."""


@dataclass(frozen=True)
class AgentRoot:
    """One enumerated root: its name in the tree, and this machine's folder (never sent)."""

    name: str
    folder: str


def _guarded_folders() -> tuple[str, ...]:
    """The engine's own folders, which no served root may hold or be."""

    from agent_runtime import paths
    from hermes_constants import get_hermes_home

    held: list[str] = []
    for folder in (get_hermes_home(), paths.store_root()):
        try:
            held.append(os.path.realpath(str(folder)))
        except (OSError, ValueError):
            continue
    return tuple(held)


def _admissible(folder: str) -> bool:
    """Whether a bound slot folder may be served: not a disk root, not home, not over the engine's own."""

    actual = os.path.realpath(folder)
    if os.path.dirname(actual) == actual:
        return False
    if actual == os.path.realpath(os.path.expanduser("~")):
        return False
    inside = actual.rstrip(os.sep) + os.sep
    # MUTATION: drop this check and a slot bound over the engine's home is served
    # (test_agent_files: test_a_root_over_the_engines_home_is_never_served).
    return not any(guarded == actual or guarded.startswith(inside) for guarded in _guarded_folders())


def agent_roots(instance_id: str) -> dict[str, AgentRoot]:
    """The agent's roots by name: its assigned slots bound to a folder here, admissible ones only."""

    from agent_runtime.persona_slots import SlotAssignmentRefused, show_instance_slots

    try:
        shown = show_instance_slots(instance_id)
    except SlotAssignmentRefused as refused:
        raise AgentNotFound(instance_id) from refused
    roots: dict[str, AgentRoot] = {}
    for row in shown.get("slots") or []:
        name, folder = row.get("name"), row.get("path")
        if not row.get("bound_here") or not isinstance(name, str) or not isinstance(folder, str):
            continue
        try:
            parse_path(name)
        except ProjectFileRefusal:
            continue
        if "/" in name or not _admissible(folder):
            continue
        roots[name] = AgentRoot(name, folder)
    return roots


def _split(roots: dict[str, AgentRoot], path: str) -> tuple[AgentRoot, str | None]:
    """The enumerated root a tree path names by its first segment, and the rest (None at the root)."""

    segments = parse_path(path)
    root = roots.get(segments[0])
    if root is None:
        raise ProjectFileRefusal("not_found", f"this agent has no root named {segments[0]!r}")
    rest = "/".join(segments[1:])
    return root, rest or None


def _prefixed(root: AgentRoot, items: list[dict]) -> list[dict]:
    return [{**item, "path": f"{root.name}/{item['path']}"} for item in items]


def _joined(root: AgentRoot, relative: str) -> str:
    return f"{root.name}/{relative}" if relative else root.name


def tree(instance_id: str, path: str | None = None, *, depth: int = DEFAULT_DEPTH,
         glob: str | None = None, offset: int = 0) -> dict:
    """The agent's tree under ``path`` to ``depth``; at the top, its roots as folders.

    With ``glob``, every file beneath ``path`` (every root when absent) whose name matches, under
    one deadline for the whole call.
    """

    if not isinstance(depth, int) or isinstance(depth, bool) or not 1 <= depth <= MAX_DEPTH:
        raise ProjectFileRefusal("bad_argument", f"depth must be 1-{MAX_DEPTH}, not {depth!r}")
    if glob is not None:
        NameGlob.parse(glob)
    deadline = Deadline()
    roots = agent_roots(instance_id)
    if path is not None:
        root, rest = _split(roots, path)
        relative, entries = tree_entries(root.folder, rest, depth=depth, glob=glob, deadline=deadline)
        return page(search_header({"path": _joined(root, relative)}, glob), "entries",
                    _prefixed(root, entries), offset, MAX_ENTRIES)
    entries: list[dict] = []
    for name in sorted(roots):
        root = roots[name]
        if glob is not None:
            entries.extend(_prefixed(root, tree_entries(root.folder, None, glob=glob, deadline=deadline)[1]))
            continue
        entries.append({"path": name, "kind": "dir"})
        if depth > 1:
            entries.extend(_prefixed(root, tree_entries(root.folder, None, depth=depth - 1)[1]))
    return page(search_header({"path": ""}, glob), "entries", entries, offset, MAX_ENTRIES)


def read(instance_id: str, path: str, *, offset: int = 0) -> dict:
    """The text of the file at ``path`` (``<root>/<relative>``), one page from ``offset``."""

    if not isinstance(path, str):
        raise ProjectFileRefusal("invalid_path", "the path is required")
    root, rest = _split(agent_roots(instance_id), path)
    if rest is None:
        raise ProjectFileRefusal("not_a_file", f"not a file: {root.name}")
    reply = _read_root(root.folder, rest, offset=offset)
    return {**reply, "path": _joined(root, reply["path"])}


def grep(instance_id: str, pattern: str, path: str | None = None, *, glob: str | None = None,
         wildcard: bool = False, offset: int = 0) -> dict:
    """Every line ``pattern`` matches under ``path``; across every root when absent.

    The pattern is literal, or a line wildcard with ``wildcard``; ``glob`` keeps the files whose
    name matches. One deadline covers the whole call, every root included.
    """

    LinePattern.parse(pattern, wildcard=wildcard)
    if glob is not None:
        NameGlob.parse(glob)
    deadline = Deadline()
    roots = agent_roots(instance_id)
    header = search_header({"pattern": pattern}, glob, wildcard)
    if path is not None:
        root, rest = _split(roots, path)
        relative, matches = grep_matches(root.folder, pattern, rest, glob=glob, wildcard=wildcard,
                                         deadline=deadline)
        return page({**header, "path": _joined(root, relative)}, "matches",
                    _prefixed(root, matches), offset, MAX_MATCHES)
    matches: list[dict] = []
    for name in sorted(roots):
        matches.extend(_prefixed(roots[name], grep_matches(
            roots[name].folder, pattern, glob=glob, wildcard=wildcard, deadline=deadline)[1]))
    return page({**header, "path": ""}, "matches", matches, offset, MAX_MATCHES)
