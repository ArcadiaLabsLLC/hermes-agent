"""Native extension contract, independent of any Harness policy."""
from pathlib import Path

import pytest

from agent import provider_access as access
from hermes_constants import reset_hermes_home_override, set_hermes_home_override


_PLUGIN = '''
from pathlib import Path
from agent.provider_access import ProviderAccess
from hermes_constants import get_hermes_home

class Access(ProviderAccess):
    name = "resources"
    def is_bound(self):
        return True
    def secret(self, name):
        return "" if name == "MISSING" else "key-" + get_hermes_home().name
    def credential_file(self, name, profile_home):
        return profile_home / "provider" / name
    def configuration(self, profile):
        return {**profile, "providers": {"selected": get_hermes_home().name}}

def register(ctx):
    ctx.register_provider_access(Access())
'''


def test_discovered_access_is_profile_scoped_and_unloads(tmp_path, monkeypatch):
    from hermes_cli.plugins import get_plugin_manager

    monkeypatch.delenv("HERMES_AUTH_HOME", raising=False)
    homes = [tmp_path / name for name in ("a", "b")]
    for home in homes:
        plugin = home / "plugins" / "resources"
        plugin.mkdir(parents=True)
        (plugin / "plugin.yaml").write_text("name: resources\nversion: '1'\n", encoding="utf-8")
        (plugin / "__init__.py").write_text(_PLUGIN, encoding="utf-8")
        (home / "config.yaml").write_text("plugins:\n  enabled: [resources]\n", encoding="utf-8")
    for home in (homes[0], homes[1], homes[0]):
        token = set_hermes_home_override(home)
        try:
            profile = {"model": {"default": "local"}, "terminal": {"backend": "docker"}}
            projected = access.provider_configuration(profile)
            assert projected == {**profile, "providers": {"selected": home.name}}
            assert "providers" not in profile
            assert access.provider_secret("API_KEY") == "key-" + home.name
            assert access.provider_secret("MISSING") == ""
            assert access.provider_credential_file("auth.json", home) == home / "provider" / "auth.json"
        finally:
            reset_hermes_home_override(token)
    token = set_hermes_home_override(homes[0])
    try:
        get_plugin_manager().unload("resources")
        assert access.provider_secret("API_KEY") is None
        assert access.provider_configuration(profile) is profile
        assert access.provider_credential_file("auth.json", homes[0]) == homes[0] / "auth.json"
    finally:
        reset_hermes_home_override(token)


def test_conflicting_or_broken_authority_never_falls_back(tmp_path, monkeypatch):
    from hermes_cli.plugins import PluginContext, PluginManifest, get_plugin_manager

    monkeypatch.setenv("HERMES_SAFE_MODE", "1")

    class Access(access.ProviderAccess):
        name = "first"

        def is_bound(self):
            return True

        def secret(self, name):
            raise OSError("provider store unavailable")

        def credential_file(self, name, profile_home):
            raise OSError("provider store unavailable")

        def configuration(self, profile):
            raise OSError("provider store unavailable")

    manager = get_plugin_manager()
    manager.discover_and_load()
    ctx = PluginContext(PluginManifest(name="resources", source="user"), manager)
    first = ctx.register_provider_access(Access())
    calls = (lambda: access.provider_secret("API_KEY"),
             lambda: access.provider_credential_file("auth.json", Path(tmp_path)),
             lambda: access.provider_configuration({}))
    try:
        for call in calls:
            with pytest.raises(OSError, match="store unavailable"):
                call()
        second = Access()
        second.name = "second"
        handle = ctx.register_provider_access(second)
        try:
            for call in calls:
                with pytest.raises(RuntimeError, match="More than one"):
                    call()
        finally:
            handle.dispose()
    finally:
        first.dispose()
