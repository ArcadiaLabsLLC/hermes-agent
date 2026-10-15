"""``run_tests_bundled.sh`` re-enters itself whatever spelling ``run_tests.sh`` used for its directory.

Row (build-fastgate-FG1): under a drive-spelled PWD the wrapper's ``$__BUNDLED_DIR``
(``/x/…`` from ``cd … && pwd``) and the path ``run_tests.sh`` passed to its
``exec run-in-hermes-env`` (``X:/…``) named one file in two spellings; the wrapper
compared strings and exited 2 "the bundled wrapper is out of date".
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[2] / "scripts" / "run_tests_bundled.sh"


def _msys_bash() -> str | None:
    bash = shutil.which("bash")
    if bash is None:
        return None
    probe = subprocess.run([bash, "-c", "uname -o"], capture_output=True, text=True, timeout=30, check=False)
    return bash if probe.returncode == 0 and probe.stdout.strip() == "Msys" else None


@pytest.mark.skipif(sys.platform != "win32", reason="a second spelling of one directory is a Windows/MSYS premise")
def test_a_drive_spelled_reexec_reenters_the_bundled_wrapper(tmp_path):
    bash = _msys_bash()
    if bash is None:
        pytest.skip("needs Git Bash (MSYS) on PATH")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(WRAPPER, scripts / "run_tests_bundled.sh")
    drive_spelled = scripts.as_posix()  # "C:/…", where the wrapper's own `pwd` says "/c/…"
    # Stand-in for run_tests.sh's stale-environment branch: re-exec under run-in-hermes-env.
    (scripts / "run_tests.sh").write_text(
        f'exec "{drive_spelled}/run-in-hermes-env" "$BASH" "{drive_spelled}/run_tests.sh" "$@"\n',
        encoding="utf-8",
        newline="\n",
    )
    (scripts / "run-in-hermes-env").write_text(
        '#!/usr/bin/env bash\nprintf "REEXEC %s\\n" "$2"\n', encoding="utf-8", newline="\n"
    )

    done = subprocess.run(
        [bash, (scripts / "run_tests_bundled.sh").as_posix(), "tests/x.py"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().endswith("/run_tests_bundled.sh"), done.stdout
