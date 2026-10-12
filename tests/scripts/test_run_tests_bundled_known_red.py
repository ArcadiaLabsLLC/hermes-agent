"""Fast-gate §2 — a known red runs once, alone, capped; pinned without spawning pytest.

Plan: ``docs/agent-runtime-harness/planned/fast-gate-2026-10-10.md`` §2 (owner
ruling Q5: the caps as written).

* Stage 1 — the cap: ``min(flat, max(60, 2 × green))`` with a green duration,
  else ``min(flat, 120)``; the record keeps the files whose last attempt timed
  out (they have no failing ids, so the red map alone forgets them).
* Stage 2 — a known red is a solo, run with no flake retry and the cap, never
  retried as a straggler, and its output names how its failing set moved; a
  NEW red still goes bundle → re-run alone → leak line. A file whose last red
  was a TIMEOUT runs at the flat timeout instead of the cap (owner ruling
  2026-10-11 on Q5: a 174 s file capped at 120 s could never go green again).
"""

from __future__ import annotations

import json
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


# ── Stage 2: known reds as solos, once, no straggler retry ──────────────────


def _tree(root: Path, rels: list[str]) -> list[Path]:
    for rel in rels:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("def test_ok():\n    pass\n", encoding="utf-8")
    return [root / rel for rel in rels]


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _events(args: list[str]):
    """The recorder's path, or None (the straggler retry passes no recorder)."""

    arg = next((a for a in args if a.startswith("--hermes-bundle-events=")), None)
    return None if arg is None else Path(arg.split("=", 1)[1])


def _write(events, rel: str, failed: list[str]) -> None:
    if events is None:
        return
    records = [{"k": "start", "t": 0.0}, {"k": "collect", "f": rel, "d": 0.1, "err": False}]
    records += [{"k": "test", "f": rel, "c": "failed", "d": 0.1, "n": n} for n in failed]
    records += [] if failed else [{"k": "test", "f": rel, "c": "passed", "d": 0.1}]
    records.append({"k": "end", "t": 1.0, "rc": int(bool(failed))})
    with events.open("a", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(r) + "\n" for r in records))


def _bundle_runner(root: Path, red: dict[str, list[str]], calls: list):
    def _run(first, args, repo_root, timeout):
        members = [first] + [Path(a) for a in args if a.endswith(".py")]
        calls.append(("bundle", [_rel(root, m) for m in members]))
        for member in members:
            _write(_events(args), _rel(root, member), red.get(_rel(root, member), []))
        return first, int(any(_rel(root, m) in red for m in members)), "bundle output", {}, 1.0

    return _run


def _solo_runner(root: Path, red: dict[str, list[str]], calls: list, rc_red: int = 1):
    def _run(path, args, repo_root, timeout, retries):
        rel = _rel(root, path)
        calls.append(("solo", rel, timeout, retries))
        _write(_events(args), rel, red.get(rel, []))
        rc = rc_red if rel in red else 0
        if rc == 124:  # the per-file runner's timeout shape: no summary, the banner
            return path, rc, f"(timed out after {timeout:.0f}s; process tree terminated)", {}, timeout
        return path, rc, "red alone" if rc else "ok", {"failed": 1} if rc else {"passed": 1}, 0.5

    return _run


def _run(root, files, red, calls, *, known=None, timed_out=(), durations=None, rc_red=1):
    known = known or {}
    durations = durations or {}
    return bundled.run(
        files, [], root, jobs=2, bundle_size=20, flat_timeout=300.0, retries=1, durations=durations,
        known_reds=known, solo_policy=bundled._solo_policy(root, 300.0, 1, durations, known, timed_out),
        bundle_runner=_bundle_runner(root, red, calls), solo_runner=_solo_runner(root, red, calls, rc_red),
    )


