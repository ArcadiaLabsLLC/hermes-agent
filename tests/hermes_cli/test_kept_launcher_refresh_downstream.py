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

import os
from pathlib import Path

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


def test_a_reminted_cmd_replaces_the_old_file_whole_and_leaves_no_staging(tmp_path):
    """The ``.cmd`` re-mint writes its own file (FH-MAIN-RED-IMPORT-LAYERS-KEPT-LAUNCHER: no reach
    into upstream's private ``_write_atomic``). Runs on every OS: the write is plain text.

    Killing mutation (2026-11-10): drop ``os.replace`` in ``_replace_file`` -> red (the old
    script stays and the staged copy is left beside it)."""
    from hermes_cli.kept_launcher_refresh import _remint_cmd

    repo = _make_repo(tmp_path)
    local = tmp_path / "bin"
    local.mkdir()
    python = tmp_path / "python.exe"
    (local / "hermes.cmd").write_text("@echo off\r\nrem october\r\n", encoding="utf-8")

    written = _remint_cmd("hermes", repo, local, python)

    assert written == local / "hermes.cmd"
    assert f'"{python}" -I -c' in written.read_text(encoding="utf-8")
    assert _embedded_script(written) == _launchers._launcher_script("hermes", repo, None)
    assert sorted(p.name for p in local.iterdir()) == ["hermes.cmd"]

def _launcher_that_runs(local: Path, name: str) -> Path | None:
    """The file a shell runs for *name*: PATHEXT picks ``.exe`` before ``.cmd`` on Windows."""
    names = (f"{name}.exe", f"{name}.cmd") if os.name == "nt" else (name,)
    return next((local / candidate for candidate in names if (local / candidate).is_file()), None)


# One test, both arms: POSIX wrappers here, the .exe/.cmd pair on Windows (no platform split).
@pytest.mark.platforms("any")
def test_a_borrowing_home_never_binds_the_checkouts_launchers_to_its_own_interpreter(tmp_path, monkeypatch):
    # RT-FU-A-QA-COPY-REWRITES-THE-OWNERS-CHECKOUT-LAUNCHERS: a Stage C QA copy launched the owner's
    # checkout under its own HERMES_HOME, found no checkout launcher and staged one on the QA tree's
    # interpreter; the #123238 keep then held that binding, so the owner's hermes ran the QA tree.
    # Red when ``checkout_launcher`` ignores the owning root (``owner = None``): the borrower's
    # interpreter is published, and the one an earlier borrower left is kept.
    from pm.environments import install_key

    repo = _make_repo(tmp_path)
    # The Launcher layout: the owning data root beside the checkout, holding its install state.
    owner_home, owner_python = _make_home(tmp_path, ".hermes")
    (owner_home / "installs" / install_key(repo)).mkdir(parents=True)
    (owner_home / "installs" / install_key(repo) / "facts.json").write_text("{}", encoding="utf-8")
    qa_home, qa_python = _make_home(tmp_path, "qa")
    local = repo / ".hermes" / "bin"

    _isolate(tmp_path, monkeypatch, qa_home)
    written = _launchers.ensure_install_launchers(repo, local)
    assert len(written) == len(_launchers.ENTRY_POINTS), written
    for name in _launchers.WINDOWS_BIN_LAUNCHERS:
        runs = _launcher_that_runs(local, name)
        assert runs is not None, name
        assert _launchers._launcher_python(runs) == owner_python, (name, _launchers._launcher_python(runs))

    # A launcher an earlier borrower bound to its own live interpreter is bound back to the owner's.
    for name in _launchers.WINDOWS_BIN_LAUNCHERS:
        for stale in local.glob(f"{name}*"):
            stale.unlink()
        assert _launchers.mint_launcher(name, repo, local, qa_python, None) is not None
        assert _launchers._launcher_python(_launcher_that_runs(local, name)) == qa_python
    _launchers.ensure_install_launchers(repo, local)
    for name in _launchers.WINDOWS_BIN_LAUNCHERS:
        assert _launchers._launcher_python(_launcher_that_runs(local, name)) == owner_python, name
    assert not any(_launchers._launcher_python(path) == qa_python for path in local.iterdir()
                   if path.is_file())


@pytest.mark.platforms("any")
def test_a_borrowing_home_whose_stamp_names_its_own_store_publishes_nothing_on_the_owners_behalf(tmp_path, monkeypatch):
    # The owner's interpreter is read through upstream's public ``resolve_store_python`` (no private
    # reach, W0-G6). That door answers the stamp's store; a stamp naming another root's store must not
    # pass for the owner's. Red when ``_publish_on_owner_store`` drops its ``owner / "tools"`` check:
    # the borrower's interpreter is minted in the owner's name.
    import json

    from hermes_cli.kept_launcher_refresh import _publish_on_owner_store

    repo = _make_repo(tmp_path)
    owner_home, owner_python = _make_home(tmp_path, ".hermes")
    qa_home, qa_python = _make_home(tmp_path, "qa")
    (repo / "install-stamp.json").write_text(
        json.dumps({"updateMechanism": "self", "runtimeDir": str(qa_home / "tools")}), encoding="utf-8")
    local = repo / ".hermes" / "bin"
    local.mkdir(parents=True)
    _isolate(tmp_path, monkeypatch, qa_home)

    assert _publish_on_owner_store("hermes", repo, local, owner_home) is None
    assert not any(path.is_file() for path in local.iterdir())

    # The stamp that names no store resolves to the owner's: published on the owner's interpreter.
    (repo / "install-stamp.json").write_text(json.dumps({"updateMechanism": "self"}), encoding="utf-8")
    from pm.environments import install_key

    (owner_home / "installs" / install_key(repo)).mkdir(parents=True)
    (owner_home / "installs" / install_key(repo) / "facts.json").write_text("{}", encoding="utf-8")
    minted = _publish_on_owner_store("hermes", repo, local, owner_home)
    assert minted is not None
    assert _launchers._launcher_python(minted) == owner_python != qa_python
