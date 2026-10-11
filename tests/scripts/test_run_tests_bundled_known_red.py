"""Fast-gate §2 — a known red runs once, alone, capped; pinned without spawning pytest.

Plan: ``docs/agent-runtime-harness/planned/fast-gate-2026-10-10.md`` §2 (owner
ruling Q5: the caps as written).

* Stage 1 — the cap: ``min(flat, max(60, 2 × green))`` with a green duration,
  else ``min(flat, 120)``; the record keeps the files whose last attempt timed
  out (they have no failing ids, so the red map alone forgets them).
"""

from __future__ import annotations

from pathlib import Path

from scripts import run_tests_bundled as bundled
from scripts import run_tests_bundled_solo as solo

plan = bundled.plan


# ── Stage 1: the cap and the timed-out record ───────────────────────────────


def test_a_known_red_with_no_green_duration_is_capped_at_120_seconds():
    assert solo.known_red_timeout("tests/ci/test_x.py", {}, 300.0) == 120.0


def test_a_known_reds_cap_is_twice_its_green_duration_floored_at_60_and_never_above_flat():
    durations = {
        str(Path("tests/a.py")): 90.0,
        str(Path("tests/b.py")): 200.0,
        str(Path("tests/c.py")): 10.0,
    }

    assert solo.known_red_timeout("tests/a.py", durations, 300.0) == 180.0
    assert solo.known_red_timeout("tests/b.py", durations, 300.0) == 300.0
    assert solo.known_red_timeout("tests/c.py", durations, 300.0) == 60.0
    assert solo.known_red_timeout("tests/x.py", {}, 90.0) == 90.0


def test_the_record_keeps_a_timed_out_file_and_carries_unrun_ones_forward(tmp_path):
    plan.record_run(
        tmp_path, {"elapsed": 1.0},
        final_rc={"tests/hang.py": 124, "tests/fixed.py": 0},
        failed={},
        previous={},
        timed_out=["tests/hang.py"],
        previous_timed_out=["tests/fixed.py", "tests/unrun.py"],
    )

    assert plan.load_timed_out(tmp_path) == {"tests/hang.py", "tests/unrun.py"}
    assert plan.load_known_reds(tmp_path) == {}
    assert plan.load_timed_out(tmp_path / "nowhere") == frozenset()


def test_a_final_attempt_killed_by_the_timeout_is_timed_out_and_an_assertion_red_is_not(tmp_path):
    outcomes = [
        bundled.FileOutcome(tmp_path / "tests/hang.py", 124, "(timed out after 120s; process tree terminated)", {}, 120.0, "solo"),
        bundled.FileOutcome(tmp_path / "tests/red.py", 1, "assert 1 == 2", {"failed": 1}, 1.0, "rerun"),
        bundled.FileOutcome(tmp_path / "tests/ok.py", 0, "", {"passed": 1}, 1.0, "bundle"),
    ]

    assert bundled._timed_out(outcomes, tmp_path) == ["tests/hang.py"]
