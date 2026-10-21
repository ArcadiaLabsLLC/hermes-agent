"""Verify-on-stop is OFF on every harness persona turn (owner ruling 2026-10-18, row
RT-VERIFY-ON-STOP-OFF): ON cost 11.8 calls / 234k input tokens / 77 s per editing turn
against 2.6 / 44k / 28 s OFF. The fork ships no opt-in: no dev-persona profile turns it on,
and a persona config with no ``agent.verify_on_stop`` resolves OFF. The one switch an
operator keeps is the explicit config key (or ``HERMES_VERIFY_ON_STOP``).

Killing mutation: ``hermes_cli/config_defaults.py`` ``"verify_on_stop": False`` -> ``True``
reds ``test_default_config_resolves_off``.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from agent.verification_stop import verify_on_stop_enabled
from hermes_cli.config_defaults import DEFAULT_CONFIG

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _no_env_switch(monkeypatch):
    monkeypatch.delenv("HERMES_VERIFY_ON_STOP", raising=False)


def test_default_config_resolves_off():
    assert DEFAULT_CONFIG["agent"]["verify_on_stop"] is False
    assert verify_on_stop_enabled(copy.deepcopy(DEFAULT_CONFIG)) is False


def test_persona_config_without_the_key_resolves_off():
    assert verify_on_stop_enabled({"agent": {"max_turns": 60}}) is False
    assert verify_on_stop_enabled({}) is False


@pytest.mark.parametrize("value", [True, "true", "on"])
def test_explicit_operator_key_still_turns_it_on(value):
    assert verify_on_stop_enabled({"agent": {"verify_on_stop": value}}) is True


def test_env_switch_still_wins(monkeypatch):
    monkeypatch.setenv("HERMES_VERIFY_ON_STOP", "1")
    assert verify_on_stop_enabled({"agent": {"verify_on_stop": False}}) is True


def _tracked_profile_configs() -> list[Path]:
    roots = [REPO_ROOT / "tests" / "fixtures" / "profile_roots", REPO_ROOT / "plugins" / "eternia-harness"]
    return sorted(p for root in roots if root.is_dir() for p in root.rglob("config.yaml"))


def test_no_shipped_profile_opts_a_persona_in():
    """Negative source walk: no profile config the fork ships sets the key truthy."""
    offenders = []
    for path in _tracked_profile_configs():
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
        agent_cfg = data.get("agent") if isinstance(data, dict) else None
        value = agent_cfg.get("verify_on_stop") if isinstance(agent_cfg, dict) else None
        if value not in (None, False, "false", "off"):
            offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {value!r}")
    assert not offenders, offenders
