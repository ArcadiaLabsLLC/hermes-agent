"""The fork's half of ``tests/hermes_cli/test_gateway_windows.py`` (lane CARRY2A).

The fork's ``hermes_cli.gateway`` resolves the gateway interpreter through
``resolve_managed_python`` (the managed venv, never ``sys.executable``), so
upstream's ``get_python_path`` patch no longer steers ``_build_gateway_argv``;
that upstream test is a strict xfail by id (``tests/_downstream/id_markers.py``)
and its fork twin, patching ``resolve_managed_python``, is here. Upstream's two
breakaway tests are strict xfails too: the fork's
``gateway_windows._spawn_detached(script_path)`` replaces that spawn, covered by
``tests/gateway/test_windows_gateway_spawn.py``.
"""

import pytest

import hermes_cli.gateway as gateway
import hermes_cli.gateway_windows as gateway_windows


@pytest.mark.windows_only
def test_build_gateway_argv_keeps_venv_console_python_for_uv_venv(monkeypatch, tmp_path):
    """No pythonw / base-interpreter detour: the venv console python.exe is
    launched hidden (CREATE_NO_WINDOW) so descendants inherit its hidden
    console instead of flashing their own (#54220/#56747).

    Windows-only: ``_build_gateway_argv()`` asserts the host is Windows and the
    argv/env overlay it returns is built from real Windows path separators and
    ``Scripts/python.exe`` layout — a patched ``sys.platform`` covered the
    branch but not any of that.
    """

    project = tmp_path / "project"
    scripts = project / "venv" / "Scripts"
    site_packages = project / "venv" / "Lib" / "site-packages"
    hermes_home = tmp_path / "hermes-home"
    base = tmp_path / "uv" / "python" / "cpython-3.11-windows-x86_64-none"
    scripts.mkdir(parents=True)
    site_packages.mkdir(parents=True)
    hermes_home.mkdir()
    base.mkdir(parents=True)

    venv_python = scripts / "python.exe"
    venv_pythonw = scripts / "pythonw.exe"
    base_pythonw = base / "pythonw.exe"
    for exe in (venv_python, venv_pythonw, base_pythonw):
        exe.write_text("", encoding="utf-8")
    (project / "venv" / "pyvenv.cfg").write_text(
        f"home = {base}\nimplementation = CPython\nuv = 0.11.14\nversion_info = 3.11.15\n",
        encoding="utf-8",
    )

    import hermes_cli.gateway as gateway

    monkeypatch.setattr(gateway, "PROJECT_ROOT", project)
    monkeypatch.setattr(gateway, "resolve_managed_python", lambda: str(venv_python))
    monkeypatch.setattr(gateway, "_profile_arg", lambda hermes_home: "")
    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: str(hermes_home))

    argv, cwd, env_overlay = gateway_windows._build_gateway_argv()

    assert argv[:3] == [str(venv_python), "-m", "hermes_cli.main"]
    assert cwd == str(hermes_home.resolve())
    assert env_overlay["VIRTUAL_ENV"] == str(project / "venv")
    assert str(project) in env_overlay["PYTHONPATH"].split(gateway_windows.os.pathsep)


def test_launcher_settings_keeps_managed_python_for_explicit_profile(monkeypatch, tmp_path):
    """A sibling cold-start selects its home without reverting to checkout Python."""
    caller = tmp_path / "caller"
    target = tmp_path / "profiles" / "alice"
    caller.mkdir()
    target.mkdir(parents=True)
    managed = str(tmp_path / "managed" / "python.exe")
    monkeypatch.setattr(gateway, "resolve_managed_python", lambda: managed)
    monkeypatch.setattr("hermes_cli.config.get_hermes_home", lambda: caller)
    monkeypatch.setattr(gateway, "_profile_arg", lambda home: "--profile alice" if home == str(target) else "")

    python, cwd, home, profile = gateway_windows._launcher_settings(target)

    assert python == managed
    assert home == str(target)
    assert profile == "--profile alice"
    assert cwd == str(caller)
