"""hermes' direct reader of a project folder: ``tree``, ``read`` and ``grep`` under the spec.

Every function takes the folder's ``root`` (a path the caller registered, never one a remote
caller gave) and a root-relative request path under the spec's grammar
(:func:`agent_runtime.project_files.paths.parse_path`). Confinement is :func:`resolve_within_root`:
the path is resolved through every symlink and refused ``outside_root`` when it leaves the
canonical root. A walk lists a symlink as ``{"kind": "link"}`` and never follows it. Every
refusal is a :class:`ProjectFileRefusal`; every reply is the spec's JSON shape, the same as
Eternia's ``ProjectFolderReader`` gives for the same case.

No process is started and nothing is written: the module is safe on a phone, where hermes
runs in Eternia's process.
"""

from __future__ import annotations

__layer__ = "stores"

import os
from collections.abc import Callable
from dataclasses import dataclass

from agent_runtime.project_files.ignore import SkipRules
from agent_runtime.project_files.paths import is_never_listed, parse_path
from agent_runtime.project_files.patterns import Deadline, LinePattern, NameGlob
from agent_runtime.project_files.replies import (
    decode_text, grep_lines, looks_binary, page, read_reply,
)
from agent_runtime.project_files.rules import (
    DEFAULT_DEPTH, MAX_DEPTH, MAX_ENTRIES, MAX_MATCHES, MAX_READ_BYTES, NEVER_LISTED,
    ProjectFileRefusal,
)

_UNBOUNDED = 1 << 30


@dataclass(frozen=True)
class _Folder:
    actual: str
    relative: str
    skip: SkipRules


def resolve_within_root(root: str, relative: str) -> str | None:
    """``relative`` under the canonical ``root``, every symlink resolved; None when it leaves.

    Raises ``OSError`` when nothing is at the path.
    """

    actual = os.path.realpath(os.path.join(root, relative), strict=True)
    if actual == root or actual.startswith(root.rstrip(os.sep) + os.sep):
        return actual
    return None


def _canonical_root(root: str) -> str:
    if not isinstance(root, str) or not os.path.isabs(root):
        raise ProjectFileRefusal("invalid_path", "the root must be an absolute folder")
    try:
        actual = os.path.realpath(root, strict=True)
    except OSError:
        raise ProjectFileRefusal("not_found", "the root folder is not there") from None
    if not os.path.isdir(actual):
        raise ProjectFileRefusal("not_found", "the root is not a folder")
    return actual


def _resolve_in_root(base: str, segments: tuple[str, ...]) -> str:
    shown = "/".join(segments)
    if is_never_listed(segments):
        raise ProjectFileRefusal("ignored", f".git is never listed or read: {shown}")
    if not segments:
        return base
    try:
        actual = resolve_within_root(base, os.path.join(*segments))
    except OSError:
        raise ProjectFileRefusal("not_found", f"nothing at {shown}") from None
    if actual is None:
        raise ProjectFileRefusal("outside_root", f"the path leads outside the root: {shown}")
    if actual != base and any(part in NEVER_LISTED
                              for part in os.path.relpath(actual, base).split(os.sep)):
        raise ProjectFileRefusal("ignored", f"the path leads into .git: {shown}")
    return actual


def _skip_rules_of(base: str) -> SkipRules:
    """The root's ``.gitignore``: a plain file within the cap and UTF-8, else no rules."""

    path = os.path.join(base, ".gitignore")
    if os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path) > MAX_READ_BYTES:
        return SkipRules()
    try:
        with open(path, "rb") as handle:
            return SkipRules.parse(handle.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError):
        return SkipRules()


def _listed_folder(root: str, path: str | None) -> _Folder:
    segments = parse_path(path)
    base = _canonical_root(root)
    actual = _resolve_in_root(base, segments)
    if not os.path.isdir(actual):
        raise ProjectFileRefusal("not_a_directory", f"not a folder: {'/'.join(segments)}")
    return _Folder(actual, "/".join(segments), _skip_rules_of(base))


def _walk_project_folder(folder: _Folder, actual: str, relative: str, depth: int,
          add: Callable[[dict], None], deadline: Deadline | None = None) -> None:
    with os.scandir(actual) as scan:
        children = sorted(scan, key=lambda entry: entry.name)
    for child in children:
        if deadline is not None:
            deadline.check()
        path = f"{relative}/{child.name}" if relative else child.name
        if child.is_symlink():
            if not folder.skip.skips(path, is_directory=False):
                add({"path": path, "kind": "link"})
        elif child.is_dir(follow_symlinks=False):
            if folder.skip.skips(path, is_directory=True):
                continue
            add({"path": path, "kind": "dir"})
            if depth > 1:
                _walk_project_folder(folder, child.path, path, depth - 1, add, deadline)
        elif child.is_file(follow_symlinks=False):
            if not folder.skip.skips(path, is_directory=False):
                add({"path": path, "kind": "file", "size": child.stat(follow_symlinks=False).st_size})


def _name(entry: dict) -> str:
    return entry["path"].rsplit("/", 1)[-1]


