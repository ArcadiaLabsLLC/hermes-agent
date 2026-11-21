"""A bundled install's switches hold on every profile (RT-FU-A-BUNDLED-INSTALLS-SWITCHES-HOLD-ON-EVERY-PROFILE).

The bundle profile's switches are written to the serve root's ``config.yaml``; a call scoped to a second
profile reads that profile's home. ``hermes_cli.config_switches.with_install_switches`` (applied by
``load_config_readonly``) holds the install-only keys from the root on every profile, per reader family:
``config_switch``, ``provider_disabled``, ``adopt_external_logins_enabled`` and the plain
``load_config_readonly`` readers (realm sync's git backend). ``mcp.stdio_servers`` stays per profile.

Each test carries a POSITIVE CONTROL: the same read on a developer install (no bundle profile installed)
takes the second profile's own value, so "held" is never the read simply not reaching the profile.
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


HELD = {"pydantic_contracts": False, "provider_sdks": False, "external_backends": False,
        "qwen_disabled": True, "adopt_external_logins": False, "git_backend": "dulwich"}
DEFAULTS = {"pydantic_contracts": True, "provider_sdks": True, "external_backends": True,
            "qwen_disabled": False, "adopt_external_logins": True, "git_backend": "binary"}


def test_a_second_profile_reads_every_phone_switch_as_the_install_set_it(homes, install):
    root, second = homes
    _write(root, apply_to_config(load_profile(PHONE), {}))
    _write(second, {})
    install(None)
    with _scoped(second):
        assert _reads() == DEFAULTS  # positive control: a developer install reads the profile's own
    install(PHONE)
    with _scoped(second):
        assert _reads() == HELD
    assert _reads() == HELD  # the root itself, unscoped


def test_a_second_profile_cannot_turn_an_install_only_switch_back_on(homes, install):
    root, second = homes
    _write(root, apply_to_config(load_profile(PHONE), {}))
    _write(second, {"tui_gateway": {"pydantic_contracts": True}, "agent": {"provider_sdks": True},
                    "terminal": {"external_backends": True}, "auth": {"adopt_external_logins": True},
                    "providers": {"qwen-oauth": {"enabled": True}}, "realm_sync": {"git_backend": "binary"}})
    install(None)
    with _scoped(second):
        assert _reads() == DEFAULTS  # positive control: the profile's own "on" is read
    install(PHONE)
    with _scoped(second):
        assert _reads() == HELD


def test_the_per_profile_key_stays_the_profiles_both_ways(homes, install):
    """``mcp.stdio_servers`` is per profile by design: the root's ``false`` is not forced on a profile."""
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
    assert config_switch("mcp", "stdio_servers") is False  # the root's own value


def test_a_key_the_root_does_not_set_is_not_forced(homes, install):
    """A bundled desktop whose root config carries none of its switches holds nothing (no writer yet:
    RT-FU-A-BUNDLED-DESKTOP-WRITES-ITS-PROFILE-SWITCHES-TO-ITS-CONFIG)."""
    from hermes_cli.config_switches import config_switch

    root, second = homes
    _write(root, {})
    _write(second, {"terminal": {"external_backends": False}})
    install(DESKTOP)
    with _scoped(second):
        assert config_switch("terminal", "external_backends") is False
        assert config_switch("voice", "mode_enabled") is True


def test_the_writers_view_and_the_cached_config_are_untouched(homes, install):
    from hermes_cli import config as _config

    root, second = homes
    _write(root, apply_to_config(load_profile(PHONE), {}))
    _write(second, {"auth": {"adopt_external_logins": True}})
    install(PHONE)
    with _scoped(second):
        cached = _config._load_config_impl(want_deepcopy=False, ensure_home=False)  # the loader's own dict
        held = _config.load_config_readonly()
        assert held["auth"]["adopt_external_logins"] is False
        assert _config.load_config_readonly() is held  # one overlay per cached pair
        assert cached["auth"]["adopt_external_logins"] is True  # the cached config was not mutated
        assert _config.load_config()["auth"]["adopt_external_logins"] is True  # a save keeps the profile's own
