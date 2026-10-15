"""``scripts/classify_reds_on_tag.py`` -- is a main red also red on the pure upstream tag?

Plan: ``docs/agent-runtime-harness/planned/fast-gate-2026-10-10.md`` §6. Stage 1 pins the
pure classifier and its emitters over fake tag outputs; stage 2 pins the tag worktree
and the runner call on a scratch git clone whose ``scripts/run_tests.sh`` is a stub.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import classify_reds_on_tag as crt

V = crt.Verdict

_RED_A = "tests/a/test_red.py::test_one"
_RED_B = "tests/a/test_red.py::TestK::test_two[x - y]"
_GREEN = "tests/a/test_green.py::test_ok"
_BROKEN = "tests/a/test_broken.py::test_never_collects"
_GONE = "tests/a/test_red.py::test_renamed_away"
_FLIP = "tests/a/test_flip.py::test_sometimes"
_CRASH = "tests/a/test_crash.py::test_dies_natively"

#: the tag runner's output shapes: the live ``║`` block, the ``--- file ---`` failure
#: section, ``FAILED`` lines with and without a message, a collection ``ERROR`` line
_RUN_1 = f"""\
[1/4] ✗ tests/a/test_red.py (2 failed)
  ╔╍ Failed: tests\\a\\test_red.py ╍╍╍
  ║ FAILED {_RED_A} - AssertionError: no [brackets] here
  ║ FAILED {_RED_B} - assert 1 == 2
  ╚╍╍╍
=== Failure output ===

--- tests\\a\\test_red.py ---
FAILED {_RED_A}
FAILED {_RED_B} - assert 1 == 2

--- tests/a/test_broken.py ---
ERROR tests/a/test_broken.py - ImportError: no module named fal

--- tests/a/test_crash.py ---
Fatal Python error: Segmentation fault

