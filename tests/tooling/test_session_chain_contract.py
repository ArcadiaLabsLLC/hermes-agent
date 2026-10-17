"""The session chain's contract: one test per promise a file EVERY test loads makes.

A change to the session chain (``scripts/run_tests_bundled_chain.py``: the root and
``tests/`` conftests, ``tests/_downstream/``, ``tests/_fixtures/``, the bundle
plugins, the pytest config) reaches every test file. The landing gate runs this
file plus one sample per test folder instead of the whole tree (owner ruling
2026-10-16, r-fastgate step 5); the release merge's whole tree is the backstop for
an interaction no promise here names. Each test pins ONE promise, and its killing
mutation is named in its docstring and recorded in the commit that landed it.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

import hermes_constants

#: the platform-native Hermes home, read at import — before any autouse fixture patches it
_NATIVE_HOME = hermes_constants._get_platform_default_hermes_home()
_CREDENTIAL = "OPENAI_API_KEY"
_FORK_BEHAVIOURAL = "HERMES_HEAD_HOME"
_SENTINEL = "session-chain-contract-sentinel"


@pytest.fixture(scope="module")
def _set_before_the_autouse_fixtures():
    """Module scope: set up before every function-scoped autouse fixture runs."""

    saved = {name: os.environ.get(name) for name in (_CREDENTIAL, _FORK_BEHAVIOURAL)}
    os.environ[_CREDENTIAL] = _SENTINEL
    os.environ[_FORK_BEHAVIOURAL] = str(_NATIVE_HOME)
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def test_root_conftest_disables_gits_optional_index_lock():
    """``conftest.py``: GIT_OPTIONAL_LOCKS=0 for every process (D3.16).
    Mutation: drop its ``os.environ.setdefault("GIT_OPTIONAL_LOCKS", "0")``."""

    assert os.environ.get("GIT_OPTIONAL_LOCKS") == "0"


def test_hermes_home_is_a_per_test_sandbox(tmp_path):
    """``tests/conftest.py::_hermetic_environment``: HERMES_HOME is ``<tmp_path>/hermes_test``.
    Mutation: drop its ``monkeypatch.setenv("HERMES_HOME", ...)``."""

    home = Path(os.environ["HERMES_HOME"])
    assert home == tmp_path / "hermes_test" and home.is_dir()
    assert hermes_constants.get_hermes_home() == home
    assert not home.resolve().is_relative_to(_NATIVE_HOME.resolve())


def test_credentials_are_scrubbed(_set_before_the_autouse_fixtures):
    """``tests/conftest.py::_hermetic_environment`` step 1: every credential-shaped var is gone.
    Mutation: skip its ``monkeypatch.delenv`` of credential-shaped names."""

    assert _CREDENTIAL not in os.environ


def test_the_forks_behavioural_vars_are_scrubbed(_set_before_the_autouse_fixtures):
    """``tests/_downstream/conftest_plugin.py::_downstream_behavioral_vars_scrubbed``: HERMES_HEAD_HOME,
    which outranks the sandboxed HERMES_HOME, is gone. Mutation: make the fixture's body ``pass``."""

    assert _FORK_BEHAVIOURAL not in os.environ


def test_process_state_is_reset_into_the_sandbox(tmp_path):
    """``conftest_plugin.py::_isolate_launcher_process_index``: the process index writes under
    ``tmp_path``, never the operator's Launcher index. Mutation: drop its ``monkeypatch.setattr``."""

    from agent_runtime import process_index

    assert Path(process_index.index_directory()).resolve().is_relative_to(tmp_path.resolve())


def test_every_test_has_the_forks_default_timeout(request):
    """``conftest_plugin.py::pytest_configure``: 30 s per test, thread method, unless the
    command line says otherwise. Mutation: ``FORK_TEST_TIMEOUT_SECONDS = 300.0``."""

    if not request.config.pluginmanager.hasplugin("timeout"):
        pytest.skip("pytest-timeout is not installed: the default is not applied")
    assert request.config.option.timeout == 30.0
    assert request.config.option.timeout_method == "thread"


def test_temp_files_land_under_the_test_tmp_root(tmp_path):
    """``scripts/_fork_test_env.sh``: under the runners, TEMP/TMP/TMPDIR are ``HERMES_TEST_TMP_ROOT``,
    so tempfile and tmp_path stay out of %TEMP%. Mutation: drop its ``TMP=… TEMP=… TMPDIR=…`` export."""

    root = os.environ.get("HERMES_TEST_TMP_ROOT")
    if not root:
        pytest.skip("not under scripts/run_tests.sh or the bundled runner")
    base = Path(root).resolve()
    assert Path(tempfile.gettempdir()).resolve().is_relative_to(base)
    assert tmp_path.resolve().is_relative_to(base)


def test_the_dependency_recorder_is_live_when_the_gate_asks(request):
    """``scripts/_bundle_plugin/hermes_dep_record.py``: with ``--hermes-gate-deps`` the recorder is
    registered and hands its directory to child processes. Mutation: drop its ``register`` call."""

    directory = request.config.getoption("hermes_gate_deps", default=None)
    if not directory:
        pytest.skip("not under the bundled runner's green-result cache")
    assert request.config.pluginmanager.get_plugin("hermes_dep_recorder") is not None
    assert os.environ.get("HERMES_GATE_CHILD_EVENTS") == os.fspath(directory)
