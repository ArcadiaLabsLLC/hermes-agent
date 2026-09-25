"""Startup triggers PM recovery without importing the damaged dependencies.

Real generation rebuilds and pre-activation startup live in tests/pm; these
checks keep marker ownership, retry limits and single-flight behavior intact.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from hermes_cli import _early_recovery as er
from pm import recovery

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Entry-point lifecycle (subprocess, real imports)
# ---------------------------------------------------------------------------

def _make_broken_dotenv_shadow(tmp_path: Path) -> Path:
    """A sys.path dir shadowing ``dotenv`` with the #57828 failure state:
    distribution metadata intact, import files wiped/broken."""
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "dotenv.py").write_text(
        "raise ImportError('import files wiped mid-install (#57828)')\n",
        encoding="utf-8",
    )
    return shadow


def _run_lifecycle_subprocess(tmp_path: Path, *, repair: bool) -> subprocess.CompletedProcess:
    shadow = _make_broken_dotenv_shadow(tmp_path)
    hermes_home = tmp_path / "hermes_home"
    hermes_home.mkdir()
    script = tmp_path / "lifecycle.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import sys

            shadow = {str(shadow)!r}
            sys.path.insert(0, shadow)

            # _early_recovery must be importable on the corrupted venv
            # (stdlib-only) — this import itself is part of the contract.
            import hermes_cli._early_recovery as er

            REPAIR = {repair!r}

            def recorder(*args, **kwargs):
                print("EARLY_RECOVERY_CALLED", flush=True)
                if REPAIR:
                    sys.path.remove(shadow)
                    sys.modules.pop("dotenv", None)

            er.recover_if_needed = recorder

            import hermes_cli.main  # noqa: F401
            print("MAIN_IMPORTED_OK", flush=True)
            """
        ),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT),
        "HERMES_HOME": str(hermes_home),
    }
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=120,
    )


def test_broken_dotenv_crashes_main_import_without_repair(tmp_path):
    """Negative control: the shadow really breaks importing hermes_cli.main,
    and recovery was invoked BEFORE the crash (i.e. before third-party
    imports) — so a real repair at that point can save the launch."""
    result = _run_lifecycle_subprocess(tmp_path, repair=False)
    assert result.returncode != 0
    assert "EARLY_RECOVERY_CALLED" in result.stdout
    assert "MAIN_IMPORTED_OK" not in result.stdout
    assert "wiped mid-install" in result.stderr




