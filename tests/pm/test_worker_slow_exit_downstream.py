"""A worker that returned its result but exits slowly (a loaded machine) does not fail the request (L7.32)."""
from __future__ import annotations

import pytest

from tests.pm._fixtures import client as client, isolated_python as isolated_python  # noqa: F401

# Spawns children with a home it builds itself; the parent's must stay real.
pytestmark = pytest.mark.real_machine_home

# Answers the one request, closes stdout, then outlives upstream's 5 s exit wait.
_SLOW_EXIT_WORKER = (
    "import json, sys, time\n"
    "request = json.loads(sys.stdin.readline())\n"
    "sys.stdout.write(json.dumps({'id': request['id'], 'type': 'result', 'result': 'done'}) + '\\n')\n"
    "sys.stdout.flush()\n"
    "sys.stdout.close()\n"
    "time.sleep(6.5)\n"
)


def test_a_result_followed_by_a_slow_exit_completes(client, monkeypatch, isolated_python):
    monkeypatch.setattr(client, "runtime_command",
                        lambda path, **kwargs: [str(isolated_python), "-I", "-c", _SLOW_EXIT_WORKER])
    assert client._request("ensure", {"name": "node", "explicit": True}) == "done"
