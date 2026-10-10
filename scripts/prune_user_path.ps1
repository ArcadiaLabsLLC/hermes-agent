# Prune leaked test / lane homes from the user PATH (design sweep D3.15 stage 2).
#
# Test runs and launcher sandboxes put <temp home>\bin on HKCU\Environment\Path before the
# fence marker was honoured everywhere (D3.15). This lists every user-PATH entry whose
# directory no longer exists, or lies under %TEMP%, %LOCALAPPDATA%\Temp,
# HERMES_TEST_TMP_ROOT or a scratchpad\live folder:
#   powershell -NoProfile -File scripts/prune_user_path.ps1          # list only (read-only)
#   powershell -NoProfile -File scripts/prune_user_path.ps1 -Apply   # rewrite the value without them
# -Apply keeps the value's registry kind (REG_SZ / REG_EXPAND_SZ) and its unexpanded
# %VAR% spellings, prints each removal, and broadcasts the change to new shells.
[CmdletBinding()]
param([switch]$Apply)
$ErrorActionPreference = "Stop"

function Get-PruneRoots {
    $roots = @($env:TEMP, $(if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'Temp' }), $env:HERMES_TEST_TMP_ROOT)
    return @($roots | Where-Object { $_ } | ForEach-Object { $_.TrimEnd('\') } | Select-Object -Unique)
}

function Get-PrunableUserPathEntry {
    # Pure over its inputs: $Exists decides whether a directory is there (tests pass a fake).
    param(
        [string]$PathValue,
        [string[]]$Roots,
        [scriptblock]$Exists = { param($dir) Test-Path -LiteralPath $dir -PathType Container }
    )
    foreach ($entry in ($PathValue -split ';')) {
        if (-not $entry.Trim()) { continue }
        $dir = [Environment]::ExpandEnvironmentVariables($entry.Trim()).TrimEnd('\')
        $reason = $null
        foreach ($root in $Roots) {
            if ($dir.Equals($root, 'OrdinalIgnoreCase') -or $dir.StartsWith("$root\", 'OrdinalIgnoreCase')) { $reason = "under $root"; break }
        }
        if (-not $reason -and $dir -match '\\scratchpad\\live(\\|$)') { $reason = 'under a scratchpad\live' }
        if (-not $reason -and -not (& $Exists $dir)) { $reason = 'directory missing' }
        if ($reason) { [pscustomobject]@{ Entry = $entry; Reason = $reason } }
    }
}

function Remove-UserPathEntry([string]$PathValue, [string[]]$Drop) {
    return ((($PathValue -split ';') | Where-Object { $Drop -cnotcontains $_ }) -join ';')
}

# Dot-sourced (tests): definitions only.
if ($MyInvocation.InvocationName -eq '.') { return }

$key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', [bool]$Apply)
try {
    $kind = $key.GetValueKind('Path')
    $value = [string]$key.GetValue('Path', '', 'DoNotExpandEnvironmentNames')
    $prune = @(Get-PrunableUserPathEntry -PathValue $value -Roots (Get-PruneRoots))
    foreach ($p in $prune) { Write-Output ("{0}: {1}  ({2})" -f $(if ($Apply) { 'removing' } else { 'would remove' }), $p.Entry, $p.Reason) }
    $total = @($value -split ';' | Where-Object { $_.Trim() }).Count
    Write-Output ("{0} of {1} user-PATH entries prunable" -f $prune.Count, $total)
    if (-not $Apply -or $prune.Count -eq 0) { return }
    $key.SetValue('Path', (Remove-UserPathEntry $value @($prune | ForEach-Object { $_.Entry })), $kind)
} finally {
    $key.Close()
}
Add-Type -Namespace HermesPrune -Name Native -MemberDefinition @'
[DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
public static extern System.IntPtr SendMessageTimeout(System.IntPtr hWnd, uint msg, System.UIntPtr wParam, string lParam, uint flags, uint timeout, out System.UIntPtr result);
'@
$ignored = [UIntPtr]::Zero
[void][HermesPrune.Native]::SendMessageTimeout([IntPtr]0xffff, 0x001A, [UIntPtr]::Zero, 'Environment', 2, 5000, [ref]$ignored)
Write-Output "user PATH rewritten; new shells pick it up"
