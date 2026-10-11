"""``scripts/classify_reds_on_tag.py`` -- is a main red also red on the pure upstream tag?

Plan: ``docs/agent-runtime-harness/planned/fast-gate-2026-10-10.md`` §6. Stage 1 pins the
pure classifier and its emitters over fake tag outputs; stage 2 pins the tag worktree
and the runner call on a scratch git repository.
"""

from __future__ import annotations

import importlib.util

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
