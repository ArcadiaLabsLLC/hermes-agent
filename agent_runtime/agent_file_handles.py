"""Which files an agent wrote this engine names to a device driving it: diffs and context files.

Row ``RT-FU-A-DEVICE-DRIVING-THIS-ENGINE-OPENS-THE-DIFFS-AND-CONTEXT-FILES-ITS-AGENT-WROTE``
(Eternia ``MC-PHONE-FILES-FILES-AN-AGENT-WROTE-OPEN-THROUGH-ITS-ENGINE``). A chat's trace names a
patch call's diff by its absolute path (``patch_diff_artifacts``), and its prompt-context frame
names the context files the turn loaded by absolute path (``prompt_observability.context_files``).
A device driving this engine from elsewhere holds those paths and cannot open them. This module
ENUMERATES the two kinds, ``media_handles.build_media_scope`` mints a content handle for each,
and ``runtime.media.get`` serves bytes by handle only — the media lane's shape, one handle table.

What is enumerated, and nothing else:

* **diffs** — the live ``paths.patch_diffs_dir()`` files named the way
  ``patch_diff_artifacts`` names them (``<stamp>_<hash>.diff``). That directory is written by one
  writer, the trace boundary, and every file in it is a diff some trace row names; an archived
  diff is no longer at the path its trace row holds, so it is not offered. Each is already capped
  at 256 KiB when written.
* **context files** — the paths the newest prompt-context frames list as loaded, whose FILE NAME
  is in :data:`SERVED_CONTEXT_FILE_NAMES` (SOUL, the instruction file, the skills snapshot). The
  name is read off the path, never off the row's own label, so a row cannot relabel a file into
  scope. ``config.yaml`` gets no handle at all (it is not in that set): it can hold
  inline secrets, and it is never served, whole or redacted (owner 2026-11-22); its safe fields
  reach a device as the agent detail's ``settings`` block (``agent_settings_summary``). The memory files (``MEMORY.md``, ``USER.md``) are not offered either: the
  row names SOUL, instruction files and the skills snapshot only.

The caller never sends a path: what it names is a handle, looked up in this derived set.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import paths

__layer__ = "stores"

__all__ = [
    "AGENT_FILE_KIND_CONTEXT_FILE",
    "AGENT_FILE_KIND_DIFF",
    "SERVED_CONTEXT_FILE_NAMES",
    "agent_written_files",
]

AGENT_FILE_KIND_DIFF = "diff"
AGENT_FILE_KIND_CONTEXT_FILE = "context_file"

#: The context files a driving device may open (by file name), each with the media type served.
#: ``config.yaml`` is deliberately absent: it is never served (owner 2026-11-22).
SERVED_CONTEXT_FILE_NAMES: dict[str, str] = {
    "SOUL.md": "text/markdown",
    "AGENTS.md": "text/markdown",
    ".skills_prompt_snapshot.json": "application/json",
}

DIFF_MEDIA_TYPE = "text/x-diff"
#: ``patch_diff_artifacts._artifact_name``: a UTC stamp, a content hash, ``.diff``.
_DIFF_NAME_RE = re.compile(r"^\d{8}T\d{6}Z_[0-9a-f]{12}\.diff$")
#: How many prompt-context frames, newest first, the context-file half reads.
_CONTEXT_FRAMES = 50


def _diff_files(limit: int) -> list[tuple[str, str, str]]:
    root = paths.patch_diffs_dir()
    try:
        names = sorted((p.name for p in root.iterdir() if _DIFF_NAME_RE.match(p.name)), reverse=True)
    except OSError:
        return []
    return [(AGENT_FILE_KIND_DIFF, str(root / name), DIFF_MEDIA_TYPE) for name in names[:limit]]


def _frame_context_paths(frame: Any) -> list[str]:
    rows = frame.get("context_files") if isinstance(frame, dict) else None
    found: list[str] = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("included") and isinstance(row.get("path"), str):
            found.append(row["path"])
    return found


def _context_files(limit: int) -> list[tuple[str, str, str]]:
    try:
        from .prompt_observability.context_store import load_latest_prompt_observability_contexts

        frames = load_latest_prompt_observability_contexts()[:_CONTEXT_FRAMES]
    except Exception:
        return []
    seen: set[str] = set()
    found: list[tuple[str, str, str]] = []
    for frame in frames:
        for reference in _frame_context_paths(frame):
            # MUTATION: add config.yaml to SERVED_CONTEXT_FILE_NAMES and test_serve_rpc_agent_files'
            # config.yaml test finds its handle in the index.
            media_type = SERVED_CONTEXT_FILE_NAMES.get(Path(reference).name)
            if reference in seen or media_type is None or not Path(reference).is_absolute():
                continue
            seen.add(reference)
            found.append((AGENT_FILE_KIND_CONTEXT_FILE, reference, media_type))
            if len(found) >= limit:
                return found
    return found


def agent_written_files(*, limit: int) -> list[tuple[str, str, str]]:
    """``(kind, reference, media_type)`` for each diff and context file in scope, diffs first.

    Never raises: a store that cannot be read contributes nothing, so a broken projection reads
    as "no files", never as "any file"."""

    diffs = _diff_files(limit)
    return diffs + _context_files(max(0, limit - len(diffs)))
