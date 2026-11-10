"""``agent_runtime.serve_starter.boot_starter_pid``: a serve records the process that STARTED it, never
the subreaper that adopted it (RT-SERVE-STARTER-PID-NOT-THE-SUBREAPER; Eternia's
QA-SERVE-STARTER-ROW-NAMES-SUBREAPER — a reaped ``systemd --user`` took the owner's desktop down)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_runtime.serve_starter import boot_starter_pid

REPO = Path(__file__).resolve().parents[2]

# A child subreaper (as ``systemd --user`` is) runs a detached spawn the way Dart's
# ProcessStartMode.detached does: fork, setsid, fork, the intermediate exits. The "serve" reads its
# starter once while the intermediate lives, then again after it was reparented to the subreaper.
_REPARENT = r"""
import ctypes, json, os, sys, time
sys.path.insert(0, sys.argv[1])
from agent_runtime.serve_starter import boot_starter_pid

if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
    raise SystemExit("prctl(PR_SET_CHILD_SUBREAPER) refused")
report_r, report_w = os.pipe()
go_r, go_w = os.pipe()
starter = os.fork()
if starter == 0:
    os.setsid()
    if os.fork() == 0:  # the serve
        alive = {"ppid": os.getppid(), "recorded": boot_starter_pid()}
        os.write(go_w, b"x")  # let the starter exit
        deadline = time.monotonic() + 20
        while os.getppid() == alive["ppid"] and time.monotonic() < deadline:
            time.sleep(0.01)
        after = {"ppid": os.getppid(), "recorded": boot_starter_pid()}
        os.write(report_w, json.dumps({"starter": alive["ppid"], "alive": alive, "after": after}).encode())
        os._exit(0)
    os.read(go_r, 1)
    os._exit(0)  # the starter exits: the serve is adopted by the subreaper (this process)
os.close(report_w)
os.waitpid(starter, 0)
data = b""
while chunk := os.read(report_r, 4096):
    data += chunk
os.waitpid(-1, 0)  # reap the adopted serve
print(json.dumps({"subreaper": os.getpid(), **json.loads(data)}))
"""


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="PR_SET_CHILD_SUBREAPER is Linux's")
def test_a_detached_serve_adopted_by_a_subreaper_records_no_starter():
    result = subprocess.run([sys.executable, "-c", _REPARENT, str(REPO)], capture_output=True, text=True,
                            timeout=60, start_new_session=True)
    assert result.returncode == 0, result.stderr
    seen = json.loads(result.stdout)
    # While its starter lives, the serve names it.
    assert seen["alive"]["recorded"] == seen["starter"] != seen["subreaper"]
    # Reparented: getppid now names the subreaper — and that is exactly what is NOT recorded.
    assert seen["after"]["ppid"] == seen["subreaper"]
    assert seen["after"]["recorded"] is None


@pytest.mark.skipif(not hasattr(os, "getsid"), reason="POSIX sessions")
def test_a_serve_its_live_starter_spawned_records_that_starter():
    """Positive controls: a plain child and a ``start_new_session`` child of a live starter keep it."""
    script = "import sys; sys.path.insert(0, sys.argv[1]); from agent_runtime.serve_starter import boot_starter_pid; print(boot_starter_pid())"
    for new_session in (False, True):
        result = subprocess.run([sys.executable, "-c", script, str(REPO)], capture_output=True, text=True,
                                timeout=60, start_new_session=new_session)
        assert result.returncode == 0, result.stderr
        assert int(result.stdout) == os.getpid(), new_session


def test_in_process_the_starter_is_the_parent():
    assert boot_starter_pid() == os.getppid()
