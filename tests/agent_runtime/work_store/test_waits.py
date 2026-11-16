"""``agent_runtime/work_store/waits.py`` and the grammar's ``waits:`` arm (FH-QUEUE-WAITS-FIELD, task
TASK-WAITS-ARE-A-FIELD; the twin of the launcher's ``test/tool/queue_waits_test.dart``)."""

from __future__ import annotations

from agent_runtime.work_store.grammar import WaitTarget, parse_note, parse_waits, row_defects
from agent_runtime.work_store.waits import field_waiters_of, missing_waits

HEAD = "---\ntype: queue\nprogram: test\n---\n\n"


def _rows(body: str, slot: str = "hermes"):
    return parse_note(HEAD + body, slot=slot, note="q.md")


def test_the_field_reads_row_ids_brain_words_and_events():
    targets, problem = parse_waits("`RT-A`, launcher `BRAIN-B` and backend `OPS-C`, v0.1", "hermes")
    assert problem is None
    assert targets == [WaitTarget(row_id="RT-A", brain="hermes"), WaitTarget(row_id="BRAIN-B", brain="launcher"),
                       WaitTarget(row_id="OPS-C", brain="backend"), WaitTarget(event="v0.1")]


def test_an_unknown_event_or_a_bare_word_is_a_problem():
    for body in ("the mac", "RT-A", ""):
        assert parse_waits(body, "hermes")[1], body
    assert parse_waits("mac-sitting", "hermes")[1] is None


def test_a_malformed_waits_field_is_a_grammar_defect():
    bad = "- **`RT-D` — parked** · DEFERRED 2026-11-15: later · waits: a mac"
    good = "- **`RT-D` — parked** · DEFERRED 2026-11-15: later · waits: mac-sitting"
    assert any("WAITS FIELD" in d for d in row_defects(bad))
    assert row_defects(good) == []


def test_a_deferred_row_with_no_machine_read_wait_is_listed_as_missing():
    rows = _rows("- **`RT-NONE` — parked** · DEFERRED 2026-11-15: until the Mac\n"
                 "- **`RT-FIELD` — parked** · DEFERRED 2026-11-15: Mac · waits: mac-sitting\n"
                 "- **`RT-LIST` — waits** · BLOCKED 2026-11-15: another lane — `RT-FIELD`\n"
                 "- **`RT-R` — ready** · READY 2026-11-15\n")
    assert [row.ref.id for row in missing_waits(rows, "hermes")] == ["RT-NONE"]


def test_a_close_lists_the_deferred_rows_that_waited_on_it():
    """KILLING MUTATION: drop ``is_waiting(row) and`` in ``field_waiters_of`` -> the READY RT-R is listed, red;
    narrow it to BLOCKED -> RT-ON-A is not, red."""
    rows = {
        "hermes": _rows("- **`RT-ON-A` — parked** · DEFERRED 2026-11-15: after A · waits: `RT-A`\n"
                        "- **`RT-B-ON-A` — waits** · BLOCKED 2026-11-15: another lane — `RT-A` · waits: `RT-A`\n"
                        "- **`RT-R` — ready** · READY 2026-11-15 · waits: `RT-A`\n"
                        "- **`RT-L` — parked** · DEFERRED 2026-11-15: after L · waits: launcher `RT-A`\n"),
        "launcher": _rows("- **`MC-ON-A` — parked** · DEFERRED 2026-11-15: after A · waits: hermes `RT-A`\n",
                          slot="launcher"),
    }
    assert [(brain, row.ref.id) for brain, row in field_waiters_of(rows, "RT-A", "hermes")] == [
        ("hermes", "RT-ON-A"), ("launcher", "MC-ON-A")]
