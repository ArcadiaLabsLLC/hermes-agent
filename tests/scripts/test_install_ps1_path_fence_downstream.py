"""install.ps1's user-PATH writer honours the registry-write fence marker (D3.15).

Three writers put ``<home>\\bin`` on ``HKCU\\Environment\\Path``; the Python audit-hook fence
(``hermes_cli/_registry_write_fence.py``) covers the two Python ones, and cannot see
PowerShell. ``scripts/install.ps1::Set-LauncherUserPath`` is the third: driven by
``tests/scripts/test_install_ps1_desktop_stage.py`` (``-Stage desktop`` -> ``Stage-Products``
-> ``Publish-UserCommand``) it leaked ``...test_desktop_stage_uses_pm_syn-25\\hermes-home\\bin``
onto the operator's PATH. The marker is an environment variable so children inherit it: the
pytest plugin (``tests/_downstream/registry_write_fence.py``) and the launcher's real-serve
sandboxes export it, and the installer now reads it.

The test dot-sources the real installer (definitions only), calls ``Set-LauncherUserPath`` on
a temp ``bin`` with the marker set, and reads the user PATH before and after. With the guard
in place nothing writes the registry; the PATH is only READ.

Mutation: delete the ``HERMES_REGISTRY_WRITE_FENCE`` guard line in ``Set-LauncherUserPath``
-> red on the missing "fenced:" line and on the changed user PATH (and the run WRITES the
operator's PATH once: run it only with the owner's accepted write, and restore it at once).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests._downstream.registry_write_fence import CHILD_FENCE_ENV

pytestmark = pytest.mark.platforms("windows")

INSTALL_PS1 = Path(__file__).resolve().parents[2] / "scripts" / "install.ps1"

_PROBE = r'''
param(
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [Parameter(Mandatory = $true)][string]$BinDir
)
$ErrorActionPreference = "Stop"
. $InstallerPath
$before = [Environment]::GetEnvironmentVariable("Path", "User")
Set-LauncherUserPath $BinDir
$after = [Environment]::GetEnvironmentVariable("Path", "User")
Write-Output ("USER_PATH_UNCHANGED=" + [string]($before -ceq $after))
'''


def test_set_launcher_user_path_is_fenced_by_the_inherited_marker(tmp_path):
    powershell = shutil.which("powershell")
    if not powershell:
        pytest.skip("Windows PowerShell is not available")
    # The plugin exports the marker into this process, so every child the suite spawns
    # (the desktop-stage installer run included) inherits it without a change of its own.
    assert os.environ.get(CHILD_FENCE_ENV) == "1", "the pytest registry fence did not export its marker"
    probe = tmp_path / "probe.ps1"
    probe.write_text(_PROBE, encoding="utf-8")
    bin_dir = tmp_path / "hermes-home" / "bin"

    run = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(probe), "-InstallerPath", str(INSTALL_PS1), "-BinDir", str(bin_dir)],
        capture_output=True, text=True, timeout=60, env=dict(os.environ),
    )

    assert run.returncode == 0, run.stdout + run.stderr
    assert f"fenced: not adding {bin_dir} to the user PATH" in run.stdout, run.stdout + run.stderr
    assert "USER_PATH_UNCHANGED=True" in run.stdout, run.stdout + run.stderr
