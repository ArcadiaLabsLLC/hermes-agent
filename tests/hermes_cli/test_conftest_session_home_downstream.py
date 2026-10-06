"""No test, and no process a test spawns, resolves the operator's HERMES_HOME.

The root ``conftest.py`` detaches the shell's home before ``tests/conftest.py``
runs (``tests/_downstream/session_home.py``) and refuses a session whose home
is a real install. Driven end to end through a nested bare ``python -m pytest``
launched with a stand-in "live" home, never the operator's.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests._downstream import session_home
from tests._downstream.session_home import detach_operator_home, live_home_refusal

_REPO = Path(__file__).resolve().parents[2]
_PROBE = "tests/_downstream/hermetic_probe.py"
#: Markers a test-spawned process inherits; a shell an operator types in has none.
_TEST_MARKERS = (session_home.ISOLATION_ENV, session_home.REAL_ROOT_ENV, session_home.SANDBOX_ENV,
                 "PYTEST_CURRENT_TEST", "PYTEST_VERSION", "PYTEST_ADDOPTS")


def _live_home(tmp_path: Path) -> Path:
    live = tmp_path / "live-stand-in"
    (live / "logs").mkdir(parents=True)
    (live / "state.db").write_bytes(b"")
    return live


def _bare_pytest(env: dict, timeout: float = 150) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", _PROBE],
        cwd=_REPO, env=env, capture_output=True, text=True, timeout=timeout,
    )


@pytest.mark.timeout(180)
def test_a_bare_run_from_a_live_shell_hands_its_children_the_sandbox(tmp_path):
    live = _live_home(tmp_path)
    out = tmp_path / "child-home.txt"
    env = {k: v for k, v in os.environ.items() if k not in _TEST_MARKERS}
    env.update(HERMES_HOME=str(live), SESSION_HOME_PROBE_OUT=str(out))

    run = _bare_pytest(env)

    assert run.returncode == 0, run.stdout + run.stderr
    child_home = Path(out.read_text(encoding="utf-8")).resolve()
    assert not child_home.is_relative_to(live.resolve()), child_home
    assert sorted(p.relative_to(live).as_posix() for p in live.rglob("*")) == ["logs", "state.db"]


@pytest.mark.timeout(180)
def test_the_session_start_guard_refuses_a_home_inside_the_real_root(tmp_path):
    live = _live_home(tmp_path)
    env = {k: v for k, v in os.environ.items() if k not in _TEST_MARKERS}
    # Spawned-by-test shape: the detach stands aside, so only the guard is left.
    env.update({session_home.ISOLATION_ENV: "1", session_home.REAL_ROOT_ENV: str(live),
                "HERMES_HOME": str(live / "profiles" / "alice"),
                "SESSION_HOME_PROBE_OUT": str(tmp_path / "unused.txt")})

    run = _bare_pytest(env)

    assert run.returncode == pytest.ExitCode.USAGE_ERROR, run.stdout + run.stderr
    assert "hermetic session home refused" in run.stdout + run.stderr
    assert sorted(p.relative_to(live).as_posix() for p in live.rglob("*")) == ["logs", "state.db"]


def test_the_refusal_names_the_root_the_profile_and_a_used_install(tmp_path):
    root = tmp_path / "install"
    (root / "profiles" / "alice").mkdir(parents=True)
    used = tmp_path / "used"
    used.mkdir()
    (used / "state.db").write_bytes(b"")
    fresh = tmp_path / "fresh"
    fresh.mkdir()

    assert "inside the real install root" in live_home_refusal(root, [root.resolve()])
    assert "inside the real install root" in live_home_refusal(root / "profiles" / "alice", [root.resolve()])
    assert "already holds state.db" in live_home_refusal(used, [])
    assert live_home_refusal(used, [], check_markers=False) is None
    assert live_home_refusal(fresh, [root.resolve()]) is None


def test_the_detach_records_the_root_and_strips_every_home_variable(tmp_path):
    root = tmp_path / "install"
    environ = {"HERMES_HOME": str(root / "profiles" / "alice"), "HERMES_HEAD_HOME": "x",
               "HERMES_AGENT_RUNTIME_ROOT": "y", "OTHER": "kept"}

    recorded = detach_operator_home(environ)

    assert Path(recorded) == root
    assert environ == {"OTHER": "kept", session_home.REAL_ROOT_ENV: recorded}


def test_the_detach_leaves_a_test_spawned_process_alone():
    environ = {session_home.ISOLATION_ENV: "1", "HERMES_HOME": "/tmp/test-home"}

    assert detach_operator_home(dict(environ)) is None
    kept = dict(environ)
    detach_operator_home(kept)
    assert kept == environ
