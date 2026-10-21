"""The chain's ``selected_git_env`` memo (``tests/_downstream/git_env_memo.py``, p10-suite S-B2)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pm
import pm.client
from hermes_cli import _subprocess_compat as compat
from tests._downstream import git_env_memo

REPO = Path(__file__).resolve().parents[1]


def test_the_memo_answers_what_ensure_would_and_a_removed_key_stays_removed():
    """Mutation: drop the removed-keys half (``env.pop``) → the second answer keeps ``GONE``."""

    calls: list = []

    def real(base):
        calls.append(dict(base))
        env = {k: v for k, v in base.items() if k != "GONE"}
        env["PATH"] = "pm-git;" + base.get("PATH", "")
        return env

    memo = git_env_memo._memo_delta(real)
    first = memo({"PATH": "p", "GONE": "x", "A": "1"})
    again = memo({"PATH": "p", "GONE": "x", "A": "2"})
    other_path = memo({"PATH": "q", "GONE": "x", "A": "3"})

    assert first == real({"PATH": "p", "GONE": "x", "A": "1"})
    assert again == {"PATH": "pm-git;p", "A": "2"}
    assert other_path == {"PATH": "pm-git;q", "A": "3"}, "a base with another PATH is never given the first PATH"
    assert len(calls) == 3  # first, other_path and the reference call; `again` was memoised


def test_a_test_that_patches_pm_ensure_sees_its_stub_every_time(monkeypatch):
    """Mutation: memoise without ``_pm_ensure``'s check → the stub is called once, not twice."""

    git_env_memo.install_if_imported()
    seen: list = []

    def stub(name, *, base_env):
        seen.append(name)
        return pm.Runner(name, {**base_env, "STUBBED": "1"})

    monkeypatch.setattr(pm, "ensure", stub)
    assert compat.selected_git_env({"PATH": "x"})["STUBBED"] == "1"
    assert compat.selected_git_env({"PATH": "x"})["STUBBED"] == "1"
    assert seen == ["git", "git"]


def test_a_test_that_patches_selected_git_env_keeps_its_stub(monkeypatch):
    """Mutation: install wraps whatever sits on the module → the stub is wrapped and stops being called."""

    from tools import checkpoint_manager

    stub = lambda base=None: {"STUB": "1"}
    monkeypatch.setattr(compat, "selected_git_env", stub)
    monkeypatch.setattr(checkpoint_manager, "selected_git_env", stub)
    git_env_memo.install_if_imported()

    assert compat.selected_git_env is stub and checkpoint_manager.selected_git_env is stub


def test_every_module_that_binds_selected_git_env_by_name_is_rebound():
    """A source walk (a NEGATIVE: no importer outside ``_CALLERS``). Mutation: drop
    ``tools.working_diff`` from ``_CALLERS`` → red."""

    tracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "*.py"], capture_output=True, text=True,
                             check=True).stdout.split()
    binders = set()
    for rel in tracked:
        if rel.startswith("tests/") or rel.startswith("hermes_cli/_subprocess_compat"):
            continue
        try:
            text = (REPO / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "selected_git_env" in text and "_subprocess_compat import" in text:
            binders.add(rel[:-3].replace("/", "."))
    assert binders and binders <= set(git_env_memo._CALLERS), binders - set(git_env_memo._CALLERS)


def test_a_stand_in_planted_deeper_in_pm_is_reached_on_every_call(monkeypatch):
    """``tests/tools/test_git_consumer_environment.py`` plants ``pm.install._installed_location`` and asserts
    it was reached. Mutation: ``_pm_patched`` returns False → the memo answers and the second call adds
    no reach."""

    import pm.install

    git_env_memo.install_if_imported()
    compat.selected_git_env({"PATH": "deeper"})  # the memo holds this base's delta
    compat.selected_git_env({"PATH": "deeper"})
    reached: list = []

    def unavailable(*args, **kwargs):
        reached.append(True)
        raise pm.InstallError("git", "managed Git unavailable")

    monkeypatch.setattr(pm.install, "_installed_location", unavailable)
    compat.selected_git_env({"PATH": "deeper"})
    first = len(reached)
    compat.selected_git_env({"PATH": "deeper"})

    assert first and len(reached) > first
