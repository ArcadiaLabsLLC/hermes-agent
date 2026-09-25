"""The serve package's routing tables (god-file program rule 12), pinned at RUNTIME.

Three vocabularies became data in lane H4, each with one reader:

* ``handle_message.OP_HANDLERS`` — the op table; its keys are ``OPS`` (what
  ``ops_manifest`` advertises) plus the handshake word ``hello``.
* ``serve_gateway_credentials.CREDENTIAL_KINDS`` — the gateway hello's four
  credential kinds; ``credential_kind`` is its only key source.
* ``end_reason.EndReason`` — the closed set of words a runtime writes for why it
  ended; both signal tables map into it.

Each table also has an import-time guard. The guard tests below are POSITIVE
controls: they plant the drift the guard exists for and watch it raise, so a
guard that stopped comparing anything would red here rather than stay green.
"""

from __future__ import annotations

import pytest

from agent_runtime import serve_gateway_credentials as credentials
from agent_runtime.serve_gateway_credentials import CREDENTIAL_KINDS, CredentialKind, credential_kind
from hermes_cli.harness_parts.serve import handle_message
from hermes_cli.harness_parts.serve.constants import HELLO_OP, OPS
from hermes_cli.harness_parts.serve.end_reason import (
    CONSOLE_CTRL_END_REASONS,
    END_REASON_VOCABULARY,
    SIGNAL_END_REASONS,
    EndReason,
)
from hermes_cli.harness_parts.serve.manifest import ops_manifest


def test_the_op_table_is_the_advertised_vocabulary_plus_the_handshake():
    assert set(handle_message.OP_HANDLERS) == {*OPS, HELLO_OP}
    advertised = set(ops_manifest(transport="stdio")["ops"])
    assert advertised == set(OPS)
    assert HELLO_OP not in advertised


def test_each_op_is_answered_by_its_own_method():
    for op, handler in handle_message.OP_HANDLERS.items():
        assert handler.__name__ == f"_op_{op}", (op, handler.__name__)


def test_the_op_guard_reds_a_table_that_drifts_from_the_vocabulary(monkeypatch):
    """Positive control: one op missing from the table must fail the import guard."""

    handle_message._guard_op_vocabulary()  # the real table passes
    drifted = dict(handle_message.OP_HANDLERS)
    drifted.pop("stacks")
    monkeypatch.setattr(handle_message, "OP_HANDLERS", drifted)
    with pytest.raises(RuntimeError, match="missing=\\['stacks'\\]"):
        handle_message._guard_op_vocabulary()


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ({"pairing_code": "ABCD-1234"}, CredentialKind.PAIRING_CODE),
        ({"peer_code": "c", "peer_install_id": "i"}, CredentialKind.PEER_CODE),
        ({"peer_install_id": "i"}, CredentialKind.PEER_INSTALL_ID),
        ({"device_id": "d"}, CredentialKind.DEVICE_ID),
        ({}, None),
        ({"device_id": "d", "peer_install_id": "i"}, None),
        ({"pairing_code": "p", "peer_code": "c"}, None),
        ({"device_id": "   "}, None),
    ],
)
def test_a_hello_names_exactly_one_credential_or_none(message, expected):
    assert credential_kind(message) == expected


def test_every_credential_kind_has_exactly_one_verifier():
    assert set(CREDENTIAL_KINDS) == set(CredentialKind)
    assert len(set(CREDENTIAL_KINDS.values())) == len(CredentialKind)


def test_the_credential_guard_reds_a_kind_with_no_verifier(monkeypatch):
    """Positive control: an enum member with no table row must fail the guard."""

    credentials._guard_credential_table()
    drifted = dict(CREDENTIAL_KINDS)
    drifted.pop(CredentialKind.DEVICE_ID)
    monkeypatch.setattr(credentials, "CREDENTIAL_KINDS", drifted)
    with pytest.raises(RuntimeError, match="device_id"):
        credentials._guard_credential_table()


def test_the_end_reason_vocabulary_is_the_enum_and_both_tables_map_into_it():
    assert END_REASON_VOCABULARY == frozenset(member.value for member in EndReason)
    assert all(isinstance(word, EndReason) for word in CONSOLE_CTRL_END_REASONS.values())
    assert all(isinstance(word, EndReason) for word in SIGNAL_END_REASONS.values())
