"""RT-GENERATED-TREE-TEACH-NEW-VERBS: the teach names the Launcher's tool-shaped verbs.

Plan ``docs/agent-runtime-harness/planned/generated-tree-host-path-teach-2026-10-31.md`` §4.
``launcher.generated.patch`` / ``.write`` landed as twins of ``patch`` / ``write_file``, and
``glob`` / ``file_glob`` as arguments of ``.tree`` / ``.grep`` (not a verb of their own). A
link offering a twin is taught the twin; a link offering only ``edit`` keeps the old teach.

Killing mutation (recorded in the landing commit): the write rule asks only ``_EDIT_VERB``
(the twin map unread) -> ``test_a_write_file_is_taught_the_write_twin`` red.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from agent_runtime import launcher_app_functions as laf
from agent_runtime.generated_tree_teach import generated_tree_read_result, generated_tree_write_refusal
from tests.agent_runtime.test_launcher_app_functions import _Launcher


def _tool(name: str, *, read_only: bool) -> dict:
    return {"name": name, "method": name.replace("_", ".", 2), "description": name,
            "parameters": {"type": "object", "properties": {}}, "reach": "localOnly", "read_only": read_only}


_EDIT = _tool("launcher_generated_edit", read_only=False)
_PATCH = _tool("launcher_generated_patch", read_only=False)
_WRITE = _tool("launcher_generated_write", read_only=False)
_TREE = _tool("launcher_generated_tree", read_only=True)
_GREP = _tool("launcher_generated_grep", read_only=True)
_V4A = "*** Begin Patch\n*** Update File: /doc/components/logic/main.luau\n@@\n-a\n+b\n*** End Patch\n"
_SEARCH_MISS = json.dumps({"error": "Path not found: /doc/components"})


@pytest.fixture(autouse=True)
def _clean():
    laf._reset_for_tests()
    yield
    laf._reset_for_tests()


@contextmanager
def _linked(tools):
    link = laf.LauncherLink(_Launcher(tools), laf.ORIGIN_LOCAL)
    laf.refresh_app_function_tools(link)
    token = laf.bind_launcher_link(link)
    try:
        yield link
    finally:
        laf.reset_launcher_link(token)


def _refuse(tool, args):
    return generated_tree_write_refusal(tool, args, offered=laf.offered_to_bound_link, host_paths=True,
                                        host_has=lambda _root: False)


def _taught(args, result=_SEARCH_MISS):
    out = generated_tree_read_result(tool_name="search_files", args=args, result=result,
                                     offered=laf.offered_to_bound_link)
    return json.loads(out)["generated_tree"]


def test_a_write_file_is_taught_the_write_twin():
    with _linked([_EDIT, _PATCH, _WRITE]):
        out = _refuse("write_file", {"path": "/doc/components/logic/main.luau", "content": "x"})
    assert out["action"] == "block"
    assert "launcher_generated_write" in out["message"] and "launcher_generated_edit" not in out["message"]


def test_a_patch_is_taught_the_patch_twin_in_both_modes():
    with _linked([_EDIT, _PATCH, _WRITE]):
        v4a = _refuse("patch", {"mode": "patch", "patch": _V4A})
        replace = _refuse("patch", {"path": "/doc/components/logic/main.luau", "old_string": "a",
                                    "new_string": "b"})
    for out in (v4a, replace):
        assert "launcher_generated_patch" in out["message"] and "launcher_generated_write" not in out["message"]


def test_a_link_without_the_twins_keeps_the_edit_teach():
    """Positive control: the same calls, the twins withdrawn, name ``edit`` as before."""

    with _linked([_EDIT]):
        write = _refuse("write_file", {"path": "/doc/x.luau", "content": "x"})
        patch = _refuse("patch", {"mode": "patch", "patch": _V4A})
    assert "launcher_generated_edit" in write["message"] and "launcher_generated_edit" in patch["message"]
    with _linked([_WRITE]):
        # a twin for the OTHER tool does not stand in for this one's
        assert _refuse("patch", {"mode": "patch", "patch": _V4A}) is None


def test_a_files_search_carries_its_pattern_to_the_tree_glob():
    with _linked([_TREE, _GREP]):
        files = _taught({"pattern": "*.luau", "target": "files", "path": "/doc/components"})
        content = _taught({"pattern": "print", "path": "/doc/components", "file_glob": "*.luau"})
        bare = _taught({"pattern": "print", "path": "/doc/components"})
    assert files["use"] == "launcher_generated_tree" and "glob='*.luau'" in files["why"]
    assert content["use"] == "launcher_generated_grep" and "file_glob='*.luau'" in content["why"]
    assert "glob" not in bare["why"]
