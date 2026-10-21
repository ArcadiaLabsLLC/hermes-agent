"""The proxy cache for cross-install media (Stage P4), out of ``media_handles``.

Bytes a paired install served are cached here under their content address, so
the fetch lane's second hop is free. The handle grammar, the cap and the mint
(:data:`~agent_runtime.media_handles.HANDLE_RE`, ``MAX_FETCH_BYTES``,
``handle_for_bytes``) stay in ``agent_runtime/media_handles.py``, which
re-exports every public name here so ``media_handles.read_cached_bytes`` keeps
answering.
"""

from __future__ import annotations

import os
from pathlib import Path

from .media_handles import HANDLE_PREFIX, HANDLE_RE, MAX_FETCH_BYTES, handle_for_bytes

__layer__ = "stores"

__all__ = [
    "MEDIA_CACHE_DIRNAME",
    "read_cached_bytes",
    "remote_cache_path",
    "write_cached_bytes",
]


# ── the proxy cache (Stage P4) ───────────────────────────────────────────────
#
# A content-addressed cache is the one kind that needs no invalidation
# protocol: the key IS the digest, so an entry can never be stale — it is
# either the bytes the handle names or it is not an entry at all. That property
# is what makes the fetch lane's second hop free rather than merely cheap, and
# it is the whole reason Stage 8 minted handles over content instead of paths.


#: Where cached peer bytes live. Under the INSTALL's root, beside
#: ``gateway/peers.json``, and reached through ``peer_store_root()`` for that
#: function's own stated reason: ``persona_profile_context`` flips
#: ``HERMES_HOME`` process-globally during a persona turn, so the ambient
#: answer depends on which unrelated persona happened to be mid-turn. A cached
#: artifact belongs to the install, exactly as a peer edge does.
MEDIA_CACHE_DIRNAME = "media_cache"


def remote_cache_path(handle: str, *, root: Path | None = None) -> Path | None:
    """Where the bytes for ``handle`` would be cached, or ``None``.

    ``None`` for anything that is not a well-formed handle — which is also the
    reason this is safe to build a path from at all. The filename is the HEX
    of the digest and nothing else: 64 characters from ``[0-9a-f]``, so no
    caller-supplied string ever reaches a path segment and there is no
    traversal question to answer, only the grammar there already was.
    """

    if not isinstance(handle, str) or not HANDLE_RE.match(handle.strip()):
        return None
    digest = handle.strip()[len(HANDLE_PREFIX) :]
    try:
        base = root if root is not None else _peer_store_root()
    except Exception:  # pragma: no cover - defensive; a cache must never raise
        return None
    if base is None:
        return None
    return base / "gateway" / MEDIA_CACHE_DIRNAME / f"{digest}.bin"


def read_cached_bytes(handle: str, *, root: Path | None = None) -> bytes | None:
    """Cached bytes for ``handle``, VERIFIED, or ``None``.

    The verification is not paranoia about our own writes; it is what keeps the
    cache from being a way to launder bytes into a content-addressed namespace.
    The file sits on a disk other things can touch, and serving whatever is at
    ``<digest>.bin`` without re-hashing would mean the handle stopped naming
    bytes the moment anybody edited one. A mismatch DELETES the entry and
    answers ``None``, so the next fetch re-dials rather than serving a lie
    forever.
    """

    path = remote_cache_path(handle, root=root)
    if path is None:
        return None
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > MAX_FETCH_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if handle_for_bytes(data) != handle.strip():
        try:
            path.unlink()
        except OSError:  # pragma: no cover - best effort
            pass
        return None
    return data


def write_cached_bytes(handle: str, data: bytes, *, root: Path | None = None) -> bool:
    """Cache verified bytes under their handle. Best effort by contract.

    Verified HERE as well as by the caller, because this is the door: a write
    whose bytes do not hash to the name would poison every later read, and the
    check costs one pass over at most 5 MiB against a dial that costs a LAN
    round trip.

    ``False`` for anything not written — a bad handle, a mismatch, a disk that
    refused. A cache that cannot write is a fetch that costs a dial next time,
    never a fetch that fails, so no caller branches on this except to say so in
    a log.
    """

    path = remote_cache_path(handle, root=root)
    if path is None or not isinstance(data, bytes):
        return False
    if len(data) > MAX_FETCH_BYTES or handle_for_bytes(data) != handle.strip():
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: a reader that opens a half-written file would hash
        # it, find a mismatch, and DELETE the entry the writer is still filling.
        temporary = path.with_name(f"{path.name}.{os.getpid()}.part")
        temporary.write_bytes(data)
        temporary.replace(path)
    except OSError:
        return False
    return True


def _peer_store_root() -> Path | None:
    try:
        from .gateway_targets import peer_store_root

        return peer_store_root()
    except Exception:  # pragma: no cover - defensive; the cache must never raise
        return None
