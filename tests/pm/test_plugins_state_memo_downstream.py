"""pm.plugins_state.read_home_selection parses a home's config.yaml once per content (fork memo)."""

from __future__ import annotations

import pytest

import pm.plugins_state as pstate
import utils


@pytest.fixture
def parses(monkeypatch):
    calls = []
    real = utils.fast_safe_load

    def counting(text):
        calls.append(text)
        return real(text)

    monkeypatch.setattr(utils, "fast_safe_load", counting)
    return calls


def test_unchanged_config_is_parsed_once(tmp_path, parses):
    (tmp_path / "config.yaml").write_text("plugins:\n  enabled: [a]\n", encoding="utf-8")
    first = pstate.read_home_selection(tmp_path)
    second = pstate.read_home_selection(tmp_path)
    assert first == second == {"plugins": {"enabled": ["a"]}}
    assert len(parses) == 1


def test_same_size_rewrite_is_reparsed(tmp_path, parses):
    config = tmp_path / "config.yaml"
    config.write_text("plugins:\n  enabled: [a]\n", encoding="utf-8")
    pstate.read_home_selection(tmp_path)
    config.write_text("plugins:\n  enabled: [b]\n", encoding="utf-8")
    assert pstate.read_home_selection(tmp_path) == {"plugins": {"enabled": ["b"]}}
    assert len(parses) == 2


def test_a_caller_edit_never_reaches_the_next_reader(tmp_path, parses):
    (tmp_path / "config.yaml").write_text("plugins:\n  enabled: [a]\n", encoding="utf-8")
    pstate.read_home_selection(tmp_path)["plugins"]["enabled"].append("leak")
    pstate.read_home_selection(tmp_path)["plugins"]["enabled"].append("leak")
    assert pstate.read_home_selection(tmp_path) == {"plugins": {"enabled": ["a"]}}


def test_a_broken_config_raises_every_time(tmp_path):
    (tmp_path / "config.yaml").write_text("plugins: [not, a, mapping]\n", encoding="utf-8")
    for _ in range(2):
        with pytest.raises(ValueError, match="plugins must be a mapping"):
            pstate.read_home_selection(tmp_path)


def test_a_missing_config_reads_as_none(tmp_path):
    assert pstate.read_home_selection(tmp_path) is None
