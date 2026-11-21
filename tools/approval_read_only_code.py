"""Fork seam for ``tools/approval_detection.py``: inline ``python -c`` / ``powershell -Command``
code that only reads or waits (RT-FU-A-READ-ONLY-CHECK-IN-A-HELPERS-TERMINAL-WAITS-ON-AN-APPROVAL).

``python -c`` is flagged ``script execution via -e/-c flag`` because its code can do anything.
Seen 2026-11-20: a dispatched helper's line-ending check (``Path(...).read_bytes()`` and
``.count(b"\\r\\n")``, printed) waited 60 s on an approval nobody saw, then stopped its job.
:func:`read_only_code` admits only Python code that provably reads: it parses with :mod:`ast`, every
node is from a short list, every call is to a named reader, every name is one the code bound
itself, imported from :data:`_IMPORTS`, or a listed builtin, and no listed name is rebound (``print =
p.unlink`` would make ``print()`` a delete) nor any attribute assigned. Anything else -- a write, ``open``,
``getattr``, an underscore attribute, a ``def``, an unknown option before ``-c``, code that does
not parse -- keeps the finding. Unknown means ask: the list is the whole of what is admitted.

Seen again 00:48Z: the same helper's ``powershell -NoProfile -Command '$id=…; try { Wait-Process -Id
$id -Timeout 570 … } catch { Write-Output … }; if (-not (Get-Process -Id $id …)) { Get-Content <log>
-Tail 80 }'`` (waiting on its own background test) was blocked the same way, so its lead ran the test.
:func:`_reads_only_powershell` admits a PowerShell script whose every command is a reader or a wait
from :data:`_PS_COMMANDS` (statement keywords aside), with no redirection, call operator, static
member (``::``), method call, backtick escape or ``-EncodedCommand``; quoted text is data, except a
double-quoted string holding ``$(...)``, which is scanned as code
(RT-FU-A-READ-ONLY-SELECT-STRING-STILL-ASKS-FOR-APPROVAL: a ``-Pattern "a|Expected:"`` read as a pipe).

Only on an Eternia chat turn: the admission applies while a harness surface has bound its approval
policy (``agent_runtime.approval_surface_policy.surface_mode``, bound by every persona chat turn's
``session_approval_scope``), so upstream's own surfaces (CLI, gateway, cron) keep upstream's rule.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from typing import Any

__all__ = ["read_only_code"]

#: Interpreter options that change nothing about what the code may do.
_QUIET_OPTIONS = frozenset({"-I", "-B", "-E", "-s", "-S", "-u", "-q", "-b", "-O", "-OO"})
#: Modules the code may import, and for ``from`` imports the names it may take (None: any name).
_IMPORTS: dict[str, frozenset[str] | None] = {
    "pathlib": frozenset({"Path", "PurePath", "PurePosixPath", "PureWindowsPath"}),
    "json": None,
    "re": None,
    "sys": None,
    "collections": frozenset({"Counter"}),
}
#: Builtins the code may call or name.
_BUILTINS = frozenset({
    "print", "len", "sum", "min", "max", "sorted", "reversed", "enumerate", "zip", "range", "str",
    "int", "float", "bool", "repr", "list", "tuple", "set", "frozenset", "dict", "any", "all", "abs",
    "round", "isinstance", "chr", "ord", "hex", "bytes", "next", "True", "False", "None",
})
#: Constructors the code may call once it imported them.
_CONSTRUCTORS = frozenset({"Path", "PurePath", "PurePosixPath", "PureWindowsPath", "Counter"})
#: Methods the code may call on anything: readers and pure text/collection helpers. Never a writer
#: (``write_*``, ``unlink``, ``rename``, ``replace`` -- ``Path.replace`` moves a file -- ``touch``,
#: ``mkdir``, ``chmod``, ``open``, ``exit``).
_METHODS = frozenset({
    "read_bytes", "read_text", "exists", "is_file", "is_dir", "iterdir", "glob", "rglob", "resolve",
    "absolute", "relative_to", "as_posix", "joinpath", "stat",
    "count", "find", "rfind", "index", "startswith", "endswith", "split", "rsplit", "splitlines",
    "strip", "lstrip", "rstrip", "lower", "upper", "decode", "encode", "format", "join",
    "items", "keys", "values", "get", "loads", "dumps", "findall", "finditer", "search", "match",
    "fullmatch", "group", "groups", "most_common", "hex",
})
_NODES = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.For, ast.If, ast.Pass, ast.Import,
    ast.ImportFrom, ast.alias, ast.Name, ast.Load, ast.Store, ast.Constant, ast.Attribute, ast.Call,
    ast.keyword, ast.Subscript, ast.Slice, ast.Tuple, ast.List, ast.Set, ast.Dict, ast.BinOp,
    ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.JoinedStr, ast.FormattedValue, ast.ListComp,
    ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.comprehension, ast.Starred, ast.operator,
    ast.unaryop, ast.boolop, ast.cmpop,
)


#: PowerShell options before ``-Command`` that change nothing about what the script may do.
_PS_QUIET_OPTIONS = frozenset({"-noprofile", "-nologo", "-noninteractive"})
#: Commands a PowerShell script may run: readers, a wait, output, and statement keywords. Not
#: ``ForEach-Object``: ``ForEach-Object Kill`` calls a method by name.
_PS_COMMANDS = frozenset({
    "get-content", "get-childitem", "get-item", "get-itemproperty", "test-path", "resolve-path",
    "select-string", "select-object", "where-object", "sort-object",
    "measure-object", "format-table", "format-list", "out-string", "get-process", "wait-process",
    "get-date", "get-location", "write-output", "write-host", "get-filehash", "split-path", "join-path",
    "try", "catch", "finally", "if", "elseif", "else", "foreach", "in", "return",
})
#: What ends a PowerShell statement or opens a nested one: the next word is a command position.
_PS_COMMAND_START = re.compile(r"(?:^|[;{}(|\n]|=)\s*([A-Za-z][\w-]*)")
_PS_VERB_NOUN = re.compile(r"\b[A-Za-z]+-[A-Za-z]+\b")
#: Redirection, the call operator, static members, method calls, backtick escapes, dot-sourcing.
_PS_REFUSED = re.compile(r"[<>&`]|::|\.\s*[A-Za-z_]\w*\s*\(|(?:^|[;{}(|\n])\s*\.")
#: Quoted strings, leftmost first: single-quoted ('' its escape) or double-quoted ("" its escape; a
#: backtick ends the match early, so the string is left in the code and refused).
_PS_QUOTED = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"`]|\"\")*\"")


def read_only_code(family: str, args: list[str]) -> bool:
    """True when the interpreter's inline code only reads or waits; False keeps the finding."""

    if family not in ("python", "powershell") or not _on_a_harness_turn():
        return False
    if family == "powershell":
        script = _powershell_command(args)
        return script is not None and _reads_only_powershell(script)
    code = _inline_code(args)
    if code is None:
        return False
    try:
        tree = ast.parse(code, mode="exec")
    except (SyntaxError, ValueError):
        return False
    return _reads_only(tree)


