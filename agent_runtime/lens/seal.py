"""A SEALED manifest: immutable canonical bytes + SHA-256 + revision.

Ported from Companion's ``monitor_seal.dart``, simplified (plan §3): the host,
watcher-generation and write-lease fencing is dropped because one process (the
serve) owns the store. What survives is the honesty the seal exists for — the
bytes that run are the bytes the operator sealed, and a reader that finds bytes
whose digest does not match refuses them rather than running a changed monitor.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .manifest import decode_manifest, read_manifest
from .wire_value import WireError, WireRefusal, bounded_int, canonical_bytes

__layer__ = "models"


@dataclass(frozen=True, slots=True)
class SealedManifest:
    monitor_id: str
    revision: int
    digest: str
    body: bytes

    @property
    def byte_length(self) -> int:
        return len(self.body)

    def manifest(self) -> dict[str, Any]:
        """The sealed manifest, re-verified: the digest must still name the bytes."""

        if hashlib.sha256(self.body).hexdigest() != self.digest:
            raise WireError(WireRefusal.INVALID_DIGEST, "sealed bytes changed")
        manifest = decode_manifest(self.body)
        if manifest["monitor_id"] != self.monitor_id:
            raise WireError(WireRefusal.INVALID_IDENTITY, "sealed identity")
        return manifest

    def reference(self) -> dict[str, Any]:
        return {"monitor_id": self.monitor_id, "revision": self.revision,
                "digest": self.digest, "byte_length": self.byte_length}


def seal_manifest(value: Any, *, revision: int) -> SealedManifest:
    """Validate ``value`` and freeze it at ``revision`` (>= 1)."""

    manifest = read_manifest(value)
    body = canonical_bytes(manifest)
    return SealedManifest(
        monitor_id=manifest["monitor_id"],
        revision=bounded_int(revision, minimum=1),
        digest=hashlib.sha256(body).hexdigest(),
        body=body,
    )
