"""The bundled runner claims the launcher's machine-wide heavy-run slot (FORK-HERMES-TEST-ENTRY-POINTS).

``scripts/run_tests_bundled_slot.py`` speaks ``EterniaLauncher/tool/heavy_run/slot_lock.dart``'s
file contract: ``slot-<i>.lock`` files, an OS lock over byte 0, a JSON note from byte 1.
A second PROCESS holds the slot here, because the property bought is cross-process
(and the kernel, not a reaper, frees a killed holder's slot).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BASH = r"C:\Program Files\Git\bin\bash.exe" if sys.platform == "win32" else "bash"


def _slot():
    spec = importlib.util.spec_from_file_location("run_tests_bundled_slot", REPO / "scripts" / "run_tests_bundled_slot.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("run_tests_bundled_slot", module)  # a dataclass resolves its module by name
    spec.loader.exec_module(module)
    return module


slot = _slot()

_HOLDER = """
import importlib.util, sys, time
spec = importlib.util.spec_from_file_location("s", sys.argv[1])
s = importlib.util.module_from_spec(spec); sys.modules["s"] = s; spec.loader.exec_module(s)
h = s.acquire("holder-label", {"ETERNIA_HEAVY_SLOT_DIR": sys.argv[2], "ETERNIA_HEAVY_SLOTS": "1"})
print("held", h.index, flush=True)
time.sleep(120)
"""


def _env(directory: Path, **extra: str) -> dict[str, str]:
    return {"ETERNIA_HEAVY_SLOT_DIR": str(directory), "ETERNIA_HEAVY_SLOTS": "1", **extra}


@pytest.mark.timeout(90)
def test_a_held_slot_makes_a_second_process_wait_naming_the_holder_and_death_frees_it(tmp_path):
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(REPO / "scripts" / "run_tests_bundled_slot.py"), str(tmp_path)],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held 0"
        said: list[str] = []
        got = slot.acquire("waiter", _env(tmp_path), log=said.append, poll_every=0.05, give_up_after=0.5)
        assert got is None
        report = "\n".join(said)
        assert "waiting for a heavy-run slot" in report and "slot 0: pid " in report and "holder-label" in report
    finally:
        holder.kill()
        holder.wait(timeout=30)
    deadline = time.monotonic() + 20
    got = None
    while got is None and time.monotonic() < deadline:  # the kernel releases a killed holder's lock
        got = slot.acquire("after", _env(tmp_path), log=lambda _l: None, poll_every=0.05, give_up_after=0.2)
    assert got is not None and got.index == 0
    got.release()


def test_the_note_is_the_launcher_format_claim_byte_then_json(tmp_path):
    held = slot.acquire("label x", _env(tmp_path))
    try:
        raw = (tmp_path / "slot-0.lock").read_bytes() if sys.platform != "win32" else None
        if raw is None:  # byte 0 is mandatorily locked on Windows: read past it, as the Dart reader does
            with open(tmp_path / "slot-0.lock", "rb") as handle:
                handle.seek(1)
                note = json.loads(handle.read())
        else:
            assert raw[:1] == b"#"
            note = json.loads(raw[1:])
        assert note["pid"] == os.getpid() and note["label"] == "label x" and note["cwd"] and note["since"]
        assert held.child_environ() == {"ETERNIA_HEAVY_SLOT_HELD": "0", "ETERNIA_HEAVY_SLOT_JOBS": str(held.jobs)}
    finally:
        held.release()
    assert (tmp_path / "slot-0.lock").read_bytes() == b"#"  # release blanks the note


@pytest.mark.parametrize("env", [{"ETERNIA_HEAVY_SLOT_HELD": "1"}, {"ETERNIA_HEAVY_SLOTS": "off"}, {"ETERNIA_HEAVY_SLOTS": "0"}])
def test_an_inherited_slot_or_a_disabled_cap_claims_nothing(tmp_path, env):
    slots = tmp_path / "slots"
    assert slot.acquire("x", {"ETERNIA_HEAVY_SLOT_DIR": str(slots), **env}) is None
    assert not slots.exists()


def test_count_and_jobs_match_the_dart_side():
    assert slot.slot_count({}) == 2 and slot.slot_count({"ETERNIA_HEAVY_SLOTS": "garbage"}) == 0
    assert slot.slot_jobs(2, 16) == 7 and slot.slot_jobs(1, 16) == 14 and slot.slot_jobs(4, 8) == 4


def test_claimed_hands_children_the_held_marker_and_takes_it_back(tmp_path, monkeypatch):
    monkeypatch.setenv("ETERNIA_HEAVY_SLOT_DIR", str(tmp_path))
    monkeypatch.delenv("ETERNIA_HEAVY_SLOT_HELD", raising=False)
    monkeypatch.delenv("ETERNIA_HEAVY_SLOTS", raising=False)
    with slot.claimed("x", log=lambda _l: None) as held:
        assert held is not None and os.environ["ETERNIA_HEAVY_SLOT_HELD"] == str(held.index)
    assert "ETERNIA_HEAVY_SLOT_HELD" not in os.environ


@pytest.mark.skipif(sys.platform == "win32" and not Path(BASH).is_file(), reason="Git Bash not installed")
def test_the_slot_dir_is_named_from_the_machine_temp_before_temp_moves(tmp_path):
    door = (REPO / "scripts" / "_fork_test_env.sh").as_posix()
    machine_tmp = tmp_path / "machine-temp"
    machine_tmp.mkdir()
    test_root = tmp_path / "test-tmp"
    test_root.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "ETERNIA_HEAVY_SLOT_DIR"}
    env.update(TMP=str(machine_tmp), TEMP=str(machine_tmp), TMPDIR=str(machine_tmp), HERMES_TEST_TMP_ROOT=str(test_root))
    script = f'. "{door}"; REPO_ROOT=.; fork_test_tmp_root >/dev/null; printf "%s\\n%s\\n" "$ETERNIA_HEAVY_SLOT_DIR" "$TEMP"'
    proc = subprocess.run([BASH, "-c", script], env=env, capture_output=True, text=True, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    slot_dir, temp = proc.stdout.splitlines()
    assert Path(slot_dir) == machine_tmp / "eternia-heavy-slots"
    assert Path(temp).resolve() == test_root.resolve()


def test_the_three_slot_variables_cross_env_i():
    listed = (REPO / "scripts" / "fork_test_env.txt").read_text(encoding="utf-8")
    names = {line.split("#")[0].strip() for line in listed.splitlines()}
    assert {"ETERNIA_HEAVY_SLOTS", "ETERNIA_HEAVY_SLOT_DIR", "ETERNIA_HEAVY_SLOT_HELD"} <= names


def test_the_runner_entry_claims_for_a_real_run_only():
    spec = importlib.util.spec_from_file_location("run_tests_bundled", REPO / "scripts" / "run_tests_bundled.py")
    bundled = sys.modules.get("run_tests_bundled") or importlib.util.module_from_spec(spec)
    if "run_tests_bundled" not in sys.modules:
        sys.modules["run_tests_bundled"] = bundled
        spec.loader.exec_module(bundled)
    claims = bundled._claims_a_heavy_slot
    assert claims(["tests"], {}) and claims(["--affected"], {})
    assert not claims(["--cache-dry-run", "tests"], {}) and not claims(["-h"], {})
    assert not claims(["tests"], {"PYTEST_CURRENT_TEST": "t.py::x (call)"})  # a test's runner: its parent paid
