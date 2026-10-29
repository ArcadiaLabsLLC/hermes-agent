"""The fork's env-extension door: scripts/fork_test_env.txt names what crosses `env -i`.

Fork-hygiene CLASS row (2026-10-15): run_tests.sh's allowlist is upstream-owned, so
every fork test variable needed a wrapper or another upstream hunk. The door is a
tracked NAME list read by ``scripts/_fork_test_env.sh``; it is run for real here.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
# A bare "bash" from Python on Windows is WSL (Running the tests.md); name Git Bash.
BASH = r"C:\Program Files\Git\bin\bash.exe" if sys.platform == "win32" else "bash"


def _extend(tmp_path: Path, listing: str, env: dict) -> subprocess.CompletedProcess:
    lst = tmp_path / "list.txt"
    lst.write_text(listing, encoding="utf-8", newline="\n")
    door = (REPO / "scripts" / "_fork_test_env.sh").as_posix()
    script = f'. "{door}"; TEST_ENV=(PRE=1); fork_test_env_extend "{lst.as_posix()}"; rc=$?; ' \
             'printf "%s\\n" "${TEST_ENV[@]}"; exit $rc'
    return subprocess.run([BASH, "-c", script], env={**os.environ, **env}, capture_output=True, text=True, timeout=60, check=False)


@pytest.mark.skipif(sys.platform == "win32" and not Path(BASH).is_file(), reason="Git Bash not installed")
def test_a_listed_set_variable_crosses_and_nothing_else_does(tmp_path):
    proc = _extend(
        tmp_path,
        "# reason\nFORK_DOOR_A  # why A\n\nFORK_DOOR_UNSET\n",
        {"FORK_DOOR_A": "a b", "FORK_DOOR_NOT_LISTED": "x"},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == ["PRE=1", "FORK_DOOR_A=a b"]


@pytest.mark.skipif(sys.platform == "win32" and not Path(BASH).is_file(), reason="Git Bash not installed")
@pytest.mark.parametrize("bad", ["HERMES_*", "1ABC", "A-B"])
def test_a_line_that_is_not_a_name_fails_the_run(tmp_path, bad):
    proc = _extend(tmp_path, f"{bad}\n", {})
    assert proc.returncode == 2
    assert "not a variable name" in proc.stderr


def test_run_tests_sources_the_door_and_the_shipped_list_holds_only_names():
    script = (REPO / "scripts" / "run_tests.sh").read_text(encoding="utf-8")
    assert 'fork_test_env_extend "$SCRIPT_DIR/fork_test_env.txt" || exit 2' in script
    names = [
        line.split("#", 1)[0].strip()
        for line in (REPO / "scripts" / "fork_test_env.txt").read_text(encoding="utf-8").splitlines()
    ]
    assert [n for n in names if n] == [
        "HERMES_TEST_IDLE_BOX", "HERMES_TEST_BODY_PATCH_UNDO",
        "ETERNIA_HEAVY_SLOTS", "ETERNIA_HEAVY_SLOT_DIR", "ETERNIA_HEAVY_SLOT_HELD",  # the launcher's heavy-run slot
    ]


@pytest.mark.skipif(sys.platform == "win32" and not Path(BASH).is_file(), reason="Git Bash not installed")
def test_the_body_patch_knob_crosses_env_i_through_the_shipped_list(tmp_path):
    """p10 S-A2: ``HERMES_TEST_BODY_PATCH_UNDO`` set by the caller reaches the test process, so an
    ``=on`` run measures the undo and not the default. Mutation: drop its line from the list."""

    listing = (REPO / "scripts" / "fork_test_env.txt").read_text(encoding="utf-8")
    proc = _extend(tmp_path, listing, {"HERMES_TEST_BODY_PATCH_UNDO": "on"})
    assert proc.returncode == 0, proc.stderr
    assert "HERMES_TEST_BODY_PATCH_UNDO=on" in proc.stdout.splitlines()


def _door(script: str, env: dict) -> subprocess.CompletedProcess:
    door = (REPO / "scripts" / "_fork_test_env.sh").as_posix()
    full = f'_has_pytest() {{ [ -n "$1" ] && [ -x "$1" ]; }}; . "{door}"; {script}'
    base = {k: v for k, v in os.environ.items() if k not in ("HERMES_PYTHON", "CI", "__HERMES_ACTIVATED")}
    return subprocess.run([BASH, "-c", full], env={**base, **env}, capture_output=True, text=True, timeout=60, check=False)


@pytest.mark.skipif(sys.platform == "win32" and not Path(BASH).is_file(), reason="Git Bash not installed")
def test_no_hermes_python_and_no_shared_venv_refuses(tmp_path):
    proc = _door('fork_shared_test_venv_fallback; echo "HP=$HERMES_PYTHON"', {"HERMES_TEST_VENV": (tmp_path / "none").as_posix()})
    assert proc.returncode == 1 and "no shared test venv" in proc.stderr


@pytest.mark.skipif(sys.platform == "win32" and not Path(BASH).is_file(), reason="Git Bash not installed")
def test_no_hermes_python_uses_the_shared_venv(tmp_path):
    exe = tmp_path / "venv" / "bin" / "python"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    proc = _door('fork_shared_test_venv_fallback; echo "HP=$HERMES_PYTHON"', {"HERMES_TEST_VENV": (tmp_path / "venv").as_posix()})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == f"HP={(tmp_path / 'venv').as_posix()}/bin/python"


def _shim_venv(tmp_path: Path, version: tuple[int, int], present: tuple[str, ...]) -> Path:
    """A shared venv whose python answers the readiness probe as a venv of ``version`` with
    only ``present`` importable: the probe's own source runs under this interpreter with
    ``sys.version_info`` and ``importlib.util.find_spec`` replaced before it."""
    venv = tmp_path / "venv"
    exe = venv / "bin" / "python"
    exe.parent.mkdir(parents=True)
    prelude = (
        "import importlib.util, sys; _real = importlib.util.find_spec; "
        f"sys.version_info = {version!r} + (0, 'final', 0); "
        f"importlib.util.find_spec = lambda n, *a: _real('json') if n in {present!r} else None"
    )
    real = Path(sys.executable).as_posix()
    exe.write_text(
        "#!/bin/sh\n"
        '[ "$1" = "-c" ] || exit 0\n'
        f"PRELUDE=\"{prelude}\"\n"
        f'exec "{real}" -c "$PRELUDE\n$2"\n',
        encoding="utf-8",
    )
    exe.chmod(0o755)
    return venv


_SENTINELS = ("ruamel.yaml", "anthropic", "aiohttp", "acp")


@pytest.mark.skipif(sys.platform == "win32", reason="the shim venv is a POSIX sh script")
def test_a_shared_venv_on_an_interpreter_below_the_runtime_pins_is_refused(tmp_path):
    venv = _shim_venv(tmp_path, (3, 12), _SENTINELS)
    proc = _door('fork_shared_test_venv_fallback; echo "HP=$HERMES_PYTHON"', {"HERMES_TEST_VENV": venv.as_posix()})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "runs Python 3.12; the runtime pins are python_version >= 3.14" in proc.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="the shim venv is a POSIX sh script")
def test_a_shared_venv_without_the_test_extras_is_refused_naming_them(tmp_path):
    venv = _shim_venv(tmp_path, (3, 14), ("ruamel.yaml",))
    proc = _door('fork_shared_test_venv_fallback; echo "HP=$HERMES_PYTHON"', {"HERMES_TEST_VENV": venv.as_posix()})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "lacks anthropic, aiohttp, acp (built without the CI test job extras)" in proc.stderr
    # Positive control: the same shim with every sentinel present is accepted.
    ready = _shim_venv(tmp_path / "ready", (3, 14), _SENTINELS)
    proc = _door('fork_shared_test_venv_fallback; echo "HP=$HERMES_PYTHON"', {"HERMES_TEST_VENV": ready.as_posix()})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == f"HP={ready.as_posix()}/bin/python"


@pytest.mark.skipif(sys.platform == "win32" and not Path(BASH).is_file(), reason="Git Bash not installed")
def test_an_interpreter_inside_the_store_root_is_refused(tmp_path):
    py = Path(sys.executable).as_posix()
    root = Path(sys.executable).resolve().parent.as_posix()  # a stand-in store root holding this interpreter
    refused = _door("fork_refuse_live_home_interpreter", {"PYTHON": py, "REAL_HERMES_ROOT": root})
    assert refused.returncode == 1 and "inside the live Hermes home" in refused.stderr
    allowed = _door("fork_refuse_live_home_interpreter", {"PYTHON": py, "REAL_HERMES_ROOT": tmp_path.as_posix()})
    assert allowed.returncode == 0, allowed.stderr


def test_run_tests_calls_both_moved_policies():
    script = (REPO / "scripts" / "run_tests.sh").read_text(encoding="utf-8")
    assert script.index(". \"$SCRIPT_DIR/_fork_test_env.sh\"") < script.index("fork_shared_test_venv_fallback")
    # The refusal runs inside fork_real_root_fence, after REAL_HERMES_ROOT is known (lane pb-a).
    assert "fork_real_root_fence" in script
    door = (REPO / "scripts" / "_fork_test_env.sh").read_text(encoding="utf-8")
    fence = door[door.index("fork_real_root_fence() {"):]
    assert fence.index("REAL_HERMES_ROOT=") < fence.index("fork_refuse_live_home_interpreter")


def _seed(tmp_path: Path, listing: str, cache_text: str | None) -> tuple[subprocess.CompletedProcess, Path]:
    lst = tmp_path / "heavy.txt"
    lst.write_text(listing, encoding="utf-8", newline="\n")
    cache = tmp_path / "test_durations.json"
    if cache_text is not None:
        cache.write_text(cache_text, encoding="utf-8")
    door = (REPO / "scripts" / "_fork_test_env.sh").as_posix()
    python = Path(sys.executable).as_posix()
    script = f'PYTHON="{python}"; . "{door}"; fork_seed_heavy_durations "{lst.as_posix()}" "{cache.as_posix()}"'
    return subprocess.run([BASH, "-c", script], capture_output=True, text=True, timeout=60, check=False), cache


@pytest.mark.skipif(sys.platform == "win32" and not Path(BASH).is_file(), reason="Git Bash not installed")
def test_a_heavy_file_gets_its_measured_duration_and_a_real_one_is_never_lowered(tmp_path):
    """FH-TOOLING-LANE-TIMEOUTS-ICON-INSTALL: the runner allows 3x a cached CLEAN wall, so a file that
    never passed inside the flat cap needs a seeded one. The key is the runner's own spelling,
    ``str(Path)``; an entry already there (a real measurement) is the positive control: it stays."""
    import json

    own = str(Path("tests/scripts/test_own.py"))
    proc, cache = _seed(tmp_path, "# why\ntests/scripts/test_heavy.py 281  # measured\ntests/scripts/test_own.py 999\n",
                        json.dumps({own: 12.5}))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(cache.read_text(encoding="utf-8")) == {
        own: 12.5, str(Path("tests/scripts/test_heavy.py")): 281.0}
    bad, _ = _seed(tmp_path, "tests/scripts/test_heavy.py soon\n", None)
    assert bad.returncode == 2 and "expected" in bad.stderr


def test_the_runner_reads_the_seeded_key_spelling():
    """The seed is only worth anything if upstream's runner looks the file up by the same key."""
    from scripts.run_tests_parallel import _effective_file_timeout

    key = str(Path("tests/scripts/test_icon_flavors.py"))
    assert _effective_file_timeout(REPO / key, REPO, 300.0, {key: 281.0}) == 843.0
    listed = (REPO / "scripts" / "fork_heavy_test_files.txt").read_text(encoding="utf-8")
    assert "tests/scripts/test_icon_flavors.py" in listed and "test_install_ps1_native_calls.py" in listed
