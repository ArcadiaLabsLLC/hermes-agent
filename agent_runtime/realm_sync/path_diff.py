"""One changed path's diff, as both git backends answer it: the ``HEAD`` blob against the file.

The port's ``diff`` verb (``git_port.SyncGit.diff``) is PATH-SCOPED (Eternia plan
``docs/embedded_hermes/planned/PHONE_PROJECT_FOLDERS_FILE_TREE_2026-11-21.md`` §5, row
``MC-PHONE-FILES-GIT-STATUS-AND-DIFF-ON-A-PHONE-PROJECT-FOLDER``): status names the changed
paths, and diff reads only those, so it costs the same on a 16k-file repository as on a small
one (measured 4 ms on the emulator), where a whole-tree diff took twenty seconds.

Each backend reads the ``HEAD`` side its own way (``git_dulwich`` from objects, ``git_binary``
with ``git cat-file``); the working side and the rendering are this module's, so the two
answer byte for byte the same. Pure: no process, no git.
"""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass
from pathlib import Path

__layer__ = "stores"
__all__ = ["MAX_SIDE_BYTES", "PathDiff", "path_diff", "working_bytes"]

#: The most bytes either side may hold (the rule spec's ``max_read_bytes``); a larger side is ``too_large``.
MAX_SIDE_BYTES = 5 * 1024 * 1024
#: A NUL in this many leading bytes makes a side binary (the rule spec's ``binary_probe_bytes``).
_BINARY_PROBE = 8192
_CONTEXT_LINES = 3


@dataclass(frozen=True, slots=True)
class PathDiff:
    """One path's change from ``HEAD`` to the working tree.

    ``change``: ``added`` (no ``HEAD`` side), ``deleted`` (no working side), ``modified`` or
    ``unchanged``. ``body``: ``text`` (``text`` holds a unified diff, empty when unchanged),
    ``binary`` (a NUL in either side's head), ``too_large`` (a side over ``MAX_SIDE_BYTES``)
    or ``not_text`` (a side that is not UTF-8); only ``text`` carries a diff."""

    path: str
    change: str
    body: str
    text: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "change": self.change, "body": self.body, "text": self.text}


def working_bytes(repo: Path, path: str) -> bytes | None:
    """The working tree's side of ``path``: a file's bytes, a symlink's target (as git stores it), else None.

    Reads at most ``MAX_SIDE_BYTES + 1`` bytes, so an oversized file is seen as one without reading it all.
    A symlink is never followed: its side is the link text, the blob git keeps for it."""

    local = Path(repo).joinpath(*path.split("/"))
    if os.path.islink(local):
        return os.fsencode(os.readlink(local))
    if not local.is_file():
        return None
    with open(local, "rb") as handle:
        return handle.read(MAX_SIDE_BYTES + 1)


def _lines(data: bytes) -> list[str]:
    return data.decode("utf-8").splitlines(keepends=True)


def _unified(path: str, old: bytes | None, new: bytes | None) -> str:
    before, after = _lines(old or b""), _lines(new or b"")
    rows: list[str] = []
    for line in difflib.unified_diff(before, after, f"a/{path}" if old is not None else "/dev/null",
                                     f"b/{path}" if new is not None else "/dev/null", n=_CONTEXT_LINES):
        if line.endswith("\n"):
            rows.append(line)
        else:
            rows.append(line + "\n\\ No newline at end of file\n")
    return "".join(rows)


def path_diff(path: str, old: bytes | None, new: bytes | None) -> PathDiff:
    """``path``'s diff from its ``HEAD`` side ``old`` to its working side ``new`` (None: absent)."""

    if old is None and new is None:
        raise ValueError(f"neither HEAD nor the working tree holds {path!r}")
    change = "added" if old is None else "deleted" if new is None else "modified" if old != new else "unchanged"
    sides = [side for side in (old, new) if side is not None]
    if any(len(side) > MAX_SIDE_BYTES for side in sides):
        return PathDiff(path, change, "too_large")
    if any(b"\x00" in side[:_BINARY_PROBE] for side in sides):
        return PathDiff(path, change, "binary")
    try:
        text = "" if change == "unchanged" else _unified(path, old, new)
    except UnicodeDecodeError:
        return PathDiff(path, change, "not_text")
    return PathDiff(path, change, "text", text)
