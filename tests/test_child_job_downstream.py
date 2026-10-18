"""``tests/_downstream/child_job.py``: a marked test's child dies with a timeout's ``os._exit``.

A real pytest process runs a one-test file that starts a sleeping child, records its
pid and ends with ``os._exit`` -- what pytest-timeout's ``thread`` method does after it
dumps the stacks, called directly so the order does not race the timer. Marked, the
child is gone once that process is; unmarked (the control that proves the check can see
a survivor), it is still running.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

psutil = pytest.importorskip("psutil")

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows-only")

_REPO = Path(__file__).resolve().parents[1]

_INNER = '''
import os, subprocess, sys
from pathlib import Path
import pytest

{mark}
def test_dies_like_a_timeout():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    Path({pid_file!r}).write_text(str(child.pid))
    os._exit(1)
'''


def _orphan_after_exit(tmp_path: Path, mark: str) -> int | None:
    """Run the inner test to its ``os._exit``; the child's pid if it is still alive, else None."""

    tmp_path.mkdir(parents=True)
    pid_file = tmp_path / "child.pid"
    inner = tmp_path / "test_inner.py"
    inner.write_text(_INNER.format(mark=mark, pid_file=str(pid_file)), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(_REPO)}
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "tests._downstream.child_job",
         "--rootdir", str(tmp_path), "-c", os.devnull, str(inner)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=90, check=False,
    )
    assert pid_file.exists(), run.stdout + run.stderr
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not psutil.pid_exists(pid):
            return None
        time.sleep(0.1)
    return pid


def test_a_marked_tests_child_dies_with_its_os_exit_and_an_unmarked_ones_survives(tmp_path):
    survivor = _orphan_after_exit(tmp_path / "unmarked", "")
    try:
        assert survivor is not None, "control: without the mark the child must outlive os._exit"
    finally:
        if survivor is not None:
            psutil.Process(survivor).kill()
    assert _orphan_after_exit(tmp_path / "marked", "@pytest.mark.children_die_with_the_test") is None
