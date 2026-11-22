"""``status`` and ``diff`` on a project folder that is a git root (the spec's git verbs).

Row ``MC-PHONE-FILES-GIT-STATUS-AND-DIFF-ON-A-PHONE-PROJECT-FOLDER`` (Eternia plan
``docs/embedded_hermes/planned/PHONE_PROJECT_FOLDERS_FILE_TREE_2026-11-21.md`` §5): git on a
phone is hermes' dulwich behind the realm-sync port (``realm_sync.git_port``), the git program on a
desktop, whichever ``realm_sync.git.sync_git`` picks for this device. ``status`` names the changed
paths; ``diff`` reads only the one asked for (the ``HEAD`` blob against the file), so neither walks
the whole tree for content. Eternia on a phone asks these through its local hermes and keeps reading
the files themselves directly.

Both verbs take a root the caller registered (never a path a remote caller gave) and refuse
``not_a_git_root`` when the root holds no ``.git``. Neither starts a process on a phone (the dulwich
backend), and neither writes: no index refresh is saved, no hook can run.
"""

from __future__ import annotations

__layer__ = "stores"

import os
from pathlib import Path

from agent_runtime.project_files.paths import is_never_listed, parse_path
from agent_runtime.project_files.reader import resolve_within_root
from agent_runtime.project_files.replies import page, read_reply
from agent_runtime.project_files.rules import MAX_ENTRIES, ProjectFileRefusal

__all__ = ["diff", "status"]


def _git_root(root: str) -> str:
    if not isinstance(root, str) or not os.path.isabs(root):
        raise ProjectFileRefusal("invalid_path", "the root must be an absolute folder")
    try:
        actual = os.path.realpath(root, strict=True)
    except OSError:
        raise ProjectFileRefusal("not_found", "the root folder is not there") from None
    if not os.path.isdir(actual):
        raise ProjectFileRefusal("not_found", "the root is not a folder")
    if not os.path.exists(os.path.join(actual, ".git")):
        raise ProjectFileRefusal("not_a_git_root", "the root is not a git repository")
    return actual


def _sync_git(root: str):
    from agent_runtime.realm_sync.git import sync_git

    return sync_git(Path(root))


def status(root: str, *, offset: int = 0) -> dict:
    """The root's changed paths against ``HEAD``: ``{path, state}``, ``state`` ``changed`` or ``new``.

    Every new file is listed by itself (never folded into its folder), sorted by path, paged like ``tree``."""

    actual = _git_root(root)
    entries = [{"path": row.path, "state": "new" if row.untracked else "changed"}
               for row in _sync_git(actual).changed(untracked_all=True)
               if not is_never_listed(tuple(row.path.split("/")))]
    entries.sort(key=lambda entry: entry["path"])
    return page({"path": ""}, "entries", entries, offset, MAX_ENTRIES)


def _confined(base: str, segments: tuple[str, ...]) -> None:
    """The path's folder lies inside the root (a symlinked folder out of it is refused).

    The file itself may be gone (a deletion is diffed against ``HEAD``), so its folder is what is resolved;
    a symlink AT the path is diffed as its link text and never followed."""

    shown = "/".join(segments)
    if is_never_listed(segments):
        raise ProjectFileRefusal("ignored", f".git is never listed or read: {shown}")
    parent = base
    for depth in range(len(segments) - 1, 0, -1):
        candidate = os.path.join(base, *segments[:depth])
        if os.path.lexists(candidate):
            parent = candidate
            break
    try:
        if resolve_within_root(base, os.path.relpath(parent, base)) is None:
            raise ProjectFileRefusal("outside_root", f"the path leads outside the root: {shown}")
    except OSError:
        raise ProjectFileRefusal("not_found", f"nothing at {shown}") from None


def diff(root: str, path: str, *, offset: int = 0) -> dict:
    """``path``'s change from ``HEAD``: ``{path, change, body}`` and, for a text body, the unified diff
    paged as ``read`` pages a file (``chars``, ``offset``, ``content``, ``next``)."""

    segments = parse_path(path)
    if not segments:
        raise ProjectFileRefusal("not_a_file", "diff names a file, not the root")
    actual = _git_root(root)
    _confined(actual, segments)
    shown = "/".join(segments)
    rows = _sync_git(actual).diff([shown])
    if not rows:
        raise ProjectFileRefusal("not_found", f"neither HEAD nor the folder holds a file at {shown}")
    row = rows[0]
    reply = {"path": shown, "change": row.change, "body": row.body}
    if row.body != "text":
        return reply
    paged = read_reply(shown, len(row.text.encode("utf-8")), row.text, offset)
    paged.pop("size")
    return {**reply, **paged}
