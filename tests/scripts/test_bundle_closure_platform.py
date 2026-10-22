"""The closure walk skips imports a platform branch makes unreachable on the bundle's target.

PKG-CLOSURE-PLATFORM-GUARDED-IMPORTS: ``stage --target linux-x64`` refused to build because the walk
counted ``tools/mcp_tool_loop.py``'s Windows-path ``import portalocker`` (after an
``if os.name == "posix": ...; return``) as a load the Linux bundle must satisfy.
"""

import ast
import textwrap

from scripts import bundle_profile_closure as closure
from scripts.bundles.targets import marker_env
from scripts.bundles.closure_platform import dead_for_target

SOURCE = textwrap.dedent('''
    import os, sys, platform

    def lock(fh):
        if os.name == "posix":
            import fcntl
            return True
        import portalocker

    def append(path):
        if os.name == "nt":
            import win32file
            return
        import posix_only

    def other():
        if sys.platform.startswith("win"):
            import winreg
        elif platform.system() != "Darwin":
            import linux_or_bsd
        if not sys.platform == "darwin":
            import not_mac
        if some_flag:
            import unknown_branch
''')


def _live(env):
    tree = ast.parse(SOURCE)
    dead = dead_for_target(tree, env)
    return {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) and id(node) not in dead
            for alias in node.names}


def test_a_posix_target_drops_the_windows_paths():
    live = _live(marker_env("linux-x64", "3.14"))
    assert {"fcntl", "posix_only", "linux_or_bsd", "not_mac", "unknown_branch"} <= live
    assert not {"portalocker", "win32file", "winreg"} & live


def test_the_windows_target_keeps_them_and_drops_the_posix_paths():
    live = _live(marker_env("win32-x64", "3.14"))
    assert {"portalocker", "win32file", "winreg", "not_mac", "unknown_branch"} <= live
    assert not {"fcntl", "posix_only"} & live


def test_macos_drops_its_own_negations():
    live = _live(marker_env("darwin-arm64", "3.14"))
    assert {"fcntl", "posix_only", "unknown_branch"} <= live
    assert not {"portalocker", "win32file", "winreg", "linux_or_bsd", "not_mac"} & live


def test_the_walk_reads_the_target_and_caches_per_target(tmp_path, monkeypatch):
    path = tmp_path / "locks.py"
    path.write_text(SOURCE, encoding="utf-8")
    monkeypatch.setattr(closure, "_IMPORTS_CACHE", {})

    def imported(target):
        monkeypatch.setattr(closure, "TARGET_ENV", marker_env(target, "3.14"))
        return {row[0] for row in closure._imports(path, "locks", False)}

    linux, windows = imported("linux-x64"), imported("win32-x64")
    assert "portalocker" not in linux and "fcntl" in linux
    assert "portalocker" in windows and "fcntl" not in windows
