r"""Fork-owned harness for the ``scripts/install.sh`` tests on a Windows host.

The upstream tests hand a bare ``"bash"`` to ``subprocess``. On POSIX that is a
PATH lookup. On Windows ``CreateProcess`` searches ``System32`` BEFORE ``PATH``,
so a bare ``bash`` lands on ``C:\Windows\System32\bash.exe`` — the WSL
launcher — whatever ``PATH`` says. WSL bash cannot open a Windows path
(``X:\wt\...\install.sh`` arrives as ``X:wt...install.sh``), so every test
that drives ``install.sh`` failed with ``No such file or directory`` while the
tests that already resolve ``shutil.which("bash")`` (Git for Windows' bash,
which does take a Windows path) passed on the same box.

This conftest makes a bare ``bash`` resolve the way the tests mean it to: by
``PATH``, exactly as on POSIX. It rewrites nothing else, touches no upstream
file, and is inert on POSIX hosts and on a Windows host whose ``PATH`` has no
bash of its own. That alone turned 21 of the 43 reds green on this box.

The other 19 — and three node-probe tests that PASS under the PATH bash only
by accident, writing their HERMES_HOME into a PUA-named directory in the
checkout root because the path in their generated driver lost its
backslashes — cannot pass on ANY Windows host, whichever bash runs them, and
each carries its reason in ``POSIX_HOST_ONLY`` below. Upstream's own shape for
such a test is ``@pytest.mark.platforms("linux")`` (already used in this directory);
these files are upstream's, so the fork cannot add the marker, and the map is
the stand-in. It retires entry by entry as upstream marks them. It is applied
on a Windows host only, so the Linux lane still runs every one of them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def path_bash_for(argv0: str, *, is_windows: bool, which=shutil.which) -> str | None:
    """The executable a bare ``bash`` argv0 should run, or None to leave it alone.

    Pure: the host is data (``is_windows``) and the PATH lookup is injected, so
    the rule is unit-testable on any host.
    """

    if not is_windows or argv0 not in ("bash", "bash.exe"):
        return None
    return which("bash")


_MINGW_REFUSAL = (
    "install.sh stops on a Windows host by design (uname CYGWIN*/MINGW*/MSYS* -> "
    "'Please use the PowerShell installer'), so its repository stage never runs here"
)
_PATH_IN_BASH_SOURCE = (
    "the test writes a Windows path into bash SOURCE (a `bash -c` body or a generated "
    "script); bash's own quoting eats the backslashes, so the path cannot survive"
)
_POSIX_FILESYSTEM = (
    "the test needs POSIX filesystem semantics a Windows host does not give: symlinks "
    "created by ln -s, or a shebang script executed directly"
)
_WSL_PATH = (
    "the test translates its script path to a WSL /mnt path, which only WSL bash reads, "
    "while WSL bash cannot take the Windows paths the rest of the harness hands it"
)

POSIX_HOST_ONLY: dict[str, str] = {
    "test_install_autostash_conflict_recovery.py::test_install_sh_repository_stage_recovers_from_autostash_conflict": _MINGW_REFUSAL,
    "test_install_autostash_conflict_recovery.py::test_install_sh_repository_stage_clean_apply_drops_stash": _MINGW_REFUSAL,
    "test_install_sh_acp_launcher.py::test_venv_install_writes_executable_acp_launcher": _PATH_IN_BASH_SOURCE,
    "test_install_sh_acp_launcher.py::test_non_venv_install_writes_acp_launcher": _PATH_IN_BASH_SOURCE,
    "test_install_sh_acp_launcher.py::test_acp_launcher_does_not_follow_a_symlink_into_the_venv": _PATH_IN_BASH_SOURCE,
    "test_install_sh_acp_launcher.py::test_venv_install_writes_executable_hermes_agent_launcher": _PATH_IN_BASH_SOURCE,
    "test_install_sh_bootstrap_marker.py::test_marker_matches_the_schema_the_desktop_validates": _PATH_IN_BASH_SOURCE,
    "test_install_sh_bootstrap_marker.py::test_marker_publish_leaves_no_temp_sibling": _PATH_IN_BASH_SOURCE,
    "test_install_sh_bootstrap_marker.py::test_explicit_commit_pin_wins_over_head": _PATH_IN_BASH_SOURCE,
    "test_install_sh_bootstrap_marker.py::test_no_marker_written_when_head_cannot_be_resolved": _PATH_IN_BASH_SOURCE,
    "test_install_sh_bootstrap_marker.py::test_missing_install_dir_is_not_fatal": _PATH_IN_BASH_SOURCE,
    "test_install_sh_node_deps_failure.py::test_root_node_dependency_failure_is_fatal": _PATH_IN_BASH_SOURCE,
    "test_install_sh_node_deps_failure.py::test_tui_node_dependency_failure_is_fatal": _PATH_IN_BASH_SOURCE,
    "test_install_sh_node_deps_failure.py::test_node_dependency_success_remains_successful": _PATH_IN_BASH_SOURCE,
    "test_install_sh_node_probe.py::test_broken_node_degrades_with_clear_error": _PATH_IN_BASH_SOURCE,
    "test_install_sh_node_probe.py::test_healthy_node_reports_success": _PATH_IN_BASH_SOURCE,
    "test_install_sh_node_probe.py::test_libatomic1_is_preinstalled_on_ubuntu": _PATH_IN_BASH_SOURCE,
    "test_install_macos_launcher.py::test_venv_launcher_bypasses_uv_console_script_that_requires_realpath": _POSIX_FILESYSTEM,
    "test_install_sh_symlink_stomp.py::test_re_running_setup_path_block_preserves_pip_entry_point": _POSIX_FILESYSTEM,
    "test_install_sh_termux_python_bounds.py::test_install_stage_provisions_supported_python_from_tur": _POSIX_FILESYSTEM,
    "test_install_sh_termux_python_bounds.py::test_setup_script_prefers_compatible_minor_over_unsupported_default": _POSIX_FILESYSTEM,
    "test_install_sh_uv_lock_config.py::test_locked_sync_helper_sanitizes_only_its_subprocess": _WSL_PATH,
}


def posix_host_only_reason(key: str, *, is_windows: bool) -> str | None:
    """The skip reason for ``<file>::<test>`` on this host, or None to run it. Pure."""

    return POSIX_HOST_ONLY.get(key) if is_windows else None


_HERE = Path(__file__).resolve().parent


def pytest_collection_modifyitems(config, items):
    # A conftest's collection hook sees the WHOLE session's items; act on this
    # directory's only.
    is_windows = sys.platform == "win32"
    for item in items:
        if Path(item.path).resolve().parent != _HERE:
            continue
        reason = posix_host_only_reason(f"{item.path.name}::{item.name}", is_windows=is_windows)
        if reason:
            item.add_marker(pytest.mark.skip(reason=f"POSIX host only: {reason}"))


_REAL_POPEN = subprocess.Popen


class _PathBashPopen(_REAL_POPEN):  # type: ignore[misc, valid-type]
    def __init__(self, args, *a, **kw):
        if isinstance(args, (list, tuple)) and args and not kw.get("shell"):
            resolved = path_bash_for(os.fspath(args[0]), is_windows=sys.platform == "win32")
            if resolved:
                args = [resolved, *args[1:]]
        super().__init__(args, *a, **kw)


@pytest.fixture(autouse=True, scope="module")
def bare_bash_resolves_by_path():
    """Module-scoped (autouse fixtures open first within a scope) so a
    module-scoped fixture that drives bash sees the resolution too; its own
    ``MonkeyPatch`` so the shared per-test instance is never touched."""

    if sys.platform != "win32" or shutil.which("bash") is None:
        yield
        return
    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(subprocess, "Popen", _PathBashPopen)
        yield
