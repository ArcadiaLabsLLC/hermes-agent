"""Every scripts/run_tests.sh run puts pm's managed node/pnpm on PATH (owner ruling 2026-11-21).

The fork's workstation runs take the shared test venv (or an explicit HERMES_PYTHON) and never
activate, and activation is what puts pm's tool dirs on PATH; a box whose only node/pnpm is pm's
then redded tests/scripts/test_bundle_pnpm.py, tests/scripts/test_webapp_renderer_freshness.py and
tests/plugins/platforms/photon/test_url_send_path.py in every lane. ``scripts/_managed_node_path.sh``
is the one copy; ``scripts/_fork_test_env.sh`` calls it for every run that will not activate, and
``scripts/daily_full_run.sh`` resolves once ahead of its steps.

pm's resolver is replaced by a stub interpreter (``HERMES_TEST_PM_PYTHON``) that answers with a
throwaway dir holding a fake ``node``; the runners themselves run for real.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX stubs; the cygpath spelling is read below")

_PROBE = '''
import json
import os
import shutil


def test_probe():
    with open({out!r}, "w", encoding="utf-8") as handle:
        json.dump({{"path": os.environ.get("PATH", ""), "node": shutil.which("node")}}, handle)
'''


def _pm_python(tmp_path: Path, prints: str) -> Path:
    """A stand-in for the bootstrap interpreter: logs each start and answers pm's resolver with *prints*."""

    stub = tmp_path / "pm_python.sh"
    stub.write_text(f'#!/usr/bin/env bash\necho started >> "{tmp_path}/pm.log"\nprintf "%s\\n" "{prints}"\n',
                    encoding="utf-8", newline="\n")
    stub.chmod(0o755)
    return stub


def _managed_dir(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "tools" / "node-9-linux-x64" / "bin"
    bin_dir.mkdir(parents=True)
    node = bin_dir / "node"
    node.write_text("#!/bin/sh\necho v9.0.0\n", encoding="utf-8", newline="\n")
    node.chmod(0o755)
    return bin_dir


def _path_without_node() -> str:
    """The caller's PATH less every dir that holds a ``node``: a shell with no node on PATH."""

    keep = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d and not (Path(d) / "node").exists()]
    return os.pathsep.join(keep)


def _clean_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("__HERMES_MANAGED_NODE_PATH", "__HERMES_ACTIVATED")}
    return {**env, **extra}


# KILLING MUTATION: drop the ``fork_managed_node_on_path "$REPO_ROOT"`` call in
# scripts/_fork_test_env.sh::fork_shared_test_venv_fallback -> the pytest child's PATH has no node
# (the caller's PATH is node-free here) and this reds; recorded red 2026-11-21.
@pytest.mark.timeout(300)
@pytest.mark.parametrize("runner", ["run_tests.sh", "run_tests_bundled.sh"])
def test_a_plain_runner_run_hands_its_pytest_child_the_managed_node(tmp_path, real_bash, runner):
    managed = _managed_dir(tmp_path)
    out = tmp_path / "seen.json"
    case = tmp_path / "case" / "test_node_probe.py"
    case.parent.mkdir()
    case.write_text(_PROBE.format(out=str(out)), encoding="utf-8")
    caller_path = _path_without_node()
    env = _clean_env(
        PATH=caller_path,
        HERMES_PYTHON=sys.executable,
        HERMES_TEST_PM_PYTHON=str(_pm_python(tmp_path, str(managed))),
        HERMES_TEST_FILE_RETRIES="0",
        HERMES_GATE_CACHE="0",
    )

    result = subprocess.run(
        [real_bash, str(_REPO / "scripts" / runner), "-j", "1", str(case)],
        cwd=str(tmp_path), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=280, check=False,
    )

    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    assert f"▶ managed node/pnpm on PATH: {managed}" in result.stdout
    seen = json.loads(out.read_text(encoding="utf-8"))
    assert seen["node"] == str(managed / "node"), seen
    assert seen["path"].startswith(f"{managed}:"), seen
    assert (tmp_path / "pm.log").read_text(encoding="utf-8").splitlines() == ["started"]  # one resolve per run


def _door(tmp_path: Path, script: str, **env: str) -> subprocess.CompletedProcess:
    helper = (_REPO / "scripts" / "_managed_node_path.sh").as_posix()
    full = f'. "{helper}"; {script}; printf "PATH=%s\\nANSWER=%s\\n" "$PATH" "${{__HERMES_MANAGED_NODE_PATH-unset}}"'
    return subprocess.run(["bash", "-c", full], env=_clean_env(**env), capture_output=True, text=True,
                          timeout=60, check=False, cwd=str(tmp_path))


