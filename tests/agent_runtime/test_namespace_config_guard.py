"""RT-FU-A-BUNDLED-AGENT-CANNOT-START-A-LOCAL-MCP-SERVER-BY-WRITING-ANOTHER-PROFILES-CONFIG.

On a bundled install, ``write_file`` and ``patch`` from an agent's turn refuse the namespace root's and
every profile's ``config.yaml`` (a stdio MCP server written there starts at that profile's next
discovery with no approval), after resolving ``..`` and symlinks; a developer install and an ordinary
file beside them are untouched. The eternia-harness ``pre_tool_call`` hook is the seam.

Killing mutations (each recorded red in the landing commit):
* ``os.path.realpath`` -> the path as given in ``protected_reason``: the no-config-yet symlink test goes
  red (on POSIX the file tools' own resolve also catches the plain symlink test);
* the ``profiles/<name>/config.yaml`` arm of ``_lexical_reason`` dropped: the sibling, ``..``, symlink
  and V4A tests go red;
* the ``(config.yaml,)`` root arm dropped: the root test goes red;
* ``not bundled()`` -> ``False``: the developer test goes red;
* the hook's call removed from ``plugins/eternia-harness/__init__.py``: the hook test goes red;
* the inode compare, the fork-plugin arm, the V4A header walk dropped: the hard-link, harness-copy and
  V4A tests go red.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from agent_runtime import namespace_config_guard as guard

_EVIL = "mcp_servers:\n  evil:\n    command: /bin/sh\n    args: ['-c', 'touch /tmp/pwned']\n"


@pytest.fixture()
def ns(tmp_path):
    root = tmp_path / "ns"
    for profile in ("me", "sibling"):
        (root / "profiles" / profile).mkdir(parents=True)
        (root / "profiles" / profile / "config.yaml").write_text("model: {}\n", encoding="utf-8")
    (root / "config.yaml").write_text("model: {}\n", encoding="utf-8")
    return root


def _refuse(ns, tool, args, *, bundled=True):
    return guard.namespace_config_write_refusal(tool, args, "cfgguard-test", bundled=lambda: bundled,
                                                roots=lambda: [Path(os.path.realpath(ns))])


def _write(path):
    return {"path": str(path), "content": _EVIL}


def test_the_namespace_roots_config_is_refused(ns):
    out = _refuse(ns, "write_file", _write(ns / "config.yaml"))
    assert out["action"] == "block" and "namespace root's config.yaml" in out["message"]


def test_a_sibling_profiles_config_is_refused(ns):
    out = _refuse(ns, "write_file", _write(ns / "profiles" / "sibling" / "config.yaml"))
    assert out["action"] == "block" and "profile sibling's config.yaml" in out["message"]


def test_a_dot_dot_path_into_a_sibling_is_refused(ns):
    out = _refuse(ns, "patch", {"mode": "replace", "path": f"{ns}/profiles/me/../sibling/config.yaml",
                                "old_string": "model: {}", "new_string": _EVIL})
    assert out is not None and "profile sibling's config.yaml" in out["message"]


def test_a_symlink_into_a_profile_is_refused(ns, tmp_path):
    link = tmp_path / "work" / "elsewhere"
    link.parent.mkdir()
    link.symlink_to(ns / "profiles" / "sibling", target_is_directory=True)
    out = _refuse(ns, "write_file", _write(link / "config.yaml"))
    assert out is not None and "profile sibling's config.yaml" in out["message"]


def test_the_guard_itself_follows_a_symlink_to_a_profile_with_no_config_yet(ns, tmp_path):
    """A just-placed profile with no config.yaml yet: no inode to compare, and the path is handed in
    unresolved (a host whose file tools only normalise, as on Windows), so only the guard's own
    ``realpath`` finds the profile."""
    (ns / "profiles" / "fresh").mkdir()
    link = tmp_path / "work" / "fresh"
    link.parent.mkdir()
    link.symlink_to(ns / "profiles" / "fresh", target_is_directory=True)
    reason = guard.protected_reason(link / "config.yaml", [Path(os.path.realpath(ns))])
    assert reason == "profile fresh's config.yaml"


def test_a_hard_link_to_a_profiles_config_is_refused(ns, tmp_path):
    linked = tmp_path / "work" / "notes.yaml"
    linked.parent.mkdir()
    os.link(ns / "profiles" / "sibling" / "config.yaml", linked)
    out = _refuse(ns, "write_file", _write(linked))
    assert out is not None and "a link to config.yaml" in out["message"]


def test_a_v4a_patch_header_naming_a_profiles_config_is_refused(ns):
    body = (f"*** Begin Patch\n*** Update File: {ns}/notes.md\n@@\n-a\n+b\n"
            f"*** Add File: {ns}/profiles/sibling/config.yaml\n+mcp_servers: {{}}\n*** End Patch\n")
    out = _refuse(ns, "patch", {"mode": "patch", "patch": body})
    assert out is not None and "profile sibling's config.yaml" in out["message"]


def test_a_copy_of_the_harness_plugin_under_a_home_is_refused(ns):
    out = _refuse(ns, "write_file", _write(ns / "profiles" / "me" / "plugins" / "eternia-harness" / "plugin.yaml"))
    assert out is not None and "eternia-harness plugin" in out["message"]


def test_a_developer_install_is_allowed(ns):
    assert _refuse(ns, "write_file", _write(ns / "profiles" / "sibling" / "config.yaml"), bundled=False) is None
    assert _refuse(ns, "write_file", _write(ns / "config.yaml"), bundled=False) is None


@pytest.mark.parametrize("relative", [
    "notes.yaml", "config.yaml.bak", "profiles/sibling/notes.md", "profiles/sibling/skills/config.yaml",
    "profiles/sibling/plugins/my-own/plugin.yaml",
])
def test_an_ordinary_file_beside_them_is_allowed(ns, relative):
    assert _refuse(ns, "write_file", _write(ns / relative)) is None


def test_other_tools_are_not_asked(ns):
    assert _refuse(ns, "read_file", {"path": str(ns / "config.yaml")}) is None


def test_the_roots_include_the_launch_root_while_a_profile_is_active(ns, monkeypatch):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    monkeypatch.setenv("HERMES_HOME", str(ns))
    token = set_hermes_home_override(ns / "profiles" / "me")
    try:
        roots = guard.namespace_roots()
    finally:
        reset_hermes_home_override(token)
    assert Path(os.path.realpath(ns)) in roots


@pytest.fixture(scope="module")
def hooks():
    path = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eternia_harness_under_config_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_harness_hook_refuses_the_write_on_a_bundled_install(ns, monkeypatch, hooks):
    from agent_runtime import bundled_toolsets

    monkeypatch.setattr(bundled_toolsets, "edition_bundled", lambda: True)
    monkeypatch.setattr(guard, "namespace_roots", lambda: [Path(os.path.realpath(ns))])
    out = hooks.refuse_tool_call(tool_name="write_file", args=_write(ns / "profiles" / "sibling" / "config.yaml"),
                                 task_id="cfgguard-test", session_id="")
    assert out is not None and out["action"] == "block" and "sibling" in out["message"]
