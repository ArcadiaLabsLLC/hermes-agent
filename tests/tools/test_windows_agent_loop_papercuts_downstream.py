"""Fork half of ``tests/tools/test_windows_agent_loop_papercuts.py`` (PR #123892, shell-hook script paths).

The two tests the carried PR adds to upstream's file live here so upstream's file keeps upstream's
bytes (FH-FOOTPRINT-FORK-TEST-HUNKS-OUT); they move back with the PR when it merges.
"""

import pytest


class TestShellHooksWindowsPathsDownstream:
    """#78293 follow-up — the path-like token of a hook command is the real script."""

    @pytest.mark.platforms("windows")
    def test_interpreter_prefixed_backslash_path_is_the_script(self, tmp_path):
        """A backslash path with an extension outside the script list (``.vbs``) is still the
        path-like token, so the approval mtime and the runnable check see the real file."""
        from agent.shell_hooks import script_is_executable, script_mtime_iso

        script = tmp_path / "guard.vbs"
        script.write_text("WScript.Quit 0\n", encoding="utf-8")
        command = f"cscript {script}"

        assert script_mtime_iso(command) == script_mtime_iso(str(script)) is not None
        assert script_is_executable(command)

    @pytest.mark.platforms("windows")
    def test_a_path_argument_before_the_script_does_not_hijack_it(self, tmp_path):
        """A path-valued argument ahead of ``-File`` must not become the monitored script."""
        from agent.shell_hooks import _command_script_path

        for name in ("guard.ps1", "guard.bat", "guard.cmd"):
            script = tmp_path / name
            command = f"powershell -NoProfile -Tag {tmp_path / 'tags.txt'} -File {script}"
            assert _command_script_path(command) == str(script)