def _lines(proc: subprocess.CompletedProcess) -> dict[str, str]:
    return dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line and not line.startswith("▶"))


# KILLING MUTATION: drop the ``[ -z "$managed" ]`` early return -> PATH gains a leading ':' (the cwd)
# and the notice is missing; this reds.
def test_nothing_resolved_leaves_path_unchanged_with_one_notice(tmp_path):
    proc = _door(tmp_path, f'fork_managed_node_on_path "{_REPO}"', PATH="/usr/bin:/bin",
                 HERMES_TEST_PM_PYTHON=str(_pm_python(tmp_path, "")))
    assert proc.returncode == 0, proc.stderr
    notices = [line for line in proc.stdout.splitlines() if line.startswith("▶")]
    assert notices == ["▶ no managed node/pnpm recorded for this checkout's pins — PATH unchanged"]
    assert _lines(proc) == {"PATH": "/usr/bin:/bin", "ANSWER": ""}


def test_no_bootstrap_interpreter_resolves_nothing(tmp_path):
    """A repo without scripts/_activation.sh (and no override) starts nothing and changes nothing."""

    proc = _door(tmp_path, f'fork_managed_node_on_path "{tmp_path}"', PATH="/usr/bin:/bin")
    assert proc.returncode == 0, proc.stderr
    assert "PATH unchanged" in proc.stdout
    assert _lines(proc)["PATH"] == "/usr/bin:/bin"


# KILLING MUTATION: drop the ``${__HERMES_MANAGED_NODE_PATH+set}`` branch -> the stub starts again
# (pm.log gains a line) and this reds.
def test_an_inherited_answer_is_reused_and_never_added_twice(tmp_path):
    managed = _managed_dir(tmp_path)
    proc = _door(tmp_path, f'fork_managed_node_on_path "{_REPO}"', PATH=f"{managed}:/usr/bin:/bin",
                 __HERMES_MANAGED_NODE_PATH=str(managed), HERMES_TEST_PM_PYTHON=str(_pm_python(tmp_path, "/nope")))
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / "pm.log").exists()  # no python started
    assert _lines(proc)["PATH"] == f"{managed}:/usr/bin:/bin"


# KILLING MUTATION: drop the ``cygpath -u -p`` line -> PATH holds ``C:\\t\\node;C:\\t\\pnpm`` and this reds.
def test_a_windows_answer_is_converted_to_a_bash_path_list(tmp_path):
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    cygpath = fake_bin / "cygpath"
    cygpath.write_text('#!/bin/sh\nfor a; do last="$a"; done\n'
                       'case "$1" in -u) printf "/c/t/node:/c/t/pnpm\\n" ;; *) printf "%s\\n" "$last" ;; esac\n',
                       encoding="utf-8", newline="\n")
    cygpath.chmod(0o755)
    proc = _door(tmp_path, f'fork_managed_node_on_path "{_REPO}"', PATH=f"{fake_bin}:/usr/bin:/bin",
                 HERMES_TEST_PM_PYTHON=str(_pm_python(tmp_path, r"C:\\t\\node;C:\\t\\pnpm")))
    assert proc.returncode == 0, proc.stderr
    assert _lines(proc)["PATH"] == f"/c/t/node:/c/t/pnpm:{fake_bin}:/usr/bin:/bin"


def test_an_activated_run_is_left_to_activation(tmp_path):
    """Activation already composes every pm package onto PATH; the door starts nothing for it."""

    door = (_REPO / "scripts" / "_fork_test_env.sh").as_posix()
    script = (f'_has_pytest() {{ [ -n "$1" ] && [ -x "$1" ]; }}; REPO_ROOT="{_REPO}"; . "{door}"; '
              'fork_shared_test_venv_fallback')
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60, check=False,
                          env=_clean_env(__HERMES_ACTIVATED="1", HERMES_TEST_PM_PYTHON=str(_pm_python(tmp_path, "/x"))))
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / "pm.log").exists()
    assert "managed node/pnpm" not in proc.stdout


def test_the_daily_run_has_no_second_copy():
    daily = (_REPO / "scripts" / "daily_full_run.sh").read_text(encoding="utf-8")
    assert "pm.install import env_for" not in daily
    assert 'fork_managed_node_on_path "$REPO_ROOT"' in daily
