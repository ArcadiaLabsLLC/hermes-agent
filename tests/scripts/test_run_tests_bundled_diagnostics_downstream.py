"""H13: an isolated green cannot erase the original failure or process-death evidence."""

import json
from pathlib import Path

import pytest

from scripts import run_tests_bundled as bundled


@pytest.mark.parametrize("kind,rc,session_rc", [
    ("failure", 1, 1), ("death", 124, None), ("contradiction", 0, 2),
    ("missing-end", 0, None), ("collection", 2, 2),
])
def test_original_attempt_survives_green_retries_scratch_cleanup_and_recording(
    tmp_path, capsys, kind, rc, session_rc,
):
    rels = [f"tests/test_{n}.py" for n in range(3)]
    files = [tmp_path / rel for rel in rels]
    events_paths = []
    original = "Traceback: original failure\napi_key=private-test-value\nAssertionError: original cause"

    def run_bundle(first, args, root, timeout):
        events_path = Path(next(a.split("=", 1)[1] for a in args if a.startswith("--hermes-bundle-events=")))
        events_paths.append(events_path)
        members = [first] + [Path(a) for a in args if a.endswith(".py")]
        records = [{"k": "start", "t": 1.0}]
        for member in members:
            rel = member.relative_to(root).as_posix()
            records.append({"k": "collect", "f": rel, "err": kind == "collection"})
            records.append({"k": "test", "f": rel, "c": "failed", "n": f"{rel}::test_bad"})
            if session_rc is None:
                break
        if session_rc is not None:
            records.append({"k": "end", "t": 2.0, "rc": session_rc})
        events_path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        return first, rc, original, {"failed": 1}, 1.0

    def green_alone(path, args, root, timeout, retries):
        return path, 0, "isolated pass", {"passed": 1}, 0.1

    result = bundled.run(
        files, [], tmp_path, jobs=2, flat_timeout=10, retries=0, durations={},
        bundle_runner=run_bundle, solo_runner=green_alone,
    )
    assert all(item.rc == 0 for item in result.outcomes)
    assert all(not path.exists() for path in events_paths)
    first = sorted(result.ledger.bundle_diagnostics, key=lambda entry: entry.bundle_index)[0]
    assert first.members == rels
    assert first.process_rc == rc and first.session_rc == session_rc
    assert first.session_ended == (session_rc is not None)
    assert first.stopped_in == (rels[0] if session_rc is None else None)
    assert first.failed[rels[0]] == [f"{rels[0]}::test_bad"]
    assert "AssertionError: original cause" in first.output
    assert "private-test-value" not in first.output

    # Use the production persistence owner, with caching disabled, as a real run does.
    store = bundled.cache.GateStore(tmp_path / "gate-store")
    gate = bundled._gate.GateRun(tmp_path, store, None)
    gate.record(result, {"elapsed": 1.0}, extra={"tests": {rels[0]: 1}})
    saved = json.loads(store.runs.read_text(encoding="utf-8").splitlines()[-1])
    assert saved["bundle_diagnostics"][0]["output"] == first.output
    assert saved["bundle_diagnostics"][0]["members"] == rels
    assert saved["bundle_diagnostics"][0]["process_rc"] == rc
    assert saved["bundle_diagnostics"][0]["stopped_in"] == first.stopped_in
    assert saved["tests"] == {rels[0]: 1}
    assert saved["red"] == {}  # final-red policy is not a second first-attempt store
    assert bundled._print_summary(result, files, tmp_path, 1.0, 2) == 0
    report = capsys.readouterr().out
    assert "not first-pass success" in report
    assert "AssertionError: original cause" in report
    assert "private-test-value" not in report
    assert "process rc=" + str(rc) in report
    assert ", ".join(rels) in report


def test_diagnostics_are_scrubbed_before_bounding_and_retained_once_per_bundle():
    limit = bundled.plan.DIAGNOSTIC_CHARS
    output = "Traceback start\n" + "x" * limit + "\npassword=" + "s" * limit + "\nAssertionError end"
    events = bundled.tally_events([
        json.dumps({"k": "end", "t": 1, "rc": 1}),
        json.dumps({"k": "test", "f": "a.py", "c": "failed", "n": "a.py::test_bad[api_key=hidden]"}),
        json.dumps({"k": "test", "f": "b.py", "c": "failed", "n": "b.py::test_bad"}),
    ])
    ledger = bundled.plan.RunLedger()
    ledger.record_bundle_diagnostic(0, ["a.py", "b.py"], 1, events, output)
    assert len(ledger.bundle_diagnostics) == 1
    item = ledger.bundle_diagnostics[0]
    assert item.output.startswith("Traceback start") and item.output.endswith("AssertionError end")
    assert item.omitted_chars > 0
    assert len(item.output) < limit + 100
    assert "s" * 16 not in item.output
    assert "hidden" not in str(ledger.diagnostic_record())


def test_confirmed_green_has_no_diagnostic_but_incomplete_recording_does():
    events = bundled.tally_events([
        json.dumps({"k": "test", "f": "a.py", "c": "passed"}),
        json.dumps({"k": "end", "t": 1, "rc": 0}),
    ])
    ledger = bundled.plan.RunLedger()
    ledger.record_bundle_diagnostic(0, ["a.py"], 0, events, "green")
    assert ledger.diagnostic_record() == {"bundle_diagnostics": []}
    assert bundled.plan.render_bundle_diagnostics(ledger.bundle_diagnostics) == []
    ledger.record_bundle_diagnostic(1, ["a.py", "missing.py"], 0, events, "incomplete")
    assert len(ledger.bundle_diagnostics) == 1
    assert ledger.bundle_diagnostics[0].output == "incomplete"
