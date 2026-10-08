"""Real inherited-pipe proof; the request reader remains owned by the worker."""
import os
import subprocess
import sys


def test_worker_requests_do_not_reach_subprocess_stdin():
    code = """
from agent_runtime.conversations.worker_entry import own_protocol_input
import subprocess, sys
own_protocol_input()
child = subprocess.run([sys.executable, '-c', 'import sys; print(repr(sys.stdin.read()))'], capture_output=True, text=True, timeout=5)
print(child.stdout.strip())
print(sys.stdin.readline().strip())
"""
    result = subprocess.run([sys.executable, "-c", code], input="owned-request\n",
                            text=True, capture_output=True, timeout=15, env=os.environ.copy())
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["''", "owned-request"]
