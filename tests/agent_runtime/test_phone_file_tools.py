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
    (root / "TODO.md").write_text("# Notes\n- buy milk\n- call mum\n", encoding="utf-8", newline="")  # LF bytes: write_text writes CRLF on Windows
    (root / "docs" / "plan.md").write_text("the plan: buy milk first\n", encoding="utf-8", newline="")
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
    """Killing mutation: skip the deepest-folder check in ``writer._write_target`` -> the file lands outside, red."""

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


def test_the_phones_installed_profile_registers_them_though_upstreams_is_findable(monkeypatch):
    """RT-FU-THE-PHONE-GATE-JUDGES-THE-CODE-BEHIND-A-PHONE-AGENTS-FILE-TOOLS: the phone ships
    ``tools.file_tools`` pinned in its forced tree, so it is findable there; the installed profile, which
    switches it off, decides. Killing mutation: drop the ``installed_switched_off`` check from
    ``upstream_file_tools_shipped`` -> the presence probe answers True and nothing registers, red."""

    import importlib.util
    import sys

    from agent_runtime import installed_profile

    monkeypatch.setattr(installed_profile, "PHONE_PLATFORMS", frozenset({*installed_profile.PHONE_PLATFORMS, sys.platform}))
    assert importlib.util.find_spec("tools.file_tools") is not None  # findable, as in phone_forced/
    assert installed_profile.installed_switched_off("tools.file_tools")
    seen = []
    assert tools.register_phone_file_tools(lambda name, **kw: seen.append(name)) == [
        "read_file", "write_file", "patch", "search_files"]
    assert seen == ["read_file", "write_file", "patch", "search_files"]


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


# ---- Row RT-PHONE-FILE-TOOLS-ACCEPT-EVERY-DESKTOP-ARGUMENT: the desktop's arguments on a phone ----


def _parameters_only(value):
    """``value`` without its descriptions: what a model may pass, never how it is told."""

    if isinstance(value, dict):
        return {key: _parameters_only(item) for key, item in value.items() if key != "description"}
    if isinstance(value, list):
        return [_parameters_only(item) for item in value]
    return value


def _same_parameters(phone: dict, upstream: dict) -> None:
    assert _parameters_only(phone) == _parameters_only(upstream)
    assert list(phone["parameters"]["properties"]) == list(upstream["parameters"]["properties"])


def test_the_phone_schemas_equal_upstreams_parameters():
    """Names, types, enums, defaults, minimum, maximum and required equal ``tools/file_tools.py``'s.

    Killing mutation: ``READ_LIMIT = 500`` (the old phone default) -> read_file's limit differs, red."""

    from tools import file_tools as upstream

    pairs = ((tools.READ_FILE_SCHEMA, upstream.READ_FILE_SCHEMA), (tools.WRITE_FILE_SCHEMA, upstream.WRITE_FILE_SCHEMA),
             (tools.PATCH_SCHEMA, upstream.PATCH_SCHEMA), (tools.SEARCH_FILES_SCHEMA, upstream.SEARCH_FILES_SCHEMA))
    for phone, desktop in pairs:
        _same_parameters(phone, desktop)
    assert [schema["name"] for _, _, schema in tools.PHONE_FILE_TOOLS] == [d["name"] for _, d in pairs]


@pytest.mark.parametrize("provider, model", [
    ("openai", "anything"), ("openrouter", "openai/gpt-5"), ("nous", "gpt-4.1"), ("openrouter", "o3-mini"),
    ("anthropic", "claude-opus"), ("openrouter", "anthropic/claude"), ("", ""), ("codex", "x"),
])
def test_the_v4a_layer_follows_upstreams_rule(monkeypatch, provider, model):
    """The override's output equals ``_patch_schema_overrides``' for each main model, parameters only.

    Killing mutation: drop ``"o3"`` from the fork's slug prefixes -> openrouter o3-mini gets no layer, red."""

    import agent.auxiliary_client as auxiliary
    from tools import file_tools as upstream

    monkeypatch.setattr(auxiliary, "_read_main_provider", lambda: provider)
    monkeypatch.setattr(auxiliary, "_read_main_model", lambda: model)
    phone, desktop = tools.patch_schema_overrides(), upstream._patch_schema_overrides()
    assert bool(phone) == bool(desktop)
    if desktop:
        _same_parameters(phone, desktop)


