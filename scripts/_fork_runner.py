"""Fork seams of ``scripts/run_tests_parallel.py`` (lane pb-a, footprint audit 2026-10-15).

The upstream runner calls into this module at one site; everything the fork adds to
how a per-file subprocess is spawned lives here, not in the upstream file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

COVERAGE_RC_ENV = "HERMES_TEST_COVERAGE_RC"


def pytest_argv(file: Path, pytest_args: list[str]) -> list[str]:
    """``python -m pytest <file> …``, wrapped in ``coverage run`` when asked.

    The wrap is the seam ``scripts/unreachable_branch_report.py`` measures
    through. Without it the report would have to re-implement ``run_tests.sh``'s
    hermetic environment to trace anything, and a second spelling of that
    environment is a second thing to keep in sync — the report would then be
    measuring branches under pins and env the suite never runs with.

    Absent-safe by construction: with the variable unset the argv is
    byte-identical to what this runner has always spawned, so an ordinary run
    pays nothing and cannot be traced by accident. Every other decision
    (``branch``, ``parallel``, ``data_file``, ``source``) lives in the config
    file the report writes, so this seam carries ONE path and no policy.
    """
    rcfile = os.environ.get(COVERAGE_RC_ENV, "").strip()
    prefix = ["-m", "coverage", "run", f"--rcfile={rcfile}"] if rcfile else []
    return [sys.executable, *prefix, "-m", "pytest", str(file), *pytest_args]
