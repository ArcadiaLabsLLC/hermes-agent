"""A dependency generation built for another Python is re-entered, never activated here.

2026-09-29, profile alice: the gateway booted on CPython 3.12 activated PM's 3.14 generation;
``openai`` imported ``pydantic_core``, whose only extension is ``cp314``, and every cron job
failed for seven hours as "the openai SDK is not installed".

Killing mutations (applied, red recorded, reverted -- see the commit message):

* ``generation_python_version`` drops the ``version_info`` key  -> uv-generation test red.
* ``generation_interpreter_for_mismatch`` returns ``None`` always -> both mismatch tests red.
* the bootstrap seam is deleted                                   -> bootstrap test red.
* ``sdk_import_failure`` ignores ``exc.name``                      -> broken-dependency test red.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pm.environments import install_state_dir, runtime_facts_path, venv_python

RUNNING = f"{sys.version_info.major}.{sys.version_info.minor}"
FOREIGN = f"{sys.version_info.major}.{sys.version_info.minor + 1}"


def _commit_generation(repo: Path, cfg: str, *, interpreter: bool = True) -> Path:
    environment = install_state_dir(repo) / "environments" / "gen" / "venv"
    environment.mkdir(parents=True)
    (environment / "pyvenv.cfg").write_text(cfg, encoding="utf-8")
    if interpreter:
        venv_python(environment).parent.mkdir(parents=True, exist_ok=True)
        venv_python(environment).write_bytes(b"")
    runtime_facts_path(repo).write_text(
        json.dumps({"packages": {"venv": {"environment": str(environment)}}}), encoding="utf-8")
    return environment


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    root = tmp_path / "repo"
    root.mkdir()
    return root


def test_uv_generation_version_is_read_from_version_info(tmp_path):
    from hermes_cli.interpreter_abi import generation_python_version

    (tmp_path / "pyvenv.cfg").write_text("home = X\nuv = 0.12.3\nversion_info = 3.14.7\n", encoding="utf-8")
    assert generation_python_version(tmp_path) == (3, 14)


def test_foreign_generation_answers_its_own_interpreter(repo):
    from hermes_cli.interpreter_abi import generation_interpreter_for_mismatch

    environment = _commit_generation(repo, f"uv = 0.12.3\nversion_info = {FOREIGN}.0\n")
    assert generation_interpreter_for_mismatch(repo) == venv_python(environment)


def test_matching_generation_is_left_to_activation(repo):
    from hermes_cli.interpreter_abi import generation_interpreter_for_mismatch

    _commit_generation(repo, f"uv = 0.12.3\nversion_info = {RUNNING}.0\n")
    assert generation_interpreter_for_mismatch(repo) is None


def test_foreign_generation_without_interpreter_refuses(repo):
    from hermes_cli.interpreter_abi import generation_interpreter_for_mismatch

    _commit_generation(repo, f"version_info = {FOREIGN}.0\n", interpreter=False)
    with pytest.raises(RuntimeError, match=f"built for Python {FOREIGN}"):
        generation_interpreter_for_mismatch(repo)


def test_bootstrap_relaunches_before_activating_a_foreign_generation(tmp_path, monkeypatch):
    """The seam and its positive control: same stubs, only the mismatch answer differs."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    root = Path(__file__).resolve().parents[2]
    code = """
import subprocess
import sys
from pathlib import Path
import pm.environments as environments
from hermes_cli import _early_recovery, interpreter_abi, venv_sync
foreign = sys.argv[1] == "foreign"
venv_sync.prepare_launch = lambda *_: None
_early_recovery.recover_if_needed = lambda *_: False
interpreter_abi.generation_interpreter_for_mismatch = lambda *_: Path("gen-python") if foreign else None
def activated(*_):
    print("ACTIVATED")
    raise SystemExit(0)
environments.activate_dependencies = activated
def call(command):
    print("RELAUNCH", command[0])
    return 7
subprocess.call = call
sys.argv = ["hermes", "-z", "hi"]
import hermes_bootstrap
"""
    env = {**os.environ, "PYTHONPATH": str(root)}
    foreign = subprocess.run([sys.executable, "-S", "-c", code, "foreign"],
                             env=env, capture_output=True, text=True, timeout=60)
    control = subprocess.run([sys.executable, "-S", "-c", code, "matching"],
                             env=env, capture_output=True, text=True, timeout=60)
    if os.name == "nt":
        assert foreign.returncode == 7, foreign.stderr
        assert "RELAUNCH gen-python" in foreign.stdout
    assert "ACTIVATED" not in foreign.stdout
    assert control.returncode == 0, control.stderr
    assert "ACTIVATED" in control.stdout and "RELAUNCH" not in control.stdout


def test_broken_sdk_dependency_is_not_reported_as_absent():
    from agent.transports.httpx_client import sdk_import_failure

    broken = ModuleNotFoundError("No module named 'pydantic_core._pydantic_core'",
                                 name="pydantic_core._pydantic_core")
    message = str(sdk_import_failure("openai", broken))
    assert "not installed" not in message and "provider_sdks: false" not in message
    assert "pydantic_core._pydantic_core" in message and "hermes pm repair" in message

    absent = ModuleNotFoundError("No module named 'openai'", name="openai")
    assert "openai SDK is not installed" in str(sdk_import_failure("openai", absent))


def test_openai_loader_names_the_broken_dependency(monkeypatch):
    from agent import process_bootstrap
    from agent.transports.httpx_client import SdkFreeWireUnavailable

    class BrokenOpenai:
        def find_spec(self, name, path=None, target=None):
            if name == "openai":
                raise ModuleNotFoundError("No module named 'pydantic_core._pydantic_core'",
                                          name="pydantic_core._pydantic_core")
            return None

    for name in [m for m in sys.modules if m == "openai" or m.startswith("openai.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "meta_path", [BrokenOpenai(), *sys.meta_path])
    monkeypatch.setattr(process_bootstrap, "_OPENAI_CLS_CACHE", None)
    with pytest.raises(SdkFreeWireUnavailable, match="failed to import"):
        process_bootstrap._load_openai_cls()
