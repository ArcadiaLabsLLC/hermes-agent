"""The at-rest cipher for phone chat history — stdlib only, so it runs wherever CPython does.

Encrypt-then-MAC over two keyed hashes CPython ships in its own core (no OpenSSL, no
native wheel): the keystream is SHAKE256's extendable output over (encryption subkey,
nonce), the tag is keyed BLAKE2b-256 over (header, associated data, ciphertext).
Subkeys are derived from the host's 32-byte history key with keyed BLAKE2b and distinct
personalisation strings, so the stream key never touches the MAC. Every seal draws a
fresh 24-byte nonce from ``os.urandom``.

Why not SQLCipher or ``cryptography``: the profile gate refuses Rust-backed packages
(``cryptography`` is one), and SQLCipher is a native SQLite build plus a crypto provider
per phone ABI that desktop CI's stdlib ``sqlite3`` cannot exercise. See
:mod:`agent_runtime.host_store.session_db` for how the database rides on this.

Envelope: ``b"HSE1" | nonce(24) | ciphertext | tag(32)``. The associated data (the
file's slot) is bound into the tag, so a blob moved to another path or profile fails
to open rather than decrypting under the wrong name.
"""

from __future__ import annotations

import hashlib
import hmac
import os

__layer__ = "models"

MAGIC = b"HSE1"
NONCE_BYTES = 24
TAG_BYTES = 32
KEY_BYTES = 32
OVERHEAD = len(MAGIC) + NONCE_BYTES + TAG_BYTES


class EnvelopeError(ValueError):
    """Not an envelope, or it fails authentication (wrong key, wrong slot, or tampered)."""


def _subkey(key: bytes, purpose: bytes) -> bytes:
    if len(key) != KEY_BYTES:
        raise EnvelopeError(f"history key must be {KEY_BYTES} bytes")
    return hashlib.blake2b(b"", key=key, person=purpose, digest_size=32).digest()


def _keystream_xor(enc_key: bytes, nonce: bytes, data: bytes) -> bytes:
    if not data:
        return b""
    stream = hashlib.shake_256(b"hsec-stream-v1\x00" + enc_key + nonce).digest(len(data))
    return (int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")).to_bytes(len(data), "big")


def _tag(mac_key: bytes, nonce: bytes, aad: bytes, ciphertext: bytes) -> bytes:
    mac = hashlib.blake2b(key=mac_key, digest_size=TAG_BYTES, person=b"hsec-mac-v1")
    mac.update(MAGIC)
    mac.update(nonce)
    mac.update(len(aad).to_bytes(8, "big"))
    mac.update(aad)
    mac.update(ciphertext)
    return mac.digest()


def seal(key: bytes, plaintext: bytes, *, aad: bytes) -> bytes:
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = _keystream_xor(_subkey(key, b"hsec-enc-v1"), nonce, bytes(plaintext))
    return MAGIC + nonce + ciphertext + _tag(_subkey(key, b"hsec-mac-key-v1"), nonce, aad, ciphertext)


def open_(key: bytes, blob: bytes, *, aad: bytes) -> bytes:
    blob = bytes(blob)
    if len(blob) < OVERHEAD or not blob.startswith(MAGIC):
        raise EnvelopeError("not a history envelope")
    nonce = blob[len(MAGIC):len(MAGIC) + NONCE_BYTES]
    ciphertext, tag = blob[len(MAGIC) + NONCE_BYTES:-TAG_BYTES], blob[-TAG_BYTES:]
    expected = _tag(_subkey(key, b"hsec-mac-key-v1"), nonce, aad, ciphertext)
    if not hmac.compare_digest(tag, expected):
        raise EnvelopeError("history envelope failed authentication (wrong key, wrong slot, or tampered)")
    return _keystream_xor(_subkey(key, b"hsec-enc-v1"), nonce, ciphertext)
