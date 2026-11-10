"""Fork half of ``tests/hermes_cli/test_setup_hermes_script.py`` (PR #121226).

On Windows, ``subprocess.run(["bash", ...])`` does not follow PATH: CreateProcess searches System32
first and runs the WSL launcher, which cannot see a drive-letter path (exit 127), and ``str(Path)``
hands bash backslashes it eats as escapes. This copy resolves bash with ``shutil.which`` and passes
the POSIX spelling; upstream's node is skipped on Windows
(``tests/_downstream/id_markers/fork_marks.py``) so upstream's file keeps its bytes
(FH-FOOTPRINT-FORK-TEST-HUNKS-OUT). Both go when the PR merges.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

SETUP_SCRIPT = Path(__file__).resolve().parents[2] / "setup-hermes.sh"


def test_setup_hermes_script_is_valid_shell_under_the_path_bash():
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH — cannot syntax-check a shell script")
    result = subprocess.run([bash, "-n", SETUP_SCRIPT.as_posix()], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