def test_a_known_red_never_enters_a_bundle_and_runs_once_with_no_retry_and_the_cap(tmp_path):
    rels = ["tests/alpha/test_0.py", "tests/alpha/test_1.py", "tests/alpha/test_2.py"]
    files = _tree(tmp_path, rels)
    red = {"tests/alpha/test_1.py": ["tests/alpha/test_1.py::test_ok"]}
    calls: list = []

    result = _run(
        tmp_path, files, red, calls, known={k: frozenset(v) for k, v in red.items()},
        durations={str(Path("tests/alpha/test_1.py")): 90.0},
    )

    bundled_rels = [rel for call in calls if call[0] == "bundle" for rel in call[1]]
    assert "tests/alpha/test_1.py" not in bundled_rels
    assert [c for c in calls if c[0] == "solo"] == [("solo", "tests/alpha/test_1.py", 180.0, 0)]
    outcome = next(o for o in result.outcomes if o.file.name == "test_1.py")
    assert (outcome.via, outcome.rc, result.reruns) == ("known-red", 1, 0)
    assert result.ledger.summary(2)["processes"]["known-red"] == 1


def test_a_timed_out_file_is_known_red_runs_at_the_flat_timeout_and_is_not_retried_as_a_straggler(tmp_path):
    files = _tree(tmp_path, ["tests/alpha/test_0.py", "tests/alpha/test_hang.py"])
    red = {"tests/alpha/test_hang.py": []}  # killed: no failing ids
    calls: list = []

    result = _run(tmp_path, files, red, calls, timed_out=["tests/alpha/test_hang.py"], rc_red=124)

    assert [c for c in calls if c[0] == "solo"] == [("solo", "tests/alpha/test_hang.py", 300.0, 0)]
    outcome = next(o for o in result.outcomes if o.file.name == "test_hang.py")
    assert (outcome.via, outcome.rc) == ("known-red", 124)
    assert "known-red timeout cap 300s; run alone: scripts/run_tests.sh tests/alpha/test_hang.py" in outcome.output
    assert result.ledger.summary(2)["processes"]["retry"] == 0


def test_a_known_red_whose_failing_set_changed_prints_the_diff_and_the_record_carries_the_new_set(tmp_path):
    files = _tree(tmp_path, ["tests/alpha/test_0.py", "tests/alpha/test_1.py"])
    now = ["tests/alpha/test_1.py::test_new", "tests/alpha/test_1.py::test_ok"]
    calls: list = []
    known = {"tests/alpha/test_1.py": frozenset({"tests/alpha/test_1.py::test_ok", "tests/alpha/test_1.py::test_gone"})}

    result = _run(tmp_path, files, {"tests/alpha/test_1.py": now}, calls, known=known)
    final_rc = {_rel(tmp_path, o.file): o.rc for o in result.outcomes}
    plan.record_run(tmp_path, {}, final_rc, result.ledger.failed, known)

    outcome = next(o for o in result.outcomes if o.file.name == "test_1.py")
    assert "failing set changed: +1 −1" in outcome.output
    assert "  + tests/alpha/test_1.py::test_new" in outcome.output
    assert "  − tests/alpha/test_1.py::test_gone" in outcome.output
    assert plan.load_known_reds(tmp_path) == {"tests/alpha/test_1.py": frozenset(now)}


def test_a_new_red_still_goes_bundle_then_alone_and_is_named_a_leak_when_green_there(tmp_path):
    files = _tree(tmp_path, ["tests/alpha/test_0.py", "tests/alpha/test_1.py"])
    calls: list = []
    bundle_red = {"tests/alpha/test_1.py": ["tests/alpha/test_1.py::test_ok"]}

    result = bundled.run(
        files, [], tmp_path, jobs=2, bundle_size=20, flat_timeout=300.0, retries=1, durations={},
        bundle_runner=_bundle_runner(tmp_path, bundle_red, calls), solo_runner=_solo_runner(tmp_path, {}, calls),
    )

    assert calls[0] == ("bundle", ["tests/alpha/test_0.py", "tests/alpha/test_1.py"])
    assert calls[1] == ("solo", "tests/alpha/test_1.py", 300.0, 1)
    assert next(o for o in result.outcomes if o.file.name == "test_1.py").via == "rerun"
    assert [_rel(tmp_path, leak.file) for leak in result.leaks] == ["tests/alpha/test_1.py"]
