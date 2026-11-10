"""A kept shared launcher keeps its interpreter and gets the current bootstrap (RT-PUBLISHED-LAUNCHER-OBSOLETE-BOOTSTRAP).

#123238 keeps a checkout launcher bound to another live root's interpreter. Keeping the whole
file froze its bootstrap: an October ``hermes.cmd`` survived a November update with a script
from before the CLI entry-point contract (Windows, 2026-11-06). Here the POSIX wrapper stands in
for the ``.cmd`` / ``.exe`` (one ``mint_launcher``, three writers that each write only on a
difference).

Killing mutation (2026-11-08): delete the ``refresh_kept_launcher`` seam call in
``hermes_cli/_launchers.py::ensure_install_launchers`` ->
``test_an_obsolete_kept_launcher_is_reminted_on_its_own_interpreter`` red (the old script stays).
"""

from __future__ import annotations

import pytest

from hermes_cli import _launchers
from tests.hermes_cli.test_hermes_home_shared_launchers import _isolate, _make_home, _make_repo, _publish


def _obsolete(target, python) -> None:
    target.write_text(f"#!/bin/sh\nexec {python} -I -c 'import sys; sys.exit(0)' \"$@\"\n", encoding="utf-8")


@pytest.mark.platforms("posix")
def test_an_obsolete_kept_launcher_is_reminted_on_its_own_interpreter(tmp_path, monkeypatch):
    default_home, default_python = _make_home(tmp_path, "default")
    temp_home, _ = _make_home(tmp_path, "sandbox")
    repo = _make_repo(tmp_path)
    _isolate(tmp_path, monkeypatch, default_home)
    current = _publish(repo)
    local = repo / ".hermes" / "bin"
    stale = local / "hermes"
    _obsolete(stale, default_python)
    untouched = {name: (local / name).stat().st_mtime_ns for name in current if name != "hermes"}

    _isolate(tmp_path, monkeypatch, temp_home)  # a launch under another root keeps the binding
    after = _publish(repo)

    assert _launchers._launcher_python(stale) == default_python  # the binding is kept ...
    assert after["hermes"] == current["hermes"]  # ... and the bootstrap is today's
    assert {name: (local / name).stat().st_mtime_ns for name in untouched} == untouched  # current ones untouched


@pytest.mark.platforms("posix")
def test_a_kept_launcher_whose_mint_fails_is_kept(tmp_path, monkeypatch):
    from hermes_cli.kept_launcher_refresh import refresh_kept_launcher

    default_home, default_python = _make_home(tmp_path, "default")
    repo = _make_repo(tmp_path)
    _isolate(tmp_path, monkeypatch, default_home)
    _publish(repo)
    stale = repo / ".hermes" / "bin" / "hermes"
    _obsolete(stale, default_python)
    before = stale.read_bytes()
    monkeypatch.setattr(_launchers, "mint_launcher", lambda *a, **k: None)
    assert refresh_kept_launcher("hermes", repo, stale.parent, stale) == stale
    assert stale.read_bytes() == before


def _embedded_script(cmd) -> str:
    """The bootstrap a ``.cmd`` launcher runs: the base64 payload of its ``-c``."""
    import base64
    import re

    return base64.b64decode(re.search(r"b64decode\('([^']+)'\)", cmd.read_text(encoding="utf-8")).group(1)).decode()


@pytest.mark.platforms("windows")  # the live failure: an October hermes.cmd bound to a QA sandbox (2026-11-06)
def test_an_obsolete_kept_cmd_is_reminted_as_a_cmd_on_its_own_interpreter(tmp_path, monkeypatch):
    """Killing mutation (2026-11-10): route a kept ``.cmd`` through ``mint_launcher`` -> red (distlib
    publishes a ``hermes.exe`` beside it and the kept ``.cmd`` keeps its October script)."""
    import base64

    _default_home, default_python = _make_home(tmp_path, "default")
    temp_home, _ = _make_home(tmp_path, "sandbox")
    repo = _make_repo(tmp_path)
    local = repo / ".hermes" / "bin"
    local.mkdir(parents=True)
    october = base64.b64encode(b"import sys; sys.exit(0)").decode()
    stale = local / "hermes.cmd"
    stale.write_text(f'@echo off\r\n"{default_python}" -I -c "import base64; exec(base64.b64decode(\'{october}\'))" %*\r\n',
                     encoding="utf-8")

    _isolate(tmp_path, monkeypatch, temp_home)  # a launch under another root keeps the binding
    written = [p for p in _launchers.ensure_install_launchers(repo, local)]

    assert str(stale) in written
    assert not (local / "hermes.exe").exists()  # nothing shadows the kept command
    assert _launchers._launcher_python(stale) == default_python  # the binding is kept ...
    assert _embedded_script(stale) == _launchers._launcher_script("hermes", repo.resolve(), None)  # ... the script is today's


@pytest.mark.platforms("windows")
def test_an_obsolete_kept_exe_is_reminted_on_its_own_interpreter(tmp_path, monkeypatch):
    """Killing mutation (2026-11-10): delete the ``refresh_kept_launcher`` seam call -> red (the
    kept ``hermes.exe`` still carries its October ``__main__.py``)."""
    from zipfile import ZipFile

    from tests.hermes_cli.test_hermes_home_shared_launchers import _write_dead_exe

    _default_home, default_python = _make_home(tmp_path, "default")
    temp_home, _ = _make_home(tmp_path, "sandbox")
    repo = _make_repo(tmp_path)
    local = repo / ".hermes" / "bin"
    local.mkdir(parents=True)
    stale = local / "hermes.exe"
    _write_dead_exe(stale, default_python)  # distlib-shaped, bound to a LIVE foreign interpreter

    _isolate(tmp_path, monkeypatch, temp_home)
    written = _launchers.ensure_install_launchers(repo, local)

    assert str(stale) in written
    assert _launchers._launcher_python(stale) == default_python
    with ZipFile(stale) as archive:
        assert archive.read("__main__.py").decode() == _launchers._launcher_script("hermes", repo.resolve(), None)
