"""Fork half of ``tests/tools/test_execution_flag_detection.py``'s real-binary grammar pin (PR #121226).

Upstream's test runs the bare name, which on Windows CreateProcess resolves from System32 FIRST
(``sort`` ran ``C:\\Windows\\System32\\sort.exe``, a namesake with another grammar) while its skip guard
vetted the PATH binary. This copy runs the binary ``shutil.which`` vetted; upstream's node is skipped
on Windows (``tests/_downstream/id_markers/fork_marks.py``) so upstream's file keeps its bytes
(FH-FOOTPRINT-FORK-TEST-HUNKS-OUT). Both go when the PR merges.
"""

import shutil
import subprocess

import pytest


@pytest.mark.parametrize(
    ("argv", "stdin", "expected_returncode", "expected_output"),
    [
        (["rg", "--", "--pre"], "ordinary text\n", 1, ""),
        (["sort", "--", "--compress-program"], "", 2, ""),
        (["rg", "--pre-glob", "--pre", "needle"], "needle\n", 0, "needle\n"),
    ],
)
def test_the_vetted_binary_confirms_option_ownership(argv, stdin, expected_returncode, expected_output):
    resolved = shutil.which(argv[0])
    if resolved is None:
        pytest.skip(f"{argv[0]} is not installed")

    completed = subprocess.run([resolved, *argv[1:]], input=stdin, text=True, capture_output=True, check=False)

    assert completed.returncode == expected_returncode
    assert completed.stdout == expected_output
