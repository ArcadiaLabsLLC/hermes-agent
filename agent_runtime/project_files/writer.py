"""The ONE checked write into a project folder: ``write`` and ``patch`` under the spec, then the write guards.

Eternia row ``MC-PHONE-FILES-A-PHONE-AGENT-READS-AND-WRITES-ITS-PROJECT-FILES`` (plan
``PHONE_PROJECT_FOLDERS_FILE_TREE_2026-11-21.md`` §9 as corrected by review w1118a.79): a phone starts
no process, so its agent's file tools write through this module instead of upstream's
``ShellFileOperations``. Every write is held, in this order, to:

1. **the rule spec** (``paths.parse_path``): a relative ``/`` path, no ``..``, never into ``.git``;
2. **confinement** (``reader.resolve_within_root``): the deepest folder that exists on the way, or the
   file itself when it exists, resolved through every symlink, must stay inside the root;
3. **the agent's write guards**: upstream's deny list (``agent.file_safety.get_write_denied_error``,
   system and credential files) and the bundled install's namespace config guard
   (``namespace_config_guard.protected_reason``: no profile's ``config.yaml``, no fork plugin folder);
4. **the read cap**: no file over ``MAX_READ_BYTES`` is written or patched.

The file is replaced atomically (a temp file beside it, then ``os.replace``), keeping an existing
file's mode. No process is started.
"""

from __future__ import annotations

__layer__ = "stores"

import os
import secrets
from pathlib import Path

from agent_runtime.project_files.paths import is_never_listed, parse_path
from agent_runtime.project_files.reader import _canonical_root, resolve_within_root
from agent_runtime.project_files.replies import decode_text, looks_binary
from agent_runtime.project_files.rules import MAX_READ_BYTES, ProjectFileRefusal

__all__ = ["WriteDenied", "checked_text", "patch", "write"]


