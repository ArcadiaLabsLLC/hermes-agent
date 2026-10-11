"""scripts/prune_user_path.ps1 picks exactly the leaked test / lane homes (D3.15 stage 2).

The pruner's filter is driven on a synthetic PATH string with a fake existence predicate;
the test dot-sources the script (definitions only) and never opens the registry.

Mutation: make the root check in ``Get-PrunableUserPathEntry`` never match (``$reason`` left
``$null`` in the ``foreach ($root ...)`` loop) -> the temp-home entries are kept, red.
Mutation: drop ``ExpandEnvironmentVariables`` -> ``%USERPROFILE%\\tools`` reads as missing
and is pruned, red.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.platforms("windows")

PRUNER = Path(__file__).resolve().parents[2] / "scripts" / "prune_user_path.ps1"

_PROBE = r'''
param([Parameter(Mandatory = $true)][string]$Pruner)
$ErrorActionPreference = "Stop"
. $Pruner
$env:USERPROFILE = 'C:\Users\op'
$existing = @('C:\Users\op\tools', 'C:\Program Files\Git\cmd', 'X:\Eternia\.hermes\bin',
              'D:\hermes-tmp\other')
$exists = { param($dir) $existing -contains $dir }.GetNewClosure()
$value = @(
    'C:\Users\op\AppData\Local\Temp\hermes-pytest\r-1\pytest-0\t-25\hermes-home\bin',
    'C:\Program Files\Git\cmd',
    'C:\Users\op\AppData\Local\Temp\p-l-longrun-b0e7243\home\bin\',
    '%USERPROFILE%\tools',
    'C:\Gone\bin',
    'D:\hermes-tmp\r-9\home\bin',
    'X:\Eternia\worktrees\lane\scratchpad\live\home\bin',
    '',
    'X:\Eternia\.hermes\bin'
) -join ';'
$roots = @('C:\Users\op\AppData\Local\Temp', 'D:\hermes-tmp')
$prune = @(Get-PrunableUserPathEntry -PathValue $value -Roots $roots -Exists $exists)
$kept = Remove-UserPathEntry $value @($prune | ForEach-Object { $_.Entry })
[pscustomobject]@{
    prune = @($prune | ForEach-Object { $_.Entry + ' | ' + $_.Reason })
    kept = $kept
} | ConvertTo-Json -Compress
'''


def test_the_pruner_drops_temp_homes_and_missing_dirs_and_keeps_the_rest(tmp_path):
    powershell = shutil.which("powershell")
    if not powershell:
        pytest.skip("Windows PowerShell is not available")
    probe = tmp_path / "probe.ps1"
    probe.write_text(_PROBE, encoding="utf-8")

    run = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(probe), "-Pruner", str(PRUNER)],
        capture_output=True, text=True, timeout=60,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    out = json.loads(run.stdout.strip().splitlines()[-1])

    assert out["prune"] == [
        r"C:\Users\op\AppData\Local\Temp\hermes-pytest\r-1\pytest-0\t-25\hermes-home\bin | under C:\Users\op\AppData\Local\Temp",
        r"C:\Users\op\AppData\Local\Temp\p-l-longrun-b0e7243\home\bin\ | under C:\Users\op\AppData\Local\Temp",
        r"C:\Gone\bin | directory missing",
        r"D:\hermes-tmp\r-9\home\bin | under D:\hermes-tmp",
        r"X:\Eternia\worktrees\lane\scratchpad\live\home\bin | under a scratchpad\live",
    ]
    # Order, the unexpanded %VAR% spelling and the empty entry survive untouched.
    assert out["kept"] == r"C:\Program Files\Git\cmd;%USERPROFILE%\tools;;X:\Eternia\.hermes\bin"
