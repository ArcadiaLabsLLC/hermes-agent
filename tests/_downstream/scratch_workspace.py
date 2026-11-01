"""A scratch git workspace for a test whose prompt build probes the agent's cwd (D3.16 audit).

``agent/coding_context.py``'s workspace block runs ``git -C <cwd> status --porcelain=2 --branch``
on every system-prompt build. A test that never names a cwd lets it resolve to the launch dir --
the checkout -- so the probe ran against this repository, kept off ``index.lock`` only by the
root conftest's ``GIT_OPTIONAL_LOCKS=0`` (rows ``FH-GIT-AUDIT-*-STATUS``). The workspace is a
code workspace (a ``pyproject.toml`` marker, one commit) so the coding posture still renders,
and ``TERMINAL_CWD`` -- the configured cwd every surface's agent resolves first
(``agent.runtime_cwd.resolve_agent_cwd``) -- names it.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

__all__ = ["scratch_git_workspace"]

_IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def scratch_git_workspace(tmp_path: Path, monkeypatch) -> Path:
    """Make ``<tmp_path>/workspace`` a committed git code workspace and the agent's cwd."""

    repo = tmp_path / "workspace"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nname = "scratch"\n', encoding="utf-8")
    env = {**os.environ, **_IDENTITY}
    for args in (["init", "-q"], ["add", "pyproject.toml"], ["commit", "-q", "-m", "seed"]):
        subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)
    monkeypatch.setenv("TERMINAL_CWD", str(repo))
    return repo
