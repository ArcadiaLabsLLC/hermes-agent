"""Fork seam for ``tools/self_repo_guard.py``: ``$VAR`` / ``${VAR}`` in a ``cd`` / ``-C`` /
``--work-tree`` target (RT-SELF-REPO-GUARD-VAR-AND-GITDIR-TARGETS).

The guard used to judge the literal word ``$TMPDIR/lr`` as a path relative to the session
cwd, so a command aimed at a scratch clone was refused as a rewrite of the live checkout.
A target is now expanded the way the shell will: from the variables assigned by EARLIER
statements of the same command (``LR="$TMPDIR/lr"; git -C "$LR" …``, ``export LR=…``; a
subshell's assignments stay in it), then the process environment the shell inherits. Never
from the same statement's ``VAR=value`` prefix: the shell expands ``git -C "$LR"`` before that
prefix takes effect, so ``LR=/x git -C "$LR" checkout`` runs in the CWD and must be judged
there. A variable defined in neither leaves the target UNRESOLVED:
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


_ASSIGNMENT_RE = re.compile(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)", re.DOTALL)
#: Builtins whose ``NAME=value`` operands set a shell variable for the statements after them.
_ASSIGNING_BUILTINS = frozenset({"export", "declare", "typeset", "local", "readonly"})


class BoundEnv(dict):
    """A statement's ``VAR=value`` prefix (the dict, read for ``GIT_WORK_TREE`` and friends)
    plus the shell variables in force when the statement's words are expanded."""

    shell_vars: Mapping[str, str] = {}


class ShellVars:
    """Shell variables assigned by the statements of one command, per subshell scope."""

    def __init__(self) -> None:
        self._by_scope: dict[tuple[int, ...], dict[str, str]] = {}

    def visible(self, scope: tuple[int, ...]) -> dict[str, str]:
        merged: dict[str, str] = {}
        for depth in range(len(scope) + 1):
            merged.update(self._by_scope.get(scope[:depth], {}))
        return merged

    def bind(self, scope: tuple[int, ...], env: Mapping[str, str], executable: str | None,
             args: list[str]) -> BoundEnv:
        """``env`` bound to the variables visible at ``scope``; records what the statement assigns
        (a bare ``A=1 B=2`` statement, or an assigning builtin's operands) for later statements."""
        bound = BoundEnv(env)
        bound.shell_vars = self.visible(scope)
        if executable is None:
            assigned = dict(env)
        elif Path(executable).name.lower() in _ASSIGNING_BUILTINS:
            assigned = {m["name"]: m["value"] for arg in args if (m := _ASSIGNMENT_RE.fullmatch(arg))}
        else:
            return bound
        own = self._by_scope.setdefault(scope, {})
        for name, value in assigned.items():
            own[name] = expand_target(value, bound)
            bound.shell_vars = {**bound.shell_vars, name: own[name]}
        return bound


def expand_target(word: str, env: Mapping[str, str]) -> str:
    """``word`` with each ``$VAR`` / ``${VAR}`` replaced from ``env``'s bound shell variables
    (:class:`BoundEnv`; never ``env``'s own prefix entries) then ``os.environ``; a word naming
    an undefined variable is returned under :data:`UNRESOLVED_ROOT`."""
    if "$" not in word:
        return word
    unresolved = False
    shell_vars = getattr(env, "shell_vars", {})

    def value(match: re.Match[str]) -> str:
        nonlocal unresolved
        name = match.group("braced") or match.group("bare")
        found = shell_vars.get(name, os.environ.get(name))
        if found is None:
            unresolved = True
            return match.group(0)
        return found

    expanded = _VAR_RE.sub(value, word)
    # A variable that itself held an unresolved target keeps the expansion unresolved.
    return _under_unresolved_root(word) if unresolved or UNRESOLVED_ROOT.name in expanded else expanded


def _under_unresolved_root(word: str) -> str:
    """``word`` placed under :data:`UNRESOLVED_ROOT`; a drive or leading separator is dropped
    first, or ``Path`` joining would let ``/x/$Y`` / ``C:/x/$Y`` replace the root and escape."""
    return str(UNRESOLVED_ROOT / re.sub(r"^[A-Za-z]:", "", word).lstrip("/\\"))


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


#: The phrase only the unresolved-variable refusal carries; :func:`block_class` reads it.
UNRESOLVED_PHRASE = "whose variable is not set in the command or the environment"
#: RT-SAFETY-BLOCK-CLASS-FIELD: a blocked terminal result is one of these two.
BLOCK_FIXABLE = "fixable"
BLOCK_FINAL = "final"


def block_class(error_text: object) -> str:
    """``fixable`` for the unresolved-variable refusal (respell the target and run again), ``final``
    for every other self-repo block (the command would rewrite the live checkout)."""
    return BLOCK_FIXABLE if isinstance(error_text, str) and UNRESOLVED_PHRASE in error_text else BLOCK_FINAL


def unresolved_message(operation: str, root: Path) -> str | None:
    """The refusal for an :class:`UnresolvedOperation`, else ``None`` (the guard's own text)."""
    if not isinstance(operation, UnresolvedOperation):
        return None
    return (
        f"Blocked: `{operation}` targets `{operation.target}`, {UNRESOLVED_PHRASE}, "
        f"so it cannot be told apart from Hermes's live source "
        f"checkout ({root}). Spell the directory out, or assign the variable in an earlier "
        f"statement of the same command (`VAR=/path; git -C \"$VAR\" …`).")
