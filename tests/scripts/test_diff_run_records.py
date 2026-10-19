"""``scripts/diff_run_records.py``: the two-run diff p10 S-A2 reads (NEW / FIXED reds, the counts)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import diff_run_records as drr

A, B, C = "tests/a_test.py", "tests/b_test.py", "tests/c_test.py"


def _store(tmp_path: Path) -> Path:
    diag = [
        {"run": "off", "f": A, "call": 1.0, "body_patches": 3, "teardown_error_ids": []},
        {"run": "off", "f": B, "call": 2.0, "teardown_errors": 1, "teardown_error_ids": [f"{B}::t_torn"]},
        {"run": "on", "f": A, "call": 1.5, "body_patches": 3, "late_fixture_patches": 1,
         "teardown_errors": 1, "teardown_error_ids": [f"{A}::t_new"]},
        {"run": "on", "f": B, "call": 2.5},
    ]
    runs = [
        {"elapsed": 10.0, "red": {B: [f"{B}::t_torn"], C: [f"{C}::carried"]}, "timed_out": []},
        {"elapsed": 11.0, "red": {A: [f"{A}::t_new"], C: [f"{C}::carried"], "tests/x.py": ["tests/x.py::not_run"]}},
    ]
    (tmp_path / "diagnosis.jsonl").write_text("".join(json.dumps(d) + "\n" for d in diag), encoding="utf-8")
    (tmp_path / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs), encoding="utf-8")
    return tmp_path


def test_new_and_fixed_reds_are_read_only_over_files_both_runs_ran(tmp_path):
    """Mutation: drop the ``rel in diag`` restriction in ``side`` → the carried ``tests/x.py`` red is NEW."""

    store = _store(tmp_path)
    off, on = drr.side(store, "off", -2), drr.side(store, "on", -1)
    found = drr.diff(off, on)
    assert found["new"] == [(f"{A}::t_new", "teardown")]
    assert found["fixed"] == [f"{B}::t_torn"]
    assert on["counts"] == {"body_patches": 3, "late_fixture_patches": 1, "teardown_errors": 1}
    assert on["seconds"]["call"] == 4.0 and off["wall"] == 10.0


def test_main_prints_both_sides(tmp_path, capsys):
    assert drr.main(["off", "on", "--store", str(_store(tmp_path))]) == 0
    out = capsys.readouterr().out
    assert "NEW (1):" in out and "FIXED (1):" in out and out.startswith("OFF: files 2")
