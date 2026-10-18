"""The Python twin of the row grammar (plan ``work-on-markdown-2026-10-18.md`` §6.1, W1).

The twin and the vault lint read the same shared fixtures (``tests/fixtures/work_queue/``, the
launcher's canonical files plus the W1 rows) and must agree row by row; :func:`grammar.apply` is
the one-line edit every write-back is.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_runtime.work_store import grammar
from agent_runtime.work_store.grammar import Op, Status
from agent_runtime.work_store.reasons import Reason, WorkRefused
from tests.tooling.test_work_queue_row_grammar import STRICTER_HERE, row_defects as lint_defects

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "work_queue"
DATE = "2026-10-18"


def _rows(name: str) -> list[grammar.Row]:
    return grammar.parse_note((FIXTURES / name).read_text(encoding="utf-8"), slot="fx", note=name)


def _duplicated(rows: list[grammar.Row]) -> set[str]:
    ids = [row.ref.id for row in rows]
    return {row_id for row_id in ids if row_id and ids.count(row_id) > 1}


def test_every_valid_fixture_row_parses_with_no_defect() -> None:
    rows = _rows("grammar_valid.md")
    assert len(rows) >= 19
    for row in rows:
        if row.ref.id in STRICTER_HERE:
            assert any(STRICTER_HERE[row.ref.id] in d for d in row.defects), row
        else:
            assert row.defects == (), (row.ref.id, row.defects)
    by_id = {row.ref.id: row for row in rows}
    assert by_id["FX-OWNER-DECISION"].status is Status.BLOCKED
    assert by_id["FX-OWNER-DECISION"].recommend == "yes, writes wait for an ask"
    assert by_id["FX-NEEDS-PLAN"].status is Status.NEEDS_PLAN and by_id["FX-NEEDS-PLAN"].status_date == "2026-10-16"
    assert by_id["FX-TAKEN"].taken == grammar.Claim("2026-10-16", "w1016c-mc")
    assert by_id["FX-RULED"].rulings == ("RULED 2026-10-16: one board per repo",)
    assert by_id["FX-READY-PLAN"].pointers == ("docs/mission_control/planned/WORK_QUEUE_BOARD_2026-10-16.md",)
    assert by_id["FX-READY"].title == "Ready row"


def test_every_defect_fixture_row_is_a_defect() -> None:
    rows = _rows("grammar_defects.md")
    assert len(rows) >= 11
    duplicated = _duplicated(rows)
    clean = [row.raw for row in rows if not row.defects and row.ref.id not in duplicated]
    assert not clean, clean


@pytest.mark.parametrize("name", ["grammar_valid.md", "grammar_defects.md"])
def test_the_twin_agrees_with_the_lint_on_every_fixture_row(name: str) -> None:
    rows = _rows(name)
    disagree = [row.raw for row in rows if bool(grammar.row_defects(row.raw)) != bool(lint_defects(row.raw))]
    assert not disagree, disagree
    words = [row.raw for row in rows if grammar.row_defects(row.raw) != lint_defects(row.raw)]
    assert not words, "the twin names a defect in different words from the lint: " + repr(words)


def test_apply_claim_release_set_status_round_trip() -> None:
    line = "- **`RT-A` — a row** · `agent_runtime/x.py` · assignee: persona:alice · READY 2026-10-18"
    claimed = grammar.apply(line, Op.CLAIM, who="persona:pi_alice_01", date=DATE, payload={})
    assert claimed == line + " · **TAKEN 2026-10-18 persona:pi_alice_01**"
    row = grammar.parse_row(claimed, slot="s", note="n", line_no=1)
    assert row.taken.persona_instance_id == "pi_alice_01" and row.assignee == grammar.Assignee("alice")
    with pytest.raises(WorkRefused) as again:
        grammar.apply(claimed, Op.CLAIM, who="lane-x", date=DATE, payload={})
    assert again.value.reason is Reason.ALREADY_TAKEN
    asked = grammar.apply(claimed, Op.SET_STATUS, who="persona:pi_alice_01", date=DATE,
                          payload={"status": "BLOCKED 2026-10-18: owner decision — A or B? · Recommend: A"})
    assert asked.endswith("BLOCKED 2026-10-18: owner decision — A or B? · Recommend: A · **TAKEN 2026-10-18 persona:pi_alice_01**")
    released = grammar.apply(asked, Op.RELEASE, who="persona:pi_alice_01", date=DATE, payload={})
    assert "TAKEN" not in released and grammar.row_defects(released) == []
    ready = grammar.apply(released, Op.SET_STATUS, who="operator", date=DATE, payload={"status": "READY 2026-10-18"})
    assert ready == line
    assert grammar.apply(ready, Op.DELETE, who="operator", date=DATE, payload={}) is None


def test_set_status_keeps_exactly_one_status() -> None:
    line = "- **`RT-B` — row** · surface · NEEDS PLAN 2026-10-18: the shape **TAKEN 2026-10-18 q**"
    edited = grammar.apply(line, Op.SET_STATUS, who="q", date=DATE,
                           payload={"status": "DEFERRED 2026-10-18: stopped — the box"})
    segments = [s.strip() for s in grammar.split_segments(edited)]
    assert sum(1 for s in segments if grammar.STATUS.match(s)) == 1
    assert edited == "- **`RT-B` — row** · surface · DEFERRED 2026-10-18: stopped — the box · **TAKEN 2026-10-18 q**"
    with pytest.raises(WorkRefused) as bad:
        grammar.apply(line, Op.SET_STATUS, who="q", date=DATE, payload={"status": "VERDICT keep"})
    assert bad.value.reason is Reason.INVALID
    with pytest.raises(WorkRefused) as unasked:
        grammar.apply(line, Op.SET_STATUS, who="q", date=DATE, payload={"status": "BLOCKED 2026-10-18: owner decision — ?"})
    assert unasked.value.reason is Reason.GRAMMAR_INVALID


def test_mint_id_is_work_six_base32() -> None:
    minted = {grammar.mint_id() for _ in range(64)}
    assert all(re.fullmatch(r"WORK-[A-Z2-7]{6}", m) and grammar.row_defects(f"- **`{m}` — x** · READY {DATE}") == []
               for m in minted)
    assert grammar.mint_id(b"\xff\xff\xff\xff\xff") == "WORK-777777"
    assert grammar.mint_id(b"\x00\x00\x00\x00\x00") == "WORK-AAAAAA"


def test_split_segments_never_splits_in_a_code_span() -> None:
    assert grammar.split_segments("- **`A` — t** · the `a · b` span · READY 2026-10-18") == [
        "- **`A` — t**", "the `a · b` span", "READY 2026-10-18"]


def test_assignee_persona_instance_vs_persona_token() -> None:
    instance = grammar.parse_row(f"- **`A` — t** · assignee: persona:pi_alice_01 · READY {DATE}", slot="s", note="n", line_no=1)
    persona = grammar.parse_row(f"- **`B` — t** · assignee: persona:alice · READY {DATE} · **TAKEN {DATE} lane-x**",
                                slot="s", note="n", line_no=2)
    assert instance.assignee.token == "pi_alice_01" and persona.assignee.token == "alice"
    assert persona.taken.who == "lane-x" and persona.taken.persona_instance_id is None
    assert grammar.parse_row("plain text", slot="s", note="n", line_no=3) is None


def test_parse_note_tracks_headings_skips_frontmatter_fences_and_flags_wraps() -> None:
    text = ("---\ntype: queue\n---\n\n## First\n\n- **`A` — a** · READY 2026-10-18\n\n```\n- **`F` — fenced** · READY 2026-10-18\n```\n"
            "### Second\n- **`B` — b** · READY 2026-10-18\n  wrapped on\n")
    rows = grammar.parse_note(text, slot="s", note="n.md")
    assert [(r.ref.id, r.heading, r.line_no) for r in rows] == [("A", "First", 7), ("B", "Second", 13)]
    assert any("next line" in d for d in rows[1].defects)
    assert grammar.find(rows, "B") is rows[1] and grammar.find(rows, "F") is None
    assert grammar.is_queue(text) and not grammar.is_queue("---\ntype: moc\n---\n")
