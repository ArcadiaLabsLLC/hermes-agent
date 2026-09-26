"""Windows Git Bash resolution — the WSL-stub-avoidance contract.

The bug these tests lock down: with Git Bash unprovisioned, ``_find_bash`` used
to fall through to ``shutil.which("bash")`` which resolves to
``C:\\Windows\\System32\\bash.exe`` — the WSL launcher — so every agent terminal
call invoked ``wsl`` and failed on a normal Windows host.

All tests run on POSIX CI: they build real fake directory trees under
``tmp_path`` and point the Windows env vars at them, mocking only
``shutil.which`` for the ``git`` / ``bash`` lookups.
"""

import os

import pytest

from tools.environments import local
from tools.environments.local import (
    _WINDOWS_PATH_SEP,
    _augment_windows_system_path,
    _find_bash,
    _windows_system_path_dirs,
)


class TestFindWindowsGitBash:
    """Bash discovery moved to upstream's ``pm.shell`` at the 2026-09-25 merge.

    The candidate ladder (Program Files Git, per-user and 32-bit roots, the
    portable Git under ``%LOCALAPPDATA%/hermes/git``, stub rejection) is
    upstream's and pinned by ``tests/pm/test_shell_candidates.py``; the fork's
    own ordering (portable Git and git-derived bash first) left with the fork's
    ``_windows_bash_candidates``. What stays pinned here: ``_find_bash`` asks pm
    and fails loudly instead of falling through to the WSL stub, and an
    operator's ``HERMES_GIT_BASH_PATH`` outranks every discovered install.
    """

    def test_find_bash_raises_when_pm_finds_no_shell(self, monkeypatch):
        import pm.shell

        monkeypatch.setattr(pm.shell, "bash", lambda: None)
        with pytest.raises(RuntimeError, match="No shell found"):
            _find_bash()

    def test_find_bash_returns_pm_answer(self, monkeypatch):
        import pm.shell

        chosen = r"C:\Program Files\Git\bin\bash.exe"
        monkeypatch.setattr(pm.shell, "bash", lambda: chosen)
        assert _find_bash() == chosen

    def test_wsl_stub_only_yields_no_candidate(self):
        from pm.shell import windows_bash_candidates

        stub = r"C:\Windows\System32\bash.exe"
        assert stub not in windows_bash_candidates(stub, {"ProgramFiles": r"D:\Progs"})

    def test_hermes_git_bash_path_takes_precedence(self):
        from pm.shell import windows_bash_candidates

        override = r"E:\custom\bash.exe"
        candidates = windows_bash_candidates(
            r"C:\msys64\usr\bin\bash.exe",
            {
                "ProgramFiles": r"D:\Progs",
                "LOCALAPPDATA": r"C:\Users\u\AppData\Local",
                "HERMES_GIT_BASH_PATH": override,
            },
        )
        assert candidates[0] == override


class TestWindowsSystemPathAugmentation:
    """The agent must be able to reach powershell.exe / cmd.exe / pwsh from its
    bash terminal even under a minimal gateway PATH.

    These drive the WINDOWS branch of ``_augment_windows_system_path`` (which
    is a documented no-op off Windows), so the fixture pins ``_IS_WINDOWS``.
    They split on ``_WINDOWS_PATH_SEP`` and never on ``os.pathsep``: on POSIX
    CI ``os.pathsep`` is ``:``, which cuts ``C:\\some\\proj\\bin`` in half at
    the drive letter and reduces the first assertion to ``'C'``.
    """

    @pytest.fixture
    def fake_windows(self, tmp_path, monkeypatch):
        win = tmp_path / "Windows"
        system32 = win / "System32"
        psdir = system32 / "WindowsPowerShell" / "v1.0"
        pwsh7 = tmp_path / "Program Files" / "PowerShell" / "7"
        for d in (system32, psdir, pwsh7, system32 / "Wbem", system32 / "OpenSSH"):
            d.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(local, "_IS_WINDOWS", True)
        monkeypatch.setenv("SystemRoot", str(win))
        monkeypatch.setenv("ProgramFiles", str(tmp_path / "Program Files"))
        monkeypatch.delenv("ProgramW6432", raising=False)
        monkeypatch.delenv("ProgramFiles(x86)", raising=False)
        return {"system32": str(system32), "psdir": str(psdir), "pwsh7": str(pwsh7)}

    def test_appends_missing_system_dirs(self, fake_windows):
        result = _augment_windows_system_path(r"C:\some\proj\bin")
        entries = result.split(_WINDOWS_PATH_SEP)
        # Caller entry preserved and still first (precedence untouched).
        assert entries[0] == r"C:\some\proj\bin"
        # PowerShell 5.1, cmd (System32), and pwsh 7 all reachable now.
        assert fake_windows["system32"] in entries
        assert fake_windows["psdir"] in entries
        assert fake_windows["pwsh7"] in entries

    def test_does_not_duplicate_present_dirs(self, fake_windows):
        existing = _WINDOWS_PATH_SEP.join([fake_windows["system32"], r"C:\proj"])
        result = _augment_windows_system_path(existing)
        # System32 already present (case/if slash-variant) is not re-appended.
        occurrences = [
            e for e in result.split(_WINDOWS_PATH_SEP)
            if os.path.normcase(e.rstrip("\\/")) == os.path.normcase(fake_windows["system32"])
        ]
        assert len(occurrences) == 1

    def test_only_existing_dirs_are_added(self, tmp_path, monkeypatch):
        # SystemRoot points at a dir with no System32 → nothing bogus appended.
        monkeypatch.setattr(local, "_IS_WINDOWS", True)
        monkeypatch.setenv("SystemRoot", str(tmp_path / "empty"))
        monkeypatch.setenv("ProgramFiles", str(tmp_path / "none"))
        monkeypatch.delenv("ProgramW6432", raising=False)
        monkeypatch.delenv("ProgramFiles(x86)", raising=False)
        assert _windows_system_path_dirs() == []
        assert _augment_windows_system_path(r"C:\proj") == r"C:\proj"

    def test_off_windows_it_is_a_no_op(self, fake_windows, monkeypatch):
        """The guard stated on its own: the caller PATH comes back byte-identical
        even though every fake system dir exists and would otherwise be added."""
        monkeypatch.setattr(local, "_IS_WINDOWS", False)
        assert _augment_windows_system_path(r"C:\some\proj\bin") == r"C:\some\proj\bin"
