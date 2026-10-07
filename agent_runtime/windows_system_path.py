"""Append-only Windows system-tooling PATH policy for local child environments."""

import os


def windows_system_path_dirs() -> "list[str]":
    """Windows dirs that host the native command tooling the agent may shell
    out to from its bash terminal — ``cmd.exe``, ``powershell.exe`` (Windows
    PowerShell 5.1), ``pwsh.exe`` (PowerShell 7), ``ssh``/``curl``, etc.

    The agent's ``terminal`` runs through Git Bash; from there it reaches
    Windows-native tooling by invoking these executables directly (e.g.
    ``powershell.exe -NoProfile -Command ...``).  A gateway launched with a
    minimal/sanitised PATH (service manager, restricted parent env) may not
    carry these, so we append the ones that exist to the subprocess PATH —
    append-only, so a healthy native PATH keeps its original precedence.
    """
    system_root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    system32 = os.path.join(system_root, "System32")
    candidates = [
        system32,
        system_root,
        os.path.join(system32, "Wbem"),  # wmic and friends
        os.path.join(system32, "WindowsPowerShell", "v1.0"),  # powershell.exe
        os.path.join(system32, "OpenSSH"),  # ssh/scp
    ]
    # PowerShell 7 (pwsh) installs outside System32.
    for base in (
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramW6432"),
        os.environ.get("ProgramFiles(x86)"),
    ):
        if base:
            candidates.append(os.path.join(base, "PowerShell", "7"))
    seen: set[str] = set()
    dirs: list[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        key = os.path.normcase(candidate)
        if key in seen:
            continue
        seen.add(key)
        if os.path.isdir(candidate):
            dirs.append(candidate)
    return dirs


def augment_windows_system_path(existing_path: str, *, is_windows: bool) -> str:
    """Append missing Windows system tooling dirs to ``existing_path``.

    Preserves the caller PATH verbatim (order + entries) and only appends the
    system dirs from :func:`windows_system_path_dirs` that aren't already
    present (case-insensitive, separator-tolerant). No-op off Windows.
    """
    if not is_windows:
        return existing_path
    entries = (
        [e for e in existing_path.split(WINDOWS_PATH_SEP) if e]
        if existing_path
        else []
    )
    present = {os.path.normcase(e.rstrip("\\/")) for e in entries}
    for directory in windows_system_path_dirs():
        if os.path.normcase(directory.rstrip("\\/")) not in present:
            entries.append(directory)
    return WINDOWS_PATH_SEP.join(entries)

WINDOWS_PATH_SEP = ";"