def test_early_recovery_module_is_stdlib_only(tmp_path):
    """The module must import in a process where every non-stdlib import
    fails — that is the whole point of its existence."""
    script = tmp_path / "stdlib_only.py"
    script.write_text(
        textwrap.dedent(
            """
            import builtins
            import sys

            STDLIB = set(sys.stdlib_module_names) | {"hermes_cli"}
            real_import = builtins.__import__

            def guard(name, globals=None, locals=None, fromlist=(), level=0):
                # level > 0 is a RELATIVE import executed from inside a
                # package whose own absolute import already cleared this
                # guard -- e.g. importlib/__init__.py doing
                # `from ._bootstrap import __import__`, which arrives here
                # as the bare name "_bootstrap". That is not a top-level
                # stdlib name, so gating it on STDLIB rejects legitimate
                # stdlib internals and makes the whole check depend on
                # which modules the host interpreter happened to preload
                # at startup. Only ABSOLUTE imports carry the signal this
                # test exists to pin.
                if level:
                    return real_import(name, globals, locals, fromlist, level)
                top = name.split(".")[0]
                if top not in STDLIB:
                    raise ImportError(f"non-stdlib import blocked: {name}")
                return real_import(name, globals, locals, fromlist, level)

            builtins.__import__ = guard
            import hermes_cli._early_recovery  # noqa: F401
            print("STDLIB_ONLY_OK")
            """
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        timeout=60,
    )
    assert "STDLIB_ONLY_OK" in result.stdout, result.stderr


@pytest.mark.parametrize("prefix", [[], ["-p", "default"], ["--profile=default"]])
def test_bootstrap_and_pm_cli_work_without_site_packages(tmp_path, prefix):
    env = {**os.environ, "HERMES_HOME": str(tmp_path / "home"), "PYTHONPATH": str(REPO_ROOT)}
    result = subprocess.run(
        [sys.executable, "-S", "-m", "hermes_cli.main", *prefix, "pm", "repair", "--help"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "hermes pm repair" in result.stdout


@pytest.mark.parametrize("marker_name", [".update-incomplete", ".lazy-refresh-incomplete"])
def test_marker_requests_pm_repair_then_clears(tmp_path, monkeypatch, capsys, marker_name):
    root = _project(tmp_path)
    marker = root / marker_name
    marker.write_text("interrupted", encoding="utf-8")
    calls = []
    monkeypatch.setattr(recovery, "repair_dependencies", calls.append)
    assert er.recover_if_needed(root, argv=[]) is True
    assert calls == [root]
    assert not marker.exists()
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("body", ["", "not json", '{"attempts": 1}', "started=1\npid=0\n"])
def test_failed_repair_keeps_marker_and_stops_at_retry_limit(tmp_path, monkeypatch, capsys, body):
    root = _project(tmp_path)
    marker = root / ".update-incomplete"
    marker.write_text(body, encoding="utf-8")
    attempts = er._read_marker_attempts(marker)
    calls = []
    def fail(project):
        calls.append(project)
        raise RuntimeError("dependency build failed")
    monkeypatch.setattr(recovery, "repair_dependencies", fail)
    for expected in range(attempts + 1, er._EARLY_CORE_INSTALL_MAX_ATTEMPTS + 1):
        assert er.recover_if_needed(root, argv=[]) is False
        assert er._read_marker_attempts(marker) == expected
        if "pid=" in body:
            assert marker.read_text(encoding="utf-8").startswith(body)
    before = len(calls)
    assert er.recover_if_needed(root, argv=[]) is False
    assert len(calls) == before
    output = capsys.readouterr()
    assert output.out == ""
    assert "hermes pm repair" in output.err


def test_recovery_obeys_live_owner_and_single_flight(tmp_path, monkeypatch):
    root = _project(tmp_path)
    marker = root / ".update-incomplete"
    marker.write_text(f"started=1\npid={os.getpid()}\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(recovery, "repair_dependencies", calls.append)
    assert er.recover_if_needed(root, argv=[]) is False
    assert calls == []
    assert marker.exists()
    marker.write_text("interrupted", encoding="utf-8")
    fd = er._claim_recovery_lock(root)
    assert fd is not None
    try:
        assert er.recover_if_needed(root, argv=[]) is False
        assert calls == []
        assert marker.exists()
    finally:
        os.close(fd)
    assert er.recover_if_needed(root, argv=["update"]) is True
    assert calls == [root]


def test_missing_environment_cannot_write_a_retry_marker_without_lock(tmp_path, monkeypatch):
    from pm.environments import install_state_dir, runtime_facts_path
    from pm.lock import Facts

    root = _project(tmp_path)
    state = install_state_dir(root)
    Facts(runtime_facts_path(root)).record_state("venv", "old", [], environment=state / "environments" / "old" / "venv")
    fd = er._claim_recovery_lock(root)
    assert fd is not None
    try:
        assert er.recover_if_needed(root, argv=[]) is False
        assert not (state / ".repair-incomplete").exists()
    finally:
        os.close(fd)


def test_pm_commands_and_healthy_startup_do_not_repair(tmp_path, monkeypatch):
    root = _project(tmp_path)
    monkeypatch.setattr(recovery, "repair_dependencies", lambda _: pytest.fail("unexpected install"))
    assert er.recover_if_needed(root, argv=[]) is False
    marker = root / ".update-incomplete"
    marker.write_text("interrupted", encoding="utf-8")
    assert er.recover_if_needed(root, argv=["pm", "repair"]) is False
    assert marker.exists()



def test_pid_liveness_recognizes_current_process():
    assert er._pid_is_running(os.getpid()) is True
    assert er._pid_is_running(0) is False

def test_marker_owner_liveness_uses_recorded_pid(tmp_path, monkeypatch):
    marker = tmp_path / ".update-incomplete"
    marker.write_text("started=1\npid=4321\n", encoding="utf-8")
    seen = []
    monkeypatch.setattr(
        er, "_pid_is_running", lambda pid: seen.append(pid) or True
    )

    assert er._marker_owner_is_live(marker) is True
    assert seen == [4321]

def _project(tmp_path: Path, *, pyproject: bool = True) -> Path:
    root = tmp_path / "proj"
    root.mkdir(exist_ok=True)
    if pyproject:
        (root / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = [\n'
            '  "ruamel.yaml==0.18.17",\n'
            '  "python-dotenv==1.2.2",\n'
            '  "PyJWT[crypto]==2.13.0",\n'
            "]\n",
            encoding="utf-8",
        )
    return root










