"""The fork half of upstream's external-Python checkout venv test, on any interpreter.

Upstream's ``test_a_checkout_venv_built_on_an_external_python_is_not_a_pre_pm_install`` asserts
the venv's ``home`` is the symlinked "system python" directory. uv keeps that link only for a
distribution Python: for a python-build-standalone interpreter (``PYTHON_BUILD_STANDALONE``,
which PM's store Python and uv's managed Pythons are) it records the build's real directory.
On such a box the upstream line is false before the test reaches its point, so the id table
marks it a strict xfail there (FH-SOURCE-LAUNCHER-AND-PM-TESTS-RED-ON-MAIN) and this twin
keeps the point checked: whichever home uv records, it is outside PM's store, and PM-built
still means no pre-PM baseline.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

from tests.pm._fixtures import (
    build_worker as build_worker,  # noqa: PLC0414 -- fixture re-export
    client as client,  # noqa: PLC0414 -- fixture re-export
    isolated_python as isolated_python,  # noqa: PLC0414 -- fixture re-export
)
from tests.pm.test_environment_build import (
    installable_project as installable_project,  # noqa: PLC0414 -- fixture re-export
    locked_project as locked_project,  # noqa: PLC0414 -- fixture re-export
)


@pytest.mark.platforms("posix")
def test_an_external_python_checkout_venv_is_pm_built_whatever_home_uv_records(installable_project, tmp_path):
    from pm import build_environment
    from pm.environments import site_packages
    from pm.extras import pre_pm_baseline

    source, _uv, env = installable_project
    external = tmp_path / "system-python" / "bin"
    external.mkdir(parents=True)
    (external / "python3").symlink_to(Path(sys.executable).resolve())
    executable = build_environment(explicit=True, source=source, python=external / "python3",
                                   out=source / ".venv", cache=tmp_path / "cache", env=env, offline=True)
    venv = executable.parent.parent
    homes = [line.removeprefix("home = ") for line in (venv / "pyvenv.cfg").read_text(encoding="utf-8").splitlines()
             if line.startswith("home = ")]
    assert len(homes) == 1
    home = Path(homes[0])
    assert home in {external, Path(sys.executable).resolve().parent}
    assert not home.is_relative_to(Path(env["HERMES_HOME"]))
    (site_packages(venv) / "hermes_agent-0.0.0.dist-info").mkdir()

    assert pre_pm_baseline(source) == []
