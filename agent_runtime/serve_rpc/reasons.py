"""The ``data.reason`` vocabulary the METHOD lane's own guards spend (rule 14).

A client branches on ``data.reason`` (see :func:`protocol.err`), so a reason is
contract, not prose. The reasons a guard in THIS package decides — as opposed to
the ones a store exception names, which :mod:`office_errors` translates — are
one closed vocabulary here instead of eight free strings declared beside the
handler that spends them. ``StrEnum`` members ARE their strings: they compare
equal to, hash like and JSON-encode as the value, so every frame on the wire is
byte-identical to the one the free strings built.
"""

from __future__ import annotations

from enum import StrEnum

__layer__ = "models"

__all__ = ["RpcRefusal"]


class RpcRefusal(StrEnum):
    """Every ``data.reason`` a guard in this package refuses with."""

    #: A verb that needs ``workspace_id`` and got no non-empty string.
    WORKSPACE_ID_REQUIRED = "workspace_id_required"
    #: A ``workspace_id`` that names no office surface / workspace record.
    WORKSPACE_NOT_FOUND = "workspace_not_found"
    #: An ``expect_revision`` that is not an integer (a ``bool`` included).
    EXPECT_REVISION_INVALID = "expect_revision_invalid"
    #: An ``updated_by`` that is not a string.
    UPDATED_BY_INVALID = "updated_by_invalid"
    #: A present-but-illegal gesture token (EG-2.3) — every write verb.
    CORRELATION_ID_INVALID = "correlation_id_invalid"
    #: An ``expect_sha256`` that is not 64 hex characters, ``null`` or omitted.
    EXPECT_SHA256_INVALID = "expect_sha256_invalid"
    #: A level/map write whose ``expect_sha256`` lost to the stored document.
    SHA256_MISMATCH = "sha256_mismatch"
    #: A ``peer.agent_chat.execute`` whose caller is not a peer.
    PEER_IDENTITY_REQUIRED = "peer_identity_required"
    #: A ``peer.announce`` naming an install other than the caller's own.
    ANNOUNCE_NAMES_OTHER_INSTALL = "announce_names_other_install"
    #: A peer thread whose chat lane could not be read.
    THREAD_UNREADABLE = "thread_unreadable"
    #: A peer thread read for a persona this runtime does not serve.
    UNSUPPORTED_PERSONA = "unsupported_persona"
    #: A peer thread read naming a session the peer does not own.
    FOREIGN_SESSION = "foreign_session"
