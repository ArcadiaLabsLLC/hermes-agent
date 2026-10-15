"""``upstream_footprint.py --add-row``: one upstream edit's ledger row and fixture move, scripted.

Fork-hygiene row (lane-1011-M3, 2026-10-15): each lane hand-merged its ledger row
and bumped ``files`` in the fixture, and a Bash heredoc once wrote a backslash as
``\\x08`` into both. The verb inserts ONE row (no other line moves), and the
fixture moves to the tree's numbers with its ``reasons`` row, written by ``json``.
"""

from __future__ import annotations

import json

import pytest

from scripts import upstream_footprint as fp

_LEDGER = (
    "# Ledger\n\npreamble\n\n"
    "| path | added | deleted | disposition | reason | stage |\n"
    "|---|---|---|---|---|---|\n"
    "| `agent/a.py` | 3 | 0 | carry | seam A | - |\n"
    "| `hermes_cli/z.py` | 31 | 2 | carry | count drifted on purpose | - |\n"
    "\ntrailer\n"
)


def _row(path: str, added: int = 4, deleted: int = 0) -> fp.FileDelta:
    return fp.FileDelta(path, added, deleted, False)


def test_a_new_row_lands_sorted_and_no_other_line_moves():
    out = fp.ledger_add_row(_LEDGER, _row("gateway/m.py"), disposition="carry", reason=r"route C:\x08 | pipe")
    before, after = _LEDGER.splitlines(), out.splitlines()
    assert [line for line in after if line not in before] == [
        r"| `gateway/m.py` | 4 | 0 | carry | route C:\x08 \| pipe | - |"
    ]
    assert after.index(r"| `gateway/m.py` | 4 | 0 | carry | route C:\x08 \| pipe | - |") == 7, "sorted between a/ and z/"
    assert "\x08" not in out, "a backslash stays a backslash"
    assert fp.ledger_rows(out)["gateway/m.py"]["reason"] == r"route C:\x08 | pipe"
    assert "| `hermes_cli/z.py` | 31 | 2 |" in out, "an unrelated row keeps its counts (unlike --ledger)"


def test_an_existing_row_is_replaced_not_duplicated():
    out = fp.ledger_add_row(_LEDGER, _row("agent/a.py", 9, 1), disposition="hook", reason="seam A, widened")
    assert out.count("`agent/a.py`") == 1
    assert "| `agent/a.py` | 9 | 1 | hook | seam A, widened | - |" in out


@pytest.mark.parametrize("reason,disposition", [("", "carry"), ("unreviewed", "carry"), ("why", "kept")])
def test_a_row_needs_a_reason_and_a_named_disposition(reason, disposition):
    with pytest.raises(ValueError):
        fp.ledger_add_row(_LEDGER, _row("gateway/m.py"), disposition=disposition, reason=reason)


def test_the_fixture_moves_to_the_tree_with_its_reason_and_round_trips_through_json():
    fixture = {"measured_at": "2026-10-14", "base": "abc", "files": 2, "deleted_lines": 2, "heavy": 0, "reasons": []}
    tree = fp.Footprint(3, 2, 0, (_row("agent/a.py"), _row("hermes_cli/z.py"), _row("gateway/m.py")))
    out = fp.fixture_add_reason(fixture, tree, change="row X", reason=r"C:\x08", today="2026-10-15")
    assert (out["files"], out["deleted_lines"], out["heavy"], out["measured_at"]) == (3, 2, 0, "2026-10-15")
    assert out["reasons"] == [{"change": "row X", "before": {"files": 2, "deleted_lines": 2, "heavy": 0},
                               "after": {"files": 3, "deleted_lines": 2, "heavy": 0}, "reason": r"C:\x08"}]
    assert json.loads(json.dumps(out, indent=2))["reasons"][0]["reason"] == "C:\\x08"
    assert fixture["files"] == 2 and fixture["reasons"] == [], "the input is not mutated"
