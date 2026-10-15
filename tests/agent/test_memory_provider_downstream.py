"""Fork-owned tests for ``plugins/memory/_module_publish.py`` (lane FOOTPRINT-DROP 2026-09-27).

``discover_plugin_cli_commands`` publishes the active provider's ``cli.py`` the way real import
machinery does: in ``sys.modules`` AND as an attribute of its parent package, so
``from <parent> import cli`` and a dotted ``monkeypatch.setattr`` agree with
``importlib.import_module``.
"""

from __future__ import annotations

import sys


def _make_plugin_with_cli(tmp_path, name):
    """Upstream's fixture plugin (a provider plus a ``cli.py`` with a relative import)."""
    from tests.agent import test_memory_provider as upstream

    upstream.TestUserInstalledProviderCli._make_plugin_with_cli(None, tmp_path, name)


def test_cli_module_is_bound_on_its_parent_package(tmp_path, monkeypatch):
    from plugins.memory import _module_name, discover_plugin_cli_commands

    name = "fpbindcli"
    _make_plugin_with_cli(tmp_path, name)
    monkeypatch.setattr("plugins.memory._get_user_plugins_dir", lambda: tmp_path / "plugins")
    monkeypatch.setattr("plugins.memory._get_active_memory_provider", lambda: name)
    parent_name = _module_name(tmp_path / "plugins" / name, name)
    try:
        assert len(discover_plugin_cli_commands()) == 1
        cli_mod = sys.modules[f"{parent_name}.cli"]
        assert getattr(sys.modules[parent_name], "cli", None) is cli_mod
    finally:
        for key in [k for k in sys.modules if k == parent_name or k.startswith(parent_name + ".")]:
            sys.modules.pop(key, None)
