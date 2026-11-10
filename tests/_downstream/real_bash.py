"""The one fork-owned answer to "which bash really runs scripts here" (FH-TEST-BASH-RESOLVER-DUPLICATES).

On Windows ``CreateProcess`` and ``shutil.which`` can answer ``bash`` with System32's WSL
launcher (a UTF-16 "no installed distributions" notice, exit 1, or a distro that re-parses
the argv) or the MSIX copy under ``WindowsApps`` (WinError 5 outside its package). Neither
runs the repo's scripts; Git for Windows' bash does. Elsewhere the PATH bash is real.

Fork-owned tests ask :func:`resolve_real_bash` (or :func:`real_bash_or_skip`) instead of
growing a private resolver or spawning a bare ``bash``;
``tests/tooling/test_fork_tests_spawn_no_bare_bash.py`` refuses a bare ``bash`` argv in a
fork-owned test. Upstream's own resolvers (``tests/conftest.py::real_bash``,
``tests/pm/activation_support.py::bash``) are upstream's files and keep their bodies; this
rule is theirs, so the two agree.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

#: Path fragments of a Windows ``bash`` that is not a POSIX shell for the repo's scripts.
_NOT_A_SCRIPT_BASH = ("system32", "windowsapps")
#: Git for Windows' bash, relative to ``%ProgramFiles%``, in preference order.
_GIT_BASH_RELS = (("Git", "bin", "bash.exe"), ("Git", "usr", "bin", "bash.exe"))


def resolve_real_bash(
    *,
    platform: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
    program_files: str | None = None,
    exists: Callable[[Path], bool] = Path.is_file,
) -> str | None:
    """The bash that runs the repo's scripts, or None when this host has none.

    The host is injectable (``platform``, ``which``, ``program_files``, ``exists``) so the
    Windows rule is unit-testable on any host.
    """

    platform = sys.platform if platform is None else platform
    found = which("bash")
    if platform != "win32":
        return found
    if found and not any(marker in found.lower() for marker in _NOT_A_SCRIPT_BASH):
        return found
    root = Path(program_files or os.environ.get("ProgramFiles") or r"C:\Program Files")
    for rel in _GIT_BASH_RELS:
        candidate = root.joinpath(*rel)
        if exists(candidate):
            return str(candidate)
    return None


def real_bash_or_skip() -> str:
    """:func:`resolve_real_bash`, or skip the calling test where the host has no POSIX bash."""

    found = resolve_real_bash()
    if found is None:
        import pytest

        pytest.skip("no POSIX bash on this host (a Windows bash here is WSL's launcher or the MSIX copy)")
    return found
