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

import os
from collections.abc import Callable
from dataclasses import dataclass

from agent_runtime.project_files.ignore import SkipRules
from agent_runtime.project_files.paths import is_never_listed, parse_path
from agent_runtime.project_files.replies import (
    check_pattern, decode_text, grep_lines, looks_binary, page, read_reply,
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


def _root(root: str) -> str:
    if not isinstance(root, str) or not os.path.isabs(root):
        raise ProjectFileRefusal("invalid_path", "the root must be an absolute folder")
    try:
        actual = os.path.realpath(root, strict=True)
    except OSError:
        raise ProjectFileRefusal("not_found", "the root folder is not there") from None
    if not os.path.isdir(actual):
        raise ProjectFileRefusal("not_found", "the root is not a folder")
    return actual


def _resolve(base: str, segments: tuple[str, ...]) -> str:
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


def _folder(root: str, path: str | None) -> _Folder:
    segments = parse_path(path)
    base = _root(root)
    actual = _resolve(base, segments)
    if not os.path.isdir(actual):
        raise ProjectFileRefusal("not_a_directory", f"not a folder: {'/'.join(segments)}")
    return _Folder(actual, "/".join(segments), _skip_rules_of(base))


def _walk(folder: _Folder, actual: str, relative: str, depth: int,
          add: Callable[[dict], None]) -> None:
    with os.scandir(actual) as scan:
        children = sorted(scan, key=lambda entry: entry.name)
    for child in children:
        path = f"{relative}/{child.name}" if relative else child.name
        if child.is_symlink():
            if not folder.skip.skips(path, is_directory=False):
                add({"path": path, "kind": "link"})
        elif child.is_dir(follow_symlinks=False):
            if folder.skip.skips(path, is_directory=True):
                continue
            add({"path": path, "kind": "dir"})
            if depth > 1:
                _walk(folder, child.path, path, depth - 1, add)
        elif child.is_file(follow_symlinks=False):
            if not folder.skip.skips(path, is_directory=False):
                add({"path": path, "kind": "file", "size": child.stat(follow_symlinks=False).st_size})


def tree(root: str, path: str | None = None, *, depth: int = DEFAULT_DEPTH, offset: int = 0) -> dict:
    """The entries under ``path`` (the root when None) to ``depth``, pre-order."""

    if not isinstance(depth, int) or isinstance(depth, bool) or not 1 <= depth <= MAX_DEPTH:
        raise ProjectFileRefusal("bad_argument", f"depth must be 1-{MAX_DEPTH}, not {depth!r}")
    folder = _folder(root, path)
    entries: list[dict] = []
    _walk(folder, folder.actual, folder.relative, depth, entries.append)
    return page({"path": folder.relative}, "entries", entries, offset, MAX_ENTRIES)


def read(root: str, path: str, *, offset: int = 0) -> dict:
    """The text of the file at ``path``, one page from ``offset`` code points."""

    segments = parse_path(path)
    shown = "/".join(segments)
    actual = _resolve(_root(root), segments)
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


def grep(root: str, pattern: str, path: str | None = None, *, offset: int = 0) -> dict:
    """Every line holding the literal ``pattern`` in the text files under ``path``."""

    check_pattern(pattern)
    folder = _folder(root, path)
    files: list[dict] = []
    _walk(folder, folder.actual, folder.relative, _UNBOUNDED,
          lambda entry: files.append(entry) if entry["kind"] == "file" else None)
    prefix = len(folder.relative) + 1 if folder.relative else 0
    matches: list[dict] = []
    for entry in files:
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
        matches.extend(grep_lines(entry["path"], text, pattern))
    return page({"pattern": pattern, "path": folder.relative}, "matches", matches, offset,
                MAX_MATCHES)
