"""The suite never re-runs ``hermes update`` inside the install that owns its interpreter.

``tests/_downstream/conftest_plugin.py::_no_owning_install_retarget`` replaces
``retarget_to_owning_install`` for every test. The proof builds the exact state
that escaped on 2026-09-28 — a venv whose owning checkout is not the project
root — and asserts that ``cmd_update``'s own call returns instead of spawning.
Delete the fixture and this goes red on the spawn.
"""

from __future__ import annotations

import subprocess
import sys

from hermes_cli import update_owning_install


def test_cmd_update_retarget_never_spawns_the_owning_install(tmp_path, monkeypatch):
    owner = tmp_path / "primary"
    (owner / "hermes_cli").mkdir(parents=True)
    (owner / "hermes_cli" / "main.py").write_text("", encoding="utf-8")
    (owner / "venv").mkdir()
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(sys, "prefix", str(owner / "venv"))
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "python"))
    monkeypatch.delenv("PYTHONPATH", raising=False)
    spawned: list[object] = []
    monkeypatch.setattr(subprocess, "call", lambda *a, **k: spawned.append(a) or 0)

    # Positive control: the state really is a redirected install.
    assert update_owning_install.owning_install_root(worktree) == owner.resolve()

    update_owning_install.retarget_to_owning_install(worktree)

    assert spawned == []
