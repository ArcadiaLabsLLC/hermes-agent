"""A bundled install's shipped switches hold on every read (RT-FU-A-BUNDLED-INSTALLS-SWITCHES-HOLD-ON-EVERY-PROFILE,
RT-FU-A-BUNDLED-DESKTOP-WRITES-ITS-PROFILE-SWITCHES-TO-ITS-CONFIG).

``hermes_cli.config_switches.with_install_switches`` (applied by ``load_config_readonly`` and by the provider
read view ``agent.provider_access.provider_configuration``) lays the SHIPPED profile's install-only switches
over the config in memory, on the serve root and on every second profile alike. Nothing is written: the
bundled desktop's serve root is the account's shared namespace home, which the Developer Edition opens too.
``PER_PROFILE_KEYS`` and ``HELD_OUT_KEYS`` follow the config.

Each test carries a POSITIVE CONTROL: the same read on a developer install (no bundle profile installed)
takes the config's own value, so "held" is never the read simply not reaching the config.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from agent_runtime.bundle_profiles.manifest import apply_to_config, load_profile
from hermes_cli import config_switches
from hermes_constants import get_hermes_home, reset_hermes_home_override, set_hermes_home_override

PHONE = "bundled-phone"
DESKTOP = "bundled-desktop"


def _write(home: Path, config: dict) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(json.dumps(config), encoding="utf-8")  # YAML is a JSON superset


@pytest.fixture
def homes(tmp_path):
    """``(root, second)``: the serve root (this process's HERMES_HOME) and a second profile's home."""
    root = Path(get_hermes_home())
    second = root / "profiles" / "neko"
    second.mkdir(parents=True, exist_ok=True)
    return root, second


@pytest.fixture
def install(monkeypatch):
    """``install(profile_or_None)``: what this process is installed as, for the seam."""

    def _install(profile: str | None) -> None:
        config = load_profile(profile).config if profile else None
        monkeypatch.setattr(config_switches, "_installed_profile_config", lambda: config)
        config_switches.reset_install_switches()

    yield _install
    config_switches.reset_install_switches()


@contextmanager
def _scoped(home: Path):
    token = set_hermes_home_override(str(home))
    try:
        yield
    finally:
        reset_hermes_home_override(token)


def _reads() -> dict:
    """Every reader family's answer, read in the current scope."""
    from agent.credential_sources import adopt_external_logins_enabled
    from agent_runtime.realm_sync.git import sync_git_backend
    from hermes_cli.config_switches import config_switch
    from hermes_cli.provider_login_catalog import provider_disabled

    return {
        "pydantic_contracts": config_switch("tui_gateway", "pydantic_contracts"),
        "provider_sdks": config_switch("agent", "provider_sdks"),
        "external_backends": config_switch("terminal", "external_backends"),
        "qwen_disabled": provider_disabled("qwen-oauth"),
        "adopt_external_logins": adopt_external_logins_enabled(),
        "git_backend": sync_git_backend().value,
    }


def _desktop_reads() -> dict:
    """The desktop profile's reader families, the runtime resolver's ``rp.load_config()`` included."""
    from agent.credential_sources import adopt_external_logins_enabled
    from hermes_cli import runtime_provider as rp
    from hermes_cli.config_switches import config_switch
    from hermes_cli.provider_login_catalog import provider_disabled

    resolver = (rp.load_config().get("providers") or {}).get("qwen-oauth") or {}
    return {
        "adopt_external_logins": adopt_external_logins_enabled(),
        "external_backends": config_switch("terminal", "external_backends"),
        "voice_mode": config_switch("voice", "mode_enabled"),
        "qwen_disabled": provider_disabled("qwen-oauth"),
        "resolver_qwen_enabled": resolver.get("enabled", True),
    }


ALL_ON = {"tui_gateway": {"pydantic_contracts": True}, "agent": {"provider_sdks": True},
          "terminal": {"external_backends": True}, "auth": {"adopt_external_logins": True},
          "providers": {"qwen-oauth": {"enabled": True}}, "realm_sync": {"git_backend": "binary"},
          "voice": {"mode_enabled": True}}
HELD = {"pydantic_contracts": False, "provider_sdks": False, "external_backends": False,
        "qwen_disabled": True, "adopt_external_logins": False, "git_backend": "dulwich"}
DEFAULTS = {"pydantic_contracts": True, "provider_sdks": True, "external_backends": True,
            "qwen_disabled": False, "adopt_external_logins": True, "git_backend": "binary"}
DESKTOP_HELD = {"adopt_external_logins": False, "external_backends": False, "voice_mode": False,
                "qwen_disabled": True, "resolver_qwen_enabled": False}
DESKTOP_ON = {"adopt_external_logins": True, "external_backends": True, "voice_mode": True,
              "qwen_disabled": False, "resolver_qwen_enabled": True}


def test_a_developer_install_reads_its_config_unchanged(homes, install):
    from hermes_cli import config as _config

    root, second = homes
    _write(root, ALL_ON)
    _write(second, {})
    install(None)
    assert _desktop_reads() == DESKTOP_ON
    with _scoped(second):
        assert _reads() == DEFAULTS
    cached = _config._load_config_impl(want_deepcopy=False, ensure_home=False)
    assert _config.load_config_readonly() is cached  # no overlay at all: the loader's own dict


def test_a_bundled_desktop_reads_the_shipped_off_over_a_root_config_that_says_on(homes, install):
    """The root config says on (the Developer Edition's shared file); the shipped profile says off."""
    root, second = homes
    _write(root, ALL_ON)
    _write(second, ALL_ON)
    install(None)
    with _scoped(second):
        assert _desktop_reads() == DESKTOP_ON  # positive control: the config's own "on" is read
    install(DESKTOP)
    assert _desktop_reads() == DESKTOP_HELD  # the root itself
    with _scoped(second):
        assert _desktop_reads() == DESKTOP_HELD  # a second profile


def test_the_build_stamp_is_what_makes_a_desktop_bundled(homes, monkeypatch):
    """The real gate, not a patched profile: the build stamp's ``bundled`` installs the desktop profile."""
    from agent_runtime import bundled_toolsets

    root, _second = homes
    _write(root, ALL_ON)
    monkeypatch.setattr(bundled_toolsets, "edition_bundled", lambda: False)
    config_switches.reset_install_switches()
    try:
        assert _desktop_reads() == DESKTOP_ON
        monkeypatch.setattr(bundled_toolsets, "edition_bundled", lambda: True)
        config_switches.reset_install_switches()
        assert _desktop_reads() == DESKTOP_HELD
    finally:
        config_switches.reset_install_switches()


def test_a_second_profile_reads_every_phone_switch_as_the_install_ships_it(homes, install):
    root, second = homes
    _write(root, {})  # nothing written anywhere: the shipped profile alone holds
    _write(second, ALL_ON)
    install(None)
    with _scoped(second):
        assert _reads() == DEFAULTS  # positive control: the profile's own "on" is read
    install(PHONE)
    with _scoped(second):
        assert _reads() == HELD
    assert _reads() == HELD  # the root itself, unscoped


def test_the_held_out_keys_follow_the_config(homes, install):
    """``local_runtime.enabled`` and ``delegation.worktree_isolation`` stay a person's to change, and
    ``auth.os_secure_store`` waits for its own row: the shipped profile never overrides them."""
    from hermes_cli import config as _config

    assert set(config_switches.HELD_OUT_KEYS) == {
        "local_runtime.enabled", "delegation.worktree_isolation", "auth.os_secure_store"}
    assert set(config_switches.HELD_OUT_KEYS) <= set(load_profile(DESKTOP).config)  # each is a real profile key
    _root, second = homes
    install(DESKTOP)
    held = {".".join(path) for path in config_switches.install_only_keys()}
    assert held and not set(config_switches.HELD_OUT_KEYS) & held
    for config in ({"local_runtime": {"enabled": False}, "delegation": {"worktree_isolation": True},
                    "auth": {"os_secure_store": False}},
                   {"local_runtime": {"enabled": True}, "delegation": {"worktree_isolation": False},
                    "auth": {"os_secure_store": True}}):
        _write(second, config)
        with _scoped(second):
            read = _config.load_config_readonly()
            assert read["local_runtime"]["enabled"] is config["local_runtime"]["enabled"]
            assert read["delegation"]["worktree_isolation"] is config["delegation"]["worktree_isolation"]
            assert read["auth"]["os_secure_store"] is config["auth"]["os_secure_store"]


def test_the_per_profile_key_stays_the_profiles_both_ways(homes, install):
    """``mcp.stdio_servers`` is per profile by design: the shipped ``false`` is not forced on a profile."""
    from hermes_cli.config_switches import config_switch

    root, second = homes
    _write(root, apply_to_config(load_profile(DESKTOP), {}))
    install(DESKTOP)
    _write(second, {})
    with _scoped(second):
        assert config_switch("mcp", "stdio_servers") is True
        assert config_switch("terminal", "external_backends") is False  # the same call holds an install-only key
    _write(second, {"mcp": {"stdio_servers": False}})
    with _scoped(second):
        assert config_switch("mcp", "stdio_servers") is False


def test_a_config_save_never_writes_the_overlay(homes, install):
    from hermes_cli import config as _config

    root, _second = homes
    _write(root, {"auth": {"adopt_external_logins": True}, "model": {"default": "x"}})
    install(DESKTOP)
    assert _config.load_config_readonly()["auth"]["adopt_external_logins"] is False
    writer = _config.load_config()
    assert writer["auth"]["adopt_external_logins"] is True  # the writer's view is the file's own
    writer["model"]["default"] = "y"
    _config.save_config(writer)
    on_disk = _config.read_raw_config()
    assert on_disk["auth"] == {"adopt_external_logins": True}
    assert on_disk["model"]["default"] == "y"
    for path in config_switches.install_only_keys():
        if path != ("auth", "adopt_external_logins"):
            assert config_switches._lookup(on_disk, path) == (False, None), path


def test_the_cached_config_and_the_shipped_switches_are_not_mutated(homes, install):
    from hermes_cli import config as _config

    _root, second = homes
    _write(second, {"auth": {"adopt_external_logins": True}})
    install(PHONE)
    switches = config_switches.install_switches()
    before = json.dumps([[list(path), value] for path, value in switches])
    with _scoped(second):
        cached = _config._load_config_impl(want_deepcopy=False, ensure_home=False)  # the loader's own dict
        held = _config.load_config_readonly()
        assert held["auth"]["adopt_external_logins"] is False
        assert _config.load_config_readonly() is held  # one overlay per cached dict
        assert cached["auth"]["adopt_external_logins"] is True  # the cached config was not mutated
        held["auth"]["adopt_external_logins"] = "mutated"  # a reader scribbling on its view ...
        held["realm_sync"]["git_backend"] = "mutated"
    fresh = config_switches.with_install_switches({}, cache=False)
    assert config_switches.install_switches() is switches  # read once
    assert json.dumps([[list(path), value] for path, value in switches]) == before  # ... never reaches them
    assert fresh["auth"]["adopt_external_logins"] is False
    assert fresh["realm_sync"]["git_backend"] == "dulwich"
    assert load_profile(PHONE).config["auth.adopt_external_logins"] is False


def test_a_reader_mutating_a_held_list_never_reaches_the_shipped_value(monkeypatch):
    """Every shipped value is a scalar today; a list-valued switch would be shared by every overlay."""
    monkeypatch.setattr(config_switches, "_installed_profile_config", lambda: {"tools.allow": ["web"]})
    config_switches.reset_install_switches()
    try:
        first = config_switches.with_install_switches({}, cache=False)
        first["tools"]["allow"].append("terminal")
        assert config_switches.with_install_switches({}, cache=False)["tools"]["allow"] == ["web"]
    finally:
        config_switches.reset_install_switches()
