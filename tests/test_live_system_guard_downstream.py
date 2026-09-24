"""Fork-owned half of ``tests/test_live_system_guard.py``.

The fork's ``_live_system_guard`` in ``tests/conftest.py`` carries a
backend-spawn arm that refuses ANY argv that would start a hermes backend,
container-shaped included, with its own message. Upstream's
``test_gateway_start_inside_a_container_exec_is_not_blocked`` and
``test_gateway_start_on_the_host_is_still_blocked`` (which matches the older
message) are strict xfail rows in ``tests/_downstream/id_markers.py``; these
are their fork halves.
"""

from __future__ import annotations

import subprocess

import pytest


def test_gateway_looking_container_command_requires_explicit_test_ownership():
    """The fork's conservative backend fence also covers container-shaped argv.

    A temporary exit-zero stub makes a guard regression harmless. Real isolated
    container integration tests must declare their ownership with the marker.
    """
    import os
    import stat

    stub_dir = os.path.join(os.environ["HERMES_HOME"], "stub-bin")
    os.makedirs(stub_dir, exist_ok=True)
    stub = os.path.join(stub_dir, "docker")
    with open(stub, "w") as fh:
        fh.write("#!/bin/sh\nexit 0\n")
    os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR)
    with pytest.raises(RuntimeError, match="START a hermes backend"):
        subprocess.run(
            [stub, "exec", "-u", "hermes", "ctr", "sh", "-c", "hermes -p prof gateway start"],
            capture_output=True,
            text=True,
        )

def test_gateway_start_on_the_host_is_blocked_by_the_backend_arm():
    with pytest.raises(RuntimeError, match="START a hermes backend"):
        subprocess.run(["python", "-m", "hermes_cli.main", "gateway", "start"])
