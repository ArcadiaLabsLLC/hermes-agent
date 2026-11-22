"""A phone agent reads, searches and edits files in the phone's project folders (Eternia row
``MC-PHONE-FILES-A-PHONE-AGENT-READS-AND-WRITES-ITS-PROJECT-FILES``, plan
``PHONE_PROJECT_FOLDERS_FILE_TREE_2026-11-21.md`` §9 as corrected by review w1118a.79).

The phone wheel ships no upstream file tools (they run on the terminal backend); the fork's
process-free ones take their names (``read_file``, ``write_file``, ``patch``, ``search_files``) over the
slots bound on the device, read through ``project_files.reader`` and written through
``project_files.writer``'s one checked path. Killing mutations are named per test and in the code.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_runtime import phone_file_tools as tools
from agent_runtime.machine_roots import machine_roots_cache_clear
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_slots import bind, declare

T0 = "2026-11-21T12:00:00+00:00"


def _call(tool, **args) -> dict:
    return json.loads(tool(args))


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    """A phone project folder ``notes`` bound on this device, holding two files."""

    machine_roots_cache_clear()
    root = tmp_path / "repos" / "local" / "notes"
    (root / "docs").mkdir(parents=True)
    (root / "TODO.md").write_text("# Notes\n- buy milk\n- call mum\n", encoding="utf-8")
    (root / "docs" / "plan.md").write_text("the plan: buy milk first\n", encoding="utf-8")
    workspace = WorkspaceStore().create(name="Phone").id
    declare(workspace, [{"name": "notes", "repo": {"clone_url": None, "local": True}}], issued_at=T0, machine="m")
    bind(workspace, "notes", str(root), issued_at=T0)
    monkeypatch.delenv("TERMINAL_CWD", raising=False)
    return root


def test_the_agent_reads_a_project_file_as_numbered_lines(project):
    got = _call(tools.read_file, path="notes/TODO.md")
    assert got["path"] == "notes/TODO.md" and got["total_lines"] == 3
    assert got["content"] == "1|# Notes\n2|- buy milk\n3|- call mum"
    window = _call(tools.read_file, path=str(project / "TODO.md"), offset=2, limit=1)
    assert window["content"] == "2|- buy milk" and window["next_offset"] == 3


def test_a_relative_path_is_read_from_the_turns_project_folder(project, monkeypatch):
    monkeypatch.setenv("TERMINAL_CWD", str(project / "docs"))
    assert _call(tools.read_file, path="plan.md")["path"] == "notes/docs/plan.md"


def test_the_agent_searches_every_project_folder(project):
    found = _call(tools.search_files, pattern="buy milk")
    assert [m["path"] for m in found["matches"]] == ["notes/TODO.md", "notes/docs/plan.md"]


def test_the_agent_writes_and_patches_and_the_person_reads_the_same_file(project):
    """Killing mutation: write the temp file and never ``os.replace`` it -> the read below is the old text."""

    made = _call(tools.write_file, path="notes/ideas/first.md", content="one idea\n")
    assert made == {"path": "notes/ideas/first.md", "size": 9, "created": True}
    patched = _call(tools.patch, path="notes/TODO.md", old_string="call mum", new_string="call dad")
    assert patched["replacements"] == 1
    assert (project / "TODO.md").read_text(encoding="utf-8") == "# Notes\n- buy milk\n- call dad\n"
    # The person's view reads the same folder through the same reader (Eternia's follows the same spec).
    from agent_runtime.project_files.reader import read

    assert read(str(project), "ideas/first.md")["content"] == "one idea\n"
    assert not any(name.endswith(".tmp") for name in os.listdir(project / "ideas"))


def test_a_patch_must_name_text_found_once(project):
    twice = _call(tools.patch, path="notes/TODO.md", old_string="- ", new_string="* ")
    assert twice["code"] == "bad_argument" and "2 times" in twice["error"]
    every = _call(tools.patch, path="notes/TODO.md", old_string="- ", new_string="* ", replace_all=True)
    assert every["replacements"] == 2


def test_nothing_outside_a_project_folder_is_read_or_written(project, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("private\n", encoding="utf-8")
    for tool, args in ((tools.read_file, {"path": str(outside)}),
                       (tools.write_file, {"path": str(outside), "content": "x"}),
                       (tools.read_file, {"path": "../outside.txt"}),
                       (tools.write_file, {"path": "notes/../../outside.txt", "content": "x"}),
                       (tools.write_file, {"path": "notes/.git/config", "content": "x"})):
        refused = _call(tool, **args)
        assert refused.get("code") in {"outside_root", "invalid_path", "ignored"}, (args, refused)
    assert outside.read_text(encoding="utf-8") == "private\n"


def test_a_write_through_a_symlinked_folder_out_of_the_root_is_refused(project, tmp_path):
    """Killing mutation: skip the deepest-folder check in ``writer._target`` -> the file lands outside, red."""

    away = tmp_path / "away"
    away.mkdir()
    (project / "linked").symlink_to(away, target_is_directory=True)
    refused = _call(tools.write_file, path="notes/linked/new.md", content="x")
    assert refused["code"] == "outside_root" and not (away / "new.md").exists()


def test_a_write_to_a_profile_config_is_refused_by_the_guard(project):
    """A hard link inside the project to the namespace's ``config.yaml`` stays inside the root, so only
    the agent's write guard stops it. Killing mutation: drop ``protected_reason`` from ``writer._guard``."""

    from hermes_constants import get_hermes_home

    config = Path(get_hermes_home()) / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("model: {}\n", encoding="utf-8")
    os.link(config, project / "settings.yaml")
    refused = _call(tools.write_file, path="notes/settings.yaml", content="mcp_servers: {evil: {}}\n")
    assert refused["code"] == "write_denied", refused
    assert config.read_text(encoding="utf-8") == "model: {}\n"


