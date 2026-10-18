"""``agent_runtime/bash_resolution_memo.py``: a bash ``_find_bash`` resolved once is not re-probed per command.

Upstream ``pm.shell.bash()`` spawns a ``bash -c "exit 0"`` probe on every call and
``tools.environments.local._find_bash`` calls it for every local-backend command.
"""

from __future__ import annotations

import pm.shell
import pytest

from agent_runtime import bash_resolution_memo
from agent_runtime.bash_resolution_memo import memoize_find_bash


@pytest.fixture
def resolver(tmp_path, monkeypatch):
    """A fake ``pm.shell.bash`` that counts its calls and answers a real file."""
    bash = tmp_path / "bash.exe"
    bash.write_text("", encoding="utf-8")
    calls: list[str] = []

    def fake_bash():
        calls.append("probe")
        return str(bash)

    monkeypatch.setattr(pm.shell, "bash", fake_bash)

    def find():
        found = pm.shell.bash()
        if found:
            return found
        raise RuntimeError("No shell found.")

    return memoize_find_bash(find), bash, calls


def test_the_local_backend_resolves_bash_through_the_memo():
    from tools.environments import local

    assert getattr(local._find_bash, "__fork_memo__", False)


def test_a_resolved_bash_is_not_probed_again(resolver):
    find, bash, calls = resolver
    assert find() == find() == str(bash)
    assert calls == ["probe"]


def test_a_changed_path_resolves_again(resolver, monkeypatch, tmp_path):
    find, _bash, calls = resolver
    find()
    monkeypatch.setenv("PATH", str(tmp_path))
    find()
    assert calls == ["probe", "probe"]


def test_a_vanished_bash_resolves_again(resolver):
    find, bash, calls = resolver
    find()
    bash.unlink()
    find()
    assert calls == ["probe", "probe"]


def test_a_replaced_resolver_is_asked_afresh(resolver, monkeypatch):
    find, _bash, _calls = resolver
    find()
    monkeypatch.setattr(pm.shell, "bash", lambda: None)
    with pytest.raises(RuntimeError, match="No shell found"):
        find()


def test_a_miss_is_never_remembered(resolver, monkeypatch):
    find, bash, calls = resolver
    answers = iter([None, str(bash)])

    def flaky():
        calls.append("probe")
        return next(answers)

    monkeypatch.setattr(pm.shell, "bash", flaky)
    with pytest.raises(RuntimeError):
        find()
    assert find() == str(bash)
    assert find() == str(bash) and calls == ["probe", "probe"]


def test_clear_forgets(resolver):
    find, _bash, calls = resolver
    find()
    bash_resolution_memo.clear()
    find()
    assert calls == ["probe", "probe"]
