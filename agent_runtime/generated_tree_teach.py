"""A generated-document path handed to a host file tool is taught, never routed.

Plan ``docs/agent-runtime-harness/planned/generated-tree-host-path-teach-2026-10-31.md``
(RT-GENERATED-TREE-TEACH-READ / -WRITE). The Launcher's generated-document tree is rooted
at ``/doc``, ``/runtime`` and ``/ref``; a model that hands one of those paths to
``read_file`` / ``search_files`` gets a HOST miss it then reasons about, and one that hands
it to ``write_file`` / ``patch`` can CREATE it (``C:\\doc\\x`` on Windows).

A call is a generated-tree call only when all three hold (plan §1 Q1):

1. **Shape** — the path AS GIVEN is POSIX-absolute with a first segment of exactly
   ``doc`` / ``runtime`` / ``ref``; for a V4A ``patch`` every header path is tested.
2. **The host does not have it** — a read is taught only when the host's own answer was
   the miss (``File not found:`` / ``Path not found:``); a write is refused only when the
   host has no top-level ``/<segment>`` and the file tools target the host filesystem.
3. **The verb is offered** — the turn's bound Launcher link lists the verb the teach names
   (``launcher_app_functions.offered_to_bound_link``, handed in by the plugin). No link:
   upstream's bytes.

The hook never calls a Launcher verb itself. The offered check, the host probe and the
backend test are parameters the plugin binds, so the policy is a pure function under test.

The verb names below are the one place hermes spells Launcher tool names for this teach;
``tests/tooling/test_no_launcher_tool_name_literals.py`` allows exactly these tokens in this
file, and the clause-3 check means a renamed or withdrawn verb disables the teach rather
than naming a tool the turn does not have.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

__layer__ = "policy"

__all__ = [
    "GENERATED_ROOTS",
    "generated_tree_path",
    "generated_tree_read_result",
]

#: The generated-document tree's top-level segments (case-exact).
GENERATED_ROOTS = ("doc", "runtime", "ref")

#: The host's miss prefixes, as ``tools/file_tools.py`` spells them.
_READ_MISS = "File not found:"
_SEARCH_MISS = "Path not found:"

_READ_VERB = "launcher_generated_read"
_GREP_VERB = "launcher_generated_grep"
_TREE_VERB = "launcher_generated_tree"
_INSPECT_VERB = "launcher_generated_inspect"

Offered = Callable[[str], bool]


def generated_tree_path(path: Any) -> str | None:
    """The path's tree root (``doc`` / ``runtime`` / ``ref``) when it is shaped like a
    generated-tree path as given, else None. ``doc/x``, ``./doc/x``, ``C:\\doc\\x``,
    ``/Doc/x`` and ``//doc`` never match."""

    if not isinstance(path, str) or not path.startswith("/"):
        return None
    first = path[1:].split("/", 1)[0]
    return first if first in GENERATED_ROOTS else None


def _why(path: str, verb: str) -> str:
    return (f"{path} is a generated document's tree path, not a host file; call {verb} with the "
            f"document_id from {_INSPECT_VERB} (a /ref path needs none).")


def _read_verb(tool_name: Any, args: dict) -> tuple[str, str] | None:
    """(the path argument, the verb to name) for a read-shaped call, else None."""

    if tool_name == "read_file":
        return args.get("path"), _READ_VERB
    if tool_name == "search_files":
        target = args.get("target") or "content"
        return args.get("path"), (_TREE_VERB if target == "files" else _GREP_VERB)
    return None


def generated_tree_read_result(tool_name: Any = None, args: Any = None, result: Any = None, *,
                               offered: Offered, **_kwargs: Any) -> str | None:
    """``transform_tool_result``: a host MISS on a generated-tree path, plus ``generated_tree``.

    None (upstream's bytes stand) for any other tool, a host hit, a relative path, a result
    that is not the miss, or a verb the bound link does not offer.
    """

    picked = _read_verb(tool_name, args if isinstance(args, dict) else {})
    if picked is None or not isinstance(result, str):
        return None
    path, verb = picked
    if generated_tree_path(path) is None:
        return None
    try:
        payload = json.loads(result)
    except ValueError:
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    miss = _READ_MISS if tool_name == "read_file" else _SEARCH_MISS
    if not (isinstance(error, str) and error.startswith(miss)) or "generated_tree" in payload:
        return None
    if not offered(verb):
        return None
    payload["generated_tree"] = {"path": path, "use": verb, "why": _why(path, verb)}
    return json.dumps(payload, ensure_ascii=False)
