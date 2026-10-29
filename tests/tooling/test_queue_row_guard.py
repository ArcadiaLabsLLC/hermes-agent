"""The queue row-history guard (row RT-QUEUE-DELETE-NEEDS-ROW-OWNER, ported from the launcher).

The pure arms drive ``tests/tooling/_queue_row_guard.py::findings`` over two in-memory vaults; the live
arm compares this checkout's vault with its merge base on ``origin/main`` and reds on a dropped
``RULED`` segment or a status date rolled back, printing teammate-row deletions as notes.
"""

from __future__ import annotations

import pytest

from tests.tooling import _queue_row_guard as guard
from tests.tooling._queue_row_guard import Change, RowOwner

pytestmark = pytest.mark.gate

_HEAD = "---\ntype: queue\n---\n\n# Q\n\n"
_FILE = "Harness_Brain/20 — Active Initiatives/q.md"
ME = RowOwner("nekwo", "me@example.com")
TEAMMATE = RowOwner("Maximus Shaban", "max@example.com")


def _rows(*lines: str) -> dict:
    return guard.rows_by_id({_FILE: _HEAD + "\n".join(lines) + "\n"})


def _findings(base: dict, head: dict, *, filer: RowOwner | None = TEAMMATE, authorized: set | None = None):
    return guard.findings(base=base, head=head, pusher=ME, filer_of=lambda row: filer,
                          authorized=authorized or set())


RULED_ROW = "- **`RT-A` — a ruled row** · RULED 2026-10-27: owner \"agreed\" · READY 2026-10-28"


def test_a_dropped_ruling_reds_and_names_its_row():
    found = _findings(_rows(RULED_ROW), _rows("- **`RT-A` — a ruled row** · READY 2026-10-28"))
    assert [(f.id, f.change, f.refuses) for f in found] == [("RT-A", Change.RULING_DROPPED, True)]
    assert "RULED 2026-10-27" in found[0].message


def test_a_kept_ruling_beside_a_moved_status_is_clean():
    """Positive control for the arm above: same ruling, status moved forward."""
    head = _rows("- **`RT-A` — a ruled row** · RULED 2026-10-27: owner \"agreed\" · BLOCKED 2026-10-29: "
                 "owner sitting — the box")
    assert _findings(_rows(RULED_ROW), head) == []


def test_a_status_date_rolled_back_reds():
    found = _findings(_rows("- **`RT-B` — b** · READY 2026-10-29"), _rows("- **`RT-B` — b** · BLOCKED 2026-10-20: "
                                                                          "owner sitting — the box"))
    assert [(f.change, f.refuses) for f in found] == [(Change.STATUS_DATE_REGRESSED, True)]


def test_a_teammates_deleted_row_is_a_note_never_a_refusal():
    found = _findings(_rows("- **`RT-C` — theirs** · READY 2026-10-29"), _rows())
    assert [(f.id, f.change, f.refuses) for f in found] == [("RT-C", Change.TEAMMATE_ROW_DELETED, False)]
    assert "Maximus Shaban" in found[0].message


@pytest.mark.parametrize("filer", [ME, RowOwner("NEKWO", "other@example.com"), RowOwner("bot", "noreply@anthropic.com"),
                                   None], ids=["self", "same-name", "automated", "unknown"])
def test_deleting_my_own_or_an_ownerless_row_says_nothing(filer):
    assert _findings(_rows("- **`RT-C` — c** · READY 2026-10-29"), _rows(), filer=filer) == []


def test_an_authorized_by_line_naming_the_row_passes_it_whole():
    messages = ["queue: drop the ruling\n\nAuthorized-by: owner, \"drop it\" — `RT-A`\n",
                "unrelated RT-B mention with no authorization"]
    authorized = guard.authorized_row_ids(messages)
    assert authorized >= {"RT-A"} and "RT-B" not in authorized
    head = _rows("- **`RT-A` — a ruled row** · READY 2026-10-28")
    assert _findings(_rows(RULED_ROW), head, authorized=authorized) == []


def test_this_checkout_drops_no_ruling_and_rolls_no_status_back(capsys):
    report = guard.run()
    if report.skipped:
        pytest.skip(report.skipped)
    for finding in report.findings:
        if not finding.refuses:
            print("NOTE " + finding.message)
    refused = [finding.message for finding in report.findings if finding.refuses]
    assert not refused, "\n".join(refused)
    assert report.compared > 0
