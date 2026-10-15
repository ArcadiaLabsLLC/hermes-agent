"""A checkout's boot never rebinds another live checkout's ``$HERMES_HOME\\bin`` launchers (L6.12)."""

from __future__ import annotations

import base64
import io
import sys
import zipfile
from pathlib import Path

import pytest

from hermes_cli import _launchers, launcher_root_owner


def _cmd_launcher(target: Path, root: Path) -> Path:
    script = _launchers._launcher_script("hermes", root, None)
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    body = f'@echo off\r\n"{sys.executable}" -I -c "import base64; exec(base64.b64decode(\'{encoded}\'))" %*\r\n'
    target.write_text(body, encoding="utf-8")
    return target


def _exe_launcher(target: Path, root: Path) -> Path:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("__main__.py", _launchers._launcher_script("hermes", root, None))
    target.write_bytes(b"MZ-loader\0" + f"#!{sys.executable} -I\r\n".encode() + buffer.getvalue())
    return target


@pytest.fixture
def layout(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "bin").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    installed = tmp_path / "installed"
    worktree = tmp_path / "worktree"
    installed.mkdir()
    worktree.mkdir()
    monkeypatch.setattr(_launchers, "_register_windows_user_path", lambda entry: pytest.fail("PATH write"))
    return home / "bin", installed, worktree


@pytest.mark.parametrize("make", [_exe_launcher, _cmd_launcher])
def test_launcher_root_reads_the_bootstrap_of_both_layouts(make, tmp_path):
    root = tmp_path / "some checkout"
    root.mkdir()
    suffix = ".exe" if make is _exe_launcher else ".cmd"
    assert launcher_root_owner.launcher_root(make(tmp_path / f"hermes{suffix}", root)) == root.resolve()


def test_a_worktree_boot_leaves_the_installed_checkouts_hermes_exe_alone(layout):
    bin_dir, installed, worktree = layout
    exe = _exe_launcher(bin_dir / "hermes.exe", installed)
    before = exe.read_bytes()
    result = _launchers._expose_windows_user_bin(worktree.resolve(), create=True)
    assert result["skipped"] == "owned-by-another-root"
    assert Path(result["owner"]).resolve() == installed.resolve()
    assert exe.read_bytes() == before


def test_a_launcher_naming_a_deleted_root_is_republished(layout, tmp_path):
    bin_dir, _, worktree = layout
    _cmd_launcher(bin_dir / "hermes.cmd", tmp_path / "gone")
    assert launcher_root_owner.foreign_launcher_root(worktree, bin_dir, ("hermes", "hermes-acp")) is None


def test_its_own_launcher_and_an_unknown_layout_publish(layout):
    bin_dir, _, worktree = layout
    _cmd_launcher(bin_dir / "hermes.cmd", worktree)
    (bin_dir / "hermes-acp.exe").write_bytes(b"not a zip")
    assert launcher_root_owner.foreign_launcher_root(worktree, bin_dir, ("hermes", "hermes-acp")) is None


def test_the_data_roots_own_install_always_republishes(layout, monkeypatch):
    bin_dir, installed, worktree = layout
    _exe_launcher(bin_dir / "hermes.exe", worktree)
    monkeypatch.setattr(launcher_root_owner, "_is_home_install", lambda root: True)
    assert launcher_root_owner.foreign_launcher_root(installed, bin_dir, ("hermes",)) is None
