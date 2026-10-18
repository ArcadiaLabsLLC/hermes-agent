"""Control for hermes_cli/git_line_endings.py and its one-line seam in noninteractive_git_env.

Killing mutation: delete the ``# fork seam: r-plugins`` lines in
``hermes_cli/_subprocess_compat.noninteractive_git_env`` -> ``test_crlf_checkout_reads_clean_*``
reds (the isolated status reports the committed file as modified).
"""

from __future__ import annotations

import os
import subprocess
import time

import pytest

from hermes_cli import git_line_endings
from hermes_cli._subprocess_compat import noninteractive_git_env


def _config(path, body):
    path.write_text(body, encoding="utf-8")
    return str(path)


@pytest.fixture
def user_config(tmp_path, monkeypatch):
    """System and global git config files the test owns; HOME redirected."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("GIT_CONFIG_NOSYSTEM", raising=False)
    system = tmp_path / "system.gitconfig"
    global_ = tmp_path / "global.gitconfig"
    system.write_text("", encoding="utf-8")
    global_.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(system))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_))
    git_line_endings._cache.clear()
    return system, global_


def test_global_overrides_system_and_unknown_values_are_dropped(user_config):
    system, global_ = user_config
    _config(system, "[core]\n\tautocrlf = true\n\teol = crlf\n")
    _config(global_, "[core]\n\tautocrlf = input\n\teol = sideways\n")
    assert git_line_endings.user_line_ending_overrides() == [("core.autocrlf", "input"), ("core.eol", "crlf")]


def test_no_line_ending_config_adds_nothing(user_config):
    assert git_line_endings.user_line_ending_overrides() == []


def test_isolated_env_replays_only_the_line_ending_keys(user_config):
    system, _ = user_config
    _config(system, "[core]\n\tautocrlf = true\n\thooksPath = /evil\n")
    env = noninteractive_git_env()
    pairs = [(env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"]) for i in range(int(env["GIT_CONFIG_COUNT"]))]
    assert ("core.autocrlf", "true") in pairs
    assert ("core.hooksPath", "/evil") not in pairs
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull


def test_crlf_checkout_reads_clean_to_the_isolated_status(user_config, tmp_path):
    """Git for Windows' default (system ``core.autocrlf=true``): a file the user committed reads clean."""
    system, _ = user_config
    _config(system, "[core]\n\tautocrlf = true\n")
    repo = tmp_path / "repo"
    user_env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=user_env)
    target = repo / "a.txt"
    target.write_bytes(b"one\r\ntwo\r\n")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True, env=user_env)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=repo, check=True, env=user_env)
    later = time.time() + 5  # stale stat: status must re-read the content
    os.utime(target, (later, later))
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True,
                            env=noninteractive_git_env(), check=True)
    assert status.stdout == ""
