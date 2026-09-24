"""Fork-owned tests moved out of ``tests/hermes_cli/test_dep_ensure.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from unittest.mock import patch


def test_ensure_git_bash_posix_is_noop_returning_bash():
    from hermes_cli.dep_ensure import ensure_git_bash
    with patch("hermes_cli.dep_ensure._IS_WINDOWS", False), \
         patch("hermes_cli.dep_ensure.shutil") as mock_shutil:
        mock_shutil.which.return_value = "/usr/bin/bash"
        assert ensure_git_bash(interactive=False) == "/usr/bin/bash"


def test_ensure_git_bash_windows_resolves_and_persists():
    from hermes_cli.dep_ensure import ensure_git_bash
    bash = r"C:\Program Files\Git\bin\bash.exe"
    persisted = {}
    with patch("hermes_cli.dep_ensure._IS_WINDOWS", True), \
         patch("hermes_cli.dep_ensure._resolve_windows_git_bash", return_value=bash), \
         patch("hermes_cli.windows_env.set_user_env",
               side_effect=lambda name, value: persisted.setdefault(name, value) or True), \
         patch("hermes_cli.windows_env.broadcast_environment_change") as mock_bcast:
        result = ensure_git_bash(interactive=False)
    assert result == bash
    assert persisted["HERMES_GIT_BASH_PATH"] == bash
    assert mock_bcast.called


def test_ensure_git_bash_windows_falls_back_to_install_then_reresolves():
    from hermes_cli import dep_ensure
    bash = r"C:\Users\x\AppData\Local\hermes\git\bin\bash.exe"
    resolves = iter([None, bash])  # first miss, then present after install
    install_calls = []
    with patch("hermes_cli.dep_ensure._IS_WINDOWS", True), \
         patch("hermes_cli.dep_ensure._resolve_windows_git_bash",
               side_effect=lambda: next(resolves)), \
         patch.object(dep_ensure, "ensure_dependency",
                      side_effect=lambda dep, interactive=True: install_calls.append(dep) or True), \
         patch("hermes_cli.windows_env.set_user_env", return_value=True), \
         patch("hermes_cli.windows_env.broadcast_environment_change"):
        result = dep_ensure.ensure_git_bash(interactive=False)
    assert result == bash
    assert install_calls == ["git"]


def test_ensure_git_bash_windows_returns_none_when_unprovisionable():
    from hermes_cli import dep_ensure
    with patch("hermes_cli.dep_ensure._IS_WINDOWS", True), \
         patch("hermes_cli.dep_ensure._resolve_windows_git_bash", return_value=None), \
         patch.object(dep_ensure, "ensure_dependency", return_value=False), \
         patch("hermes_cli.windows_env.set_user_env") as mock_set:
        result = dep_ensure.ensure_git_bash(interactive=False)
    assert result is None
    assert not mock_set.called  # nothing persisted on failure
