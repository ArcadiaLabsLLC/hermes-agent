"""Fast-gate §3 stage 2 — the runner shards slow files only on a tail-bound run.

Plan: ``docs/agent-runtime-harness/planned/fast-gate-2026-10-10.md`` §3. Pinned
without spawning pytest (the solo launcher is injected):

* a tail-bound run (Σ estimates / jobs < 2 × max) splits a file cached green
  ≥ 90 s with ≥ 2k recorded tests into k = min(4, ceil(s / 45)) shards; a
  work-bound run, a known red and a file on the unsharded list run whole;
* a file is green only when every shard is; a red shard runs the file once
  WHOLE: green whole → the file is green and printed as an unsharded-list
  candidate, red whole → an ordinary red;
* the record keeps each slow file's test count for the next plan.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import run_tests_bundled as bundled

plan, shard = bundled.plan, bundled.shard


def _tree(root: Path, rels: list[str]) -> list[Path]:
    for rel in rels:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("def test_ok():\n    pass\n", encoding="utf-8")
    return [root / rel for rel in rels]


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _arg(args: list[str], prefix: str):
    return next((a.split("=", 1)[1] for a in args if a.startswith(prefix)), None)


def _solo_runner(root: Path, calls: list, red_shards: set[str] = frozenset(), red_whole: bool = False):
    """Records ``(rel, shard spec or None)``; a shard in ``red_shards`` fails one test."""

    def _run(path, args, repo_root, timeout, retries):
        rel, spec = _rel(root, path), _arg(args, "--hermes-shard=")
        calls.append((rel, spec))
        red = spec in red_shards if spec else red_whole
        events = _arg(args, "--hermes-bundle-events=")
        if events:
            records = [{"k": "start", "t": 0.0}, {"k": "collect", "f": rel, "d": 1.0, "err": False},
                       {"k": "test", "f": rel, "c": "failed" if red else "passed", "d": 10.0,
                        **({"n": f"{rel}::test_{spec}"} if red else {})},
                       {"k": "end", "t": 1.0, "rc": int(red)}]
            Path(events).write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        return path, int(red), "red" if red else "ok", {"failed": 1} if red else {"passed": 10}, 11.0

    return _run


_SLOW = "tests/alpha/test_slow.py"


def _setup(root: Path, *, others: int = 2, tests: int = 40, slow_seconds: float = 290.0):
    rels = [_SLOW] + [f"tests/alpha/test_{i}.py" for i in range(others)]
    files = _tree(root, rels)
    durations = {str(Path(_SLOW)): slow_seconds}
    plan.record_run(root, {}, {}, {}, {}, extra={"tests": {_SLOW: tests}})
    return files, durations


def _policy(root, files, durations, jobs=2, known=None):
    base = bundled._solo_policy(root, 300.0, 0, durations, known or {})
    return bundled._with_shards(base, files, root, durations, jobs)


def _run(root, files, durations, policy, calls, **runner):
    return bundled.run(
        files, [], root, jobs=2, bundle_size=20, flat_timeout=300.0, retries=0, durations=durations,
        solo_seconds=60.0, solo_policy=policy, bundle_runner=_green_bundle(root), solo_runner=_solo_runner(root, calls, **runner),
    )


def _green_bundle(root: Path):
    def _run(first, args, repo_root, timeout):
        members = [first] + [Path(a) for a in args if a.endswith(".py")]
        records = [{"k": "start", "t": 0.0}]
        for rel in (_rel(root, m) for m in members):
            records += [{"k": "collect", "f": rel, "d": 0.1, "err": False}, {"k": "test", "f": rel, "c": "passed", "d": 0.1}]
        records.append({"k": "end", "t": 1.0, "rc": 0})
        Path(_arg(args, "--hermes-bundle-events=")).write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        return first, 0, "bundle", {}, 1.0

    return _run


# ── the planner rule ────────────────────────────────────────────────────────


def test_a_tail_bound_plan_shards_the_slow_file_into_four_and_a_work_bound_plan_does_not(tmp_path):
    files, durations = _setup(tmp_path)

    tail = _policy(tmp_path, files, durations)
    work = _policy(tmp_path, files + _tree(tmp_path, [f"tests/beta/test_{i}.py" for i in range(40)]), durations)

    assert tail.shards.counts == {_SLOW: 4} and tail.shards.line() == "tail-bound: sharding 1 files into 4 shards"
    assert work.shards.counts == {} and work.shards.line() == "work-bound: no sharding"


def test_k_follows_the_duration_and_a_file_with_too_few_tests_runs_whole():
    assert shard.shard_count(89.0, 100) == 1
    assert shard.shard_count(100.0, 100) == 3
    assert shard.shard_count(400.0, 100) == 4
    assert shard.shard_count(400.0, 7) == 1  # 2k = 8 tests needed
    assert shard.shard_count(None, 100) == 1


def test_a_known_red_and_a_listed_file_are_never_sharded(tmp_path):
    files, durations = _setup(tmp_path)

    known = _policy(tmp_path, files, durations, known={_SLOW: frozenset({f"{_SLOW}::t"})})
    (tmp_path / shard.UNSHARDED_LIST).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / shard.UNSHARDED_LIST).write_text(f"{_SLOW}  # observed: shard 1/4 red\n", encoding="utf-8")
    listed = _policy(tmp_path, files, durations)

    assert known.shards.counts == {} and listed.shards.counts == {}


# ── running the shards and joining them ─────────────────────────────────────


def test_every_shard_runs_and_a_green_file_is_one_outcome_with_the_shards_seconds(tmp_path):
    files, durations = _setup(tmp_path)
    calls: list = []

    result = _run(tmp_path, files, durations, _policy(tmp_path, files, durations), calls)

    assert sorted(spec for rel, spec in calls if rel == _SLOW) == ["0/4", "1/4", "2/4", "3/4"]
    slow = [o for o in result.outcomes if _rel(tmp_path, o.file) == _SLOW]
    assert len(slow) == 1 and (slow[0].rc, slow[0].via, slow[0].seconds) == (0, "4 shards", 44.0)
    assert slow[0].summary == {"passed": 40}
    assert result.ledger.file_seconds[_SLOW] == 44.0  # 4 × (1 s collect + 10 s tests)
    assert result.ledger.summary(2)["processes"]["shard"] == 4


def test_a_red_shard_with_a_green_whole_run_is_green_and_an_unsharded_candidate(tmp_path):
    files, durations = _setup(tmp_path)
    calls: list = []
    policy = _policy(tmp_path, files, durations)

    result = _run(tmp_path, files, durations, policy, calls, red_shards={"1/4"})

    assert (_SLOW, None) in calls  # the one whole run
    slow = [o for o in result.outcomes if _rel(tmp_path, o.file) == _SLOW]
    assert len(slow) == 1 and (slow[0].rc, slow[0].via) == (0, shard.WHOLE_CHECK_VIA)
    assert policy.closing_lines()[1].startswith("=== 1 file(s) red sharded, green whole")
    assert policy.closing_lines()[2] == f"  {_SLOW}  # observed: shard 1/4 {{'failed': 1}} red sharded, green whole"
    assert result.ledger.failed[_SLOW] == []


def test_a_red_shard_with_a_red_whole_run_is_an_ordinary_red(tmp_path):
    files, durations = _setup(tmp_path)
    calls: list = []
    policy = _policy(tmp_path, files, durations)

    result = _run(tmp_path, files, durations, policy, calls, red_shards={"2/4"}, red_whole=True)

    slow = [o for o in result.outcomes if _rel(tmp_path, o.file) == _SLOW]
    assert len(slow) == 1 and slow[0].rc == 1 and policy.closing_lines() == []


def test_the_record_keeps_a_slow_files_test_count_and_carries_unrun_ones():
    ran = {"tests/slow.py": (120.0, 50), "tests/fast.py": (3.0, 9), "tests/gone_slow.py": (10.0, 30)}
    previous = {"tests/gone_slow.py": 30, "tests/unrun.py": 12}

    assert shard.tests_after(previous, ran) == {"tests/slow.py": 50, "tests/unrun.py": 12}
