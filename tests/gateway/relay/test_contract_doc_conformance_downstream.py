"""Fork-owned tests moved out of ``tests/gateway/relay/test_contract_doc_conformance.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from __future__ import annotations

import re
from gateway.session import SessionSource

from tests.gateway.relay.test_contract_doc_conformance import (  # noqa: F401 — upstream names the moved tests use
    _doc_text,
    _parse_discriminator_columns,
    _session_source_wire_keys,
)


def _parse_session_source_table(text: str) -> set[str]:
    """Parse §3's "SessionSource fields (the wire surface)" table → field names."""
    section = text.split("### SessionSource fields (the wire surface)", 1)[-1]
    section = section.split("### SessionSource discriminators per platform", 1)[0]
    return set(re.findall(r"^\|\s*`([a-z_]+)`\s*\|", section, re.M))


def test_session_source_wire_keys_documented_in_contract():
    """Every wire key SessionSource.to_dict() emits is a row in the §3 table.

    §3's field table advertises itself as "every key the gateway accepts on the
    wire", and the connector repo hand-mirrors it into TypeScript. A key the
    gateway emits but the doc never names is a key the connector author cannot
    know to populate or read — a silent cross-repo gap.
    """
    documented = _parse_session_source_table(_doc_text())
    assert documented, "Failed to parse any rows from the §3 SessionSource table."

    undocumented = sorted(_session_source_wire_keys() - documented)
    assert not undocumented, (
        f"SessionSource wire keys absent from the §3 contract-doc field table: "
        f"{undocumented}. The connector normalizes events into these keys; if the "
        f"doc doesn't name them the connector author can't know to populate them. "
        f"Add a row per key (or, if a key is deliberately gateway-internal, stop "
        f"emitting it from to_dict())."
    )


def test_internal_only_session_fields_stay_off_the_wire():
    """Guard the inverse: fields deliberately NOT serialized must not leak.

    ``is_bot`` is an internal author-classification flag. ``role_authorized``
    and ``delivered_via_upstream_relay`` are trust signals stamped LOCALLY —
    ``delivered_via_upstream_relay`` in particular is what authz keys the
    upstream-trust decision off, so if it ever became a wire key a peer could
    forge it. If serializing any of these is intentional, it must be a
    deliberate, documented, cross-repo change — not a silent one.
    """
    leaked = sorted(
        {"is_bot", "role_authorized", "delivered_via_upstream_relay"}
        & _session_source_wire_keys()
    )
    assert not leaked, (
        f"Fields now serialized by SessionSource.to_dict() that must not be: "
        f"{leaked}. These are internal/trust-local. If a wire key is genuinely "
        f"intended, add it to docs/relay-connector-contract.md §3 and the "
        f"connector's SessionSource interface, then update this guard."
    )


def test_discriminator_columns_exist_on_dataclass():
    """§3's per-platform table headers must exist as SessionSource fields.

    These columns drive build_session_key() and are the #1 High-severity risk
    surface (Discord scope collision). If the doc advertises a discriminator
    column the dataclass can't carry, the connector has nowhere to put it.
    """
    columns = _parse_discriminator_columns(_doc_text())
    assert columns, "Failed to parse the §3 per-platform discriminator table."

    dc_fields = SessionSource.__dataclass_fields__  # type: ignore[attr-defined]
    wire_keys = _session_source_wire_keys()
    for discriminator in columns:
        assert discriminator in dc_fields, (
            f"Contract doc §3 lists '{discriminator}' as a session discriminator "
            f"column, but SessionSource has no such field."
        )
        # And it must be reachable on the wire (chat_type is always emitted; the
        # rest are conditional but still possible keys).
        assert discriminator in wire_keys, (
            f"Discriminator '{discriminator}' never appears in "
            f"SessionSource.to_dict() output — the connector cannot transmit it."
        )