--- tests/a/test_flip.py ---
FAILED {_FLIP} - TimeoutError
"""
_RUN_2 = _RUN_1.replace(f"\n--- tests/a/test_flip.py ---\nFAILED {_FLIP} - TimeoutError\n", "\n")

_PRESENCE = crt.Presence(
    nodes=frozenset({_RED_A, _RED_B, _GREEN, _FLIP, _CRASH}),
    collect_errors=frozenset({"tests/a/test_broken.py"}),  # its --collect-only pass failed
    missing_files=frozenset(),
)
_NODES = [_RED_A, _RED_B, _GREEN, _BROKEN, _GONE, _FLIP, _CRASH]


def _verdicts():
    runs = [crt.parse_run_output(_RUN_1), crt.parse_run_output(_RUN_2)]
    return crt.classify(_NODES, runs, _PRESENCE), runs


def test_the_parser_reads_node_lines_without_cutting_a_parametrize_id():
    run = crt.parse_run_output(_RUN_1)
    assert run.red_nodes == {_RED_A, _RED_B, _FLIP, "tests/a/test_broken.py"}
    assert run.red_files == {
        "tests/a/test_red.py", "tests/a/test_broken.py", "tests/a/test_crash.py", "tests/a/test_flip.py",
    }


def test_the_five_verdicts_come_out_right():
    verdicts, _ = _verdicts()
    assert verdicts == {
        _RED_A: V.UPSTREAM_RED,
        _RED_B: V.UPSTREAM_RED,
        _GREEN: V.FORK_CAUSED_OR_FLAKY,  # its file printed no node line: green on the tag
        _BROKEN: V.UPSTREAM_COLLECT_ERROR,
        _GONE: V.ABSENT_ON_TAG,  # its file runs, the node is not collected
        _FLIP: V.NONDETERMINISTIC_ON_TAG,  # red in run 1 only
        _CRASH: V.UPSTREAM_COLLECT_ERROR,  # its file failed with no node line, every run
    }


def test_a_missing_file_or_a_collection_error_at_the_tag_wins_over_the_runs():
    presence = crt.Presence(frozenset(), frozenset({"tests/a/test_green.py"}), frozenset({"tests/a/test_red.py"}))
    verdicts = crt.classify([_RED_A, _GREEN], [crt.parse_run_output(_RUN_1)], presence)
    assert verdicts == {_RED_A: V.ABSENT_ON_TAG, _GREEN: V.UPSTREAM_COLLECT_ERROR}


def test_the_table_round_trips_to_rows_keyed_by_exactly_the_upstream_reds(tmp_path):
    verdicts, _ = _verdicts()
    text = crt.emit_table(verdicts, "v9.9.9", "0123456789", "2026-10-10")
    module_path = tmp_path / f"upstream_reds_{crt.slug('v9.9.9')}.py"
    module_path.write_text(text, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("upstream_reds_v999", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert set(module._NODES) == {_RED_A, _RED_B}
    assert set(module.ROWS) == {_RED_A, _RED_B}
    assert "v9.9.9 0123456789" in module._REASON


def test_a_backslash_inside_a_parametrize_id_survives_the_parse_and_the_table(tmp_path):
    """v0.21.7: ``[...new_tab(\"a\")\\nnew_tab(...)...]`` came back with ``/`` and named no test."""
    node = 'tests/tools/test_browser_use_cli.py::test_private[mixed-new_tab("a")\\nnew_tab("b")-None]'
    windows_line = "FAILED " + node.replace("tests/tools/", "tests\\tools\\", 1) + " - AssertionError"
    run = crt.parse_run_output(windows_line)
    assert run.red_nodes == {node}
    assert run.red_files == {"tests/tools/test_browser_use_cli.py"}
    text = crt.emit_table({node: V.UPSTREAM_RED}, "v9.9.9", "0123456789", "2026-10-10")
    module_path = tmp_path / "upstream_reds_backslash.py"
    module_path.write_text(text, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("upstream_reds_backslash", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert list(module._NODES) == [node]


def test_skip_rows_name_the_whole_file_and_the_nondeterministic_files():
    verdicts, _ = _verdicts()
    rows = crt.emit_skip_rows(verdicts, "v9.9.9", "0123456789")
    assert [row.split(" · ")[0] for row in rows] == [
        "tests/a/test_broken.py", "tests/a/test_crash.py", "tests/a/test_flip.py",
    ]
    assert all(row.split(" · ")[1].startswith("upstream: ") and row.endswith(" · 0123456789") for row in rows)


def test_the_report_counts_every_verdict():
    verdicts, runs = _verdicts()
    report = crt.emit_report(verdicts, runs)
    assert f"NONDETERMINISTIC_ON_TAG  {_FLIP}  [red,pass]" in report
    assert report[-1] == (
        "verdicts: ABSENT_ON_TAG 1, FORK_CAUSED_OR_FLAKY 1, NONDETERMINISTIC_ON_TAG 1, "
        "UPSTREAM_COLLECT_ERROR 2, UPSTREAM_RED 2"
    )


# ── Stage 2: the tag worktree and the tag's runner, on a scratch clone ────────

_STUB = """#!/usr/bin/env bash
echo "args: $*"
echo "python=$HERMES_PYTHON workers=$HERMES_TEST_WORKERS"
echo "=== Failure output ==="
echo "--- tests/test_a.py ---"
echo "FAILED tests/test_a.py::test_red - boom"
exit 1
"""


def _bash() -> Path:
    if crt.GIT_BASH.is_file():
        return crt.GIT_BASH
    found = shutil.which("bash")
    if found is None or "system32" in found.lower():  # WSL's launcher is not the repo's shell
        pytest.skip("no POSIX bash")
    return Path(found)


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL)
    return done.stdout


@pytest.fixture()
def clone(tmp_path):
    repo, neutral = tmp_path / "clone", tmp_path / "neutral"
    (repo / "scripts").mkdir(parents=True)
    (repo / "tests").mkdir()
    neutral.mkdir()
    (repo / "scripts" / "run_tests.sh").write_text(_STUB, encoding="utf-8", newline="\n")
    (repo / "tests" / "test_a.py").write_text("def test_red():\n    pass\n\n\ndef test_green():\n    pass\n",
                                              encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "one")
    _git(repo, "tag", "v1")
    (repo / "tests" / "test_a.py").write_text("def test_moved_on():\n    pass\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "two")
    return repo, neutral


def _record_git_cwd(monkeypatch):
    seen = []
    real = crt._git

    def recording(args, cwd):
        seen.append(Path(cwd).resolve())
        return real(args, cwd)

    monkeypatch.setattr(crt, "_git", recording)
    return seen


def test_the_tag_worktree_is_cut_from_the_neutral_dir_runs_the_tags_runner_and_is_removed(clone, monkeypatch):
    repo, neutral = clone
    seen = _record_git_cwd(monkeypatch)
    python = Path(sys.executable)
    with crt.TagWorktree(repo, "v1", neutral) as tag_tree:
        assert tag_tree.path.parent == neutral
        assert "test_red" in (tag_tree.path / "tests" / "test_a.py").read_text(encoding="utf-8")  # the tag, not HEAD
        presence = crt.collect_present(tag_tree.path, ["tests/test_a.py", "tests/test_gone.py"], python=python)
        runs = crt.run_files(tag_tree.path, ["tests/test_a.py"], 2, neutral, bash=_bash(), python=python)
    assert seen and set(seen) == {neutral.resolve()}  # every git call: cwd = the neutral directory
    assert not tag_tree.path.exists()
    assert str(tag_tree.path.name) not in _git(repo, "worktree", "list")
    assert presence.nodes == {"tests/test_a.py::test_red", "tests/test_a.py::test_green"}
    assert presence.missing_files == {"tests/test_gone.py"} and not presence.collect_errors
    assert [run.red_nodes for run in runs] == [{"tests/test_a.py::test_red"}] * 2
    log = (neutral / "tag-run-1.log").read_text(encoding="utf-8")
    assert "args: --file-retries 0 tests/test_a.py" in log
    assert f"python={python} workers=2" in log
    assert (neutral / "tag-run-2.rc").read_text(encoding="utf-8").strip() == "1"


def test_main_prints_the_verdicts_and_leaves_no_worktree(clone, monkeypatch, capsys):
    repo, neutral = clone
    monkeypatch.chdir(neutral)
    rc = crt.main(["--tag", "v1", "--repo", str(repo), "--worktrees", str(neutral), "--python", sys.executable,
                   "--bash", str(_bash()), "--nodeid", "tests/test_a.py::test_red",
                   "--nodeid", "tests/test_a.py::test_green", "--nodeid", "tests/test_a.py::test_moved_on"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "UPSTREAM_RED             tests/test_a.py::test_red  [red,red]" in out
    assert "FORK_CAUSED_OR_FLAKY     tests/test_a.py::test_green  [pass,pass]" in out
    assert "ABSENT_ON_TAG            tests/test_a.py::test_moved_on  [-]" in out
    assert _git(repo, "worktree", "list").count("\n") == 1


def test_it_refuses_the_primary_checkout_and_a_neutral_dir_inside_a_checkout(clone, monkeypatch, capsys):
    repo, neutral = clone
    monkeypatch.chdir(repo)
    assert crt.main(["--tag", "v1", "--repo", str(repo), "--nodeid", "tests/test_a.py::test_red"]) == 2
    assert "refusing to run inside the primary checkout" in capsys.readouterr().err
    with pytest.raises(SystemExit, match="inside a git checkout"):
        crt.TagWorktree(repo, "v1", repo / "tests")
    assert _git(repo, "worktree", "list").count("\n") == 1