def _on_a_harness_turn() -> bool:
    # Lazy: tools.approval_context imports the policy module at load, and this module loads with
    # tools.approval_detection, before it.
    from agent_runtime.approval_surface_policy import surface_mode

    return surface_mode() is not None


def _powershell_command(args: list[str]) -> str | None:
    """The ``-Command`` script when only quiet options come before it and nothing after it."""

    for index, token in enumerate(args):
        option = token.lower()
        if option in ("-command", "-c"):
            return args[index + 1] if index + 2 == len(args) else None
        if option not in _PS_QUIET_OPTIONS:
            return None
    return None


def _reads_only_powershell(script: str) -> bool:
    # Single-quoted text is data in PowerShell ('' is its only escape). Double-quoted text is data
    # too unless it holds "$(...)", which runs commands, so that string is scanned as code; a
    # backtick escape stays in and is refused. Without this a -Pattern "a|Expected:" read its "|" as a
    # pipe into a command "Expected" (RT-FU-A-READ-ONLY-SELECT-STRING-STILL-ASKS-FOR-APPROVAL).
    code = _PS_QUOTED.sub(_quoted_as_data, script)
    if "'" in code.replace("''", "") or _PS_REFUSED.search(code):
        return False
    commands = {match.group(1).lower() for match in _PS_COMMAND_START.finditer(code)}
    commands |= {match.group(0).lower() for match in _PS_VERB_NOUN.finditer(code)}
    return commands <= _PS_COMMANDS


