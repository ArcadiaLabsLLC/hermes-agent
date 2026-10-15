"""``scripts/worker_protocol.py`` -- the worker-count protocol's sampler, sample and receipt.

Plan: ``docs/agent-runtime-harness/planned/fast-gate-2026-10-10.md`` §4 stage 1. Times are
the plan's 12 s run at a 5 s interval, scaled by 1/20.
"""

from __future__ import annotations

import json
import sys
import time

from scripts import worker_protocol as wp


def _fake_cpu(interval: float) -> float:
    time.sleep(interval)  # psutil.cpu_percent(interval=...) blocks for the interval
    return 50.0


def test_the_sampler_records_a_sample_per_interval_and_stops_with_the_run():
    sampler = wp.SaturationSampler(interval=0.25, cpu=_fake_cpu, mem=lambda: 40.0)
    with sampler:
        time.sleep(1.2)  # the plan's 12 s run at 5 s, scaled
    assert not sampler.thread.is_alive()  # stopped AND joined with the run
    taken = len(sampler.cpu_samples)
    assert taken >= 2  # >= 1 sample per interval of the run
    time.sleep(0.6)
    assert len(sampler.cpu_samples) == taken  # nothing samples after the run
    summary = sampler.summary()
    assert summary["cpu_busy_pct"] == {"mean": 50.0, "p90": 50.0}
    assert summary["mem_peak_pct"] == 40.0 and summary["samples"] == taken


def test_the_sample_is_every_slow_file_plus_a_seeded_draw_from_the_fast_band():
    seconds = {f"tests/slow_{i}.py": 60.0 + i for i in range(5)}
    seconds.update({f"tests/band_{i:03}.py": 0.5 + (i % 35) / 10 for i in range(300)})
    seconds.update({"tests/tiny.py": 0.1, "tests/mid.py": 20.0, "tests/slow_skip.py": 90.0})
    first = wp.build_sample(seconds, exclude=["tests/slow_skip.py"])
    assert first[:5] == [f"tests/slow_{i}.py" for i in range(5)]
    assert len(first) == 205 and all(rel.startswith("tests/band_") for rel in first[5:])
    assert "tests/slow_skip.py" not in first and "tests/tiny.py" not in first and "tests/mid.py" not in first
    assert wp.build_sample(seconds, exclude=["tests/slow_skip.py"]) == first  # the seed is the identity
    assert wp.build_sample(seconds, exclude=["tests/slow_skip.py"], seed=8) != first


def test_the_log_parser_keeps_each_files_last_attempt():
    log = (
        "[  1/3] ✗ tests/a/test_x.py (bundle, 12.5s) {'failed': 1}\n"
        "[  2/3] ✓ tests\\a\\test_y.py (solo, 61.0s) {'passed': 3}\n"
        "[  3/3] ✓ tests/a/test_x.py (rerun, 3.25s) {'passed': 4}\n"
    )
    assert wp.last_attempt_seconds(log) == {"tests/a/test_x.py": 3.25, "tests/a/test_y.py": 61.0}


def test_measure_writes_a_receipt_with_the_runs_own_ledger_line(tmp_path):
    ledger = tmp_path / wp.RUNS_FILE
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps({"elapsed": 1.0, "floor_seconds": 1.0}) + "\n", encoding="utf-8")
    line = json.dumps({"elapsed": 10.0, "floor_seconds": 7.5, "red": {}})
    script = (
        "import time, pathlib; time.sleep(0.5); "
        f"p = pathlib.Path({str(ledger)!r}); p.write_text(p.read_text() + {line!r} + '\\n')"
    )
    receipt = wp.measure([sys.executable, "-c", script], 12, tmp_path, interval=0.1)
    assert receipt["rc"] == 0 and receipt["workers"] == 12
    assert receipt["ledger"] == json.loads(line)  # the line THIS run appended, not the earlier one
    assert receipt["floor_over_elapsed"] == 0.75
    assert receipt["samples"] >= 1 and receipt["cpu_busy_pct"]["mean"] is not None
