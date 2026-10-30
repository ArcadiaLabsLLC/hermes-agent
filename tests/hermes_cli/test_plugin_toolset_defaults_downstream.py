"""The fork's two seam lines in ``hermes_cli/tools_config.py`` (RT-LOCAL-RECOVERY-FROZEN-SAFE-TOOLS).

eternia-harness registers ``skill_search`` into the BUILT-IN ``skills`` toolset, so the plugin
key set names ``skills``; without the seam, ``_enabled_plugin_toolsets`` turned ``skills`` back on
for an explicit ``platform_toolsets.cli: []``. The plugin's ``schedule`` toolset is opt-in. The
``lens`` toolset stays a default-on plugin toolset: that residue is the probe's id-marked xfail
(``tests/_downstream/id_markers/fork_marks.py``).
"""
import hermes_cli.tools_config as tools_config


def _resolve(monkeypatch, plugin_keys, toolsets):
    monkeypatch.setattr(tools_config, "_get_plugin_toolset_keys", lambda: set(plugin_keys))
    config = {} if toolsets is None else {"platform_toolsets": {"cli": toolsets}}
    return tools_config._get_platform_tools(config, "cli", include_default_mcp_servers=False)


def test_a_plugin_tool_in_a_built_in_toolset_does_not_reopen_an_explicit_empty_list(monkeypatch):
    enabled = _resolve(monkeypatch, {"skills", "lens"}, [])
    assert "skills" not in enabled, enabled
    # Positive control: a plugin-OWNED default-on key on the same list is still turned on.
    assert "lens" in enabled, enabled


def test_a_built_in_toolset_a_plugin_also_names_is_still_enabled_when_saved(monkeypatch):
    assert "skills" in _resolve(monkeypatch, {"skills"}, ["skills"])


def test_the_schedule_toolset_is_opt_in(monkeypatch):
    assert "schedule" not in _resolve(monkeypatch, {"schedule"}, None)
    assert "schedule" not in _resolve(monkeypatch, {"schedule"}, ["hermes-cli"])
    # Positive control: naming it on the saved list opts the profile in.
    assert "schedule" in _resolve(monkeypatch, {"schedule"}, ["hermes-cli", "schedule"])
