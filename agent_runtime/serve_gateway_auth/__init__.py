"""Per-DEVICE credentials for the gateway listener: pair, verify, revoke.

Where ``serve_auth.py`` mints ONE secret per runtime root — "whoever holds this
is the machine owner" — this module mints one per paired DEVICE, so that
"whoever holds this" finally has a name, a tier, and a revocation. That is the
whole of the gateway plan's Stage 1 credential half and of the authorization
chokepoint's Stage A5: the front-door gate (``call_authorization.py``) already
asks "may this caller run this tier?"; until now the socket lane had one answer
for every peer because it had one secret.

Two files, both under ``<store_root>/gateway/`` beside ``install.json``:

* ``devices.json`` — the paired devices. One row each:
  ``{device_id, name, tier, verifier, created_at, last_seen, revoked,
  revoked_at, expires_at, account_device_id}``. Two kinds of field in that row
  (R-IP14; ``gateway_peers``' module docstring states the same split in full):
  ``name`` and ``last_seen`` are CACHE facts — what the device called itself at
  redemption, and when the network last saw it — while ``device_id``, ``tier``,
  ``verifier``, ``created_at``, ``expires_at`` and the two revocation fields are
  TRUST, written by the ceremony or by a revoke and never by a hello.
  ``account_device_id`` is a LABEL a hello never writes either: it is copied
  from the pending entry an ``introduce`` scoped, and nothing authenticates
  against it (:class:`DeviceRecord`).

  **One live row per account device** (RL-23). A redeem scoped to an
  ``account_device_id`` revokes every non-revoked row carrying the same label,
  in the same write, stamping ``revoked_reason: "superseded"`` and
  ``superseded_by: <the new device id>`` on each — two additive fields, absent
  on every row written before the rule and absent on every hand-run revoke.
  Before it, a launcher re-pairing on a backoff minted a live credential per
  attempt: five rows on one machine for one far device, fourteen on the other
  side. An UNLABELLED row supersedes nothing, because an unlabelled row is
  attributable to nobody. The old credential's next hello answers
  ``device_revoked`` — the honest word — and
  :func:`prune_revoked_devices` removes revoked rows thirty days after their
  ``revoked_at``, at serve boot, never a live one.

  **``expires_at`` is S2's one new credential rule** (R-IP15 as amended).
  ``None`` means never, and that is what every manual ``harness gateway pair``
  keeps minting; a code minted by ``harness gateway introduce`` carries
  :data:`CREDENTIAL_TTL_SECONDS_INTRODUCED` through the pending entry, and the
  stamp is computed at REDEEM so the code's own ten-minute window is not
  charged against the credential's thirty days. :func:`verify_device_proof`
  refuses an expired row AFTER the proof, beside the revocation arm and for the
  same anti-probing reason, and the wire collapses both into one rejection.
* ``pairing.json`` — the SHORT-LIVED half: pending codes (hashed, salted) and
  the failed-redeem counter that arms the lockout. Nothing durable lives here;
  a lost ``pairing.json`` costs an operator one re-run of ``harness gateway
  pair``.

What is stored, and the honest limit of hashing it
--------------------------------------------------

The plaintext device token is returned to its caller EXACTLY ONCE, by
:func:`redeem_pairing_code`, and is never written to either file, to a log
line, to a frame, or to an event. What lands in ``devices.json`` is the
**verifier** — ``sha256(token)`` — and the proof a device presents is an HMAC
keyed by that verifier (:func:`device_proof`).

State the limit plainly, because a security note that overclaims is worse than
none: **the verifier is HMAC-key-equivalent.** A challenge-response where the
server holds no secret at all is an ASYMMETRIC scheme (the device signs, the
server holds only a public key); this is a symmetric one, chosen because the
plan of record specifies "the same HMAC challenge-response as today, keyed by
the device token" and because the loopback lane's :func:`serve_socket.hello_proof`
is the discipline being extended rather than replaced. So anyone who can read
``devices.json`` can impersonate every device in it, exactly as anyone who can
read ``serve_auth_token`` can impersonate the machine owner. Digesting the token
before storing it buys one real thing and not two: the bytes a device holds — the
bytes that travelled through the pairing channel and now sit in a phone's
keystore — are not the bytes on this disk, so a store read cannot recover an
issued credential, only the ability to answer a challenge with it. If
store-read resistance is ever wanted, the upgrade is the R1 survey's bullet 2
(the device holds a P-256 key and the install pins its JWK thumbprint), and it
changes only :func:`device_proof` and this file — never the wire's shape, which
says "proof" and nothing about how it was computed.

File permissions, honestly (the same gap, restated where it now matters more)
-----------------------------------------------------------------------------

``devices.json`` is created ``0600`` where that means something. **On Windows it
does not** — mode bits map only onto the read-only attribute and the file
inherits its parent directory's ACL, so on a default install it is readable by
any process running as this user. ``serve_auth.py`` recorded this gap for the
root token and declined to fix it there; the gap is unchanged, and the exposure
is larger, because the file now gates a listener that is reachable from another
machine. A best-effort DACL narrowing is applied on Windows and its
outcome is REPORTED rather than assumed — a permission posture this module
cannot enforce is never claimed as enforced.

Pairing discipline
------------------

Imitated from ``gateway/pairing.py``, not imported — and that is a decision
rather than laziness. That module is the MESSAGING gateway's: its store is
resolved from ``get_hermes_home()`` / ``get_hermes_dir()`` (a HERMES home, not a
store root, and this lane's whole Stage 0 finding is that those are provably
different scopes on this machine), it is keyed by ``(platform, user_id)``, and
it mirrors approvals into per-platform allowlist env vars. Importing it would
mean either bending a store-root credential into a platform/user pair or
teaching it a second storage scope; what is worth reusing is its RULES, and
those are restated here with the same numbers and the same reasons:

* 8-character codes from a 32-character unambiguous alphabet (no ``0``/``O``,
  no ``1``/``I``), chosen with :func:`secrets.choice`.
* The code is NEVER stored in plaintext — a random 16-byte salt and
  ``sha256(salt + code)`` are, and redemption compares in constant time.
* A short TTL, a cap on pending codes, and a lockout after repeated failed
  redeems, checked BEFORE the pending lookup so a lockout blocks a code that
  was already issued (``pairing.py`` fixed exactly that bug, #10195).
* A successful redeem clears the failure streak, so isolated typos cannot
  accumulate into a spurious lockout.
* **Codes are never logged.** Nothing in this module writes one anywhere except
  the return value handed to its caller.

Two numbers deviate from ``pairing.py``'s, both downward, both because the
channel is different. Its code is DM'd to a stranger who may take an hour to
read it; this one is printed on the operator's own terminal for them to type or
scan within seconds, so the TTL is ten minutes rather than an hour and the
window in which a guess is worth anything shrinks with it. And there is no
per-requester rate limit on MINTING, because the requester is the operator at
the install's own console — the party the whole tier traces its authority to
(Ruling A: the tier is client security auth, and an operator-run pairing on the
install's machine IS the account-auth trace). The cap on PENDING codes still
applies: three unredeemed codes at once is a mistake, not a workflow.

Root as INPUT
-------------

Every function takes ``store_root``. This module never resolves a root and
never reads ``HERMES_HOME`` — the same rule ``serve_auth.py``,
``gateway_identity.py`` and ``serve_socket/`` all state, for the same reason:
several roots coexist on this machine, and a credential store free to re-derive
its own root could pair a device against one install and answer for another.

Never raises for a READ
-----------------------

:func:`lookup_device`, :func:`list_devices` and :func:`verify_device_proof`
answer with a typed outcome and never propagate an ``OSError``: they run on the
socket lane's handshake path, where an exception is a peer that learns nothing
and a runtime that logged a traceback. The WRITE paths (mint, redeem, revoke)
do report failure as a typed refusal too, because their caller is a CLI verb
that owes the operator an exit code rather than a stack trace.
"""