def test_a_registered_phone_patch_advertises_v4a_by_upstreams_rule(monkeypatch):
    """Killing mutation: skip ``_layer_v4a_on_patch`` -> the OpenAI-family schema has no ``mode``, red."""

    import agent.auxiliary_client as auxiliary
    import tools.registry as registry_module

    fresh = registry_module.ToolRegistry()
    monkeypatch.setattr(registry_module, "registry", fresh)
    monkeypatch.setattr(tools, "upstream_file_tools_shipped", lambda: False)
    tools.register_phone_file_tools(lambda name, **kw: fresh.register(name, **kw))
    monkeypatch.setattr(auxiliary, "_read_main_provider", lambda: "openai")
    monkeypatch.setattr(auxiliary, "_read_main_model", lambda: "gpt-5")
    (definition,) = fresh.get_definitions({"patch"}, quiet=True)
    assert definition["function"]["parameters"]["required"] == ["mode"]
    monkeypatch.setattr(auxiliary, "_read_main_provider", lambda: "anthropic")
    monkeypatch.setattr(auxiliary, "_read_main_model", lambda: "claude-opus")
    (definition,) = fresh.get_definitions({"patch"}, quiet=True)
    assert "mode" not in definition["function"]["parameters"]["properties"]


def test_read_file_takes_upstreams_offset_and_limit(project):
    """Killing mutation: drop ``min(..., READ_LIMIT)`` -> a limit of 5000 reads all 2100 lines, red."""

    (project / "long.txt").write_text("".join(f"line {n}\n" for n in range(1, 2101)), encoding="utf-8")
    default = _call(tools.read_file, path="notes/long.txt")
    assert default["content"].count("\n") == 1999 and default["next_offset"] == 2001
    wide = _call(tools.read_file, path="notes/long.txt", limit=5000)
    assert wide["next_offset"] == 2001
    tail = _call(tools.read_file, path="notes/long.txt", offset=0, limit=2)
    assert tail["content"] == "1|line 1\n2|line 2"


_V4A = """*** Begin Patch
*** Update File: notes/TODO.md
@@ # Notes @@
 - buy milk
-- call mum
+- call dad
*** Add File: notes/ideas/new.md
+first idea
+second idea
*** Update File: notes/TODO.md
+- water plants
*** End Patch"""


def test_a_v4a_patch_adds_and_updates_files_through_the_writer(project):
    got = _call(tools.patch, mode="patch", patch=_V4A)
    assert got["success"] is True
    assert got["files_modified"] == ["notes/TODO.md"] and got["files_created"] == ["notes/ideas/new.md"]
    assert (project / "TODO.md").read_text(encoding="utf-8") == "# Notes\n- buy milk\n- call dad\n- water plants\n"
    assert (project / "ideas" / "new.md").read_text(encoding="utf-8") == "first idea\nsecond idea"
    assert "+- call dad" in got["diff"]
    again = _call(tools.patch, mode="patch", patch="*** Begin Patch\n*** Add File: notes/ideas/new.md\n+x\n*** End Patch")
    assert again["code"] == "bad_argument" and "already exists" in again["error"]
    missed = _call(tools.patch, mode="patch",
                   patch="*** Begin Patch\n*** Update File: notes/TODO.md\n-no such line\n+x\n*** End Patch")
    assert missed["code"] == "bad_argument" and "exactly" in missed["error"]


def test_a_replace_patch_answers_the_diff_the_runner_records_as_a_v4a_patch_does(project):
    """A phone agent's find-and-replace edit draws View diff like its V4A edits (row
    ``RT-FU-A-PHONE-AGENTS-FIND-AND-REPLACE-EDIT-SHOWS-NO-VIEW-DIFF``, seen live on the emulator: the
    replace arm answered no ``diff``, so ``record_patch_diff`` recorded nothing). Both arms spell it
    through one helper, so the same edit answers the same diff either way. Killing mutation: drop
    ``"diff"`` from the replace arm's answer -> ``record_patch_diff`` records nothing, red."""

    from agent_runtime.patch_diff_artifacts import record_patch_diff

    replaced = tools.patch({"path": "notes/TODO.md", "old_string": "call mum", "new_string": "call dad"})
    assert json.loads(replaced)["replacements"] == 1
    recorded = record_patch_diff(replaced)  # the JSON string the runner hands it
    assert recorded is not None and (recorded["patch_adds"], recorded["patch_dels"]) == (1, 1)
    diff = json.loads(replaced)["diff"]
    assert Path(recorded["patch_artifact"]).read_text(encoding="utf-8") == diff
    assert diff.startswith("--- a/notes/TODO.md\n+++ b/notes/TODO.md\n") and "-- call mum\n+- call dad\n" in diff
    back = _call(tools.patch, mode="patch",
                 patch="*** Begin Patch\n*** Update File: notes/TODO.md\n-- call dad\n+- call mum\n*** End Patch")
    forth = _call(tools.patch, mode="patch",
                  patch="*** Begin Patch\n*** Update File: notes/TODO.md\n-- call mum\n+- call dad\n*** End Patch")
    assert back["diff"] != diff and forth["diff"] == diff


