"""Fork: a checkout's owner may live BESIDE it, at ``<parent>/.hermes`` (the Launcher's layout).

``owning_home_root`` looked only at the checkout's parent and the platform default, so a
sandbox ``HERMES_HOME`` (a Stage C session's) found no owner for ``X:/Eternia/hermes-agent``,
whose owner is ``X:/Eternia/.hermes``, and acted as the owner (runtime R623).

Killing mutation: drop the sibling candidate in ``pm.environments.owning_home_root`` ->
``test_a_sandbox_home_borrows_from_the_sibling_root`` reds (None).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pm.environments import install_key, owning_home_root

pytestmark = pytest.mark.platforms("any")


def _layout(tmp_path, monkeypatch) -> Path:
    import hermes_constants

    monkeypatch.setattr(hermes_constants, "_get_platform_default_hermes_home", lambda: tmp_path / "platform-default")
    root = tmp_path / "Eternia" / "hermes-agent"
    root.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='example'\n", encoding="utf-8")
    return root


def _state(data_root: Path, checkout: Path) -> None:
    facts = data_root / "installs" / install_key(checkout) / "facts.json"
    facts.parent.mkdir(parents=True, exist_ok=True)
    facts.write_text(json.dumps({"packages": {"venv": {"stamp": "complete"}}}), encoding="utf-8")


def _home(monkeypatch, path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(path))


def test_a_sandbox_home_borrows_from_the_sibling_root(tmp_path, monkeypatch):
    root = _layout(tmp_path, monkeypatch)
    _state(tmp_path / "Eternia" / ".hermes", root)
    _home(monkeypatch, tmp_path / "sandbox" / "hermes")
    assert owning_home_root(root) == tmp_path / "Eternia" / ".hermes"


def test_the_sibling_root_itself_is_the_owner_not_a_borrower(tmp_path, monkeypatch):
    root = _layout(tmp_path, monkeypatch)
    _state(tmp_path / "Eternia" / ".hermes", root)
    _home(monkeypatch, tmp_path / "Eternia" / ".hermes")
    assert owning_home_root(root) is None


def test_no_sibling_state_keeps_the_old_answer(tmp_path, monkeypatch):
    # Positive control: the same sandbox with no sibling state finds no owner.
    root = _layout(tmp_path, monkeypatch)
    _home(monkeypatch, tmp_path / "sandbox" / "hermes")
    assert owning_home_root(root) is None
