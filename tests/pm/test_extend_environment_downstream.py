"""``pm._fork_extend_environment``: one extra INTO the running environment (w1015b-con-x).

Owner ruling 2026-10-15: install in place; a resolver conflict tells the caller to build a
new generation; a held file (os error 32) is waited out before it raises.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


class _Engine:
    def __init__(self, replies):
        self.replies, self.commands = list(replies), []

    def _run(self, command, *, cwd, timeout):
        self.commands.append(command)
        code, stderr = self.replies.pop(0)
        return subprocess.CompletedProcess(command, code, "", stderr)


@pytest.fixture
def engine(monkeypatch, tmp_path):
    import pm.environment
    import pm.environments
    import pm.operations

    def use(*replies):
        fake = _Engine(replies)
        monkeypatch.setattr(pm.environment, "managed_environment", lambda *a, **k: fake)
        monkeypatch.setattr(pm.environments, "venv_python", lambda venv: Path(venv) / "python")
        monkeypatch.setattr(pm.operations, "_require_install_allowed", lambda explicit: None)
        monkeypatch.setattr("time.sleep", lambda _: None)
        return fake
    return use


def test_pm_extends_the_environment_in_place_and_waits_out_a_held_file(engine, tmp_path):
    from pm._fork_extend_environment import extend_environment

    fake = engine((2, "failed to remove directory x.data (os error 32)"), (0, ""))
    assert extend_environment(["anthropic==0.87.0"], environment=tmp_path, explicit=True) is True
    assert len(fake.commands) == 2
    assert fake.commands[0][:4] == ["pip", "install", "--python", str(tmp_path.absolute() / "python")]


def test_pm_answers_a_resolver_conflict_with_false(engine, tmp_path):
    from pm._fork_extend_environment import extend_environment

    engine((1, "No solution found when resolving dependencies"))
    assert extend_environment(["anthropic==0.87.0"], environment=tmp_path, explicit=True) is False
