"""The test seal (``tests/_downstream/seal.py``, row FH-ONE-TEST-SEAL): what a test sees of the
machine, and what it may leave running."""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from tests._downstream import seal

REPO = Path(__file__).resolve().parents[2]


# ── (b) home ─────────────────────────────────────────────────────────────────


def test_the_fork_platform_root_is_this_tests_folder(tmp_path):
    from agent_runtime import host_tools, resolution

    assert host_tools.platform_default_root().parent == tmp_path
    # the resolver the runtime reads through, with no HERMES_HOME
    assert resolution._default_hermes_root({}).parent == tmp_path


def test_a_test_that_moves_home_still_gets_its_own_layout(monkeypatch, tmp_path):
    from agent_runtime import host_tools

    monkeypatch.setenv("HOME", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "elsewhere"))
    assert host_tools.platform_default_root().parent == tmp_path / "elsewhere"


def test_no_fork_module_binds_the_platform_root_by_name():
    """A ``from .host_tools import platform_default_root`` keeps the unsealed function, so the
    seal's pin would not reach that module (a source walk proves only this negative)."""
    found = []
    for root in ("agent_runtime", "hermes_cli", "plugins", "pm"):
        for path in (REPO / root).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("host_tools"):
                    if any(alias.name == "platform_default_root" for alias in node.names):
                        found.append(f"{path.relative_to(REPO).as_posix()}:{node.lineno}")
    assert not found, "read the root as host_tools.platform_default_root(...): " + ", ".join(found)


# ── (c) launch arguments ─────────────────────────────────────────────────────


def test_a_test_sees_no_launch_arguments():
    assert sys.argv[1:] == []


# ── (d) leftovers ────────────────────────────────────────────────────────────


def _run_planted(tmp_path: Path, body: str, *, sealed: bool) -> subprocess.CompletedProcess:
    """Run one planted test file in a child pytest, its folder sealed or not."""
    folder = REPO / "tests" / "_downstream" / "_seal_planted"
    folder.mkdir(exist_ok=True)
    planted = folder / f"test_planted_{os.getpid()}_{threading.get_ident()}.py"
    planted.write_text(textwrap.dedent(body), encoding="utf-8")
    roots = tmp_path / "roots.txt"
    roots.write_text("tests/_downstream/_seal_planted/\n" if sealed else "", encoding="utf-8")
    env = {**os.environ, "HERMES_TEST_SEAL_ROOTS": str(roots)}
    try:
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly",
             str(planted.relative_to(REPO))],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=240,
        )
    finally:
        planted.unlink(missing_ok=True)
        try:
            folder.rmdir()
        except OSError:
            pass


_LEAKS = """
    import subprocess, sys, threading

    def test_leaves_a_thread():
        stop = threading.Event()
        threading.Thread(target=stop.wait, args=(30,), name="planted-leak", daemon=True).start()

    def test_leaves_a_child():
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])

    def test_cleans_up():
        stop = threading.Event()
        thread = threading.Thread(target=stop.wait, args=(30,), daemon=True)
        thread.start()
        stop.set()
        thread.join()
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
"""


def test_a_leftover_in_a_sealed_folder_fails_its_test_and_the_child_is_killed(tmp_path):
    result = _run_planted(tmp_path, _LEAKS, sealed=True)
    out = result.stdout + result.stderr
    assert result.returncode == 1, out
    assert "3 passed, 2 errors" in out, out
    assert "thread 'planted-leak' started at tests/_downstream/_seal_planted/" in out, out
    assert re.search(r"child pid \d+ \(python[\d.]*\) started at tests/_downstream/_seal_planted/", out), out


def test_a_leftover_elsewhere_is_reported_and_left_alone(tmp_path):
    result = _run_planted(tmp_path, _LEAKS, sealed=False)
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert out.count(seal.LEFTOVER_REPORT) == 2, out
    assert "test_cleans_up" not in out.split("test-seal", 1)[-1], out


def test_the_sealed_roots_list_names_real_folders_and_files():
    for root in seal.SEALED_ROOTS:
        assert (REPO / root).is_file() if root.endswith(".py") else (REPO / root).is_dir(), root


def test_a_listed_file_seals_that_file_only(monkeypatch, tmp_path):
    roots = tmp_path / "roots.txt"
    roots.write_text("tests/a/test_one.py  # one file\ntests/b\n", encoding="utf-8")
    monkeypatch.setattr(seal, "SEALED_ROOTS_PATH", roots)
    monkeypatch.setattr(seal, "SEALED_ROOTS", seal._read_sealed_roots())
    assert seal.is_sealed("tests/a/test_one.py")
    assert not seal.is_sealed("tests/a/test_two.py")
    assert seal.is_sealed("tests/b/test_any.py") and not seal.is_sealed("tests/bc/test_any.py")
