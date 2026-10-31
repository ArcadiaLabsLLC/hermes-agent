"""RT-GENERATED-TREE-TEACH-READ: a host miss on a generated-document path names the tree verb.

Plan ``docs/agent-runtime-harness/planned/generated-tree-host-path-teach-2026-10-31.md`` §1-§2.
A ``read_file`` / ``search_files`` HOST MISS on a ``/doc`` · ``/runtime`` · ``/ref`` path, in a
turn whose bound Launcher link offers the verb, carries ``generated_tree: {path, use, why}``;
a host hit, no link, or a relative path keep upstream's bytes.

Killing mutation (recorded in the landing commit): drop clause 2 (teach on any shape match,
hit or miss) -> ``test_a_host_hit_keeps_upstream_bytes`` red.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager

import pytest

from agent_runtime import launcher_app_functions as laf
from agent_runtime.generated_tree_teach import generated_tree_path
from agent_runtime.generated_tree_teach import generated_tree_read_result as _teach
from tests.agent_runtime.test_launcher_app_functions import _Launcher

_TREE_TOOLS = [
    {"name": name, "method": name.replace("_", ".", 2), "description": name,
     "parameters": {"type": "object", "properties": {}}, "reach": "localOnly", "read_only": True}
    for name in ("launcher_generated_read", "launcher_generated_grep", "launcher_generated_tree")
]
_MISS = json.dumps({"error": "File not found: /doc/components/logic/main.luau"})
_PATH = "/doc/components/logic/main.luau"


@pytest.fixture(autouse=True)
def _clean():
    laf._reset_for_tests()
    yield
    laf._reset_for_tests()


@contextmanager
def _linked(tools=_TREE_TOOLS):
    link = laf.LauncherLink(_Launcher(tools), laf.ORIGIN_LOCAL)
    laf.refresh_app_function_tools(link)
    token = laf.bind_launcher_link(link)
    try:
        yield link
    finally:
        laf.reset_launcher_link(token)


def _read_result(**kwargs):
    """The policy bound as the plugin binds it: the real bound-link check."""
    return _teach(**kwargs, offered=laf.offered_to_bound_link)


def test_the_shape_is_rooted_and_case_exact():
    assert [generated_tree_path(p) for p in ("/doc", "/doc/x", "/runtime/a", "/ref/format.md")] == [
        "doc", "doc", "runtime", "ref"]
    assert {generated_tree_path(p) for p in ("doc/x", "./doc/x", "C:\\doc\\x", "/Doc/x", "//doc", "/docs/x", 3)} == {None}


def test_a_read_miss_names_the_read_verb():
    with _linked():
        out = json.loads(_read_result(tool_name="read_file", args={"path": _PATH}, result=_MISS))
    assert out["error"].startswith("File not found:")
    assert out["generated_tree"]["use"] == "launcher_generated_read"
    assert out["generated_tree"]["path"] == _PATH and _PATH in out["generated_tree"]["why"]


def test_a_host_hit_keeps_upstream_bytes():
    hit = json.dumps({"content": "1|print('real /doc')", "total_lines": 1})
    with _linked():
        assert _read_result(tool_name="read_file", args={"path": _PATH}, result=hit) is None
        # positive control: the same call, the host's answer a miss
        assert _read_result(tool_name="read_file", args={"path": _PATH}, result=_MISS) is not None


def test_no_link_or_an_unoffered_verb_keeps_upstream_bytes():
    assert _read_result(tool_name="read_file", args={"path": _PATH}, result=_MISS) is None
    with _linked(_TREE_TOOLS[1:]):
        assert _read_result(tool_name="read_file", args={"path": _PATH}, result=_MISS) is None


def test_a_relative_path_keeps_upstream_bytes():
    with _linked():
        assert _read_result(tool_name="read_file", args={"path": "doc/x"}, result=_MISS) is None


def test_search_names_grep_for_content_and_tree_for_files():
    miss = json.dumps({"error": "Path not found: /ref/schemas"})
    with _linked():
        grep = _read_result(tool_name="search_files", args={"pattern": "x", "path": "/ref/schemas"},
                                          result=miss)
        tree = _read_result(tool_name="search_files",
                                          args={"pattern": "*.json", "target": "files", "path": "/ref/schemas"},
                                          result=miss)
        # a read miss's prefix is not a search miss
        assert _read_result(tool_name="search_files", args={"path": "/ref/x"}, result=_MISS) is None
    assert json.loads(grep)["generated_tree"]["use"] == "launcher_generated_grep"
    assert json.loads(tree)["generated_tree"]["use"] == "launcher_generated_tree"


def test_the_plugin_hook_teaches_on_the_model_dispatch_path(monkeypatch):
    """End to end: the real ``read_file`` misses on the host, and the plugin's registered
    ``transform_tool_result`` callback sees the bound link inside ``handle_function_call``."""
    import model_tools
    from tests.agent_runtime.test_codex_stream_receipt import _plugin_hooks

    _plugin, hooks = _plugin_hooks()
    monkeypatch.setattr("hermes_cli.plugins.has_hook", lambda name: name in hooks)
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook",
                        lambda name, **kw: [cb(**kw) for cb in hooks.get(name, ())])
    path = f"/doc/{uuid.uuid4().hex}/main.luau"  # a miss even on a host with a real /doc

    def _read(task):
        return json.loads(model_tools.handle_function_call(
            "read_file", {"path": path}, task_id=task, session_id="s-teach", tool_call_id="tc1",
            skip_pre_tool_call_hook=True))

    assert "generated_tree" not in _read("t-unlinked")
    with _linked():
        taught = _read("t-linked")
    assert taught["generated_tree"]["use"] == "launcher_generated_read", taught
