"""A cold compute-host child that says hello after the fixed 10 s still starts.

The child imports ``tui_gateway.server`` before its hello: 5.6-6.2 s idle on
the measuring box, 10.8-28.5 s with its cores saturated. Against the fixed 10 s
wait in ``HostSupervisor._spawn`` that refused the first isolated turn of a
loaded machine (``5019 compute host did not send hello``), which is the
``test_native_app_functions[isolated-compute]`` -j8 flake (fork-hygiene row,
2026-10-01). The fork's additive grace (``_HELLO_COLD_START_GRACE_SECS``)
waits for a LIVE child first.

*Killing mutation:* ``_HELLO_COLD_START_GRACE_SECS = 0.0`` -> ``start()``
raises ``compute host did not send hello``.
"""

from __future__ import annotations

import json
import sys

import pytest

from tui_gateway.host_supervisor import HostSupervisor

pytestmark = pytest.mark.timeout(90)

#: Past the fixed 10 s wait, so only the grace can admit it.
_HELLO_AFTER_SECS = 10.6


def test_a_child_that_says_hello_after_ten_seconds_still_starts(tmp_path):
    hello = json.dumps({"type": "hello", "host_pid": 0, "boot_id": "cold", "build_sha": "unknown",
                        "hermes_home": str(tmp_path)})
    script = (
        "import sys, time\n"
        f"time.sleep({_HELLO_AFTER_SECS})\n"
        f"sys.stdout.write({hello!r} + '\\n'); sys.stdout.flush()\n"
        "sys.stdin.readline()\n"
    )
    supervisor = HostSupervisor(
        registry_path=tmp_path / "registry.json", argv=[sys.executable, "-c", script], cwd=tmp_path,
        expected_build_sha="unknown", expected_hermes_home=str(tmp_path), respawn_max=0,
        autostart=False,
    )
    try:
        supervisor.start()
        assert supervisor.is_running()
    finally:
        supervisor.shutdown()
