"""RT-GENERATED-TREE-TEACH-WRITE: a host write to a generated-document path is blocked.

Plan ``docs/agent-runtime-harness/planned/generated-tree-host-path-teach-2026-10-31.md`` §1-§2.
``write_file`` / ``patch`` (V4A header paths included) naming a ``/doc`` · ``/runtime`` · ``/ref``
path, on a host with no such top-level directory and a link offering the edit verb, is a
``pre_tool_call`` block naming that verb, so nothing lands at ``C:\\doc`` or ``/doc``.

Killing mutation (recorded in the landing commit): drop the V4A header walk (a ``patch`` in
``patch`` mode reads only ``path``) -> ``test_a_v4a_patch_naming_a_tree_path_is_blocked`` red.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import pytest

from agent_runtime import launcher_app_functions as laf
from agent_runtime.generated_tree_teach import generated_tree_write_refusal
from tests.agent_runtime.test_launcher_app_functions import _Launcher

_EDIT = [{"name": "launcher_generated_edit", "method": "launcher.generated.edit", "description": "edit",
          "parameters": {"type": "object", "properties": {}}, "reach": "localOnly", "read_only": False}]
_V4A = ("*** Begin Patch\n*** Update File: src/ok.py\n@@\n-a\n+b\n"
        "*** Add File: /ref/format.md\n+hello\n*** End Patch\n")


@pytest.fixture(autouse=True)
def _clean():
    laf._reset_for_tests()
    yield
    laf._reset_for_tests()


@contextmanager
def _linked(tools=_EDIT):
    link = laf.LauncherLink(_Launcher(tools), laf.ORIGIN_LOCAL)
    laf.refresh_app_function_tools(link)
    token = laf.bind_launcher_link(link)
    try:
        yield link
    finally:
        laf.reset_launcher_link(token)


def _refuse(tool, args, *, host_has=lambda _root: False, host_paths=True):
    return generated_tree_write_refusal(tool, args, offered=laf.offered_to_bound_link, host_paths=host_paths,
                                        host_has=host_has)


def test_a_write_file_naming_a_tree_path_is_blocked():
    with _linked():
        out = _refuse("write_file", {"path": "/ref/format.md", "content": "x"})
    assert out["action"] == "block"
    assert "launcher_generated_edit" in out["message"] and "/ref/format.md" in out["message"]


def test_a_v4a_patch_naming_a_tree_path_is_blocked():
    with _linked():
        out = _refuse("patch", {"mode": "patch", "patch": _V4A})
        assert _refuse("patch", {"mode": "replace", "path": "/doc/components/x/main.luau",
                                 "old_string": "a", "new_string": "b"})["action"] == "block"
    assert out["action"] == "block" and "/ref/format.md" in out["message"]


def test_a_host_with_the_directory_writes_as_upstream_does():
    with _linked():
        # positive control: the same call is blocked when the host lacks /ref
        assert _refuse("write_file", {"path": "/ref/format.md"}) is not None
        assert _refuse("write_file", {"path": "/ref/format.md"}, host_has=lambda root: root == "ref") is None
        assert _refuse("patch", {"mode": "patch", "patch": _V4A}, host_has=lambda root: True) is None


def test_no_link_a_sandbox_or_a_relative_path_keeps_upstream():
    assert _refuse("write_file", {"path": "/doc/x"}) is None
    with _linked():
        assert _refuse("write_file", {"path": "/doc/x"}, host_paths=False) is None
        assert _refuse("write_file", {"path": "doc/x"}) is None
        assert _refuse("read_file", {"path": "/doc/x"}) is None
    with _linked([]):
        assert _refuse("write_file", {"path": "/doc/x"}) is None


@pytest.mark.skipif(os.path.isdir("/ref"), reason="this host has a real /ref, which the rule writes through")
def test_the_plugin_blocks_on_the_pre_tool_call_dispatch(monkeypatch):
    """End to end: upstream's ``pre_tool_call`` dispatcher -> the plugin's one callback."""
    from hermes_cli import plugins
    from tests.agent_runtime.test_codex_stream_receipt import _plugin_hooks

    _plugin, hooks = _plugin_hooks()
    monkeypatch.setattr(plugins, "invoke_hook", lambda name, **kw: [cb(**kw) for cb in hooks.get(name, ())])
    monkeypatch.delenv("TERMINAL_ENV", raising=False)
    with _linked():
        message, _args = plugins._dispatch_pre_tool_call_hooks("write_file", {"path": "/ref/format.md", "content": "x"})
    assert message and "launcher_generated_edit" in message
    unlinked, _args = plugins._dispatch_pre_tool_call_hooks("write_file", {"path": "/ref/format.md", "content": "x"})
    assert not unlinked
