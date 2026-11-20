"""A terminal command Hermes gave up on leaves nothing of itself running (RT-FU-A-TIMED-OUT-TERMINAL-COMMAND-KEEPS-RUNNING-ON-WINDOWS).

Seen 2026-11-20 in the owner's install on Windows: a ``dart`` claim command answered "[Command timed out after
30s]" (exit 124) and the git commit it was making landed six seconds later, so the agent's retry met its own
claim. The done-when's check, through the real local backend and no faking: a foreground command whose child
writes a file AFTER the timeout must leave no file behind. Portable on purpose — it runs on Linux, and the same
file is the Windows read (``REQUIRES windows`` on the row; Linux passed 2026-11-20).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from tools.environments.local import LocalEnvironment

_TIMEOUT_S = 2
#: Long enough that the child's write lands well after the timeout answer, short enough to keep the test quick.
_CHILD_SLEEP_S = 4


def _late_writer(marker: str) -> str:
    """A command whose Python child writes ``marker`` after the timeout; ``; true`` keeps the shell a parent."""
    exe = Path(sys.executable).as_posix()
    code = f"import pathlib, time; time.sleep({_CHILD_SLEEP_S}); pathlib.Path({marker!r}).write_text('late')"
    return f'"{exe}" -c "{code}"; true'


def test_a_timed_out_command_s_child_never_writes_after_the_answer(tmp_path):
    """Mutation: ``LocalEnvironment._kill_process`` kills only the shell (``proc.kill()``) -> the child
    outlives the timeout answer and writes its file, red."""
    env = LocalEnvironment(cwd=str(tmp_path), timeout=_TIMEOUT_S)
    try:
        result = env.execute(_late_writer("late.txt"), timeout=_TIMEOUT_S)
    finally:
        env.cleanup()
    assert result["returncode"] == 124 and result.get("hermes_timed_out") is True, result
    time.sleep(_CHILD_SLEEP_S + 1.5)
    assert not (tmp_path / "late.txt").exists(), "a descendant of the timed-out command kept running"
