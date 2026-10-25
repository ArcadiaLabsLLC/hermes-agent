"""Fork seam for ``tools/self_repo_guard.py``: ``$VAR`` / ``${VAR}`` in a ``cd`` / ``-C`` /
``--work-tree`` target (RT-SELF-REPO-GUARD-VAR-AND-GITDIR-TARGETS).

The guard used to judge the literal word ``$TMPDIR/lr`` as a path relative to the session
cwd, so a command aimed at a scratch clone was refused as a rewrite of the live checkout.
A target is now expanded from the command's own ``VAR=value`` prefix, then the process
environment the shell inherits. A variable defined in neither leaves the target UNRESOLVED:
it is placed under :data:`UNRESOLVED_ROOT`, a root no real path lives under, so the guard
neither mistakes it for the checkout nor waves it through — a mutating command aimed at it
is refused with a message that names the unresolved word.

``--git-dir`` without ``--work-tree`` is deliberately not handled here: git really does use
the cwd as the work tree there, so the guard's cwd judgement is right.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Mapping

_VAR_RE = re.compile(r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|(?P<bare>[A-Za-z_][A-Za-z0-9_]*))")
#: The root unresolved targets are placed under: absolute on every platform, never a real dir.
UNRESOLVED_ROOT = Path(os.path.abspath(os.sep)) / "␀hermes-unresolved-shell-target"


def expand_target(word: str, env: Mapping[str, str]) -> str:
    """``word`` with each ``$VAR`` / ``${VAR}`` replaced from ``env`` then ``os.environ``;
    a word naming an undefined variable is returned under :data:`UNRESOLVED_ROOT`."""
    if "$" not in word:
        return word
    unresolved = False

    def value(match: re.Match[str]) -> str:
        nonlocal unresolved
        name = match.group("braced") or match.group("bare")
        found = env.get(name, os.environ.get(name))
        if found is None:
            unresolved = True
            return match.group(0)
        return found

    expanded = _VAR_RE.sub(value, word)
    return str(UNRESOLVED_ROOT / word) if unresolved else expanded


def is_unresolved(path: Path) -> bool:
    try:
        return path == UNRESOLVED_ROOT or path.is_relative_to(UNRESOLVED_ROOT)
    except (TypeError, ValueError):
        return False


class UnresolvedOperation(str):
    """An operation the guard refused because its target could not be resolved."""

    target: str


def unresolved_operation(operation: str, target: Path) -> UnresolvedOperation:
    marked = UnresolvedOperation(operation)
    try:
        marked.target = target.relative_to(UNRESOLVED_ROOT).as_posix()
    except ValueError:
        marked.target = str(target)
    return marked


def unresolved_message(operation: str, root: Path) -> str | None:
    """The refusal for an :class:`UnresolvedOperation`, else ``None`` (the guard's own text)."""
    if not isinstance(operation, UnresolvedOperation):
        return None
    return (
        f"Blocked: `{operation}` targets `{operation.target}`, whose variable is not set in the "
        f"command or the environment, so it cannot be told apart from Hermes's live source "
        f"checkout ({root}). Spell the directory out, or set the variable on the same command "
        f"(`VAR=/path git -C \"$VAR\" …`).")
