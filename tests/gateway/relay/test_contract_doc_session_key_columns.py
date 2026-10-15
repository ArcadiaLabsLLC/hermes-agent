"""Contract conformance: every session-key discriminator in the relay contract doc has a per-platform column.

website/docs/developer-guide/relay-connector-contract.md is the formal
interface the connector repo implements against. §3 marks some
``SessionSource`` fields as session-key discriminators; the per-platform
table below it tells the connector how to fill each one. A column silently
dropped from that table leaves a key-forming field with no guidance.

Fork-owned: split out of upstream's ``test_contract_doc_conformance.py`` when
upstream purged that file (2026-09 "purge low-value tests"); this check was
the fork's addition to it.
"""

from __future__ import annotations

import re
from pathlib import Path

# Repo root: tests/gateway/relay/ -> repo root is parents[3]
_CONTRACT_DOC = (
    Path(__file__).resolve().parents[3] / "website" / "docs" / "developer-guide" / "relay-connector-contract.md"
)


def _doc_text() -> str:
    assert _CONTRACT_DOC.exists(), f"Contract doc missing at {_CONTRACT_DOC}."
    return _CONTRACT_DOC.read_text(encoding="utf-8")


def _table_cells(line: str) -> list[str]:
    """Split one markdown table row into cells, honouring escaped pipes.

    Type cells like ``string\\|null`` contain an ESCAPED pipe, so a naive
    ``split("|")`` shifts every later cell left by one and silently reads the
    wrong column — which is how ``user_id`` and ``thread_id`` first went
    missing from the discriminator set here without any test going red.
    """
    return [c.strip().strip("*` ") for c in re.split(r"(?<!\\)\|", line.strip("|"))]
def _parse_discriminator_columns(text: str) -> list[str]:
    """Parse the per-platform table's column headers (minus the ``Platform`` key).

    The headers ARE the doc's claim about which discriminators exist; reading
    them out of the doc (rather than hardcoding the five current ones) keeps
    this an invariant instead of a change-detector snapshot.
    """
    section = text.split("### SessionSource discriminators per platform", 1)[-1]
    for line in section.splitlines():
        line = line.strip()
        if line.startswith("|"):
            return [c for c in _table_cells(line)[1:] if c]
    return []
def test_session_key_discriminators_have_a_per_platform_column():
    """Rows the §3 table marks "Session-key discriminator" must have a column.

    The reverse of the check above, and the one that catches a DELETION: the
    per-platform table is what tells the connector how to fill each
    discriminator on each platform, so silently dropping a column (e.g.
    ``scope_id``, the Discord server-isolation key) leaves a field the table
    still calls key-forming with no per-platform guidance. Header-existence
    alone cannot see that — removing a header only makes the doc claim less.
    """
    text = _doc_text()
    section = text.split("### SessionSource fields (the wire surface)", 1)[-1]
    section = section.split("### SessionSource discriminators per platform", 1)[0]
    key_forming = set()
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = _table_cells(line)
        # | field | type | always sent | meaning |
        if len(cells) >= 4 and re.fullmatch(r"[a-z_]+", cells[0]):
            if "Session-key discriminator" in cells[3]:
                key_forming.add(cells[0])
    assert key_forming, "Failed to parse any session-key discriminators from §3."

    columns = set(_parse_discriminator_columns(text))
    missing = sorted(key_forming - columns)
    assert not missing, (
        f"§3 marks {missing} as session-key discriminators, but the per-platform "
        f"discriminator table has no column for them. The connector needs the "
        f"per-platform row to know what to put there; get it wrong and two "
        f"scopes collide into one session."
    )


