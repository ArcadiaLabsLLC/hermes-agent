"""W0-G1 — every fork production file is <= 800 CODE lines, or grandfathered and shrinking.

Plan: ``docs/agent-runtime-harness/planned/downstream-god-file-refactor.md`` §2
Wave 0 and ``god-file-program-2026-09-24.md`` §9 (ruling Q1: code lines bind).
The population and the counter are ``scripts/god_file_probe.py``'s; the
baseline is ``tests/fixtures/size_ceiling_grandfathered.json``, written by
``god_file_probe.py --write-fixtures`` (which refuses growth). The ledger line
this gate prints is the program's ``[ds-size]`` count.
"""

from __future__ import annotations

from scripts import god_file_probe as probe


def _drift() -> probe.Drift:
    return probe.compare_numbers("W0-G1 size ceiling", probe.size_live(), probe.size_fixture())


def test_the_population_is_the_fork_and_only_the_fork():
    """Positive control on the enumeration: known fork files are in, a known upstream file is out."""
    files = set(probe.fork_production_files())
    assert "hermes_cli/harness.py" in files
    assert "agent_runtime/store/base.py" in files
    assert "tests/_downstream/id_markers.py" in files
    assert "hermes_cli/main.py" not in files, "an upstream file entered the fork population"
    assert not any(p.startswith("tests/") and not p.startswith("tests/_downstream/") for p in files)


def test_the_counter_counts_code_lines_not_raw_lines():
    assert probe.code_lines('x = 1\n\n# comment\n    # indented comment\n"""doc"""\n') == 2


def test_no_new_file_crosses_the_ceiling():
    print(probe.size_ledger_line())
    drift = _drift()
    assert not drift.new, (
        "these fork files are over 800 code lines and not grandfathered — split to a layout "
        "(program rule 1), never add a row:\n" + drift.render()
    )


def test_no_grandfathered_file_grew():
    drift = _drift()
    assert not drift.grew, "a grandfathered file GREW — the list only shrinks:\n" + drift.render()


def test_a_file_under_the_ceiling_loses_its_row():
    drift = _drift()
    assert not drift.stale, (
        "these rows describe files now at or under 800 code lines — delete the row in the "
        "commit that crossed:\n" + drift.render()
    )