from __future__ import annotations

# The layout (FH-SERVE-GATEWAY-AUTH-OVER-CEILING): one module per responsibility, this package
# the one public door — every caller keeps importing from ``agent_runtime.serve_gateway_auth``.
from ..gateway_pairing_codes import CODE_ALPHABET, CODE_LENGTH, CODE_TTL_SECONDS, LOCKOUT_SECONDS, MAX_FAILED_REDEEMS, MAX_PENDING_CODES
from .devices import list_devices, lookup_device, note_device_seen, prune_revoked_devices, revoke_device, verify_device_proof
from .pairing import mint_pairing_code, redeem_pairing_code
from .proof import device_proof, device_verifier
from .records import (
    AUTH_BAD_PROOF,
    AUTH_EXPIRED,
    AUTH_MALFORMED,
    AUTH_OK,
    AUTH_REVOKED,
    AUTH_UNKNOWN_DEVICE,
    CREDENTIAL_TTL_SECONDS_INTRODUCED,
    DEFAULT_DEVICE_TIER,
    DEVICE_STORE_CONTRACT,
    DEVICE_STORE_FILENAME,
    DEVICE_TOKEN_BYTES,
    GATEWAY_PROOF_ALGORITHM,
    GATEWAY_PROOF_CONTRACT,
    PAIRING_STORE_FILENAME,
    REVOKED_ROW_RETENTION_SECONDS,
    REVOKED_SUPERSEDED,
    DeviceAuth,
    DeviceCredential,
    DeviceRecord,
    PairingCode,
    StoreRefusal,
)
from .store import device_store_path, pairing_store_path, read_pairing, store_lock, write_pairing

__layer__ = "stores"

__all__ = [
    "AUTH_BAD_PROOF",
    "AUTH_EXPIRED",
    "AUTH_MALFORMED",
    "AUTH_OK",
    "AUTH_REVOKED",
    "AUTH_UNKNOWN_DEVICE",
    "CODE_ALPHABET",
    "CODE_LENGTH",
    "CODE_TTL_SECONDS",
    "CREDENTIAL_TTL_SECONDS_INTRODUCED",
    "DEFAULT_DEVICE_TIER",
    "DEVICE_STORE_CONTRACT",
    "DEVICE_STORE_FILENAME",
    "DEVICE_TOKEN_BYTES",
    "GATEWAY_PROOF_ALGORITHM",
    "GATEWAY_PROOF_CONTRACT",
    "LOCKOUT_SECONDS",
    "MAX_FAILED_REDEEMS",
    "MAX_PENDING_CODES",
    "PAIRING_STORE_FILENAME",
    "REVOKED_ROW_RETENTION_SECONDS",
    "REVOKED_SUPERSEDED",
    "DeviceAuth",
    "DeviceCredential",
    "DeviceRecord",
    "PairingCode",
    "StoreRefusal",
    "device_proof",
    "device_store_path",
    "device_verifier",
    "list_devices",
    "lookup_device",
    "mint_pairing_code",
    "note_device_seen",
    "pairing_store_path",
    "prune_revoked_devices",
    "read_pairing",
    "redeem_pairing_code",
    "revoke_device",
    "store_lock",
    "verify_device_proof",
    "write_pairing",
]
