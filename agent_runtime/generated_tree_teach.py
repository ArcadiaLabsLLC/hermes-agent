"""A generated-document path handed to a host file tool is taught, never routed.

Plan ``docs/agent-runtime-harness/planned/generated-tree-host-path-teach-2026-10-31.md``
(RT-GENERATED-TREE-TEACH-READ / -WRITE / -NEW-VERBS). The Launcher's generated-document tree is rooted
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
import os
from collections.abc import Callable
from typing import Any

__layer__ = "policy"

__all__ = [
    "GENERATED_ROOTS",
    "generated_tree_path",
    "generated_tree_read_result",
    "generated_tree_write_refusal",
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
_EDIT_VERB = "launcher_generated_edit"
#: The Launcher's tool-shaped writes (``launcher.generated.patch`` / ``.write``, plan §4
#: RT-GENERATED-TREE-TEACH-NEW-VERBS): ``patch`` and ``write_file`` each have a twin, so the
#: teach names the twin and the model keeps the argument shape it already reached for. A
#: Launcher without them is taught the by-path ``edit`` as before.
_PATCH_VERB = "launcher_generated_patch"
_WRITE_VERB = "launcher_generated_write"
_WRITE_TWINS = {"write_file": _WRITE_VERB, "patch": _PATCH_VERB}

Offered = Callable[[str], bool]
HostHas = Callable[[str], bool]


def generated_tree_path(path: Any) -> str | None:
    """The path's tree root (``doc`` / ``runtime`` / ``ref``) when it is shaped like a
    generated-tree path as given, else None. ``doc/x``, ``./doc/x``, ``C:\\doc\\x``,
    ``/Doc/x`` and ``//doc`` never match."""

    if not isinstance(path, str) or not path.startswith("/"):
        return None
    first = path[1:].split("/", 1)[0]
    return first if first in GENERATED_ROOTS else None


def _why(path: str, verb: str, filter_hint: str = "") -> str:
    return (f"{path} is a generated document's tree path, not a host file; call {verb}{filter_hint} "
            f"with the document_id from {_INSPECT_VERB} (a /ref path needs none).")


def _filter_hint(tool_name: Any, args: dict) -> str:
    """A ``search_files`` name filter, carried to the verb that takes it: ``target='files'``'s
    ``pattern`` is the tree's ``glob``, a content search's ``file_glob`` is grep's
    (``launcher.generated.tree`` / ``.grep``; glob is an argument there, not a verb)."""

    if tool_name != "search_files":
        return ""
    if (args.get("target") or "content") == "files":
        name, value = "glob", args.get("pattern")
    else:
        name, value = "file_glob", args.get("file_glob")
    return f" with {name}={value!r}" if isinstance(value, str) and value.strip() else ""


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
    hint = _filter_hint(tool_name, args if isinstance(args, dict) else {})
    payload["generated_tree"] = {"path": path, "use": verb, "why": _why(path, verb, hint)}
    return json.dumps(payload, ensure_ascii=False)


def host_has_root(segment: str) -> bool:
    """Does this host have a top-level ``/<segment>`` directory? (The write rule's probe.)"""

    return os.path.isdir("/" + segment)


def _write_paths(tool_name: Any, args: dict) -> list[Any]:
    """Every path a ``write_file`` / ``patch`` call names: ``path``, or each V4A header's
    (a Move's both ends). A V4A body that does not parse names none; upstream refuses it."""

    if tool_name == "write_file":
        return [args.get("path")]
    if (args.get("mode") or "replace") != "patch":
        return [args.get("path")]
    from tools.patch_parser import parse_v4a_patch

    operations, error = parse_v4a_patch(str(args.get("patch") or ""))
    if error:
        return []
    return [p for op in operations for p in (op.file_path, op.new_path) if p]


def generated_tree_write_refusal(tool_name: Any, args: Any, *, offered: Offered, host_paths: bool,
                                 host_has: HostHas = host_has_root) -> dict | None:
    """``pre_tool_call``: a ``write_file`` / ``patch`` naming a generated-tree path, on a host
    with no such top-level directory, is blocked naming the Launcher's twin verb
    (``launcher_generated_write`` / ``_patch``), or its by-path edit verb when the bound link
    offers no twin; else None.

    ``host_paths`` is whether the file tools write the host filesystem (a sandbox backend
    keeps upstream's behaviour, plan §1 Q1 clause 2).
    """

    if tool_name not in ("write_file", "patch") or not host_paths:
        return None
    paths = _write_paths(tool_name, args if isinstance(args, dict) else {})
    hit = next((p for p in paths if (root := generated_tree_path(p.strip() if isinstance(p, str) else p))
                and not host_has(root)), None)
    if hit is None:
        return None
    lead = (f"{hit} is a generated-document path; {tool_name} writes the host filesystem, so nothing "
            "was written.")
    twin = _WRITE_TWINS[tool_name]
    if offered(twin):
        shape = ("path and content" if twin == _WRITE_VERB
                 else "path, old_string and new_string, or patch as a V4A patch")
        return {"action": "block", "message": (
            f"{lead} Use {twin} instead, with the same {shape}, plus the document_id and read_version "
            f"from {_INSPECT_VERB}.")}
    if not offered(_EDIT_VERB):
        return None
    return {"action": "block", "message": (
        f"{lead} Edit the document with {_EDIT_VERB} (its by-path replace / write operations), with "
        f"the document_id from {_INSPECT_VERB}.")}
