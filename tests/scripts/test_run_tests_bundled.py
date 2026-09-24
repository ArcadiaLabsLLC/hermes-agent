"""The bundled runner's contract: membership, the solo re-run, the unbundled list.

``scripts/run_tests_bundled.py`` runs up to N test files in one pytest process.
What makes that safe to trust is three properties, pinned here without
spawning pytest — the bundle and solo launchers are injected:

* every discovered file runs exactly once, in a bundle or alone;
* a failing bundle re-runs its unclean members ONE FILE PER PROCESS, and a
  member red in the bundle but green alone is reported as an isolation leak;
* a file named in ``scripts/test_bundles_unbundled.txt`` never enters a bundle.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load():
    name = "hermes_run_tests_bundled"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _REPO_ROOT / "scripts" / "run_tests_bundled.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bundled = _load()


def _tree(root: Path, rels: list[str]) -> list[Path]:
    paths = []
    for rel in rels:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_ok():\n    pass\n", encoding="utf-8")
        paths.append(path)
    return paths


def _rels(root: Path, paths) -> list[str]:
    return [p.resolve().relative_to(root.resolve()).as_posix() for p in paths]


# ── membership ──────────────────────────────────────────────────────────────


def test_every_file_lands_in_exactly_one_bundle_or_solo(tmp_path):
    rels = [f"tests/alpha/test_{i:02d}.py" for i in range(23)] + [
        f"tests/beta/test_{i:02d}.py" for i in range(5)
    ] + ["tests/beta/sub/test_deep.py", "tests/test_root_level.py"]
    files = _tree(tmp_path, rels)

    bundles, solos = bundled.assign_bundles(files, tmp_path, 10, unbundled=["tests/alpha/test_03.py"])

    placed = _rels(tmp_path, [f for b in bundles for f in b] + solos)
    assert sorted(placed) == sorted(rels)
    assert len(placed) == len(set(placed))
    assert all(1 <= len(b) <= 10 for b in bundles)
    # Bundles never cross a top-level test directory.
    for bundle in bundles:
        assert len({tuple(r.split("/")[:2]) for r in _rels(tmp_path, bundle)}) == 1


def test_bundles_keep_path_order_within_their_directory(tmp_path):
    rels = [f"tests/alpha/test_{i:02d}.py" for i in range(7)]
    files = _tree(tmp_path, list(reversed(rels)))

    bundles, _solos = bundled.assign_bundles(files, tmp_path, 3)

    assert [_rels(tmp_path, b) for b in bundles] == [rels[0:3], rels[3:6], rels[6:7]]


def test_bundle_size_one_runs_everything_alone(tmp_path):
    files = _tree(tmp_path, ["tests/alpha/test_a.py", "tests/alpha/test_b.py"])

    bundles, solos = bundled.assign_bundles(files, tmp_path, 1)

    assert bundles == [] and len(solos) == 2


# ── the unbundled list ──────────────────────────────────────────────────────


def test_a_listed_file_never_enters_a_bundle(tmp_path):
    listing = tmp_path / "unbundled.txt"
    listing.write_text(
        "# header comment\n\n"
        "tests/alpha/test_leaky.py  # observed: bundle #4 {'failed': 2} after 7 earlier members\n",
        encoding="utf-8",
    )
    files = _tree(tmp_path, ["tests/alpha/test_a.py", "tests/alpha/test_leaky.py", "tests/alpha/test_z.py"])

    unbundled = bundled.load_unbundled(listing)
    bundles, solos = bundled.assign_bundles(files, tmp_path, 20, unbundled)

    assert unbundled == {"tests/alpha/test_leaky.py"}
    assert _rels(tmp_path, solos) == ["tests/alpha/test_leaky.py"]
    assert "tests/alpha/test_leaky.py" not in _rels(tmp_path, [f for b in bundles for f in b])
    # Positive control: the same file with the list empty IS bundled.
    bundles, solos = bundled.assign_bundles(files, tmp_path, 20, set())
    assert solos == [] and "tests/alpha/test_leaky.py" in _rels(tmp_path, bundles[0])


def test_a_missing_unbundled_list_is_empty(tmp_path):
    assert bundled.load_unbundled(tmp_path / "absent.txt") == set()


# ── per-file results out of one bundle ──────────────────────────────────────


def _event_lines(records):
    return [json.dumps(r) for r in records]


def test_events_fold_into_per_file_counts():
    events = bundled.tally_events(
        _event_lines(
            [
                {"k": "start", "t": 1.0},
                {"k": "collect", "f": "tests/a/test_x.py", "d": 0.5, "err": False},
                {"k": "test", "f": "tests/a/test_x.py", "c": "passed", "d": 0.1},
                {"k": "test", "f": "tests/a/test_x.py", "c": "", "d": 0.0},
                {"k": "test", "f": "tests/a/test_x.py", "c": "error", "d": 0.2, "n": "tests/a/test_x.py::t2"},
                {"k": "test", "f": "tests/a/test_y.py", "c": "skipped", "d": 0.0},
                {"k": "end", "t": 2.0, "rc": 1},
            ]
        )
        + ['{"k": "test", "f": torn']
    )

    assert events.files["tests/a/test_x.py"].summary() == {"passed": 1, "errors": 1}
    assert events.files["tests/a/test_x.py"].failed_nodeids == ["tests/a/test_x.py::t2"]
    assert not events.files["tests/a/test_x.py"].clean
    assert events.files["tests/a/test_y.py"].clean
    assert events.session_end == 2.0


def test_a_killed_bundle_reruns_the_running_member_and_everything_behind_it():
    members = ["a.py", "b.py", "c.py", "d.py"]
    events = bundled.tally_events(
        _event_lines(
            [{"k": "start", "t": 1.0}]
            + [{"k": "collect", "f": m, "d": 0.1, "err": False} for m in members]
            + [
                {"k": "test", "f": "a.py", "c": "passed", "d": 1.0},
                {"k": "test", "f": "b.py", "c": "passed", "d": 1.0},
            ]
        )
    )

    assert bundled.members_to_rerun(members, events, 124) == ["b.py", "c.py", "d.py"]


# ── the solo re-run ─────────────────────────────────────────────────────────


def _fake_bundle_runner(red_in_bundle: set[str], root: Path):
    """A bundle launcher that writes the plugin's events: every member passes
    except the ones in ``red_in_bundle``, which record one failed test."""

    def _run(first, args, repo_root, timeout):
        events_arg = next(a for a in args if a.startswith("--hermes-bundle-events="))
        events_path = Path(events_arg.split("=", 1)[1])
        members = [first] + [Path(a) for a in args if a.endswith(".py")]
        records = [{"k": "start", "t": 0.0}]
        rc = 0
        for member in members:
            rel = member.resolve().relative_to(root.resolve()).as_posix()
            records.append({"k": "collect", "f": rel, "d": 0.0, "err": False})
            if rel in red_in_bundle:
                rc = 1
                records.append({"k": "test", "f": rel, "c": "failed", "d": 0.0, "n": f"{rel}::test_ok"})
            else:
                records.append({"k": "test", "f": rel, "c": "passed", "d": 0.0})
        records.append({"k": "end", "t": 1.0, "rc": rc})
        events_path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        return first, rc, "bundle output", {}, 1.0

    return _run


def test_a_failing_bundle_reruns_its_red_member_alone_and_names_the_leak(tmp_path):
    rels = [f"tests/alpha/test_{i}.py" for i in range(5)]
    files = _tree(tmp_path, rels)
    solo_calls: list[str] = []

    def _solo(path, args, repo_root, timeout, retries):
        solo_calls.append(path.resolve().relative_to(tmp_path.resolve()).as_posix())
        return path, 0, "ok", {"passed": 1}, 0.5

    result = bundled.run(
        files,
        [],
        tmp_path,
        jobs=2,
        bundle_size=20,
        flat_timeout=300.0,
        retries=1,
        durations={},
        bundle_runner=_fake_bundle_runner({"tests/alpha/test_3.py"}, tmp_path),
        solo_runner=_solo,
    )

    assert solo_calls == ["tests/alpha/test_3.py"]
    by_file = {o.file.resolve().relative_to(tmp_path.resolve()).as_posix(): o for o in result.outcomes}
    assert sorted(by_file) == rels
    assert by_file["tests/alpha/test_3.py"].via == "rerun"
    assert all(by_file[r].via == "bundle" and by_file[r].rc == 0 for r in rels if r != "tests/alpha/test_3.py")
    assert [leak.earlier for leak in result.leaks] == [rels[:3]]
    assert result.leaks[0].failed_nodeids == ["tests/alpha/test_3.py::test_ok"]


def test_a_member_red_alone_too_is_a_failure_not_a_leak(tmp_path):
    files = _tree(tmp_path, ["tests/alpha/test_a.py", "tests/alpha/test_b.py"])

    def _solo(path, args, repo_root, timeout, retries):
        return path, 1, "assert 1 == 2", {"failed": 1}, 0.5

    result = bundled.run(
        files,
        [],
        tmp_path,
        jobs=1,
        bundle_size=20,
        flat_timeout=300.0,
        retries=0,
        durations={},
        bundle_runner=_fake_bundle_runner({"tests/alpha/test_b.py"}, tmp_path),
        solo_runner=_solo,
    )

    assert result.leaks == []
    failed = [o for o in result.outcomes if o.rc != 0]
    assert [o.file.name for o in failed] == ["test_b.py"] and failed[0].summary == {"failed": 1}


def test_a_green_bundle_runs_nothing_alone(tmp_path):
    files = _tree(tmp_path, [f"tests/alpha/test_{i}.py" for i in range(3)])

    def _solo(*_args):  # pragma: no cover - reaching it is the failure
        raise AssertionError("a green bundle must not re-run a member")

    result = bundled.run(
        files,
        [],
        tmp_path,
        jobs=1,
        bundle_size=20,
        flat_timeout=300.0,
        retries=0,
        durations={},
        bundle_runner=_fake_bundle_runner(set(), tmp_path),
        solo_runner=_solo,
    )

    assert result.reruns == 0 and all(o.rc == 0 for o in result.outcomes)


def test_the_bundle_timeout_scales_with_its_members(tmp_path):
    files = _tree(tmp_path, ["tests/alpha/test_a.py", "tests/alpha/test_b.py"])
    durations = {str(Path("tests/alpha/test_a.py")): 100.0, str(Path("tests/alpha/test_b.py")): 50.0}

    assert bundled.bundle_timeout(files, tmp_path, 300.0, durations) == pytest.approx(450.0)
    assert bundled.bundle_timeout(files, tmp_path, 300.0, {}) == pytest.approx(300.0)
