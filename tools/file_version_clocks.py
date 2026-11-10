"""Fork-owned clock check for ``tools/file_tools_read_tracking.py::_file_version``.

Windows Python can report creation time through ``stat(path).st_ctime`` and change time through
``fstat(fd).st_ctime``, so upstream's compare of the handle's stat against the path's stat never
matches there. The fork compares each clock to itself (path before/after, handle before/after);
identity, size and mtime still bind the opened bytes to the path. Owner ruling D3.03 2026-10-10;
retires against upstream issue #128639. The upstream file keeps three seam lines.
"""

from __future__ import annotations

import os

_FIELDS = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")


def _view(st: os.stat_result, names: tuple[str, ...] = _FIELDS) -> tuple:
    return tuple(getattr(st, name) for name in names)


def path_clock_before(path_before: os.stat_result, handle_before: os.stat_result,
                      path_after: os.stat_result, handle_after: os.stat_result) -> os.stat_result | None:
    """The path's own ``before`` stat when every clock agrees with itself, else ``None``.

    Upstream's compare then reads the path view (``before`` vs ``stat(path)`` after the hash).
    """
    if not (_view(path_before) == _view(path_after) and _view(handle_before) == _view(handle_after)
            and _view(path_before, _FIELDS[:-1]) == _view(handle_before, _FIELDS[:-1])):
        return None
    return path_before