def _quoted_as_data(match: re.Match[str]) -> str:
    text = match.group(0)
    if text.startswith("'"):
        return "''"
    return text if "$(" in text else '""'


def _inline_code(args: list[str]) -> str | None:
    """The ``-c`` code when only quiet options come before it, else None."""

    index = 0
    while index < len(args):
        token = args[index]
        if token == "-c":
            return args[index + 1] if index + 1 < len(args) else None
        if token == "-X" and index + 1 < len(args):
            index += 2
            continue
        if token not in _QUIET_OPTIONS:
            return None
        index += 1
    return None


def _reads_only(tree: ast.Module) -> bool:
    # Two passes over one table each, keyed by node type: the first binds every name the code
    # imports or assigns (refusing a rebound builtin or constructor), the second checks every use
    # against what was bound. A node type with no row needs no check beyond being in _NODES.
    bound: set[str] = set(_BUILTINS)
    for node in ast.walk(tree):
        if not isinstance(node, _NODES):
            return False
        binds = _BINDS.get(type(node))
        if binds is not None and not binds(node, bound):
            return False
    for node in ast.walk(tree):
        uses = _USES.get(type(node))
        if uses is not None and not uses(node, bound):
            return False
    return True


def _binds_import(node: ast.Import, bound: set[str]) -> bool:
    if any(alias.name not in _IMPORTS for alias in node.names):
        return False
    names = {(alias.asname or alias.name).split(".")[0] for alias in node.names}
    if names & (_BUILTINS | _CONSTRUCTORS) - set(_IMPORTS):
        return False
    bound.update(names)
    return True


def _binds_import_from(node: ast.ImportFrom, bound: set[str]) -> bool:
    allowed = _IMPORTS.get(node.module or "", frozenset())
    if node.level or node.module not in _IMPORTS or any(
            alias.name == "*" or (allowed is not None and alias.name not in allowed) for alias in node.names):
        return False
    if any(alias.asname and alias.asname in _BUILTINS | _CONSTRUCTORS for alias in node.names):
        return False
    bound.update(alias.asname or alias.name for alias in node.names)
    return True


def _binds_name(node: ast.Name, bound: set[str]) -> bool:
    if not isinstance(node.ctx, ast.Store):
        return True
    if node.id in _BUILTINS or node.id in _CONSTRUCTORS:
        return False
    bound.add(node.id)
    return True


def _reads_attribute(node: ast.Attribute, bound: set[str]) -> bool:
    return isinstance(node.ctx, ast.Load)


def _uses_attribute(node: ast.Attribute, bound: set[str]) -> bool:
    return not node.attr.startswith("_")


def _uses_name(node: ast.Name, bound: set[str]) -> bool:
    return not node.id.startswith("_") and node.id in bound


def _uses_call(node: ast.Call, bound: set[str]) -> bool:
    return _reader_call(node.func, bound)


#: Pass one of :func:`_reads_only`: what a node binds, or False when it may not bind it.
_BINDS: dict[type[ast.AST], Callable[[Any, set[str]], bool]] = {
    ast.Import: _binds_import,
    ast.ImportFrom: _binds_import_from,
    ast.Name: _binds_name,
    ast.Attribute: _reads_attribute,
}
#: Pass two of :func:`_reads_only`: whether a node's use of a name, attribute or call is a read.
_USES: dict[type[ast.AST], Callable[[Any, set[str]], bool]] = {
    ast.Attribute: _uses_attribute,
    ast.Name: _uses_name,
    ast.Call: _uses_call,
}


def _reader_call(func: ast.expr, bound: set[str]) -> bool:
    if isinstance(func, ast.Name):
        return func.id in _BUILTINS or func.id in {"Path", "PurePath", "PurePosixPath", "PureWindowsPath", "Counter"} \
            and func.id in bound
    return isinstance(func, ast.Attribute) and func.attr in _METHODS
