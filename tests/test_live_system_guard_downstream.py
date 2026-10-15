"""Fork-owned half of ``tests/test_live_system_guard.py``.

The fork's ``_live_system_guard`` in ``tests/conftest.py`` carries a
backend-spawn arm that refuses ANY argv that would start a hermes backend,
container-shaped included, with its own message. Upstream's
``test_gateway_start_inside_a_container_exec_is_not_blocked`` and
``test_gateway_start_on_the_host_is_still_blocked`` (which matches the older
message) are strict xfail rows in ``tests/_downstream/id_markers/``; these
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


_ABSENT_SHELL = "sh-absent-for-the-live-system-guard-test"


def test_a_script_comment_that_names_hermes_is_not_a_backend_start():
    """Prose in a shell comment is not a command (docker/stage2-hook.sh's keygen
    block says "Hermes loads $HERMES_HOME/.env" and later echoes "gateway").

    The shell is a name that does not exist, so a guard that lets the argv
    through ends in FileNotFoundError and never spawns anything.
    """
    script = "# Hermes loads the env file, so\ntrue\necho gateway api_server\n"
    with pytest.raises(FileNotFoundError):
        subprocess.run([_ABSENT_SHELL, "-c", script])


def test_the_same_script_with_the_command_uncommented_is_refused():
    """Positive control for the test above: one line changed, and it must block."""
    script = "true\nhermes loads the env\necho gateway api_server\n"
    with pytest.raises(RuntimeError, match="START a hermes backend"):
        subprocess.run([_ABSENT_SHELL, "-c", script])