def test_a_v4a_patch_writes_nothing_when_one_file_is_refused(project, tmp_path):
    """Every file is checked before any is written. Killing mutation: drop ``_guard`` from
    ``writer.checked_text`` -> TODO.md is written before the config link's write is refused, red."""

    from hermes_constants import get_hermes_home

    config = Path(get_hermes_home()) / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("model: {}\n", encoding="utf-8")
    os.link(config, project / "settings.yaml")
    before = (project / "TODO.md").read_text(encoding="utf-8")
    for refused_part, code in (("*** Update File: notes/settings.yaml\n-model: {}\n+mcp_servers: {evil: {}}\n",
                                "write_denied"),
                               (f"*** Add File: {tmp_path / 'outside.md'}\n+x\n", "outside_root"),
                               ("*** Add File: notes/.git/hooks/post-commit\n+x\n", "ignored")):
        text = f"*** Begin Patch\n*** Update File: notes/TODO.md\n-- call mum\n+- call dad\n{refused_part}*** End Patch"
        refused = _call(tools.patch, mode="patch", patch=text)
        assert refused["code"] == code, refused
        assert (project / "TODO.md").read_text(encoding="utf-8") == before
    assert config.read_text(encoding="utf-8") == "model: {}\n" and not (tmp_path / "outside.md").exists()


@pytest.mark.parametrize("operation", ["*** Delete File: notes/TODO.md", "*** Move File: notes/TODO.md -> notes/done.md"])
def test_a_v4a_delete_or_move_is_refused_in_words_and_nothing_is_written(project, operation):
    """Killing mutation: drop the Delete/Move refusal in ``_apply_v4a`` -> the Update before it is written, red."""

    text = f"*** Begin Patch\n*** Update File: notes/TODO.md\n-- call mum\n+- call dad\n{operation}\n*** End Patch"
    refused = _call(tools.patch, mode="patch", patch=text)
    assert refused["code"] == "bad_argument" and "not available on a phone yet" in refused["error"]
    assert "call mum" in (project / "TODO.md").read_text(encoding="utf-8")
    assert sorted(os.listdir(project)) == ["TODO.md", "docs"]
    assert _call(tools.patch, mode="rewrite", path="notes/TODO.md")["code"] == "bad_argument"


def test_search_takes_every_desktop_argument_over_the_reader(project):
    """Killing mutations: drop the ``order='modified'`` sort -> discovery order, red; page content
    from 0 -> ``offset=1`` repeats the first match, red; drop the ``before`` half of ``grep_lines``'
    context -> no line above, red; bound ``after`` by ``len(lines)`` -> an empty line after the final
    newline, red."""

    (project / "docs" / "old.md").write_text("buy milk\n", encoding="utf-8")
    os.utime(project / "docs" / "old.md", (1_000_000, 1_000_000))
    os.utime(project / "TODO.md", (2_000_000, 2_000_000))
    found = _call(tools.search_files, pattern="*.md", target="files")
    assert found["files"] == ["notes/TODO.md", "notes/docs/old.md", "notes/docs/plan.md"]
    newest = _call(tools.search_files, pattern="*.md", target="find", order="modified", limit=2)
    assert newest["files"] == ["notes/docs/plan.md", "notes/TODO.md"] and newest["truncated"] is True
    assert newest["total_count"] == 3

    content = _call(tools.search_files, pattern="buy milk", path=".")
    assert [m["path"] for m in content["matches"]] == ["notes/TODO.md", "notes/docs/old.md", "notes/docs/plan.md"]
    assert [m["path"] for m in _call(tools.search_files, pattern="buy milk", offset=1, limit=1)["matches"]] == [
        "notes/docs/old.md"]
    assert _call(tools.search_files, pattern="buy milk", file_glob="plan*")["total_count"] == 1
    assert _call(tools.search_files, pattern="- ", output_mode="count")["counts"] == {"notes/TODO.md": 2}
    assert _call(tools.search_files, pattern="milk", output_mode="files_only", target="grep")["files"] == [
        "notes/TODO.md", "notes/docs/old.md", "notes/docs/plan.md"]
    (hit,) = _call(tools.search_files, pattern="buy milk", path="notes/TODO.md", context=1)["matches"]
    assert hit["path"] == "notes/TODO.md" and hit["line"] == 2
    assert hit["before"] == [{"line": 1, "text": "# Notes"}] and hit["after"] == [{"line": 3, "text": "- call mum"}]
    (last,) = _call(tools.search_files, pattern="call mum", path="notes/TODO.md", context=2)["matches"]
    assert last["after"] == [], "the final newline starts no empty line"


# A pattern holding a regex character runs ripgrep's matcher, else the regex package, else is refused in
# words (row RT-PHONE-REGEX-SEARCH-RUNS-RIPGREPS-MATCHER-FROM-A-NATIVE-LIBRARY):
# tests/agent_runtime/test_project_files_native_match.py.
