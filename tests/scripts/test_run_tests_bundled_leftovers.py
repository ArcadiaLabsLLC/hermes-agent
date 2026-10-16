"""A gate run names the hermes update processes it started that outlive it (fork-hygiene 2026-10-15)."""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from scripts import run_tests_bundled as bundled

lo = bundled._leftovers
NOW = 1_000_000.0


@pytest.mark.parametrize("cmdline", [
    ["python.exe", "-m", "hermes_cli.main", "update", "--yes", "--gateway", "--branch", "main", "--keep-stash"],
    ["python.exe", "-I", "-c", "import hermes_bootstrap, runpy; runpy.run_module('hermes_cli.main')", "update"],
    [r"C:\x\venv\Scripts\hermes.exe", "update", "--yes"],
])
def test_an_orphaned_update_started_in_the_run_is_named(cmdline):
    found = lo.match([lo.Proc(7, NOW + 5, cmdline, parent_alive=False)], NOW)
    assert [p.pid for p in found] == [7]
    assert lo.lines(found)[0].startswith("=== ⚠ OUTLIVED THE RUN: 1")


@pytest.mark.parametrize("proc", [
    lo.Proc(1, NOW + 5, ["python", "-m", "hermes_cli.main", "update"], parent_alive=True),  # still owned
    lo.Proc(2, NOW - 60, ["python", "-m", "hermes_cli.main", "update"], parent_alive=False),  # older than the run
    lo.Proc(3, NOW + 5, ["python", "-m", "hermes_cli.main", "gateway", "run"], parent_alive=False),  # not an update
    lo.Proc(4, NOW + 5, ["git", "update-index"], parent_alive=False),
])
def test_an_owned_older_or_other_process_is_not(proc):
    assert lo.match([proc], NOW) == []
    assert lo.lines([]) == []


@pytest.mark.timeout(60)
def test_scan_finds_a_real_orphan_of_the_shape(tmp_path):
    """Positive control through psutil: a live child whose parent has exited."""
    pytest.importorskip("psutil")
    started = time.time()
    marker = tmp_path / "pid.txt"
    # The parent starts a sleeper whose argv carries the update shape (the words are only
    # sys.argv to it, nothing runs hermes) and exits at once, orphaning it.
    spawner = (
        "import subprocess, sys; "
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)', "
        "'-m', 'hermes_cli.main', 'update', '--yes'], "
        "creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0)); "
        f"open(r'{marker}', 'w').write(str(p.pid))"
    )
    subprocess.run([sys.executable, "-c", spawner], check=True, timeout=30)
    pid = int(marker.read_text())
    try:
        found = {p.pid for p in lo.scan(started)}
        assert pid in found
    finally:
        import psutil

        try:
            psutil.Process(pid).kill()
        except psutil.Error:
            pass
