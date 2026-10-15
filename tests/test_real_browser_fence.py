"""The real-browser fence (``tests/_downstream/real_browser_fence.py``) holds at the spawn door.

Killing mutation: make ``real_browser_spawn`` return ``None`` unconditionally ->
``test_a_real_agent_browser_spawn_skips_instead_of_running`` reaches the OS and fails
with ``FileNotFoundError`` instead of the fence's skip.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from tests._downstream.real_browser_fence import real_browser_spawn

_OUTSIDE = os.path.join(os.path.abspath(os.sep), "h13-fence-nowhere", "node_modules", ".bin")


def test_a_real_agent_browser_spawn_skips_instead_of_running():
    with pytest.raises(pytest.skip.Exception, match="real-browser fence: .*agent-browser"):
        subprocess.run([os.path.join(_OUTSIDE, "agent-browser.cmd"), "--version"])


@pytest.mark.parametrize("program", [
    "agent-browser.cmd", "agent-browser-win32-x64.exe", "chrome.exe", "msedge", "google-chrome",
])
def test_every_browser_spelling_outside_the_temp_roots_is_fenced(program, tmp_path):
    assert real_browser_spawn([os.path.join(_OUTSIDE, program)], None, None, (str(tmp_path),))


def test_a_launcher_reaching_agent_browser_is_fenced(tmp_path):
    assert real_browser_spawn(["npx", "agent-browser", "open"], None, None, (str(tmp_path),))


def test_a_fake_under_the_temp_root_runs(tmp_path):
    """POSITIVE CONTROL for the allow arm: the same name inside the run's temp is a test fake."""
    fake = tmp_path / "bin" / "agent-browser.cmd"
    assert real_browser_spawn([str(fake), "--version"], None, None, (str(tmp_path),)) is None


def test_an_ordinary_spawn_is_untouched(tmp_path):
    assert real_browser_spawn([sys.executable, "-c", "pass"], None, None, (str(tmp_path),)) is None
    assert subprocess.run([sys.executable, "-c", "pass"]).returncode == 0
