"""tests/_downstream/plugin_discovery_cache.py: kept discovery gives the registries a cold discovery gives."""

from __future__ import annotations

import os

from hermes_cli import plugins

from tests._downstream import plugin_discovery_cache as cache


def _registered_after_discovery():
    """Reset every manager as the per-test sandbox does, discover, and read what landed in the registries."""

    from tools.registry import registry

    plugins._reset_plugin_managers_for_tests()
    plugins.discover_plugins()
    manager = plugins.get_plugin_manager()
    return {
        "tools": sorted(registry.get_all_tool_names()),
        "hooks": {name: len(callbacks) for name, callbacks in manager._hooks.items() if callbacks},
        "plugins": sorted((key, bool(p.enabled), p.error) for key, p in manager._plugins.items()),
    }


def test_kept_discovery_registers_what_a_cold_discovery_registers():
    """Killing mutation: hand out ``kept[1][:-1]`` on a scan hit (one bundled plugin dropped)."""

    assert cache.install_if_imported()
    cache.set_bypass(True)
    try:
        cold = _registered_after_discovery()
    finally:
        cache.set_bypass(False)
    cache.clear()
    _registered_after_discovery()  # fills the cache
    hits = cache.stats()["hits"]
    warm = _registered_after_discovery()
    assert cache.stats()["hits"] > hits, "the second discovery was not served from the cache"
    assert cold["plugins"], "no bundled plugin was discovered: the comparison would prove nothing"
    assert warm == cold


def test_the_reset_fixture_rediscovers_cold(cold_plugin_discovery):
    """Killing mutation: make ``cold_plugin_discovery`` yield without ``set_bypass(True)``."""

    assert cache.install_if_imported()
    _registered_after_discovery()
    hits = cache.stats()["hits"]
    _registered_after_discovery()
    assert cache.stats()["hits"] == hits


def test_an_edited_bundled_tree_is_a_miss(tmp_path, monkeypatch):
    """A scan of the bundled root is re-used only while the tree's signature is unchanged.
    Killing mutation: drop ``kept[0] == signature`` from the hit test."""

    root = tmp_path / "bundled"
    (root / "one").mkdir(parents=True)
    (root / "one" / "plugin.yaml").write_text("name: one\n", encoding="utf-8")
    calls = []

    def real(path, source, *, skip_names=None, prefix="", depth=0):
        calls.append(path)
        return [sorted(p.name for p in root.iterdir())]

    scan = cache._caching_scan(real, root)
    cache.clear()
    assert scan(root, "bundled") == [["one"]]
    assert scan(root, "bundled") == [["one"]] and len(calls) == 1
    (root / "two").mkdir()
    (root / "two" / "plugin.yaml").write_text("name: two\n", encoding="utf-8")
    assert scan(root, "bundled") == [["one", "two"]] and len(calls) == 2
    cache.clear()


def test_bytecode_written_into_a_plugin_dir_is_not_a_miss(tmp_path):
    """Another process's first import writes ``__pycache__`` into the plugin directories (a fresh
    worktree under ``-j``); that changes the directories' mtimes but not what a scan finds, so it is
    not a miss, while an edited manifest still is. Killing mutation: put the directories' own
    ``st_mtime_ns`` back into ``_tree_signature``."""

    root = tmp_path / "bundled"
    plugin = root / "group" / "one"
    plugin.mkdir(parents=True)
    manifest = plugin / "plugin.yaml"
    manifest.write_text("name: one\n", encoding="utf-8")
    before = cache._tree_signature(str(root))
    for directory in (plugin, root / "group"):
        (directory / "__pycache__").mkdir()
        # NTFS updates a directory's listed mtime lazily (seen ~1 s later); set it now.
        stamp = directory.stat().st_mtime_ns + 5 * 10**9
        os.utime(directory, ns=(stamp, stamp))
    assert cache._tree_signature(str(root)) == before
    manifest.write_text("name: one\nversion: 2\n", encoding="utf-8")
    assert cache._tree_signature(str(root)) != before
