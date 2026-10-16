"""Positive tests for the Windows system-tooling PATH append on terminal children."""

import os

from tools.environments import local as local_mod


def _tooling_root(tmp_path):
    root = tmp_path / "Windows"
    for sub in ("System32", os.path.join("System32", "WindowsPowerShell", "v1.0")):
        (root / sub).mkdir(parents=True)
    return root


def test_system_path_dirs_lists_only_existing_tooling_dirs(tmp_path, monkeypatch):
    root = _tooling_root(tmp_path)
    monkeypatch.setenv("SystemRoot", str(root))
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        monkeypatch.setenv(var, str(tmp_path / "absent"))

    dirs = local_mod._windows_system_path_dirs()

    assert dirs == [
        str(root / "System32"),
        str(root),
        os.path.join(str(root / "System32"), "WindowsPowerShell", "v1.0"),
    ]


def test_augment_appends_missing_dirs_after_the_callers_entries(monkeypatch):
    monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
    monkeypatch.setattr(local_mod, "_windows_system_path_dirs",
                        lambda: [r"C:\Windows\System32", r"C:\Tools"])

    result = local_mod._augment_windows_system_path(r"D:\bin;C:\Tools\;E:\more")

    assert result == r"D:\bin;C:\Tools\;E:\more;C:\Windows\System32"


def test_augment_fills_an_empty_path(monkeypatch):
    monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)
    monkeypatch.setattr(local_mod, "_windows_system_path_dirs", lambda: [r"C:\Windows\System32"])

    assert local_mod._augment_windows_system_path("") == r"C:\Windows\System32"


def test_augment_is_a_no_op_off_windows(monkeypatch):
    monkeypatch.setattr(local_mod, "_IS_WINDOWS", False)
    monkeypatch.setattr(local_mod, "_windows_system_path_dirs", lambda: ["/should/not/appear"])

    assert local_mod._augment_windows_system_path("/usr/bin:/bin") == "/usr/bin:/bin"