def tree_entries(root: str, path: str | None = None, *, depth: int = DEFAULT_DEPTH,
                 glob: str | None = None, deadline: Deadline | None = None) -> tuple[str, list[dict]]:
    """``(the listed folder's relative path, every entry under it to depth)``, pre-order, unpaged.

    With ``glob``, every file beneath the folder at any depth whose name matches it, files only,
    under ``deadline`` (a fresh one when None).
    """

    if not isinstance(depth, int) or isinstance(depth, bool) or not 1 <= depth <= MAX_DEPTH:
        raise ProjectFileRefusal("bad_argument", f"depth must be 1-{MAX_DEPTH}, not {depth!r}")
    names = None if glob is None else NameGlob.parse(glob)
    folder = _listed_folder(root, path)
    entries: list[dict] = []
    if names is None:
        _walk_project_folder(folder, folder.actual, folder.relative, depth, entries.append)
        return folder.relative, entries

    def add(entry: dict) -> None:
        if entry["kind"] == "file" and names.matches(_name(entry)):
            entries.append(entry)

    _walk_project_folder(folder, folder.actual, folder.relative, _UNBOUNDED, add,
                         deadline or Deadline())
    return folder.relative, entries


def search_header(header: dict, glob: str | None, wildcard: bool = False) -> dict:
    """``header`` with the reply's echo of a ``glob`` and of ``wildcard: true``, when given."""

    return {**header, **({"glob": glob} if glob is not None else {}),
            **({"wildcard": True} if wildcard else {})}


def tree(root: str, path: str | None = None, *, depth: int = DEFAULT_DEPTH, glob: str | None = None,
         offset: int = 0) -> dict:
    """The entries under ``path`` (the root when None) to ``depth``, pre-order; with ``glob``, matching files."""

    relative, entries = tree_entries(root, path, depth=depth, glob=glob)
    return page(search_header({"path": relative}, glob), "entries", entries, offset, MAX_ENTRIES)


def read(root: str, path: str, *, offset: int = 0) -> dict:
    """The text of the file at ``path``, one page from ``offset`` code points."""

    segments = parse_path(path)
    shown = "/".join(segments)
    actual = _resolve_in_root(_canonical_root(root), segments)
    if not os.path.isfile(actual):
        raise ProjectFileRefusal("not_a_file", f"not a file: {shown}")
    if os.path.getsize(actual) > MAX_READ_BYTES:
        raise ProjectFileRefusal("too_large", f"the file is over {MAX_READ_BYTES} bytes: {shown}")
    with open(actual, "rb") as handle:
        data = handle.read(MAX_READ_BYTES + 1)
    if len(data) > MAX_READ_BYTES:
        raise ProjectFileRefusal("too_large", f"the file is over {MAX_READ_BYTES} bytes: {shown}")
    if looks_binary(data):
        raise ProjectFileRefusal("binary", f"the file is binary: {shown}")
    return read_reply(shown, len(data), decode_text(data, shown), offset)


def grep_matches(root: str, pattern: str, path: str | None = None, *, glob: str | None = None,
                 wildcard: bool = False, deadline: Deadline | None = None,
                 context: int = 0) -> tuple[str, list[dict]]:
    """``(the searched folder's relative path, every line the pattern matches)``, unpaged.

    The pattern is literal, or a line wildcard with ``wildcard``; ``glob`` keeps the files whose
    name matches. The walk and every line ask ``deadline`` (a fresh one when None). ``context``
    lines around each match ride on it (:func:`replies.grep_lines`).
    """

    matcher = LinePattern.parse(pattern, wildcard=wildcard)
    names = None if glob is None else NameGlob.parse(glob)
    deadline = deadline or Deadline()
    folder = _listed_folder(root, path)
    files: list[dict] = []

    def add(entry: dict) -> None:
        if entry["kind"] == "file" and (names is None or names.matches(_name(entry))):
            files.append(entry)

    _walk_project_folder(folder, folder.actual, folder.relative, _UNBOUNDED, add, deadline)
    prefix = len(folder.relative) + 1 if folder.relative else 0
    matches: list[dict] = []
    for entry in files:
        deadline.check()
        if entry["size"] > MAX_READ_BYTES:
            continue
        local = os.path.join(folder.actual, *entry["path"][prefix:].split("/"))
        with open(local, "rb") as handle:
            data = handle.read(MAX_READ_BYTES + 1)
        if len(data) > MAX_READ_BYTES or looks_binary(data):
            continue
        try:
            text = decode_text(data, entry["path"])
        except ProjectFileRefusal:
            continue
        matches.extend(grep_lines(entry["path"], text, matcher, deadline, context))
    return folder.relative, matches


def grep(root: str, pattern: str, path: str | None = None, *, glob: str | None = None,
         wildcard: bool = False, offset: int = 0) -> dict:
    """Every line ``pattern`` matches in the text files under ``path`` whose name ``glob`` matches."""

    relative, matches = grep_matches(root, pattern, path, glob=glob, wildcard=wildcard)
    return page(search_header({"pattern": pattern, "path": relative}, glob, wildcard), "matches",
                matches, offset, MAX_MATCHES)
