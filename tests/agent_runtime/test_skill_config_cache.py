"""agent.skill_utils._load_raw_config keeps one parse per home when a process alternates homes."""

from __future__ import annotations

import pytest

import agent.skill_utils as su
from agent_runtime import skill_config_cache
from hermes_constants import reset_hermes_home_override, set_hermes_home_override


@pytest.fixture
def bounded(monkeypatch):
    monkeypatch.setattr(su, "_RAW_CONFIG_CACHE", {})
    monkeypatch.setattr(su, "_raw_config_cache_clear", su._raw_config_cache_clear)
    return skill_config_cache.install_bounded_skill_config_cache(bound=2)


@pytest.fixture
def parses(monkeypatch):
    calls = []
    real = su.yaml_load
    monkeypatch.setattr(su, "yaml_load", lambda text: calls.append(text) or real(text))
    return calls


def _home(tmp_path, name, backend):
    home = tmp_path / name
    home.mkdir()
    (home / "config.yaml").write_text(f"skills:\n  backend: {backend}\n", encoding="utf-8")
    return home


def _read(home):
    token = set_hermes_home_override(str(home))
    try:
        return su._load_raw_config()
    finally:
        reset_hermes_home_override(token)


def test_alternating_homes_parse_each_home_once(tmp_path, bounded, parses):
    a, b = _home(tmp_path, "a", "one"), _home(tmp_path, "b", "two")
    reads = [_read(home)["skills"]["backend"] for home in (a, b, a, b, a)]
    assert reads == ["one", "two", "one", "two", "one"]
    assert len(parses) == 2


def test_a_rewritten_config_is_reparsed(tmp_path, bounded, parses):
    a = _home(tmp_path, "a", "one")
    _read(a)
    (a / "config.yaml").write_text("skills:\n  backend: other-value\n", encoding="utf-8")
    assert _read(a)["skills"]["backend"] == "other-value"
    assert len(parses) == 2


def test_the_bound_evicts_the_least_recently_used_home(tmp_path, bounded, parses):
    a, b, c = (_home(tmp_path, n, n) for n in "abc")
    for home in (a, b, a, c):  # c evicts b (a was used after b)
        _read(home)
    assert len(parses) == 3
    _read(a)
    assert len(parses) == 3
    _read(b)
    assert len(parses) == 4
    assert len(su._RAW_CONFIG_CACHE) == 2


def test_the_test_hook_still_empties_the_cache(tmp_path, bounded, parses):
    _read(_home(tmp_path, "a", "one"))
    su._raw_config_cache_clear()
    assert len(su._RAW_CONFIG_CACHE) == 0


def test_install_is_idempotent(bounded):
    assert skill_config_cache.install_bounded_skill_config_cache() is bounded
