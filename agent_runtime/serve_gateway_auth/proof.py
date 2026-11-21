"""The derivation: the stored verifier and the HMAC proof a device presents.

Part of the :mod:`agent_runtime.serve_gateway_auth` layout; the package docstring is the design.
"""

from __future__ import annotations

import hashlib
import hmac

from .records import GATEWAY_PROOF_CONTRACT

__layer__ = "stores"


# ── the derivation ───────────────────────────────────────────────────────────


def device_verifier(token: str) -> str:
    """``sha256(token)`` as lowercase hex — what the install stores.

    ONE derivation, called by the pairing path to compute what to store and by
    the client half to compute the HMAC key. A second copy of this line is how
    two ends start disagreeing about what a credential is.
    """

    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def device_proof(token: str, nonce: str, *, port: int, device_id: str) -> str:
    """The device's answer to a gateway challenge, as lowercase hex.

    ``HMAC-SHA256(key=sha256(token), msg="gwv<contract>|<port>|<device_id>|<nonce>")``.

    Three things are bound into the message and each closes a different hole:

    * the **nonce** is fresh per connection, so a captured transcript is not
      replayable;
    * the **port** is what each end knows from its OWN socket — the server from
      what it listens on, the client from what it dialled — so an impostor that
      relays a live challenge to the real service gets an answer that does not
      verify there. This is ``serve_socket.hello_proof``'s argument and it is
      copied deliberately: binding to anything the greeting merely ASSERTS
      (``boot_id``, a claimed port) is binding to a number the impostor echoes;
    * the **device id**, so a proof minted by one device cannot be presented
      under another device's name even if the two ever shared a token. They do
      not — each pairing mints its own 256 bits — but a derivation that would
      still be sound if they did is the one worth writing.

    The token is the KEY (through its digest) and never the message, so the
    proof discloses nothing about it. It does not travel, in either direction.
    """

    message = f"gwv{GATEWAY_PROOF_CONTRACT}|{int(port)}|{device_id!s}|{nonce}"
    return hmac.new(
        device_verifier(token).encode("ascii"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def proof_from_verifier(verifier: str, nonce: str, *, port: int, device_id: str) -> str:
    """The server's half: it holds the verifier, never the token."""

    message = f"gwv{GATEWAY_PROOF_CONTRACT}|{int(port)}|{device_id!s}|{nonce}"
    return hmac.new(
        str(verifier).encode("ascii"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()


# ── the reverse lane's proof (review w1118a.79) ──────────────────────────────


def reverse_lane_proof(token: str, nonce: str, *, lane_id: str, device_id: str) -> str:
    """A granted computer's answer to a phone's challenge over a lane the phone dialled.

    ``HMAC-SHA256(key=sha256(token), msg="gwvr<contract>|<lane id>|<device_id>|<nonce>")``:
    the device proof's shape (:func:`device_proof`) with the LANE ID in place of the
    port. Through the computer's splice the computer's Eternia dials a loopback port the
    phone never sees, so the port binds nothing here; the lane id is the value each end
    knows from its own side — the phone minted it, the computer's Eternia read it from
    its own Hermes when it attached. A proof answered for one lane does not verify on
    another, and the ``gwvr`` prefix keeps it from ever verifying as a device proof.
    """

    return reverse_proof_from_verifier(device_verifier(token), nonce, lane_id=lane_id, device_id=device_id)


def reverse_proof_from_verifier(verifier: str, nonce: str, *, lane_id: str, device_id: str) -> str:
    """The phone's half: it holds the grant's verifier, never the token."""

    message = f"gwvr{GATEWAY_PROOF_CONTRACT}|{lane_id!s}|{device_id!s}|{nonce}"
    return hmac.new(
        str(verifier).encode("ascii"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