def test_a_phone_registers_the_four_tools_under_upstreams_names(monkeypatch):
    monkeypatch.setattr(tools, "upstream_file_tools_shipped", lambda: False)
    seen = []
    names = tools.register_phone_file_tools(lambda name, **kw: seen.append((name, kw["toolset"])))
    assert names == ["read_file", "write_file", "patch", "search_files"]
    assert {toolset for _, toolset in seen} == {"file"}
    from toolsets import resolve_toolset

    assert set(resolve_toolset("file")) == set(names)


def test_a_desktop_keeps_upstreams_file_tools():
    """Killing mutation: register them where upstream's ship -> they shadow upstream's, red."""

    assert tools.upstream_file_tools_shipped()
    assert tools.register_phone_file_tools(lambda *a, **k: pytest.fail("registered on a desktop")) == []


def test_the_phone_profile_turns_the_file_toolset_on_and_still_ships_no_upstream_file_tool():
    from agent_runtime.bundle_profiles.manifest import load_profile

    phone = load_profile("bundled-phone", validate=False)
    assert "file" not in phone.disabled_toolsets
    excluded = Path("agent_runtime/bundle_profiles/bundled-phone.yaml").read_text(encoding="utf-8")
    for module in ("tools.file_tools", "tools.file_operations", "tools.terminal_tool"):
        assert f"- {module}\n" in excluded or f"- {module} " in excluded, module


def test_a_miss_reads_as_upstreams_so_the_generated_tree_teach_applies(project):
    """A ``/doc`` path is a generated document's, never a project file's: the phone's miss carries
    upstream's wording, which ``generated_tree_teach`` keys on to name the app-function verb."""

    from agent_runtime.generated_tree_teach import _READ_MISS, _SEARCH_MISS

    assert _call(tools.read_file, path="/doc/intro.md")["error"].startswith(_READ_MISS)
    assert _call(tools.search_files, pattern="x", path="/doc")["error"].startswith(_SEARCH_MISS)