class WriteDenied(Exception):
    """A write the agent's write guards refuse; ``message`` is the guard's own sentence."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _target(root: str, path: str) -> tuple[str, str]:
    """``(the file's real path, its shown path)``: confined to ``root``, its folder may not exist yet."""

    segments = parse_path(path)
    shown = "/".join(segments)
    if not segments:
        raise ProjectFileRefusal("not_a_file", "a write names a file, not the root")
    if is_never_listed(segments):
        raise ProjectFileRefusal("ignored", f".git is never written: {shown}")
    base = _canonical_root(root)
    candidate = os.path.join(base, *segments)
    if os.path.lexists(candidate):
        try:
            actual = resolve_within_root(base, os.path.join(*segments))
        except OSError:  # a dangling link: where it points is unknown, so it is never written through
            raise ProjectFileRefusal("outside_root", f"the path leads nowhere inside the root: {shown}") from None
        if actual is None:
            raise ProjectFileRefusal("outside_root", f"the path leads outside the root: {shown}")
        if os.path.isdir(actual):
            raise ProjectFileRefusal("not_a_file", f"not a file: {shown}")
    else:
        # The deepest folder that exists on the way decides: a symlinked folder out of the root is refused.
        depth = len(segments) - 1
        while depth > 0 and not os.path.lexists(os.path.join(base, *segments[:depth])):
            depth -= 1
        # MUTATION: skip this check and a new file is written through a symlinked folder out of the root
        # (test_phone_file_tools: test_a_write_through_a_symlinked_folder_out_of_the_root_is_refused).
        folder = resolve_within_root(base, os.path.join(*segments[:depth])) if depth else base
        if folder is None:
            raise ProjectFileRefusal("outside_root", f"the path leads outside the root: {shown}")
        actual = os.path.join(folder, *segments[depth:])
    if any(part in (".git",) for part in os.path.relpath(actual, base).split(os.sep)):
        raise ProjectFileRefusal("ignored", f"the path leads into .git: {shown}")
    return actual, shown


def _guard(actual: str) -> None:
    """The agent's write guards on the real path: upstream's deny list, then the namespace config guard."""

    from agent.file_safety import get_write_denied_error
    from agent_runtime.namespace_config_guard import namespace_roots, protected_reason

    denied = get_write_denied_error(actual)
    if denied:
        raise WriteDenied(denied)
    # MUTATION: drop this guard and a project folder's link to a profile's config.yaml is written through
    # (test_phone_file_tools: test_a_write_to_a_profile_config_is_refused_by_the_guard).
    reason = protected_reason(Path(actual), namespace_roots())
    if reason is not None:
        raise WriteDenied(f"Refusing to write it: it is {reason}. Nothing was written.")


def _replace_file(actual: str, data: bytes) -> bool:
    """Atomically put ``data`` at ``actual``; True when the file is new."""

    created = not os.path.exists(actual)
    os.makedirs(os.path.dirname(actual), exist_ok=True)
    mode = None if created else os.stat(actual).st_mode & 0o7777
    temp = os.path.join(os.path.dirname(actual), f".{os.path.basename(actual)}.{secrets.token_hex(4)}.tmp")
    try:
        with open(temp, "xb") as handle:
            handle.write(data)
        if mode is not None:
            os.chmod(temp, mode)
        os.replace(temp, actual)
    except BaseException:
        if os.path.lexists(temp):
            os.unlink(temp)
        raise
    return created


def _text_of(actual: str, shown: str) -> str:
    """The text file at ``actual``: within the read cap, not binary, UTF-8."""

    with open(actual, "rb") as handle:
        data = handle.read(MAX_READ_BYTES + 1)
    if len(data) > MAX_READ_BYTES:
        raise ProjectFileRefusal("too_large", f"the file is over {MAX_READ_BYTES} bytes: {shown}")
    if looks_binary(data):
        raise ProjectFileRefusal("binary", f"the file is binary: {shown}")
    return decode_text(data, shown)


def checked_text(root: str, path: str) -> str | None:
    """The text at ``path`` under ``root`` once a write there has passed every check, writing nothing.

    The spec, confinement and the agent's write guards are :func:`write`'s own; None when no file is
    there yet. A multi-file edit asks this for every file before it writes any (row
    ``RT-PHONE-FILE-TOOLS-ACCEPT-EVERY-DESKTOP-ARGUMENT``: a V4A patch is validated whole first)."""

    actual, shown = _target(root, path)
    # MUTATION: skip the guard here and a V4A patch writes its first file before the guard refuses a
    # later one (test_phone_file_tools: test_a_v4a_patch_writes_nothing_when_one_file_is_refused).
    _guard(actual)
    if not os.path.lexists(actual):
        return None
    if not os.path.isfile(actual):
        raise ProjectFileRefusal("not_a_file", f"not a file: {shown}")
    return _text_of(actual, shown)


def write(root: str, path: str, content: str) -> dict:
    """Put ``content`` (UTF-8) at ``path`` under ``root``, making its folders: ``{path, size, created}``."""

    if not isinstance(content, str):
        raise ProjectFileRefusal("bad_argument", "content must be text")
    data = content.encode("utf-8")
    if len(data) > MAX_READ_BYTES:
        raise ProjectFileRefusal("too_large", f"the content is over {MAX_READ_BYTES} bytes")
    actual, shown = _target(root, path)
    _guard(actual)
    created = _replace_file(actual, data)
    return {"path": shown, "size": len(data), "created": created}


def patch(root: str, path: str, old: str, new: str, *, replace_all: bool = False) -> dict:
    """Replace ``old`` with ``new`` in the text file at ``path``: once, or every time with ``replace_all``.

    ``old`` must be found, and found once unless ``replace_all``: ``{path, replacements, size}``."""

    if not isinstance(old, str) or not old or not isinstance(new, str):
        raise ProjectFileRefusal("bad_argument", "old_string must be non-empty text and new_string text")
    actual, shown = _target(root, path)
    if not os.path.isfile(actual):
        raise ProjectFileRefusal("not_found", f"nothing at {shown}")
    text = _text_of(actual, shown)
    count = text.count(old)
    if count == 0:
        raise ProjectFileRefusal("bad_argument", f"old_string was not found in {shown}")
    if count > 1 and not replace_all:
        raise ProjectFileRefusal("bad_argument", f"old_string is found {count} times in {shown}; "
                                                 "give more context or set replace_all")
    updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
    encoded = updated.encode("utf-8")
    if len(encoded) > MAX_READ_BYTES:
        raise ProjectFileRefusal("too_large", f"the patched file would be over {MAX_READ_BYTES} bytes")
    _guard(actual)
    _replace_file(actual, encoded)
    return {"path": shown, "replacements": count if replace_all else 1, "size": len(encoded)}
