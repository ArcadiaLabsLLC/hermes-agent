"""Warm plugin home resolution stays cheap while profile selection stays live.

Positive control: bypass the cached key at the upstream seam; the warm syscall
budget test fails. Killing mutation: freeze the helper to the first home; the
real manager profile-switch test fails. These are isolated-home, no-provider-call
checks; full request parity is recorded in the lane's characterization evidence.
"""
from pathlib import Path

import pytest

import hermes_constants
import hermes_cli.plugins as plugins
from agent_runtime import plugin_manager_home


@pytest.fixture(autouse=True)
def isolated_managers(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(hermes_constants, "_HOME_KEY_CACHE", {})
    monkeypatch.setattr(plugins, "_plugin_manager", None)
    monkeypatch.setattr(plugins, "_plugin_managers_by_home", {})
    monkeypatch.setattr(plugins, "_published_gateway_message_injector", None)
    monkeypatch.setattr(plugins, "_published_tui_message_injector", None)


def test_warm_manager_key_resolves_an_existing_home_once(tmp_path, monkeypatch):
    expected = tmp_path.resolve()
    calls = []
    original = Path.resolve

    def counted(path, *args, **kwargs):
        calls.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", counted)
    for _ in range(25):
        assert plugins._plugin_home_key() == expected
    assert calls == [tmp_path], "warm manager lookup repeated filesystem resolution"


def test_real_managers_follow_context_home_and_reuse_each_identity(tmp_path):
    home_a, home_b = tmp_path / "a", tmp_path / "b"
    home_a.mkdir()
    home_b.mkdir()
    token = hermes_constants.set_hermes_home_override(str(home_a))
    try:
        manager_a = plugins.get_plugin_manager()
    finally:
        hermes_constants.reset_hermes_home_override(token)
    token = hermes_constants.set_hermes_home_override(str(home_b))
    try:
        manager_b = plugins.get_plugin_manager()
    finally:
        hermes_constants.reset_hermes_home_override(token)
    token = hermes_constants.set_hermes_home_override(str(home_a))
    try:
        assert plugins.get_plugin_manager() is manager_a
    finally:
        hermes_constants.reset_hermes_home_override(token)
    assert manager_a is not manager_b
    assert manager_a.scope_key == hermes_constants.hermes_home_key(home_a)
    assert manager_b.scope_key == hermes_constants.hermes_home_key(home_b)


def test_equivalent_existing_paths_share_manager(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    manager = plugins.get_plugin_manager()
    monkeypatch.setenv("HERMES_HOME", str(home / ".." / "home"))
    assert plugins.get_plugin_manager() is manager


def test_environment_home_changes_do_not_freeze_manager(tmp_path, monkeypatch):
    home = tmp_path / "other"
    home.mkdir()
    first = plugins.get_plugin_manager()
    monkeypatch.setenv("HERMES_HOME", str(home))
    assert plugins.get_plugin_manager() is not first
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert plugins.get_plugin_manager() is first


def test_missing_home_is_not_memoized_until_creation(tmp_path):
    home = tmp_path / "later"
    expected = home.resolve()
    assert plugin_manager_home.cached_plugin_home_key(home) == expected
    assert str(home) not in hermes_constants._HOME_KEY_CACHE
    home.mkdir()
    assert plugin_manager_home.cached_plugin_home_key(home) == expected
    assert str(home) in hermes_constants._HOME_KEY_CACHE


def test_helper_failure_retains_upstream_fallback(tmp_path, monkeypatch):
    def broken(_home):
        raise OSError("resolution unavailable")

    monkeypatch.setattr(plugin_manager_home, "hermes_home_key", broken)
    assert plugin_manager_home.cached_plugin_home_key(tmp_path) is None
    assert plugins._plugin_home_key() == tmp_path.resolve()


def test_all_resolution_failures_still_return_expanded_home(tmp_path, monkeypatch):
    def broken(*_args, **_kwargs):
        raise OSError("resolution unavailable")

    monkeypatch.setattr(plugin_manager_home, "hermes_home_key", broken)
    monkeypatch.setattr(Path, "resolve", broken)
    assert plugins._plugin_home_key() == tmp_path.expanduser()
