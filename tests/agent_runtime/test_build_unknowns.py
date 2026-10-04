"""The typed-unknown index (plan ``build-running-work-2026-10-04.md`` §1 ``unknowns``, row H1).

Owner rule 2026-10-04 "index the unknowns": bounded to a 32-entry WIRE limit, deduped by
kind + evidence hash with the newest sighting kept, evidence redacted, and a truncation
declared ``by_design`` through the accountant.
"""

from __future__ import annotations

import pytest

from agent_runtime.builds import unknowns as u
from agent_runtime.projection_accountant import ProjectionAccountant


def test_the_kinds_include_every_slot_kind_and_the_starter_kind():
    assert {"slot_unresolved", "slot_unbound_here", "slot_probe_unknown", "starter_unknown"} <= set(u.UNKNOWN_KINDS)
    assert len(set(u.UNKNOWN_KINDS)) == len(u.UNKNOWN_KINDS)


def test_a_kind_outside_the_vocabulary_is_refused_not_recorded():
    index = u.UnknownsIndex()
    with pytest.raises(ValueError):
        index.add("something_new", "x", 1.0)
    assert len(index) == 0
    # Positive control: the same call with a typed kind lands.
    index.add(u.UNKNOWN_STAGE_LINE_UNRECOGNIZED, "x", 1.0)
    assert len(index) == 1


def test_a_repeated_sighting_is_one_entry_carrying_the_newest_time():
    index = u.UnknownsIndex()
    index.add(u.UNKNOWN_STAGE_LINE_UNRECOGNIZED, "Running Gradle task...", 10.0)
    index.add(u.UNKNOWN_STAGE_LINE_UNRECOGNIZED, "Running  Gradle task...", 20.0)  # same after collapsing
    index.add(u.UNKNOWN_STAGE_LINE_UNRECOGNIZED, "Running Gradle task...", 5.0)  # an OLDER sighting never wins
    assert index.wire() == [{"kind": "stage_line_unrecognized", "evidence": "Running Gradle task...", "seen_at": 20.0}]
    # Positive control: the same evidence under a different kind is a different entry.
    index.add(u.UNKNOWN_OUTPUT_UNREADABLE, "Running Gradle task...", 21.0)
    assert len(index) == 2


def test_the_bound_keeps_the_newest_32_and_declares_the_truncation_by_design():
    index = u.UnknownsIndex()
    for i in range(40):
        index.add(u.UNKNOWN_STAGE_LINE_UNRECOGNIZED, f"line {i}", float(i))
    accountant = ProjectionAccountant("running_work")
    wire = index.wire(accountant, entity_id="build:agent:s1")
    assert len(wire) == u.UNKNOWNS_WIRE_LIMIT == 32
    assert [entry["evidence"] for entry in wire] == [f"line {i}" for i in range(8, 40)]
    summary = accountant.summary()
    assert summary["reasons"] == {u.UNKNOWNS_TRUNCATED: 8}
    assert summary["by_design"] == [u.UNKNOWNS_TRUNCATED]


def test_an_index_within_the_bound_accounts_nothing():
    index = u.UnknownsIndex()
    for i in range(32):
        index.add(u.UNKNOWN_STAGE_LINE_UNRECOGNIZED, f"line {i}", float(i))
    accountant = ProjectionAccountant("running_work")
    assert len(index.wire(accountant)) == 32
    assert accountant.summary()["reasons"] == {}


def test_evidence_is_redacted_and_bounded():
    entry = u.unknown(u.UNKNOWN_ENV_UNOBSERVED, "api_key=sk-abcdefghijklmnopqrstuvwxyz " + "x" * 400, 1.0)
    assert "sk-abcdefghij" not in entry.evidence
    assert "[redacted]" in entry.evidence
    assert len(entry.evidence) == u.EVIDENCE_LIMIT


def test_a_writer_list_merges_and_its_untyped_entries_are_counted_not_coerced():
    index = u.UnknownsIndex()
    refused = index.extend_wire([
        {"kind": "stage_line_unrecognized", "evidence": "Running Gradle", "seen_at": 3.0},
        {"kind": "made_up", "evidence": "?", "seen_at": 4.0},
        "not a dict",
    ])
    assert refused == 2
    assert index.kinds() == {"stage_line_unrecognized"}
