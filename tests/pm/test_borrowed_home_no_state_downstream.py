"""A checkout launched under a borrowed HERMES_HOME with no state of its own never runs bare.

Row RT-WORKTREE-LAUNCHER-UNDER-A-BORROWED-HOME-RUNS-WITHOUT-ITS-PACKAGES (seen 2026-11-15): a worktree's
``.hermes/bin/hermes`` under an Eternia QA copy's ``HERMES_HOME`` ran its owner's store Python with no
dependency ``site-packages``. Fork hook ``pm/_fork_borrowed_home.py`` (ledger row ``pm/environments.py``).

Each case boots the runner's base interpreter in ``-I`` mode, as the launcher does, and calls
``activate_dependencies`` for a temporary checkout.

Killing mutation: make ``pm.environments._fork_borrowed_home_environment`` return ``None`` -> the owner
case prints ``owner importable: False`` and the store case ``owner importable: False`` (no refusal);
both red, recorded 2026-11-15 by lane w1114a-h3 (and again after the store check moved off the
private launcher parse, same day).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pm.environments import install_key, site_packages

pytestmark = pytest.mark.platforms("any")

REPO = Path(__file__).resolve().parents[2]
BASE_PYTHON = getattr(sys, "_base_executable", sys.executable)
CODE = (
    "import sys, importlib.util; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
    "from pm.environments import activate_dependencies\n"
    "if len(sys.argv) > 3:\n    sys.prefix = sys.base_prefix = sys.argv[3]  # boot as if from that store's Python\n"
    "try:\n    activate_dependencies(Path(sys.argv[2]))\n"
    "except RuntimeError as exc:\n    print('refused:', exc); raise SystemExit(0)\n"
    "print('owner importable:', importlib.util.find_spec('owner_only') is not None)"
)


def _boot(tmp_path: Path, root: Path, *prefix: Path) -> str:
    env = {key: value for key, value in os.environ.items()
           if key not in ("HERMES_RUNTIME_DIR", "HERMES_DEPENDENCY_ROOT", "HERMES_DEPENDENCY_CHECKOUT")}
    env["HERMES_HOME"] = str(tmp_path / "qa-copy" / ".hermes")  # the borrowed home: no state for this checkout
    result = subprocess.run([BASE_PYTHON, "-I", "-c", CODE, str(REPO), str(root), *map(str, prefix)], env=env,
                            capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _checkout(tmp_path: Path) -> Path:
    root = tmp_path / "ws" / "hermes-agent"
    root.mkdir(parents=True)
    return root


def _owner_environment(owner: Path, root: Path) -> None:
    state = owner / "installs" / install_key(root)
    venv = state / "environments" / "g1" / "venv"
    venv.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text(f"version = {sys.version_info.major}.{sys.version_info.minor}.0\n")
    site_packages(venv).mkdir(parents=True)
    (site_packages(venv) / "owner_only.py").write_text("")
    facts = {"packages": {"venv": {"stamp": "complete", "environment": str(venv.resolve())}}}
    (state / "facts.json").write_text(json.dumps(facts), encoding="utf-8")


def test_a_borrowed_home_runs_on_its_owners_committed_environment(tmp_path):
    root = _checkout(tmp_path)
    _owner_environment(tmp_path / "ws" / ".hermes", root)  # the data root beside the checkout owns it
    assert _boot(tmp_path, root) == "owner importable: True"


def test_a_bare_store_python_under_a_borrowed_home_refuses_like_the_unset_home_launch(tmp_path):
    # The launcher execs the platform root's store Python (an older entry beside the current one),
    # while the borrowed home's own store_root names another tools/.
    store = tmp_path / "machine" / ".hermes" / "tools"
    (store / "python-3.14.7").mkdir(parents=True)
    facts = {"packages": {"python": {"entry": "python-3.14.9", "version": "3.14.9"}}}
    (store / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    assert (_boot(tmp_path, _checkout(tmp_path), store / "python-3.14.7")
            == "refused: no dependency environment is committed for this install")


def test_a_borrowed_home_with_no_owner_and_a_foreign_interpreter_keeps_upstreams_launch(tmp_path):
    # No launcher names this interpreter and no root owns the checkout: upstream's branch decides.
    assert _boot(tmp_path, _checkout(tmp_path)) == "owner importable: False"
